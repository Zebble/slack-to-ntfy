"""FastAPI app: receive Slack webhooks, transform, forward to ntfy."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .config import load_config
from .forwarder import forward
from .slack import build_context, parse_slack_request

# Load a .env from the working directory (if present) so non-Docker runs pick
# up the same vars the compose file injects. Existing environment variables
# always take precedence.
_dotenv = find_dotenv(usecwd=True)
if _dotenv:
    load_dotenv(_dotenv)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("slack-to-ntfy")

_TIMEOUT = float(os.environ.get("FORWARD_TIMEOUT", "10"))
# Reject inbound bodies larger than this (bytes); Slack/ntfy payloads are small.
_MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", "65536"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = load_config()
    app.state.endpoints = app.state.config.endpoint_map()
    app.state.client = httpx.AsyncClient(timeout=_TIMEOUT)
    log.info(
        "loaded %d endpoint(s): %s",
        len(app.state.endpoints),
        ", ".join(app.state.endpoints) or "(none)",
    )
    try:
        yield
    finally:
        await app.state.client.aclose()


# Interactive docs and the OpenAPI schema are disabled so the public surface
# reveals nothing about the configured routes.
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# Optional Host-header allowlist (comma-separated). Inactive unless set.
_allowed_hosts = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()
]
if _allowed_hosts:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)


def _not_found() -> Response:
    """Generic 404 used for unknown, disabled, and unauthorized endpoints alike,
    so probing /hook/<guess> can't enumerate which endpoints exist."""
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _authorized(endpoint, request: Request) -> bool:
    if not endpoint.inbound_token:
        return True
    presented = request.headers.get("x-slack-to-ntfy-token") or request.query_params.get(
        "token"
    )
    return presented == endpoint.inbound_token


async def _read_body(request: Request, limit: int) -> bytes | None:
    """Read the request body, returning None if it exceeds `limit` bytes."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                return None
        except ValueError:
            return None
    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/hook/{name}")
async def hook(name: str, request: Request) -> Response:
    endpoint = request.app.state.endpoints.get(name)
    if endpoint is None or not endpoint.enabled or not _authorized(endpoint, request):
        if endpoint is None:
            reason = "unknown endpoint"
        elif not endpoint.enabled:
            reason = "endpoint disabled"
        else:
            reason = "unauthorized"
        log.warning("rejected POST /hook/%s: %s", name, reason)
        return _not_found()

    raw = await _read_body(request, _MAX_BODY_BYTES)
    if raw is None:
        log.warning("rejected POST /hook/%s: body exceeds %d bytes", name, _MAX_BODY_BYTES)
        return JSONResponse({"detail": "Payload Too Large"}, status_code=413)

    payload = parse_slack_request(request.headers.get("content-type", ""), raw)
    context = build_context(payload)

    try:
        result = await forward(request.app.state.client, endpoint, context)
    except httpx.HTTPError as exc:
        log.error("endpoint=%s forward failed: %s", name, exc)
        return JSONResponse({"error": "failed to forward to ntfy"}, status_code=502)

    upstream_ok = 200 <= result.status_code < 300
    log.info(
        "endpoint=%s title=%r -> ntfy status=%d",
        name,
        context["title"],
        result.status_code,
    )
    return JSONResponse(
        {"forwarded": upstream_ok, "ntfy_status": result.status_code},
        status_code=200 if upstream_ok else 502,
    )

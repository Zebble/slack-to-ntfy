"""FastAPI app: receive Slack webhooks, transform, forward to ntfy."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from . import __version__
from .config import AppConfig, load_config
from .forwarder import forward
from .slack import build_context, parse_slack_request

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("slack-to-ntfy")

_TIMEOUT = float(os.environ.get("FORWARD_TIMEOUT", "10"))


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


app = FastAPI(title="slack-to-ntfy", version=__version__, lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/")
async def index(request: Request) -> dict[str, object]:
    config: AppConfig = request.app.state.config
    return {
        "service": "slack-to-ntfy",
        "version": __version__,
        "endpoints": [
            {"name": e.name, "enabled": e.enabled, "path": f"/hook/{e.name}"}
            for e in config.endpoints
        ],
    }


def _authorized(endpoint, request: Request) -> bool:
    if not endpoint.inbound_token:
        return True
    presented = request.headers.get("x-slack-to-ntfy-token") or request.query_params.get(
        "token"
    )
    return presented == endpoint.inbound_token


@app.post("/hook/{name}")
async def hook(name: str, request: Request) -> Response:
    endpoints = request.app.state.endpoints
    endpoint = endpoints.get(name)
    if endpoint is None:
        return JSONResponse({"error": f"unknown endpoint: {name}"}, status_code=404)
    if not endpoint.enabled:
        return JSONResponse({"error": f"endpoint disabled: {name}"}, status_code=403)
    if not _authorized(endpoint, request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    raw = await request.body()
    payload = parse_slack_request(request.headers.get("content-type", ""), raw)
    context = build_context(payload)

    try:
        result = await forward(request.app.state.client, endpoint, context)
    except httpx.HTTPError as exc:
        log.error("endpoint=%s forward failed: %s", name, exc)
        return JSONResponse(
            {"error": "failed to forward to ntfy", "detail": str(exc)},
            status_code=502,
        )

    log.info(
        "endpoint=%s title=%r -> ntfy status=%d",
        name,
        context["title"],
        result.status_code,
    )
    upstream_ok = 200 <= result.status_code < 300
    return JSONResponse(
        {
            "forwarded": True,
            "ntfy_status": result.status_code,
            "ntfy_response": result.body[:500],
        },
        status_code=200 if upstream_ok else 502,
    )

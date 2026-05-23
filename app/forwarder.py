"""Render an endpoint's templates against the Slack context and forward to ntfy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from jinja2 import ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from .config import EndpointConfig

# Sandboxed so operator-supplied templates can't reach Python internals.
# ChainableUndefined makes `{{ payload.missing.field }}` render empty instead
# of raising, so a missing payload field is forgiving rather than fatal.
_env = SandboxedEnvironment(undefined=ChainableUndefined, autoescape=False)


@dataclass
class ForwardResult:
    status_code: int
    body: str


def _render(template: str, context: dict[str, Any]) -> str:
    return _env.from_string(template).render(**context)


def build_request(
    endpoint: EndpointConfig, context: dict[str, Any]
) -> tuple[str, str, dict[str, str], str]:
    """Return (method, url, headers, body) with all templates rendered.

    Headers that render to an empty/whitespace-only value are dropped, so a
    template like ``{% if secrets.token %}Bearer {{ secrets.token }}{% endif %}``
    simply omits the header when (for example) no NTFY_TOKEN is configured.
    """
    full_context = {**context, "secrets": endpoint.secrets}
    url = _render(endpoint.url, full_context)
    headers: dict[str, str] = {}
    for name, value in endpoint.headers.items():
        rendered = _render(value, full_context).strip()
        if rendered:
            headers[name] = rendered
    body = _render(endpoint.body, full_context)
    return endpoint.method, url, headers, body


async def forward(
    client: httpx.AsyncClient, endpoint: EndpointConfig, context: dict[str, Any]
) -> ForwardResult:
    method, url, headers, body = build_request(endpoint, context)
    response = await client.request(
        method, url, headers=headers, content=body.encode("utf-8")
    )
    return ForwardResult(status_code=response.status_code, body=response.text)

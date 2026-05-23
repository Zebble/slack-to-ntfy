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
# of raising, matching the forgiving feel of Proxmox's template fields.
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
    """Return (method, url, headers, body) with all templates rendered."""
    full_context = {**context, "secrets": endpoint.secrets}
    url = _render(endpoint.url, full_context)
    headers = {
        name: _render(value, full_context) for name, value in endpoint.headers.items()
    }
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

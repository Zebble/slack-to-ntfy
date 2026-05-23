"""Configuration loading and validation.

The config file is operator-controlled and intentionally mirrors the shape of
Proxmox VE's generic webhook target: each endpoint defines a method, URL,
templated headers, a templated body, and a bag of secrets.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: object) -> object:
    """Recursively expand ${VAR} and ${VAR:-default} in string values.

    Lets secrets and URLs be supplied via environment variables instead of
    being written into the config file in plaintext.
    """
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class EndpointConfig(BaseModel):
    name: str
    enabled: bool = True
    method: str = "POST"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = "{{ message }}"
    secrets: dict[str, str] = Field(default_factory=dict)
    # When set, inbound requests must present this token via the
    # `X-Slack-To-Ntfy-Token` header or `?token=` query parameter.
    inbound_token: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v):
            raise ValueError(
                f"endpoint name {v!r} may only contain letters, digits, '.', '_' and '-'"
            )
        return v

    @field_validator("method")
    @classmethod
    def _upper_method(cls, v: str) -> str:
        return v.upper()


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    endpoints: list[EndpointConfig] = Field(default_factory=list)

    def endpoint_map(self) -> dict[str, EndpointConfig]:
        return {e.name: e for e in self.endpoints}


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    config_path = Path(path or os.environ.get("CONFIG_PATH", "/config/config.yaml"))
    if not config_path.is_file():
        raise FileNotFoundError(f"config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text()) or {}
    raw = _expand_env(raw)
    config = AppConfig.model_validate(raw)

    names = [e.name for e in config.endpoints]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"duplicate endpoint names in config: {sorted(duplicates)}")

    return config

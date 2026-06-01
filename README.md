# slack-to-ntfy

[![CI](https://github.com/Zebble/slack-to-ntfy/actions/workflows/ci.yml/badge.svg)](https://github.com/Zebble/slack-to-ntfy/actions/workflows/ci.yml)
[![Docker](https://github.com/Zebble/slack-to-ntfy/actions/workflows/docker.yml/badge.svg)](https://github.com/Zebble/slack-to-ntfy/actions/workflows/docker.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A small, containerized middleware that ingests **Slack incoming-webhook**
payloads and forwards them to an [ntfy](https://ntfy.sh) instance.

Lots of tools can post to a "Slack webhook" but not to ntfy. Point those tools
at this service instead and they'll reach your ntfy topics. The transform is
fully template-driven: each endpoint defines a method, URL, templated headers, a
templated body, and a bag of secrets — similar to how Proxmox VE configures its
generic webhook targets.

```
  app that speaks Slack  ──POST /hook/<name>──▶  slack-to-ntfy  ──POST──▶  ntfy
   (Slack JSON payload)                       (renders templates)      (your topic)
```

## Endpoint configuration

Each endpoint describes how a Slack payload is forwarded to one ntfy topic:

| Config key       | Purpose |
|------------------|---------|
| `name`           | Inbound path becomes `/hook/<name>` |
| `enabled`        | Toggle the endpoint on or off |
| `method` / `url` | HTTP method and target ntfy URL |
| `headers`        | Templated request headers |
| `body`           | Templated request body |
| `secrets`        | Values referenced as `{{ secrets.X }}` |

Templates use Jinja2 (`{{ variable }}` syntax).

## Quick start

```bash
git clone https://github.com/Zebble/slack-to-ntfy.git && cd slack-to-ntfy
cp config.example.yaml config.yaml      # edit topics/headers to taste
cp .env.example .env                    # set NTFY_TOKEN etc. (gitignored)
docker compose up -d
```

`docker compose` pulls the prebuilt multi-arch image from
`ghcr.io/zebble/slack-to-ntfy:latest` by default — pass `--build` to build
locally instead. Both `config.yaml` and `.env` are gitignored so your topics
and tokens stay local. Compose auto-loads `.env`; the values flow into the
container and are referenced from `config.yaml` as `${NTFY_TOKEN}`.

Send a test notification:

```bash
curl -X POST http://localhost:8080/hook/system_alerts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello from Slack format","username":"tester"}'
```

Then reconfigure your Slack-webhook-emitting app to post to
`http://<host>:8080/hook/system_alerts` instead of its Slack webhook URL.

## Configuration

See [`config.example.yaml`](config.example.yaml). Each endpoint becomes an
inbound path `/hook/<name>`. Secrets and URLs support `${VAR}` and
`${VAR:-default}` environment expansion so nothing sensitive needs to live in
the file.

### Template variables

Available in every `headers` value, `body`, and `url`:

| Variable        | Meaning |
|-----------------|---------|
| `{{ title }}`   | Derived title: header block → first attachment title → username → `"Slack notification"` |
| `{{ message }}` | Flattened, human-readable body built from `text`, blocks, and attachments (Slack `<url\|label>` markup unwrapped) |
| `{{ text }}`    | The raw Slack `text` field |
| `{{ priority }}`| `1`–`5` derived from attachment color (`danger`=5, `warning`=4, else 3) for ntfy's `Priority` header |
| `{{ emoji }}`   | `icon_emoji` with the colons stripped — handy as an ntfy `Tags` value |
| `{{ color }}`   | First attachment color |
| `{{ username }}` `{{ channel }}` `{{ icon_url }}` | Corresponding Slack fields |
| `{{ payload }}` | The full parsed payload, e.g. `{{ payload.attachments[0].title }}` |
| `{{ secrets.X }}` | A value from this endpoint's `secrets` block |

Missing fields render as empty strings rather than erroring (e.g.
`{{ payload.nope.deep }}` → `""`). Headers that render to an empty value are
dropped from the outgoing request.

### ntfy auth is optional

A token is recommended but not required — it works against ntfy instances with
no auth or public topics. The example config sends `Authorization` only when a
token is set:

```yaml
Authorization: "{% if secrets.token %}Bearer {{ secrets.token }}{% endif %}"
```

With `NTFY_TOKEN` empty the rendered value is blank, so the header is omitted
entirely rather than sending an invalid `Bearer ` value.

### Per-endpoint tokens

Tokens are configured per endpoint, not globally:

- **ntfy (outbound)** — each endpoint's `secrets.token`, used by its
  `Authorization` header. Point endpoints at different `secrets` values (or
  different `${...}` env vars) to send to topics that need different tokens.
- **Slack (inbound)** — each endpoint's `inbound_token`, the token a caller
  must present. Set a different one per endpoint, or omit it to leave that
  endpoint open.

Because docker compose injects the whole `.env` (`env_file`), you can add as
many per-endpoint token variables as you like without touching the compose
file — just reference them from `config.yaml`.

### Inbound payload formats

Accepts what Slack accepts: a JSON body (`application/json`), a form-encoded
`payload=<json>` field, or — as a fallback — a plain-text body used as the
message.

### Optional inbound auth

Set `inbound_token` on an endpoint to require a token. Callers then pass it via
the `X-Slack-To-Ntfy-Token` header or `?token=` query parameter. When unset,
the (secret-ish) URL path is the only gate, just like a Slack webhook URL.

## Endpoints

| Method & path        | Purpose |
|----------------------|---------|
| `POST /hook/<name>`  | Receive a Slack-format payload and forward to the named ntfy target |
| `GET /healthz`       | Liveness check; returns `{"status":"ok"}` |

A `POST /hook/<name>` returns `200` with `{"ntfy_status": ...}` on a successful
forward, a generic `404` for unknown / disabled / unauthorized endpoints, `413`
if the body exceeds the size cap, and `502` if ntfy is unreachable or errors.

## Hardening for public deployment

This service is meant to sit behind a TLS-terminating reverse proxy (e.g.
NPMPlus). The app itself is locked down for an internet-facing deployment:

- **No discovery surface.** There is no index/listing route, and the
  interactive docs and OpenAPI schema (`/docs`, `/redoc`, `/openapi.json`) are
  disabled. `/healthz` returns only `{"status":"ok"}` — no version.
- **No endpoint enumeration.** Unknown, disabled, and unauthorized requests all
  return an identical `404`, so probing `/hook/<guess>` can't reveal which
  endpoints (or token-protected endpoints) exist. Real reasons are logged
  server-side only.
- **Body size cap.** Requests larger than `MAX_BODY_BYTES` (default 64 KiB) are
  rejected with `413` before any parsing.
- **No server fingerprint.** The `Server` response header is suppressed.
- **Optional Host allowlist.** Set `ALLOWED_HOSTS` to reject requests whose
  `Host` header doesn't match (e.g. direct-to-IP scans).

Recommended for a public instance:

- Give **every** endpoint an `inbound_token` (the URL path alone is only
  secret-ish), and put real auth tokens on your ntfy topics.
- At the proxy, restrict to the methods/paths you use, add rate limiting, and
  consider an IP allowlist if your sources have stable addresses.

## Configuration via environment

Set these in `.env` (see [`.env.example`](.env.example)). docker compose
injects the whole file into the container (`env_file`) and also uses it for
`${VAR}` interpolation; the app loads it directly for local runs. Real
environment variables always override `.env`.

Token variables are referenced from `config.yaml` and are up to you — add one
per endpoint (e.g. `NTFY_TOKEN`, `NTFY_TOKEN_APP`, `INBOUND_TOKEN_APP`) and they
all reach the container. The fixed knobs are:

| Variable          | Default                | Purpose |
|-------------------|------------------------|---------|
| `HOST_PORT`       | `8080`                 | Host port published by docker compose |
| `CONFIG_PATH`     | `/config/config.yaml`  | Path to the config file |
| `LOG_LEVEL`       | `INFO`                 | Logging verbosity |
| `FORWARD_TIMEOUT` | `10`                   | ntfy request timeout (seconds) |
| `MAX_BODY_BYTES`  | `65536`                | Max inbound request body size; larger → `413` |
| `ALLOWED_HOSTS`   | _(unset)_              | Comma-separated `Host` allowlist; unset disables the check |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow. The short version:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env        # optional; loaded automatically on startup
cp config.example.yaml config.yaml
CONFIG_PATH=./config.yaml uvicorn app.main:app --reload   # run locally
pytest                                                    # run tests
```

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md). Please use GitHub's
private vulnerability reporting rather than filing a public issue.

## License

[MIT](LICENSE) © 2026 Wade Weppler

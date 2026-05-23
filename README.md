# slack-to-ntfy

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
git clone <this-repo> && cd slack-to-ntfy
cp config.example.yaml config.yaml      # edit topics/headers to taste
cp .env.example .env                    # set NTFY_TOKEN etc. (gitignored)
docker compose up -d --build
```

Both `config.yaml` and `.env` are gitignored so your topics and tokens stay
local. Compose auto-loads `.env`; the values flow into the container and are
referenced from `config.yaml` as `${NTFY_TOKEN}`.

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
| `GET /`              | List configured endpoints |
| `GET /healthz`       | Health check (used by the container healthcheck) |

A `POST /hook/<name>` returns `200` with `{"ntfy_status": ...}` on a successful
forward, `404`/`403`/`401` for unknown/disabled/unauthorized endpoints, and
`502` if ntfy is unreachable or returns an error.

## Configuration via environment

Set these in `.env` (see [`.env.example`](.env.example)). The app loads `.env`
on startup via `python-dotenv`, and docker compose loads it for `${VAR}`
interpolation — so the same file works for Docker and local runs. Real
environment variables always override `.env`.

| Variable          | Default                | Purpose |
|-------------------|------------------------|---------|
| `NTFY_TOKEN`      | —                      | ntfy token; referenced as `${NTFY_TOKEN}` in `config.yaml` |
| `INBOUND_TOKEN`   | —                      | Inbound token for endpoints using `inbound_token` |
| `HOST_PORT`       | `8080`                 | Host port published by docker compose |
| `CONFIG_PATH`     | `/config/config.yaml`  | Path to the config file |
| `LOG_LEVEL`       | `INFO`                 | Logging verbosity |
| `FORWARD_TIMEOUT` | `10`                   | ntfy request timeout (seconds) |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env        # optional; loaded automatically on startup
cp config.example.yaml config.yaml
CONFIG_PATH=./config.yaml uvicorn app.main:app --reload   # run locally
pytest                                                    # run tests
```

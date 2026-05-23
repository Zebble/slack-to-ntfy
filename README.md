# slack-to-ntfy

A small, containerized middleware that ingests **Slack incoming-webhook**
payloads and forwards them to an [ntfy](https://ntfy.sh) instance.

Lots of tools can post to a "Slack webhook" but not to ntfy. Point those tools
at this service instead and they'll reach your ntfy topics. The transform is
fully template-driven, modeled on the flexibility of **Proxmox VE's generic
webhook target**: each endpoint defines a method, URL, templated headers, a
templated body, and a bag of secrets.

```
  app that speaks Slack  ──POST /hook/<name>──▶  slack-to-ntfy  ──POST──▶  ntfy
   (Slack JSON payload)                       (renders templates)      (your topic)
```

## How it maps to the Proxmox webhook UI

| Proxmox field        | slack-to-ntfy config            |
|----------------------|---------------------------------|
| Endpoint Name        | `endpoints[].name` (→ `/hook/<name>`) |
| Enable               | `endpoints[].enabled`           |
| Method / URL         | `endpoints[].method` / `endpoints[].url` |
| Headers              | `endpoints[].headers` (templated) |
| Body                 | `endpoints[].body` (templated)  |
| Secrets              | `endpoints[].secrets`           |

Templates use Jinja2, which shares Proxmox's `{{ variable }}` syntax.

## Quick start

```bash
git clone <this-repo> && cd slack-to-ntfy
cp config.example.yaml config.yaml      # edit topics/headers to taste
export NTFY_TOKEN=tk_your_ntfy_token    # referenced as ${NTFY_TOKEN} in config
docker compose up -d --build
```

Send a test notification:

```bash
curl -X POST http://localhost:8080/hook/dc_proxmox_alerts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello from Slack format","username":"tester"}'
```

Then reconfigure your Slack-webhook-emitting app to post to
`http://<host>:8080/hook/dc_proxmox_alerts` instead of its Slack webhook URL.

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
`{{ payload.nope.deep }}` → `""`).

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

| Variable          | Default                | Purpose |
|-------------------|------------------------|---------|
| `CONFIG_PATH`     | `/config/config.yaml`  | Path to the config file |
| `LOG_LEVEL`       | `INFO`                 | Logging verbosity |
| `FORWARD_TIMEOUT` | `10`                   | ntfy request timeout (seconds) |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
pytest
```

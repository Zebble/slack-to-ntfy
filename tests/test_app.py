import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.forwarder import ForwardResult, build_request

CONFIG = """
server:
  host: 0.0.0.0
  port: 8080
endpoints:
  - name: alerts
    url: "https://ntfy.example.com/alerts"
    headers:
      Authorization: "{% if secrets.token %}Bearer {{ secrets.token }}{% endif %}"
      Title: "{{ title }}"
      Priority: "{{ priority }}"
    body: "{{ message }}"
    secrets:
      token: "tk_alerts"
  - name: secured
    url: "https://ntfy.example.com/secured"
    headers:
      Authorization: "{% if secrets.token %}Bearer {{ secrets.token }}{% endif %}"
    body: "{{ message }}"
    secrets:
      token: "tk_secured"
    inbound_token: "letmein"
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG)
    monkeypatch.setenv("CONFIG_PATH", str(cfg))

    captured = {}

    async def fake_forward(http_client, endpoint, context):
        method, url, headers, body = build_request(endpoint, context)
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return ForwardResult(status_code=200, body="1")

    monkeypatch.setattr(main, "forward", fake_forward)

    with TestClient(main.app) as c:
        c.captured = captured
        yield c


def test_root_is_not_found(client):
    # No index/listing route is exposed.
    assert client.get("/").status_code == 404


def test_docs_and_schema_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body == {"status": "ok"}  # no version / fingerprint leaked


def test_hook_forwards_slack_payload(client):
    resp = client.post("/hook/alerts", json={"text": "boom", "username": "mon"})
    assert resp.status_code == 200
    assert resp.json()["ntfy_status"] == 200
    assert client.captured["url"] == "https://ntfy.example.com/alerts"
    assert client.captured["headers"]["Title"] == "mon"
    assert client.captured["body"] == "boom"


def test_per_endpoint_ntfy_token(client):
    client.post("/hook/alerts", json={"text": "a"})
    assert client.captured["headers"]["Authorization"] == "Bearer tk_alerts"

    client.post(
        "/hook/secured",
        json={"text": "b"},
        headers={"X-Slack-To-Ntfy-Token": "letmein"},
    )
    assert client.captured["headers"]["Authorization"] == "Bearer tk_secured"


def test_unknown_endpoint_404(client):
    assert client.post("/hook/nope", json={"text": "x"}).status_code == 404


def test_inbound_auth_failure_is_indistinguishable_from_unknown(client):
    # Missing/bad inbound token returns the same 404 as an unknown endpoint,
    # so token-protected endpoints can't be enumerated.
    unknown = client.post("/hook/nope", json={"text": "x"})
    no_token = client.post("/hook/secured", json={"text": "x"})
    assert no_token.status_code == 404
    assert no_token.json() == unknown.json()

    ok = client.post(
        "/hook/secured",
        json={"text": "x"},
        headers={"X-Slack-To-Ntfy-Token": "letmein"},
    )
    assert ok.status_code == 200


def test_body_too_large_rejected(client):
    big = "x" * 70000
    resp = client.post(
        "/hook/alerts", content=big, headers={"Content-Type": "text/plain"}
    )
    assert resp.status_code == 413


def test_form_encoded_payload(client):
    body = "payload=" + json.dumps({"text": "viaform"})
    resp = client.post(
        "/hook/alerts",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert client.captured["body"] == "viaform"

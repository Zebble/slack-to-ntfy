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
      Title: "{{ title }}"
      Priority: "{{ priority }}"
    body: "{{ message }}"
    secrets:
      token: "tk"
  - name: secured
    url: "https://ntfy.example.com/secured"
    body: "{{ message }}"
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


def test_index_lists_endpoints(client):
    data = client.get("/").json()
    names = {e["name"] for e in data["endpoints"]}
    assert names == {"alerts", "secured"}


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_hook_forwards_slack_payload(client):
    resp = client.post("/hook/alerts", json={"text": "boom", "username": "mon"})
    assert resp.status_code == 200
    assert resp.json()["ntfy_status"] == 200
    assert client.captured["url"] == "https://ntfy.example.com/alerts"
    assert client.captured["headers"]["Title"] == "mon"
    assert client.captured["body"] == "boom"


def test_unknown_endpoint_404(client):
    assert client.post("/hook/nope", json={"text": "x"}).status_code == 404


def test_inbound_token_required(client):
    assert client.post("/hook/secured", json={"text": "x"}).status_code == 401
    ok = client.post(
        "/hook/secured",
        json={"text": "x"},
        headers={"X-Slack-To-Ntfy-Token": "letmein"},
    )
    assert ok.status_code == 200


def test_form_encoded_payload(client):
    body = "payload=" + json.dumps({"text": "viaform"})
    resp = client.post(
        "/hook/alerts",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert client.captured["body"] == "viaform"

from app.config import EndpointConfig
from app.forwarder import build_request
from app.slack import build_context


def test_build_request_renders_proxmox_style_target():
    endpoint = EndpointConfig(
        name="dc_proxmox_alerts",
        url="https://ntfy.example.com/dc_proxmox_alerts",
        headers={
            "Authorization": "Bearer {{ secrets.token }}",
            "Title": "DC PVE - {{ title }}",
            "Priority": "{{ priority }}",
            "Tags": "computer",
        },
        body="{{ message }}",
        secrets={"token": "tk_secret"},
    )
    ctx = build_context(
        {
            "text": "VM 101 stopped",
            "username": "proxmox",
            "attachments": [{"color": "danger"}],
        }
    )
    method, url, headers, body = build_request(endpoint, ctx)

    assert method == "POST"
    assert url == "https://ntfy.example.com/dc_proxmox_alerts"
    assert headers["Authorization"] == "Bearer tk_secret"
    assert headers["Title"] == "DC PVE - proxmox"
    assert headers["Priority"] == "5"
    assert headers["Tags"] == "computer"
    assert body == "VM 101 stopped"


def test_missing_payload_field_renders_empty():
    endpoint = EndpointConfig(
        name="x",
        url="https://ntfy.example.com/x",
        headers={"Title": "{{ payload.nope.deep }}"},
        body="{{ message }}",
    )
    ctx = build_context({"text": "hi"})
    _, _, headers, _ = build_request(endpoint, ctx)
    assert headers["Title"] == ""

import json

from app.slack import build_context, parse_slack_request


def test_parse_json_body():
    body = json.dumps({"text": "hello"}).encode()
    assert parse_slack_request("application/json", body) == {"text": "hello"}


def test_parse_form_encoded_payload():
    body = b"payload=%7B%22text%22%3A%22hi%22%7D"  # {"text":"hi"}
    assert parse_slack_request(
        "application/x-www-form-urlencoded", body
    ) == {"text": "hi"}


def test_parse_plain_text_fallback():
    assert parse_slack_request("text/plain", b"just text") == {"text": "just text"}


def test_context_simple_text():
    ctx = build_context({"text": "Server is down", "username": "monitor"})
    assert ctx["message"] == "Server is down"
    assert ctx["title"] == "monitor"
    assert ctx["priority"] == 3


def test_context_header_and_attachment():
    payload = {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Disk Alert"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Usage at 95%"}},
        ],
        "attachments": [
            {
                "color": "danger",
                "title": "node1",
                "fields": [{"title": "Mount", "value": "/var", "short": True}],
            }
        ],
    }
    ctx = build_context(payload)
    assert ctx["title"] == "Disk Alert"
    assert "Usage at 95%" in ctx["message"]
    assert "Mount: /var" in ctx["message"]
    assert ctx["color"] == "danger"
    assert ctx["priority"] == 5


def test_link_unwrapping_and_emoji():
    payload = {
        "text": "See <https://example.com|the dashboard>",
        "icon_emoji": ":warning:",
    }
    ctx = build_context(payload)
    assert ctx["message"] == "See the dashboard (https://example.com)"
    assert ctx["emoji"] == "warning"


def test_color_priority_hex():
    ctx = build_context({"attachments": [{"color": "#36a64f", "text": "ok"}]})
    assert ctx["priority"] == 3

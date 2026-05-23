"""Parse Slack incoming-webhook payloads into a flat template context.

Any tool that can post to a Slack incoming webhook can instead post here. We
accept the same payload shapes Slack does (JSON body, or a form-encoded
`payload=` field) and flatten the interesting bits into variables that config
templates can reference: `{{ text }}`, `{{ title }}`, `{{ message }}`,
`{{ priority }}`, `{{ emoji }}`, `{{ color }}`, plus the full `{{ payload }}`.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs

# Slack link/mention syntax: <url|label>, <url>, <@U123|name>, <#C123|chan>.
_LINK_RE = re.compile(r"<([^>|]+)(?:\|([^>]+))?>")

# Maps Slack attachment colors to ntfy priorities (1=min .. 5=max/urgent).
_COLOR_PRIORITY = {
    "danger": 5,
    "warning": 4,
    "good": 3,
}
_HEX_PRIORITY = {
    "#ff0000": 5,
    "#f00": 5,
    "#e01e5a": 5,  # Slack red
    "#ff9900": 4,
    "#ffa500": 4,
    "#daa038": 4,  # Slack yellow
    "#36a64f": 3,
    "#2eb67d": 3,  # Slack green
}


def parse_slack_request(content_type: str, body: bytes) -> dict[str, Any]:
    """Decode a raw inbound request body into a Slack payload dict."""
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    text = body.decode("utf-8", errors="replace")

    if ctype == "application/x-www-form-urlencoded" or (
        not ctype and text.startswith("payload=")
    ):
        form = parse_qs(text, keep_blank_values=True)
        if "payload" in form:
            try:
                return json.loads(form["payload"][0])
            except (json.JSONDecodeError, IndexError):
                return {}
        # Bare form fields (e.g. text=hello) — fold single values into a dict.
        return {k: v[0] if len(v) == 1 else v for k, v in form.items()}

    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Not JSON — treat the whole body as the message text.
        return {"text": text}
    return data if isinstance(data, dict) else {"text": text}


def _unwrap_slack_markup(value: str) -> str:
    """Turn Slack's <url|label> / <@U123|name> markup into plain text."""

    def repl(match: re.Match[str]) -> str:
        target, label = match.group(1), match.group(2)
        if target.startswith(("@", "#")):  # user/channel mention
            return label or target
        if label:
            return f"{label} ({target})"
        return target

    out = _LINK_RE.sub(repl, value)
    out = out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return out


def _as_text(node: Any) -> str:
    """Best-effort extraction of human text from a Slack block/text node."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if "text" in node:
            return _as_text(node["text"])
        if "elements" in node:
            return " ".join(_as_text(e) for e in node["elements"]).strip()
    if isinstance(node, list):
        return " ".join(_as_text(n) for n in node).strip()
    return ""


def _render_blocks(blocks: list[Any]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in ("section", "header", "context"):
            txt = _as_text(block).strip()
            if txt:
                lines.append(txt)
        if btype == "section" and isinstance(block.get("fields"), list):
            for field in block["fields"]:
                txt = _as_text(field).strip()
                if txt:
                    lines.append(txt)
    return lines


def _render_attachments(attachments: list[Any]) -> list[str]:
    lines: list[str] = []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        for key in ("pretext", "author_name", "title", "text", "footer"):
            val = att.get(key)
            if isinstance(val, str) and val.strip():
                line = val.strip()
                if key == "title" and att.get("title_link"):
                    line = f"{line} ({att['title_link']})"
                lines.append(line)
        for field in att.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            ftitle = (field.get("title") or "").strip()
            fvalue = (field.get("value") or "").strip()
            if ftitle and fvalue:
                lines.append(f"{ftitle}: {fvalue}")
            elif fvalue:
                lines.append(fvalue)
    return lines


def _first_attachment_color(attachments: list[Any]) -> str:
    for att in attachments:
        if isinstance(att, dict) and att.get("color"):
            return str(att["color"])
    return ""


def _derive_priority(color: str) -> int:
    if not color:
        return 3
    key = color.strip().lower()
    if key in _COLOR_PRIORITY:
        return _COLOR_PRIORITY[key]
    return _HEX_PRIORITY.get(key, 3)


def build_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Slack payload into variables available to config templates."""
    blocks = payload.get("blocks") or []
    attachments = payload.get("attachments") or []

    block_lines = _render_blocks(blocks) if isinstance(blocks, list) else []
    att_lines = _render_attachments(attachments) if isinstance(attachments, list) else []

    top_text = payload.get("text")
    top_text = top_text.strip() if isinstance(top_text, str) else ""

    parts: list[str] = []
    if top_text:
        parts.append(top_text)
    parts.extend(block_lines)
    parts.extend(att_lines)
    message = _unwrap_slack_markup("\n".join(p for p in parts if p).strip())

    # Title preference: header block -> first attachment title -> username -> default.
    title = ""
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "header":
                title = _as_text(block).strip()
                if title:
                    break
    if not title and isinstance(attachments, list):
        for att in attachments:
            if isinstance(att, dict) and (att.get("title") or "").strip():
                title = att["title"].strip()
                break
    if not title:
        title = (payload.get("username") or "").strip()
    if not title:
        title = "Slack notification"
    title = _unwrap_slack_markup(title)

    color = _first_attachment_color(attachments) if isinstance(attachments, list) else ""
    icon_emoji = payload.get("icon_emoji") or ""
    emoji = icon_emoji.strip(":") if isinstance(icon_emoji, str) else ""

    if not message:
        message = title

    return {
        "payload": payload,
        "text": top_text,
        "message": message,
        "title": title,
        "username": payload.get("username") or "",
        "channel": payload.get("channel") or "",
        "icon_emoji": icon_emoji,
        "icon_url": payload.get("icon_url") or "",
        "emoji": emoji,
        "color": color,
        "priority": _derive_priority(color),
        "attachments": attachments if isinstance(attachments, list) else [],
        "blocks": blocks if isinstance(blocks, list) else [],
    }

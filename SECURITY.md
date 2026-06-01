# Security Policy

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Use GitHub's private vulnerability reporting instead:
<https://github.com/Zebble/slack-to-ntfy/security/advisories/new>

I'll aim to acknowledge reports within a few business days.

## Scope

This project is a public-facing webhook bridge, so reports of the following
are especially welcome:

- Authentication or authorization bypass on `/hook/<name>`
- Endpoint enumeration via response differences (status code, body, timing)
- Server-side template injection or sandbox escape via the Jinja2 templates
  (note: templates are operator-supplied, but Slack payload data flows through
  them and shouldn't be able to break out of the sandbox)
- Resource exhaustion that bypasses `MAX_BODY_BYTES`
- Token/secret leakage in logs or error responses

## Out of scope

- Findings that require an already-compromised operator account or local
  filesystem access
- Misconfigurations in a specific deployment (e.g. a missing `inbound_token`
  on a publicly reachable endpoint) — these are deployment issues, not bugs
  in the project

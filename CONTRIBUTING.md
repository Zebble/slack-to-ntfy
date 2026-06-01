# Contributing

Contributions are welcome. For anything larger than a small fix, please open
an issue first to discuss the change.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env             # tokens / settings; loaded automatically
cp config.example.yaml config.yaml
pytest                           # run the test suite
CONFIG_PATH=./config.yaml uvicorn app.main:app --reload
```

The Dockerfile and CI both target Python 3.12.

## Pull requests

- Keep changes focused — one logical change per PR.
- Add or update tests for behavior changes.
- Update the README, `config.example.yaml`, and `.env.example` when you add
  or change a configuration knob.
- `pytest` must pass; CI will run it on every PR.
- Don't commit real tokens, topic URLs, or other secrets. `.env` and
  `config.yaml` are gitignored for that reason.

## Reporting security issues

Please follow [SECURITY.md](SECURITY.md) — do not file public issues for
vulnerabilities.

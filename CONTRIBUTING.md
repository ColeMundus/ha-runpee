# Contributing

Use Python 3.14.7 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked --no-default-groups --group dev
uv pip check --python .venv/bin/python
uv run --no-sync python scripts/check_compat.py minimum
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest --cov=custom_components.runpee --cov-branch --cov-report=term-missing --cov-fail-under=90
uv run --no-sync python scripts/package.py
git diff --check
```

Run the latest tested Core in a separate environment; the two harness groups are intentionally incompatible:

```sh
export UV_PROJECT_ENVIRONMENT=.venv-latest
uv sync --locked --no-default-groups --group latest
uv pip check --python "$UV_PROJECT_ENVIRONMENT/bin/python"
uv run --no-sync python scripts/check_compat.py latest
uv run --no-sync pytest --cov=custom_components.runpee --cov-branch --cov-report=term-missing --cov-fail-under=90
unset UV_PROJECT_ENVIRONMENT
```

The pinned lanes are Core 2026.10.0 and 2026.11.0, not a claim that every intervening release was independently tested. Clear inherited `PYTHONPATH`/`PYTHONHOME` overrides when running from an agent or another project's environment.

Tests must stay offline and use synthetic data. Exercise actual Home Assistant flows and lifecycle APIs; mock the provider boundary, not Home Assistant itself. Do not commit real API responses, APKs, credentials, personal playback history, or assistant workspace files.

Dependency changes are proposed by Dependabot and reviewed before merging. Never silently update installed integrations.

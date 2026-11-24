"""Compatibility pin guards and the literal required-job entry point."""

import itertools
import json
import runpy
from pathlib import Path

import pytest
import yaml

from scripts.check_compat import HARNESSES, LANES, validate


@pytest.mark.parametrize("lane", LANES)
def test_exact_lane(lane):
    validate(lane, dict(LANES[lane]), (3, 14, 7))


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("package", ["homeassistant", "harness", "aiohttp", "probatio"])
@pytest.mark.parametrize("wrong", ["0.0.0", None])
def test_reject_wrong_or_missing_pin(lane, package, wrong):
    installed = dict(LANES[lane])
    if package == "harness":
        package = next(name for name in HARNESSES if name in installed)
    if wrong is None:
        del installed[package]
    else:
        installed[package] = wrong
    with pytest.raises(ValueError):
        validate(lane, installed, (3, 14, 7))


@pytest.mark.parametrize("lane", LANES)
def test_reject_overlapping_or_other_harness_and_python(lane):
    installed = dict(LANES[lane])
    other = next(name for name in HARNESSES if name not in installed)
    installed[other] = "2026.11.0" if lane == "minimum" else "0.13.371"
    with pytest.raises(ValueError, match="Exactly one"):
        validate(lane, installed, (3, 14, 7))
    correct = next(name for name in HARNESSES if name in LANES[lane])
    del installed[correct]
    with pytest.raises(ValueError):
        validate(lane, installed, (3, 14, 7))
    with pytest.raises(ValueError, match="Python"):
        validate(lane, dict(LANES[lane]), (3, 14, 2))


def test_literal_gate_all_outcomes(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["checks"]["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "include": [
                {"lane": "minimum", "group": "dev"},
                {"lane": "latest", "group": "latest"},
            ]
        },
    }
    assert (
        jobs["required"]["if"]
        == "${{ always() && needs.scope.outputs.docs_only != 'true' }}"
    )
    assert set(jobs["required"]["needs"]) == {
        "scope",
        "checks",
        "hassfest",
        "hacs",
        "actionlint",
    }
    hacs_condition = jobs["hacs"]["if"]
    assert "github.event.repository.private == false" in hacs_condition
    assert "needs.scope.outputs.docs_only != 'true'" in hacs_condition
    command = jobs["required"]["steps"][-1]["run"]
    assert command == "python3 scripts/check_ci.py"
    outcomes = ("success", "failure", "skipped", "cancelled")
    for private, checks, hassfest, hacs in itertools.product(
        (True, False), outcomes, outcomes, outcomes
    ):
        results = {
            "checks": checks,
            "hassfest": hassfest,
            "hacs": hacs,
            "actionlint": "success",
        }
        with monkeypatch.context() as environment:
            environment.setenv("PRIVATE", json.dumps(private))
            environment.setenv(
                "NEEDS",
                json.dumps({key: {"result": value} for key, value in results.items()}),
            )
            with pytest.raises(SystemExit) as exit_status:
                runpy.run_path(str(root / "scripts/check_ci.py"), run_name="__main__")
        expected = checks == hassfest == "success" and hacs == (
            "skipped" if private else "success"
        )
        assert exit_status.value.code == (0 if expected else 1), results

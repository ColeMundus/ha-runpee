"""Compatibility pin guards and the literal required-job entry point."""

import itertools
import json
import os
import subprocess
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


def test_literal_gate_all_outcomes():
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
    assert jobs["required"]["if"] == "always()"
    assert set(jobs["required"]["needs"]) == {"checks", "hassfest", "hacs"}
    assert jobs["hacs"]["if"] == "github.event.repository.private == false"
    command = jobs["required"]["steps"][-1]["run"]
    assert command == "python3 scripts/check_ci.py"
    outcomes = ("success", "failure", "skipped", "cancelled")
    for private, checks, hassfest, hacs in itertools.product(
        (True, False), outcomes, outcomes, outcomes
    ):
        results = {"checks": checks, "hassfest": hassfest, "hacs": hacs}
        result = subprocess.run(
            command,
            shell=True,
            cwd=root,
            env={
                **os.environ,
                "PRIVATE": json.dumps(private),
                "NEEDS": json.dumps(
                    {key: {"result": value} for key, value in results.items()}
                ),
            },
            capture_output=True,
            timeout=10,
            check=False,
        )
        expected = checks == hassfest == "success" and hacs == (
            "skipped" if private else "success"
        )
        assert result.returncode == (0 if expected else 1), results

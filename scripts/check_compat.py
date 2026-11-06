"""Reject drift from the locked, mutually exclusive compatibility lanes."""

import argparse
import importlib
import json
import sys
from importlib.metadata import PackageNotFoundError, version

LANES = {
    "minimum": {
        "homeassistant": "2026.10.0",
        "pytest-homeassistant-custom-component": "0.13.371",
        "aiohttp": "3.14.4",
        "probatio": "0.13.0",
    },
    "latest": {
        "homeassistant": "2026.11.0",
        "pytest-homeassistant": "2026.11.0",
        "aiohttp": "3.14.5",
        "probatio": "0.13.0",
    },
}
HARNESSES = ("pytest-homeassistant", "pytest-homeassistant-custom-component")


def validate(lane: str, installed: dict[str, str], python: tuple[int, ...]) -> None:
    """Validate exact Core, harness and framework pins, rejecting overlap."""
    expected = LANES[lane]
    if python != (3, 14, 7):
        raise ValueError(f"Wrong Python version: {python}")
    if sum(name in installed for name in HARNESSES) != 1:
        raise ValueError("Exactly one harness must be installed")
    for name, pin in expected.items():
        if installed.get(name) != pin:
            raise ValueError(f"Wrong {name}: expected {pin}, got {installed.get(name)}")


def main() -> None:
    """Read real distribution metadata and print actual framework import paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=LANES)
    args = parser.parse_args()
    installed = {}
    for name in set(LANES[args.lane]) | set(HARNESSES):
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            pass
    validate(args.lane, installed, sys.version_info[:3])
    # Core must install its HTTPX/validation aliases before dependent imports.
    modules = ["homeassistant", "aiohttp", "probatio"]
    modules.append(
        "pytest_homeassistant"
        if "pytest-homeassistant" in installed
        else "pytest_homeassistant_custom_component"
    )
    paths = {name: importlib.import_module(name).__file__ for name in modules}
    print(json.dumps({"python": sys.version, "versions": installed, "paths": paths}))


if __name__ == "__main__":
    main()

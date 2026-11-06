"""Exercise distribution guards with synthetic, isolated package trees."""

import hashlib
import itertools
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from scripts.check_ci import accepted
from scripts.package import FILES, PREFIX, build


@pytest.fixture
def package_tree(tmp_path: Path) -> Path:
    """Construct only synthetic content, never live provider responses."""
    component = tmp_path / PREFIX
    for relative in FILES:
        target = component / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic\n")
    (tmp_path / "LICENSE").write_text("synthetic\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0b0"\n')
    (component / "manifest.json").write_text(
        json.dumps({"domain": "runpee", "version": "0.1.0b0"})
    )
    for relative in ("strings.json", "translations/en.json"):
        (component / relative).write_text("{}")
    Image.new("RGBA", (256, 256)).save(component / "brand/icon.png")
    return tmp_path


def test_package_is_deterministic_complete_and_checksummed(package_tree: Path) -> None:
    archive = build(package_tree, package_tree / "dist")
    first = archive.read_bytes()
    assert build(package_tree, package_tree / "dist").read_bytes() == first
    assert archive.with_suffix(".zip.sha256").read_text() == (
        f"{hashlib.sha256(first).hexdigest()}  {archive.name}\n"
    )
    with zipfile.ZipFile(archive) as package:
        assert package.namelist() == [f"{PREFIX}/{name}" for name in sorted(FILES)]
        assert all(".." not in Path(name).parts for name in package.namelist())
        destination = package_tree / "installed"
        package.extractall(destination)
        assert (destination / PREFIX / "LICENSE").read_text() == "synthetic\n"


@pytest.mark.parametrize(
    "change",
    ["extra", "missing", "symlink", "version", "translation", "license", "icon"],
)
def test_package_rejects_drift(package_tree: Path, change: str) -> None:
    component = package_tree / PREFIX
    if change == "extra":
        (component / "capture.json").write_text("{}")
    elif change == "missing":
        (component / "client.py").unlink()
    elif change == "symlink":
        target = component / "client.py"
        target.unlink()
        target.symlink_to(package_tree / "LICENSE")
    elif change == "version":
        (component / "manifest.json").write_text(
            '{"domain":"runpee", "version":"1.0.0"}'
        )
    elif change == "translation":
        (component / "translations/en.json").write_text('{"different":true}')
    elif change == "license":
        (component / "LICENSE").write_text("different")
    else:
        Image.new("RGB", (32, 32)).save(component / "brand/icon.png")
    with pytest.raises(ValueError):
        build(package_tree, package_tree / "dist")


def test_package_rejects_symlinked_root(package_tree: Path) -> None:
    component = package_tree / PREFIX
    renamed = component.with_name("elsewhere")
    component.rename(renamed)
    component.symlink_to(renamed, target_is_directory=True)
    with pytest.raises(ValueError, match="root"):
        build(package_tree, package_tree / "dist")


def test_ci_gate_fails_closed() -> None:
    outcomes = ("success", "failure", "cancelled", "skipped")
    for private, checks, hassfest, hacs in itertools.product(
        (True, False), outcomes, outcomes, outcomes
    ):
        assert accepted(
            private, {"checks": checks, "hassfest": hassfest, "hacs": hacs}
        ) == (
            checks == hassfest == "success"
            and hacs == ("skipped" if private else "success")
        )
    assert not accepted(False, {})


@pytest.mark.parametrize("private", [True, False])
def test_literal_ci_entrypoint(private: bool) -> None:
    root = Path(__file__).resolve().parents[2]
    results = {"checks": "success", "hassfest": "success", "hacs": "skipped"}
    env = {
        **os.environ,
        "PRIVATE": json.dumps(private),
        "NEEDS": json.dumps({key: {"result": value} for key, value in results.items()}),
    }
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_ci.py")],
        env=env,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == (0 if private else 1)

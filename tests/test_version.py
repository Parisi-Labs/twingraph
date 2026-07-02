"""Version metadata stays in lockstep across pyproject, package, and changelog."""

import re
import tomllib
from pathlib import Path

import twingraph

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    with (_PACKAGE_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_dunder_version_matches_pyproject():
    assert twingraph.__version__ == _pyproject_version()


def test_changelog_has_entry_for_current_version():
    changelog = (_PACKAGE_ROOT / "CHANGELOG.md").read_text()
    version = _pyproject_version()
    pattern = rf"^## \[{re.escape(version)}\]"
    assert re.search(pattern, changelog, flags=re.MULTILINE), (
        f"CHANGELOG.md has no '## [{version}]' section for the current version"
    )

"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from papercrown.project.manifest import Manifest, build_manifest
from papercrown.project.recipe import BookConfig, load_book_config

# Repository root shared by tests that need project-relative paths.
PAPERCROWN_ROOT = Path(__file__).parent.parent.resolve()
# Root directory for test fixtures.
FIXTURE_ROOT = Path(__file__).parent / "fixtures"
# Canonical minimal recipe used by smoke-style unit tests.
MINI_RECIPE_PATH = FIXTURE_ROOT / "recipes" / "mini.yaml"


@pytest.fixture(scope="session")
def papercrown_root() -> Path:
    return PAPERCROWN_ROOT


@pytest.fixture(scope="session")
def fixture_root() -> Path:
    return FIXTURE_ROOT


@pytest.fixture(scope="session")
def mini_recipe_path() -> Path:
    return MINI_RECIPE_PATH


@pytest.fixture
def mini_recipe() -> BookConfig:
    return load_book_config(MINI_RECIPE_PATH)


@pytest.fixture
def mini_manifest(mini_recipe) -> Manifest:
    return build_manifest(mini_recipe)


@pytest.fixture(scope="session")
def has_external_tools() -> dict[str, bool]:
    """Detect which optional external tools are available."""
    return {
        "pandoc": shutil.which("pandoc") is not None,
        "obsidian-export": shutil.which("obsidian-export") is not None,
        "weasyprint": (
            (PAPERCROWN_ROOT / ".venv" / "Scripts" / "weasyprint.exe").is_file()
            or (PAPERCROWN_ROOT / ".venv" / "bin" / "weasyprint").is_file()
            or shutil.which("weasyprint") is not None
        ),
    }


@pytest.fixture
def require_pandoc(has_external_tools):
    if not has_external_tools["pandoc"]:
        pytest.skip("pandoc not installed")


@pytest.fixture
def require_weasyprint(has_external_tools):
    if not has_external_tools["weasyprint"]:
        pytest.skip("weasyprint not installed")

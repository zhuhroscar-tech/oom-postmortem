"""Regression tests for current setuptools packaging metadata."""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def test_license_metadata_uses_spdx_string_form():
    text = PYPROJECT.read_text()

    assert 'license = "MIT"' in text
    assert 'license-files = ["LICENSE"]' in text
    assert "license = {" not in text
    assert "License :: OSI Approved :: MIT License" not in text


def test_build_backend_requires_current_setuptools_for_spdx_license_metadata():
    text = PYPROJECT.read_text()

    assert 'requires = ["setuptools>=77", "wheel"]' in text

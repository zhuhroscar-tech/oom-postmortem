"""Repository-level contract checks for release hygiene."""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CURRENT_VERSION = "0.1.7"


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_required_project_files_exist():
    required = [
        "README.md",
        "README.zh-CN.md",
        "CHANGELOG.md",
        "LICENSE",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
    ]

    missing = [path for path in required if not (PROJECT_ROOT / path).is_file()]
    assert missing == []


def test_readmes_link_release_history_license_and_downloads():
    for filename in ("README.md", "README.zh-CN.md"):
        text = _read(filename)
        assert "https://github.com/zhuhroscar-tech/oom-postmortem/releases" in text
        assert "SHA256SUMS.txt" in text
        assert "CHANGELOG.md" in text
        assert "LICENSE" in text
        assert "oom-postmortem.pyz" in text


def test_changelog_tracks_current_version_and_initial_release():
    changelog = _read("CHANGELOG.md")

    assert f"## v{CURRENT_VERSION} - " in changelog
    assert "## v0.1.0 - " in changelog
    assert "kernel OOM killer" in changelog
    assert "systemd-oomd" in changelog
    assert "memory.events" in changelog


def test_ci_builds_and_smokes_downloadable_artifacts():
    ci = _read(".github/workflows/ci.yml")

    assert "python -m pytest" in ci
    assert "python -m build" in ci
    assert "dist/oom-postmortem.pyz" in ci
    assert "oom-postmortem --version" in ci
    assert "SHA256SUMS.txt" in ci
    assert "actions/upload-artifact" in ci


def test_codeql_scans_python_on_main_and_schedule():
    codeql = _read(".github/workflows/codeql.yml")

    assert "github/codeql-action/init" in codeql
    assert "languages: python" in codeql
    assert re.search(r"branches:\s*\[main\]", codeql)
    assert "schedule:" in codeql

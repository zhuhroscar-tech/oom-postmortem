import json

import pytest

from oom_postmortem.cli import main
from oom_postmortem.core import (
    KernelOomEvent,
    OomPostmortemReport,
    MECHANISM_KERNEL_OOM,
    MECHANISM_NONE_FOUND,
)


def _fake_report(mechanism=MECHANISM_KERNEL_OOM):
    return OomPostmortemReport(
        mechanism=mechanism,
        explanation="example explanation",
        kernel_events=[KernelOomEvent(pid="123", comm="myservice", raw_line="raw", oom_score_adj=200)],
    )


def test_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert "oom-postmortem" in capsys.readouterr().out


def test_text_output(monkeypatch, capsys):
    monkeypatch.setattr("oom_postmortem.cli.diagnose_host", lambda since: _fake_report())
    rc = main([])
    out = capsys.readouterr().out
    assert "kernel_oom" in out
    assert "myservice" in out
    assert rc == 2


def test_json_output(monkeypatch, capsys):
    monkeypatch.setattr("oom_postmortem.cli.diagnose_host", lambda since: _fake_report())
    rc = main(["--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["mechanism"] == MECHANISM_KERNEL_OOM
    assert rc == 2


def test_none_found_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        "oom_postmortem.cli.diagnose_host",
        lambda since: OomPostmortemReport(mechanism=MECHANISM_NONE_FOUND, explanation="nothing"),
    )
    rc = main([])
    assert rc == 0


def test_since_passed_through(monkeypatch):
    captured = {}

    def fake_diagnose(since):
        captured["since"] = since
        return OomPostmortemReport(mechanism=MECHANISM_NONE_FOUND, explanation="nothing")

    monkeypatch.setattr("oom_postmortem.cli.diagnose_host", fake_diagnose)
    main(["--since", "1 hour ago"])
    assert captured["since"] == "1 hour ago"

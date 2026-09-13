import json

import pytest

from oom_postmortem.cli import main
from oom_postmortem.core import (
    KernelOomEvent,
    OomPostmortemReport,
    MECHANISM_DIAGNOSTIC_FAILED,
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


def test_diagnostic_failed_returns_three_and_warn_level(monkeypatch, capsys):
    monkeypatch.setattr(
        "oom_postmortem.cli.diagnose_host",
        lambda since: OomPostmortemReport(
            mechanism=MECHANISM_DIAGNOSTIC_FAILED, explanation="journal unreadable"
        ),
    )
    rc = main(["--no-color"])
    out = capsys.readouterr().out
    assert "diagnostic_failed" in out
    assert "journal unreadable" in out
    assert rc == 3


def test_diagnostic_failed_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        "oom_postmortem.cli.diagnose_host",
        lambda since: OomPostmortemReport(
            mechanism=MECHANISM_DIAGNOSTIC_FAILED, explanation="journal unreadable"
        ),
    )
    rc = main(["--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["mechanism"] == MECHANISM_DIAGNOSTIC_FAILED
    assert rc == 3


def test_since_passed_through(monkeypatch):
    captured = {}

    def fake_diagnose(since):
        captured["since"] = since
        return OomPostmortemReport(mechanism=MECHANISM_NONE_FOUND, explanation="nothing")

    monkeypatch.setattr("oom_postmortem.cli.diagnose_host", fake_diagnose)
    main(["--since", "1 hour ago"])
    assert captured["since"] == "1 hour ago"


def test_text_output_prints_oomd_and_cgroup_sections(monkeypatch, capsys):
    from oom_postmortem.core import OomdEvent, CgroupOomEvent, MECHANISM_SYSTEMD_OOMD

    report = OomPostmortemReport(
        mechanism=MECHANISM_SYSTEMD_OOMD,
        explanation="oomd explanation",
        oomd_events=[OomdEvent(unit_or_cgroup="myservice.service", raw_line="raw")],
        cgroup_events=[CgroupOomEvent(cgroup_path="/sys/fs/cgroup/x", oom_kill_count=3)],
    )
    monkeypatch.setattr("oom_postmortem.cli.diagnose_host", lambda since: report)
    rc = main(["--no-color"])
    out = capsys.readouterr().out
    assert "systemd-oomd kills" in out
    assert "myservice.service" in out
    assert "oom_kill counters" in out
    assert "oom_kill=3" in out
    assert rc == 2

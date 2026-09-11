import subprocess

from oom_postmortem.core import (
    MECHANISM_CGROUP_LIMIT,
    MECHANISM_KERNEL_OOM,
    MECHANISM_NONE_FOUND,
    MECHANISM_SYSTEMD_OOMD,
    diagnose,
    diagnose_host,
    find_cgroup_oom_events,
    get_kernel_oom_events,
    get_oomd_events,
    parse_kernel_oom_journal,
    parse_memory_events,
    parse_oomd_journal,
    run,
)


KERNEL_OOM_SAMPLE = (
    "2026-09-10T03:12:12+0000 host kernel: myservice invoked oom-killer: "
    "gfp_mask=0x140cca(GFP_HIGHUSER_MOVABLE), order=0, oom_score_adj=200\n"
    "2026-09-10T03:12:12+0000 host kernel: Out of memory: Killed process "
    "1966928 (llama-server) total-vm:164222812kB anon-rss:31651260kB "
    "oom_score_adj:200\n"
)

OOMD_SAMPLE = (
    "2026-09-10T10:40:58+0000 host systemd-oomd[783]: Killed "
    "/system.slice/myservice.service due to memory pressure for "
    "/system.slice being 63.30% > 50.00% for > 20s with reclaim activity\n"
)

MEMORY_EVENTS_SAMPLE = "low 0\nhigh 3\nmax 5\noom 1\noom_kill 2\noom_group_kill 0\n"
MEMORY_EVENTS_SAMPLE_ZERO = "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n"


def test_parse_kernel_oom_journal():
    events = parse_kernel_oom_journal(KERNEL_OOM_SAMPLE)
    assert len(events) == 1
    assert events[0].pid == "1966928"
    assert events[0].comm == "llama-server"
    assert events[0].oom_score_adj == 200


def test_parse_kernel_oom_journal_no_match():
    assert parse_kernel_oom_journal("nothing relevant here") == []


def test_get_kernel_oom_events_uses_runner():
    def fake_runner(cmd, timeout=15):
        assert cmd[0] == "journalctl"
        assert "-k" in cmd
        return KERNEL_OOM_SAMPLE

    events = get_kernel_oom_events(runner=fake_runner)
    assert len(events) == 1


def test_get_kernel_oom_events_passes_since():
    captured = {}

    def fake_runner(cmd, timeout=15):
        captured["cmd"] = cmd
        return ""

    get_kernel_oom_events(since="1 hour ago", runner=fake_runner)
    assert "--since" in captured["cmd"]
    assert "1 hour ago" in captured["cmd"]


def test_parse_oomd_journal():
    events = parse_oomd_journal(OOMD_SAMPLE)
    assert len(events) == 1
    assert events[0].unit_or_cgroup == "/system.slice/myservice.service"


def test_get_oomd_events_uses_runner():
    def fake_runner(cmd, timeout=15):
        assert "systemd-oomd" in cmd
        return OOMD_SAMPLE

    events = get_oomd_events(runner=fake_runner)
    assert len(events) == 1


def test_parse_memory_events_nonzero():
    assert parse_memory_events(MEMORY_EVENTS_SAMPLE) == 2


def test_parse_memory_events_zero():
    assert parse_memory_events(MEMORY_EVENTS_SAMPLE_ZERO) == 0


def test_parse_memory_events_missing_key():
    assert parse_memory_events("low 0\nhigh 0\n") is None


def test_parse_memory_events_malformed_value_returns_none():
    # A corrupted/truncated cgroup memory.events file should not crash the
    # tool -- the oom_kill counter must be a valid integer, and if it isn't
    # (disk corruption, partial read, unexpected kernel format change) the
    # parser must degrade to None rather than raising.
    assert parse_memory_events("oom_kill not-a-number\n") is None


def test_find_cgroup_oom_events_filters_zero_counts():
    def fake_runner(cmd, timeout=15):
        if cmd[0] == "find":
            return "/sys/fs/cgroup/system.slice/a.service/memory.events\n/sys/fs/cgroup/system.slice/b.service/memory.events\n"
        if cmd[0] == "cat":
            if "a.service" in cmd[1]:
                return MEMORY_EVENTS_SAMPLE
            return MEMORY_EVENTS_SAMPLE_ZERO
        return ""

    events = find_cgroup_oom_events(runner=fake_runner)
    assert len(events) == 1
    assert events[0].oom_kill_count == 2
    assert "a.service" in events[0].cgroup_path


def test_diagnose_prioritizes_kernel_oom():
    report = diagnose(
        kernel_events=parse_kernel_oom_journal(KERNEL_OOM_SAMPLE),
        oomd_events=parse_oomd_journal(OOMD_SAMPLE),
        cgroup_events=[],
    )
    assert report.mechanism == MECHANISM_KERNEL_OOM


def test_diagnose_falls_back_to_oomd():
    report = diagnose(
        kernel_events=[],
        oomd_events=parse_oomd_journal(OOMD_SAMPLE),
        cgroup_events=[],
    )
    assert report.mechanism == MECHANISM_SYSTEMD_OOMD


def test_diagnose_falls_back_to_cgroup_limit():
    def fake_runner(cmd, timeout=15):
        if cmd[0] == "find":
            return "/sys/fs/cgroup/system.slice/a.service/memory.events\n"
        if cmd[0] == "cat":
            return MEMORY_EVENTS_SAMPLE
        return ""

    report = diagnose(
        kernel_events=[],
        oomd_events=[],
        cgroup_events=find_cgroup_oom_events(runner=fake_runner),
    )
    assert report.mechanism == MECHANISM_CGROUP_LIMIT


def test_diagnose_none_found():
    report = diagnose(kernel_events=[], oomd_events=[], cgroup_events=[])
    assert report.mechanism == MECHANISM_NONE_FOUND


def test_report_to_dict_roundtrip():
    report = diagnose(
        kernel_events=parse_kernel_oom_journal(KERNEL_OOM_SAMPLE),
        oomd_events=[],
        cgroup_events=[],
    )
    d = report.to_dict()
    assert d["mechanism"] == MECHANISM_KERNEL_OOM
    assert d["kernel_events"][0]["pid"] == "1966928"


def test_diagnose_host_integration():
    def fake_runner(cmd, timeout=15):
        if cmd[0] == "journalctl" and "-k" in cmd:
            return KERNEL_OOM_SAMPLE
        if cmd[0] == "journalctl":
            return ""
        if cmd[0] == "find":
            return ""
        return ""

    report = diagnose_host(runner=fake_runner)
    assert report.mechanism == MECHANISM_KERNEL_OOM


def test_run_returns_stdout_on_success(monkeypatch):
    class FakeResult:
        stdout = "hello\n"

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: FakeResult()
    )
    assert run(["echo", "hi"]) == "hello\n"


def test_run_returns_empty_on_missing_binary(monkeypatch):
    def raise_oserror(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr(subprocess, "run", raise_oserror)
    assert run(["definitely-not-a-real-binary"]) == ""


def test_run_returns_empty_on_subprocess_error(monkeypatch):
    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="journalctl", timeout=15)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert run(["journalctl"], timeout=15) == ""


def test_find_cgroup_oom_events_skips_blank_lines():
    def fake_runner(cmd, timeout=15):
        if cmd[0] == "find":
            return "\n/sys/fs/cgroup/system.slice/a.service/memory.events\n\n"
        if cmd[0] == "cat":
            return MEMORY_EVENTS_SAMPLE
        return ""

    events = find_cgroup_oom_events(runner=fake_runner)
    assert len(events) == 1


def test_find_cgroup_oom_events_no_matches():
    def fake_runner(cmd, timeout=15):
        return ""

    assert find_cgroup_oom_events(runner=fake_runner) == []

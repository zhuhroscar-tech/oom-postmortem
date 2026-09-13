"""Core logic for oom-postmortem.

The problem: "something got OOM-killed" on modern Linux can mean at
least three genuinely distinct mechanisms, each logged in a different
place, each requiring a different fix -- and a detailed 2026 write-up
(cr0x.net's "Ubuntu 24.04 OOM killer: prove it, fix it, prevent repeats")
walks the exact same multi-source manual correlation every time because
no tool automates it:

  1. The classic kernel OOM killer -- the kernel cannot satisfy an
     allocation and reclaim fails; it scores every process by
     oom_badness() and SIGKILLs the worst offender. Logged in the
     kernel ring buffer / `journalctl -k` as "Out of memory: Killed
     process ...".

  2. systemd-oomd -- a userspace daemon that watches PSI (pressure
     stall information) per cgroup and proactively kills a whole
     cgroup/unit *before* the kernel would ever trigger, when
     sustained memory pressure crosses a configured threshold. Logged
     via `journalctl -u systemd-oomd` as "Killed ... due to memory
     pressure".

  3. cgroup v2 memory-limit OOM -- a process is killed because its own
     cgroup (a systemd unit's MemoryMax=, a container's memory limit,
     a Kubernetes pod's QoS-derived limit) was exceeded, even while the
     *host* has plenty of free RAM. Evidenced by `oom_kill` counters
     incrementing in that cgroup's `memory.events` file, not by any
     host-wide "Out of memory" journal line.

Given a target (a PID that no longer exists, a unit name, or nothing --
scan everything), this tool correlates the kernel journal, the
systemd-oomd journal, and cgroup `memory.events` files to answer: which
mechanism killed it, when, and what evidence backs that conclusion --
instead of a human manually running `journalctl -k`, `journalctl -u
systemd-oomd`, and `find /sys/fs/cgroup -name memory.events` and
reconciling timestamps by hand.

Strictly read-only: never kills anything, never modifies OOMScoreAdjust,
memory limits, or cgroup settings. It only reads journal and cgroupfs
files.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


MECHANISM_KERNEL_OOM = "kernel_oom"
MECHANISM_SYSTEMD_OOMD = "systemd_oomd"
MECHANISM_CGROUP_LIMIT = "cgroup_memory_limit"
MECHANISM_NONE_FOUND = "no_oom_kill_found"
MECHANISM_DIAGNOSTIC_FAILED = "diagnostic_failed"

MECHANISM_EXPLANATIONS = {
    MECHANISM_KERNEL_OOM: (
        "The kernel's global OOM killer fired: it could not satisfy a memory "
        "allocation anywhere on the host and reclaim failed, so it scored "
        "every candidate process by oom_badness() and killed the worst "
        "offender. This means the whole host was under real memory pressure, "
        "not just one cgroup."
    ),
    MECHANISM_SYSTEMD_OOMD: (
        "systemd-oomd killed this proactively based on sustained PSI (pressure "
        "stall information) for the process's cgroup/slice, before the kernel "
        "itself would have hit a hard OOM. It kills at the cgroup level (the "
        "whole unit/slice), not just one process, by design."
    ),
    MECHANISM_CGROUP_LIMIT: (
        "The process was killed because its own cgroup (a systemd unit's "
        "MemoryMax=, a container's memory limit, or similar) was exceeded -- "
        "'memory.events' for that cgroup shows oom_kill incrementing. This can "
        "happen even while the host overall has plenty of free RAM; it is a "
        "local limit, not global exhaustion."
    ),
    MECHANISM_NONE_FOUND: (
        "No kernel OOM kill, systemd-oomd kill, or cgroup oom_kill event was "
        "found in the inspected window/target. The process may have exited "
        "for a different reason (crash, manual kill, normal exit)."
    ),
    MECHANISM_DIAGNOSTIC_FAILED: (
        "Could not reliably determine whether an OOM kill occurred: one or "
        "more underlying reads (journalctl -k, journalctl -u systemd-oomd, "
        "or the cgroupfs memory.events scan) failed -- most commonly because "
        "the current user lacks permission to read the systemd journal (not "
        "a member of the 'systemd-journal'/'adm' group; try running as root "
        "or via sudo) or /sys/fs/cgroup could not be walked. This is NOT a "
        "confirmed 'no OOM kill happened' result -- it means the check "
        "itself could not run to completion."
    ),
}


def run(cmd: list, timeout: int = 15) -> Optional[str]:
    """Run a read-only subprocess command, returning stdout.

    Returns None (not "") when the command could not be run or exited
    non-zero -- distinct from a real empty result -- so callers can tell
    "this read genuinely found nothing" apart from "this read failed
    (permission denied, missing binary, timeout)". Journal-reading
    commands routinely fail with a nonzero exit and an empty stdout when
    the caller lacks permission to read the systemd journal; treating
    that the same as "no events" would silently misreport an
    undetermined result as a confirmed clean one.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout or ""


_KERNEL_OOM_RE = re.compile(
    r"Killed process (\d+) \(([^)]+)\).*?(?:total-vm|anon-rss)?", re.IGNORECASE
)
_OOM_SCORE_ADJ_RE = re.compile(r"oom_score_adj[:=]\s*(-?\d+)")


@dataclass
class KernelOomEvent:
    pid: str
    comm: str
    raw_line: str
    oom_score_adj: Optional[int] = None


def parse_kernel_oom_journal(text: str) -> list:
    """Parse `journalctl -k` output for kernel OOM-killer victim lines."""
    events = []
    for line in text.splitlines():
        m = _KERNEL_OOM_RE.search(line)
        if not m:
            continue
        adj_m = _OOM_SCORE_ADJ_RE.search(line)
        events.append(
            KernelOomEvent(
                pid=m.group(1),
                comm=m.group(2),
                raw_line=line,
                oom_score_adj=int(adj_m.group(1)) if adj_m else None,
            )
        )
    return events


def get_kernel_oom_events(since: Optional[str] = None, runner=run) -> tuple:
    """Returns (events, ok) -- ok is False when the underlying `journalctl -k`
    read itself failed (missing binary, permission denied, timeout), as
    opposed to running successfully and finding zero kernel OOM lines."""
    cmd = ["journalctl", "-k", "--no-pager", "-o", "short-iso"]
    if since:
        cmd += ["--since", since]
    text = runner(cmd)
    if text is None:
        return [], False
    return parse_kernel_oom_journal(text), True


_OOMD_KILL_RE = re.compile(r"Killed (\S+) due to memory pressure", re.IGNORECASE)


@dataclass
class OomdEvent:
    unit_or_cgroup: str
    raw_line: str


def parse_oomd_journal(text: str) -> list:
    """Parse `journalctl -u systemd-oomd` output for kill actions."""
    events = []
    for line in text.splitlines():
        m = _OOMD_KILL_RE.search(line)
        if m:
            events.append(OomdEvent(unit_or_cgroup=m.group(1), raw_line=line))
    return events


def get_oomd_events(since: Optional[str] = None, runner=run) -> tuple:
    """Returns (events, ok) -- ok is False when the underlying
    `journalctl -u systemd-oomd` read itself failed."""
    cmd = ["journalctl", "-u", "systemd-oomd", "--no-pager", "-o", "short-iso"]
    if since:
        cmd += ["--since", since]
    text = runner(cmd)
    if text is None:
        return [], False
    return parse_oomd_journal(text), True


@dataclass
class CgroupOomEvent:
    cgroup_path: str
    oom_kill_count: int


def parse_memory_events(text: str) -> Optional[int]:
    """Parse a cgroup v2 `memory.events` file for the oom_kill counter."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "oom_kill":
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def find_cgroup_oom_events(cgroup_root: str = "/sys/fs/cgroup", runner=run) -> tuple:
    """Walk cgroupfs for memory.events files reporting a nonzero oom_kill
    counter. Uses `find` + reading each file via the runner so this stays
    testable without real filesystem access.

    Returns (events, ok) -- ok is False when the `find` scan itself failed
    (e.g. /sys/fs/cgroup unreadable). A per-file `cat` failure (a cgroup
    that disappeared between `find` and `cat`, a genuinely transient race)
    is not treated as a global failure -- that file is just skipped, since
    `find` having succeeded already establishes the scan ran.
    """
    out = runner(["find", cgroup_root, "-name", "memory.events"])
    if out is None:
        return [], False
    events = []
    for path in out.splitlines():
        path = path.strip()
        if not path:
            continue
        content = runner(["cat", path])
        if content is None:
            continue
        count = parse_memory_events(content)
        if count:
            events.append(CgroupOomEvent(cgroup_path=path, oom_kill_count=count))
    return events, True


@dataclass
class OomPostmortemReport:
    mechanism: str
    explanation: str
    kernel_events: list = field(default_factory=list)
    oomd_events: list = field(default_factory=list)
    cgroup_events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mechanism": self.mechanism,
            "explanation": self.explanation,
            "kernel_events": [
                {"pid": e.pid, "comm": e.comm, "oom_score_adj": e.oom_score_adj, "raw_line": e.raw_line}
                for e in self.kernel_events
            ],
            "oomd_events": [
                {"unit_or_cgroup": e.unit_or_cgroup, "raw_line": e.raw_line} for e in self.oomd_events
            ],
            "cgroup_events": [
                {"cgroup_path": e.cgroup_path, "oom_kill_count": e.oom_kill_count}
                for e in self.cgroup_events
            ],
        }


def diagnose(
    kernel_events: list,
    oomd_events: list,
    cgroup_events: list,
    all_sources_ok: bool = True,
) -> OomPostmortemReport:
    """Classify which OOM mechanism fired, in priority order: kernel OOM
    (most authoritative -- means the whole host was out of memory), then
    systemd-oomd (proactive, cgroup-scoped), then cgroup limit-only OOM,
    else none found.

    `all_sources_ok=False` means at least one underlying read failed
    (permission denied, missing binary, timeout). A positive finding from
    any *other* successfully-read source still stands (real evidence is
    real evidence), but if none of the three sources found anything, that
    must be reported as MECHANISM_DIAGNOSTIC_FAILED -- "we don't know" --
    rather than the false reassurance of MECHANISM_NONE_FOUND, since an
    unreadable journal looks identical to a genuinely empty one.
    """
    if kernel_events:
        return OomPostmortemReport(
            mechanism=MECHANISM_KERNEL_OOM,
            explanation=MECHANISM_EXPLANATIONS[MECHANISM_KERNEL_OOM],
            kernel_events=kernel_events,
            oomd_events=oomd_events,
            cgroup_events=cgroup_events,
        )
    if oomd_events:
        return OomPostmortemReport(
            mechanism=MECHANISM_SYSTEMD_OOMD,
            explanation=MECHANISM_EXPLANATIONS[MECHANISM_SYSTEMD_OOMD],
            kernel_events=kernel_events,
            oomd_events=oomd_events,
            cgroup_events=cgroup_events,
        )
    if cgroup_events:
        return OomPostmortemReport(
            mechanism=MECHANISM_CGROUP_LIMIT,
            explanation=MECHANISM_EXPLANATIONS[MECHANISM_CGROUP_LIMIT],
            kernel_events=kernel_events,
            oomd_events=oomd_events,
            cgroup_events=cgroup_events,
        )
    if not all_sources_ok:
        return OomPostmortemReport(
            mechanism=MECHANISM_DIAGNOSTIC_FAILED,
            explanation=MECHANISM_EXPLANATIONS[MECHANISM_DIAGNOSTIC_FAILED],
        )
    return OomPostmortemReport(
        mechanism=MECHANISM_NONE_FOUND,
        explanation=MECHANISM_EXPLANATIONS[MECHANISM_NONE_FOUND],
    )


def diagnose_host(since: Optional[str] = None, runner=run) -> OomPostmortemReport:
    kernel_events, kernel_ok = get_kernel_oom_events(since=since, runner=runner)
    oomd_events, oomd_ok = get_oomd_events(since=since, runner=runner)
    cgroup_events, cgroup_ok = find_cgroup_oom_events(runner=runner)
    all_ok = kernel_ok and oomd_ok and cgroup_ok
    return diagnose(kernel_events, oomd_events, cgroup_events, all_sources_ok=all_ok)

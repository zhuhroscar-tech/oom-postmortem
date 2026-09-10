"""oom-postmortem CLI."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import diagnose_host, MECHANISM_NONE_FOUND


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oom-postmortem",
        description=(
            "Determine which of several distinct OOM mechanisms killed a "
            "process: the kernel OOM killer, systemd-oomd, or a cgroup "
            "memory-limit kill -- instead of manually correlating "
            "journalctl -k, journalctl -u systemd-oomd, and cgroup "
            "memory.events by hand. Strictly read-only."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--since", default=None,
        help="Only consider journal events since this time (journalctl --since syntax, "
             "e.g. '1 hour ago', '2026-09-10 08:00:00'). Default: entire available journal.",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return p


def _print_text(report) -> None:
    print(f"Mechanism: {report.mechanism}")
    print(report.explanation)
    if report.kernel_events:
        print("\nKernel OOM killer victims:")
        for e in report.kernel_events:
            adj = f" oom_score_adj={e.oom_score_adj}" if e.oom_score_adj is not None else ""
            print(f"  pid {e.pid} ({e.comm}){adj}")
    if report.oomd_events:
        print("\nsystemd-oomd kills:")
        for e in report.oomd_events:
            print(f"  {e.unit_or_cgroup}")
    if report.cgroup_events:
        print("\ncgroups with oom_kill counters incremented:")
        for e in report.cgroup_events:
            print(f"  {e.cgroup_path}: oom_kill={e.oom_kill_count}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report = diagnose_host(since=args.since)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_text(report)

    if report.mechanism == MECHANISM_NONE_FOUND:
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

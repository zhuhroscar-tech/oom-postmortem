"""oom-postmortem CLI."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import diagnose_host, MECHANISM_DIAGNOSTIC_FAILED, MECHANISM_NONE_FOUND
from .style import print_fields, resolve_style, status_headline


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
    p.add_argument("--no-color", action="store_true", help="Disable colored output.")
    return p


def _print_text(report, style) -> None:
    if report.mechanism == MECHANISM_NONE_FOUND:
        level = "ok"
    elif report.mechanism == MECHANISM_DIAGNOSTIC_FAILED:
        level = "warn"
    else:
        level = "fail"
    print(status_headline(style, level, report.mechanism))
    print(report.explanation)
    if report.kernel_events:
        print("\nKernel OOM killer victims:")
        rows = []
        for e in report.kernel_events:
            adj = f" oom_score_adj={e.oom_score_adj}" if e.oom_score_adj is not None else ""
            rows.append((f"pid {e.pid}", f"{e.comm}{adj}"))
        print_fields(rows)
    if report.oomd_events:
        print("\nsystemd-oomd kills:")
        for e in report.oomd_events:
            print(f"  {e.unit_or_cgroup}")
    if report.cgroup_events:
        print("\ncgroups with oom_kill counters incremented:")
        rows = [(e.cgroup_path, f"oom_kill={e.oom_kill_count}") for e in report.cgroup_events]
        print_fields(rows)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report = diagnose_host(since=args.since)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        style = resolve_style(no_color_flag=args.no_color)
        _print_text(report, style)

    if report.mechanism == MECHANISM_NONE_FOUND:
        return 0
    if report.mechanism == MECHANISM_DIAGNOSTIC_FAILED:
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())

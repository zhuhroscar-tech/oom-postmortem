[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

# oom-postmortem

Inspect Linux OOM evidence from the kernel journal, systemd-oomd, and cgroup v2 counters in one read-only report. The CLI summarizes the mechanism it finds and includes supporting process or cgroup details, with JSON output for scripts.

![Example terminal output](docs/images/example-output.png)

## Requirements and install

Requires Python 3.9+ on Linux with systemd, `journalctl`, and cgroup v2. macOS, Windows, and non-systemd hosts are not supported. Full journal and cgroup access may require elevated permissions.

```bash
git clone https://github.com/zhuhroscar-tech/oom-postmortem.git
cd oom-postmortem
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

A standalone `oom-postmortem.pyz` is available from [Releases](https://github.com/zhuhroscar-tech/oom-postmortem/releases). Verify it against the same release's `SHA256SUMS.txt`, then run it with Python 3; no pip installation is needed.

## Quick start

```bash
oom-postmortem --since "1 hour ago"
oom-postmortem --since "1 hour ago" --json
python -m pytest -v
```

Without `--since`, the tool inspects the available journal and current cgroup counters. If permissions prevent inspection, use an account with journal access or deliberately rerun with elevated permissions, for example `sudo .venv/bin/oom-postmortem --since "1 hour ago"` from this checkout.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | No OOM evidence found in the inspected sources |
| `2` | OOM evidence found and classified; argparse also uses this for invalid arguments |
| `3` | No positive finding and at least one source could not be read reliably |

## Interpret the report

Classification prioritizes kernel events, then systemd-oomd, then nonzero cgroup `oom_kill` counters. Review the evidence, not just the label: kernel victim lines alone do not necessarily distinguish global exhaustion from cgroup-limited OOM.

`--since` filters journal entries only. cgroup counters are cumulative, have no event timestamps, and may reflect earlier incidents. The tool does not correlate a requested PID or unit, and its summary is not definitive attribution for every concurrent incident.

For follow-up, inspect host memory pressure, the unit's `ManagedOOMMemoryPressure=` policy, or its `MemoryMax=`/container limit as appropriate. Do not change limits based solely on the summary.

## Safety

No process killing, configuration changes, persistent state, network access, or telemetry. It reads evidence only; missing logs or removed cgroups can limit diagnosis. See [CI](.github/workflows/ci.yml) for Linux tests and artifact builds.

[MIT license](LICENSE).

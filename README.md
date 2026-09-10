# oom-postmortem

Determine which of several distinct OOM mechanisms killed a process on
Linux — instead of manually correlating `journalctl -k`, `journalctl -u
systemd-oomd`, and cgroup `memory.events` by hand.

## The problem

"Something got OOM-killed" on a modern systemd/cgroup-v2 Linux host can
mean at least three genuinely distinct mechanisms, each logged in a
different place, each pointing to a different fix. A detailed 2026
write-up (cr0x.net's *Ubuntu 24.04 OOM killer: prove it, fix it, prevent
repeats*) walks the exact same multi-source manual correlation every
time because no tool automates it:

1. **The classic kernel OOM killer** — the kernel cannot satisfy an
   allocation anywhere on the host and reclaim fails, so it scores every
   process by `oom_badness()` and kills the worst offender. This means
   *global* host-wide memory exhaustion. Evidence: `journalctl -k` /
   `dmesg` shows "Out of memory: Killed process ...".
2. **systemd-oomd** — a userspace daemon that watches PSI (pressure
   stall information) per cgroup and proactively kills a whole
   cgroup/unit *before* the kernel would ever fire, once sustained
   pressure crosses a configured threshold. Evidence:
   `journalctl -u systemd-oomd` shows "Killed ... due to memory pressure".
3. **cgroup v2 memory-limit OOM** — a process is killed because its own
   cgroup (a systemd unit's `MemoryMax=`, a container limit, a
   Kubernetes pod's QoS-derived limit) was exceeded, even while the host
   overall has plenty of free RAM. Evidence: that cgroup's
   `memory.events` file shows its `oom_kill` counter incrementing, with
   no host-wide kernel OOM log line at all.

Getting this wrong means "fixing" the wrong layer (adding host RAM when
it was actually a `MemoryMax=` limit, or tuning `OOMScoreAdjust` when
`systemd-oomd`'s policy was the actual actor) and having the incident
recur.

## What this does

```
$ oom-postmortem --since "1 hour ago"

Mechanism: kernel_oom
The kernel's global OOM killer fired: it could not satisfy a memory
allocation anywhere on the host and reclaim failed, so it scored every
candidate process by oom_badness() and killed the worst offender. This
means the whole host was under real memory pressure, not just one cgroup.

Kernel OOM killer victims:
  pid 1966928 (llama-server) oom_score_adj=200
```

Checked in priority order (most-authoritative first): kernel OOM killer,
then systemd-oomd, then cgroup memory-limit OOM, else "no OOM kill
found in this window."

**Strictly read-only.** It never kills anything, never modifies
`OOMScoreAdjust`, memory limits, or cgroup settings — it only reads
journal and cgroupfs files.

## Install

Requires Python 3.9+ on a systemd/cgroup-v2 Linux host (uses
`journalctl`/cgroupfs; meaningless on macOS/Windows or non-systemd
distros).

```bash
pip install oom-postmortem
```

Or run the standalone zipapp with no install:

```bash
curl -LO https://github.com/zhuhroscar-tech/oom-postmortem/releases/download/v0.1.0/oom-postmortem.pyz
python3 oom-postmortem.pyz --version
```

Verify the download against `SHA256SUMS.txt` in the same release before
running it.

## Usage

```bash
sudo oom-postmortem                          # scan the whole available journal + cgroupfs
sudo oom-postmortem --since "1 hour ago"      # narrow the journal window (journalctl --since syntax)
sudo oom-postmortem --json                    # machine-readable output
```

Exit code `0` = no OOM kill found in the window, `2` = an OOM kill was
identified and attributed to a mechanism.

## If it finds a problem

This tool only diagnoses; it never modifies anything.

- `kernel_oom` → this is global host memory exhaustion. Look at overall
  memory usage/RSS across all processes at that time, not just the
  victim; consider adding swap, reducing overall workload concurrency,
  or capping non-critical processes with `OOMScoreAdjust`/cgroup limits
  so the kernel has better victim choices next time.
- `systemd_oomd` → check `ManagedOOMMemoryPressure=` and related policy
  on the affected unit/slice; decide deliberately whether to protect it
  or leave it killable, rather than being surprised by the "auto" default.
- `cgroup_memory_limit` → find and adjust the specific `MemoryMax=` (or
  container/pod memory limit) on that cgroup — adding host RAM will not
  help a local limit.

## Uninstall

```bash
pip uninstall oom-postmortem
```
No config files, no persistent state — a stateless read-only diagnostic.

## Privacy / permissions

- No network access, no telemetry.
- Reads `journalctl -k`, `journalctl -u systemd-oomd`, and
  `/sys/fs/cgroup/**/memory.events`. Full journal/cgroupfs access
  typically requires root, same as any other use of these commands.
- Writes nothing to disk.

## Distro / architecture support

Requires systemd and cgroup v2 (the vast majority of current distros;
`systemd-oomd`-specific detection degrades gracefully to "no oomd
events" on hosts without it running). Pure Python, no compiled
dependencies.

## Reproducible build / test

```bash
git clone https://github.com/zhuhroscar-tech/oom-postmortem
cd oom-postmortem
python3 -m pip install -e .[dev]
python3 -m pytest -v
```

CI (`.github/workflows/ci.yml`) runs the suite on real Ubuntu runners
across Python 3.9 and 3.12, then smoke-tests the console script and a
standalone `.pyz` against real journal/cgroupfs state on the runner.

## License

MIT — see [LICENSE](LICENSE).

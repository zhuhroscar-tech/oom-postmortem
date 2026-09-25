# Changelog

All notable source-quality changes to `oom-postmortem` are documented here.

## v0.1.8 - 2026-09-25

- Made CI run explicitly on `v*` release tags so release artifacts are validated from the tag being published.
- Added package project URLs for homepage, issues, and changelog metadata.
- Added repository-contract coverage for tag-triggered release validation and package resource links.

## v0.1.7 - 2026-09-24

- Added this changelog and README release-history links.
- Added repository-contract tests for required files, README links, CI/CodeQL wiring, current changelog entry, and release artifacts.

## v0.1.6 - 2026-09-24

- Modernized packaging license metadata to the current SPDX string form.
- Added regression coverage for packaging metadata and version parity.
- Published wheel, sdist, standalone `.pyz`, and checksums.

## v0.1.5 - 2026-09-19

- Added source/package version consistency checks.
- Published refreshed wheel, sdist, standalone `.pyz`, and checksums.

## v0.1.4 - 2026-09-13

- Refined Linux OOM evidence parsing and CLI reporting behavior.
- Published release artifacts for source installs and standalone execution.

## v0.1.3 - 2026-09-13

- Fixed permission-denied journal reads so they are distinguished from a clean no-OOM result.
- Improved diagnostic exit behavior when evidence sources cannot be read reliably.

## v0.1.2 - 2026-09-13

- Improved early CLI/package polish and release artifact coverage.

## v0.1.1 - 2026-09-11

- Added post-initial packaging and documentation polish.

## v0.1.0 - 2026-09-10

- Initial public release.
- Provided read-only inspection for kernel OOM killer evidence, systemd-oomd events, and cgroup v2 `memory.events` counters.

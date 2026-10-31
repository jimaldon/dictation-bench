# Security

## Scope

`dictation-bench` runs the software **you** configure, under **your** account, and talks to
local endpoints. It does not sandbox what you point it at: a `custom` or `cli` engine is an
arbitrary command you chose to run, with the same permissions you have.

What we do keep safe:

- No network calls except to the engine URL you configure (defaults are loopback).
- No telemetry, no analytics, no accounts.
- `results/` is git-ignored so a benchmark of your own voice does not get committed by default.

## Reporting a problem

If you find a way this tool **misreports** results — a scoring bug that flips a ranking, a
capability claim the code makes that the software does not have, a preset that is silently
wrong — that is a correctness bug and we want it. Open an issue with the `correctness` label
and include `results/results.json` from the run if you can.

For anything that would leak transcripts or recordings from someone else's machine, please
report privately via GitHub Security Advisories rather than a public issue.

## Known non-issues

- The tool trusts engine output. A malicious binary could return fabricated transcripts; use
  software you trust, or verify a checksum before benchmarking it.
- Corpus audio is synthetic voice and carries no personal data.

# Changelog

All notable changes to this project are documented here. Versioning is semantic once
`1.0`; before that, **results may not be comparable across minor versions** — always keep
the `results.json` a report was generated from.

## [0.1.0] — 2026-10-31

First public release. There is no earlier version to compare against; this entry documents
what the tool does and why it is shaped this way.

### Added

- `bench`, `doctor`, `engines`, `corpus`, `init` commands.
- Four adapter types: OpenAI-compatible `http`, `cli` (stdout), `json-cli` (JSON per call,
  warm-repeat aware) and `custom` (any command).
- Bundled 28-clip / 112.8 s reference corpus (shipped in the wheel; no setup step).
- Three scoring layers — naive, Whisper-style, number-aware — applied identically to
  reference and hypothesis, with the artefact shown side by side.
- Raw word-error counts and a Wilson 95% range, so a one-word difference is labelled as one.
- Cold (first phrase) and warm latency, recorded separately.
- Decision report: table, per-group accuracy, pros/cons per engine, a recommendation that
  names the condition that would change it, and explicit limitations.
- `results/report.md`, `results/table.csv`, `results/results.json` per run.
- Presets: whisper.cpp, WhisperKit, NeMo-Speech, faster-whisper-server, LM Studio, Moonshine,
  hns, parakeet.cpp, Handy.
- `corpus --from-clip` (your own recording and mic) and `--pollute` (background speech).
- `scripts/dictbench-ptt` + `docs/recipe/` — a minimal launchd + shell-script dictation stack.
- 53 tests; CI across Linux/macOS × Python 3.10–3.13 plus wheel build and shellcheck.

### Fixed before first release

- Inline `--engine-json` entries were silently dropped when combined with `--preset`.
  They are now merged, and a misconfigured engine is a hard error instead of a shorter table.
- A single measured engine is no longer labelled "most accurate".
- A real numeric failure is now reported as an accuracy con ("Misses numbers"), not as a
  scoring artefact.
- The reference corpus is now included in the installed package (previously only in a
  source checkout).
- `tomli` is installed on Python 3.10, where `tomllib` does not exist.

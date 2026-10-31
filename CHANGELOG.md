# Changelog

Notable changes to this project. Versioning follows semver once 1.0 is reached. Before that,
**results may not be comparable across minor versions**, so keep the `results.json` a report was
generated from.

## 0.1.0, 2026-10-31

First public release. There is no earlier version to compare against, so this entry records what
the tool does and why it is shaped this way.

### Added

- Commands: `bench`, `doctor`, `engines`, `corpus`, `init`.
- Four adapter types: OpenAI-compatible `http`, `cli` for stdout, `json-cli` for JSON per call with
  warm repeats, and `custom` for any command.
- A bundled reference corpus of 28 clips and 112.8 s, shipped inside the package so there is no
  setup step.
- Three scoring layers, naive, Whisper-style and number-aware, applied identically to reference and
  hypothesis, with the artifact visible side by side.
- Raw word error counts and a Wilson 95% range, so a one-word difference is labelled as one.
- Cold and warm latency recorded separately.
- A decision report: the table, per-group accuracy, pros and cons per engine, a recommendation that
  names the condition that would change it, and stated limitations.
- `results/report.md`, `results/table.csv` and `results/results.json` per run.
- Presets for whisper.cpp, WhisperKit, NeMo-Speech, faster-whisper-server, LM Studio, Moonshine,
  hns, parakeet.cpp and Handy.
- `corpus --from-clip` for your own recording and microphone, and `--pollute` for background speech.
- `scripts/dictbench-ptt` with `docs/recipe/` for a minimal launchd and shell script dictation stack.
- 58 tests, plus CI across Linux and macOS for Python 3.10 through 3.13, a wheel build and
  shellcheck.

### Fixed before the first release

- Inline `--engine-json` entries were silently dropped when combined with `--preset`. They are now
  merged, and a misconfigured engine is a hard error instead of a shorter table.
- A single measured engine is no longer labelled "most accurate".
- A real numeric failure is reported as an accuracy con, "Misses numbers", rather than as a scoring
  artifact.
- First phrase latency was always blank: the summary read a per-call flag to find the cold clip.
  `EngineRun` now records `cold_clip` and `cold_s` explicitly, with regression tests.
- Memory was reported in decimal GB, showing 25.8 for a 24 GB machine.
- The report now warns when an engine's warm number is its own internal inference timer, instead of
  quietly mixing two quantities in one column.
- The reference corpus is included in the installed package, and `tomli` is installed on Python 3.10
  where `tomllib` does not exist.

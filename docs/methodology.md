# Methodology

This page exists so the numbers can be argued with. If something here is wrong, that is a bug, so
please open an issue.

## What is measured

| Axis | Definition | Unit |
|:--|:--|:--|
| Everyday WER | Word errors divided by reference words, over the `main`, `jargon`, `polluted` and `long` groups | % |
| Group WER | Same, per group (`main`, `numeric`, `stress`, `long`, and so on) | % |
| First phrase | Wall time for the first clip, with the engine not previously used in this run | s |
| Every phrase after | Median wall time over the remaining clips | s |
| Failures | Clips that errored or returned nothing | count |

Corpus WER is total edits over total reference words. It is not the mean of per-clip WER, because a
long clip and a short clip should not carry equal weight.

## Scoring: three normalisers, applied identically

Every normaliser is applied to both the reference and the hypothesis:

- `basic` lowercases, keeps `[a-z0-9']`, and collapses whitespace. This is what many quick
  benchmarks do.
- `whisper` adds OpenAI Whisper's `EnglishTextNormalizer`, which sits behind most published WER
  numbers and the Open ASR Leaderboard conventions.
- `reconciling` adds explicit number and format reconciliation: spelled numbers to digits,
  thousands separators, clock forms, spaced digit runs, and single letter plus number joins.

The report prints all three for every engine. The choice of scorer can flip a ranking, and much of
the disagreement between published tables comes from exactly that.

An example from this project's own history, with the same engine outputs scored two ways:

| Scorer | Engine A, writes digits | Engine B, writes words |
|:--|--:|--:|
| basic | 9.6% | 3.7% |
| reconciling | 2.7% | 3.9% |

B looks 2.6 times better under the first scorer and worse under the second. Neither engine changed.

## Why raw error counts are printed

On a 259-word corpus, "1.9% versus 2.3% WER" is five errors against six. That is one word. The
report prints errors, reference words and a 95% range:

```
| Engine | Word errors | Reference words | WER (95% range) |
```

and states when a gap falls into one-word territory. Small corpora cannot rank engines that are
nearly equal, and more decimal places do not help.

The 95% range is a Wilson interval over word errors. Errors are not independent draws, since one
hard word can cost two edits, so treat the range as a check on whether a difference is one word
rather than as a formal significance test.

## Cold and warm latency

Cold is the first clip of the run with no prior traffic. For a loaded app it includes process start
and model load. For a resident server it is first-request warm-up.

Warm is the median of the remaining clips. For a resident server this is what every phrase costs.

For a process-per-clip CLI the warm number is still not what a user feels in an app that loads the
model once, and the report says so under "Before you trust this".

Neither number includes audio capture, voice activity detection, the hotkey path, the paste
keystroke or clipboard handling. Those are app-level costs that can add tens to hundreds of
milliseconds.

## Corpus

The bundled reference corpus has 28 clips and 112.8 s of audio, rendered with macOS `say` (Samantha,
170 wpm) to 16 kHz mono PCM16. The text is exact ground truth because it was synthesised.

| Group | Clips | Purpose |
|:--|--:|:--|
| `main` | 19 | everyday prose, the headline |
| `numeric` | 6 | numbers, times, money, where engines differ on format |
| `stress` | 2 | acronyms and spelled letters |
| `long` | 1 | about 20 s, for length effects |
| `jargon` | 5 | technical and proper nouns, counted in the headline |
| `polluted` | 0 to 5 | optional, the same speech with a second speaker over it |

`--pollute` renders background-speech versions, because clean synthetic audio makes good models
look identical to one another.

`corpus.json` records provenance and a SHA-256 per file. `testdata/reference` is byte-identical to
the corpus the project was developed on.

## Reproducibility

The corpus is deterministic for a given voice and macOS version, and `say` voices change between
major releases, which is why `corpus.json` is written on every render.

Model versions matter more than engine versions. Record them in `bench.toml` `notes`. Every run
writes a fresh `results.json` with the exact per-clip transcripts, so two runs can be compared
without re-running anything.

## Known biases

Synthetic speech is easier than real speech, so all engines score better than they would on your
voice and gaps can compress. Use `--from-clip` with your own recording to correct for it.

The default corpus is English only. Parakeet and Nemotron are multilingual; use a corpus in the
language you care about.

Short test items favour models with fixed windows. Whisper pads to 30 s, so real-time factor on a
two-second clip understates its cost on a long file, which is what the `long` group is for.

Latency moves with thermal state, power mode and background load by tens of percent. Run
comparisons inside one session.

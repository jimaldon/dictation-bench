# Methodology

This page exists so the numbers can be argued with. If something here is wrong, that is a
bug — open an issue.

## 1. What is measured

| Axis | Definition | Unit |
|:--|:--|:--|
| Everyday WER | Word errors / reference words over `main`, `jargon`, `polluted`, `long` groups | % |
| Group WER | Same, per group (`main`, `numeric`, `stress`, `long`, …) | % |
| First phrase (cold) | Wall time for the **first** clip, engine not previously used in this run | s |
| After that (warm) | Median wall time over the remaining clips | s |
| Failures | Clips that errored or returned nothing | count |

Corpus WER is **total edits over total reference words** — not the mean of per-clip WER.
A long clip and a short clip do not get equal weight.

## 2. Scoring: three normalisers, applied identically

Applied to **both** reference and hypothesis, always:

- `basic` — lowercase, keep `[a-z0-9']`, collapse whitespace.
  This is what many quick benchmarks do.
- `whisper` — `basic` plus OpenAI Whisper's `EnglishTextNormalizer` (the normaliser behind
  most published WER numbers and the Open ASR Leaderboard conventions).
- `reconciling` — `basic` plus explicit number/format reconciliation:
  spelled numbers → digits, thousands separators, clock forms, spaced digit runs,
  single letter + number joins.

The report prints all three for every engine. That is deliberate: **the choice of scorer can
flip rankings**, and most disagreements between published tables come from it.

Example from the project's own history — the same engine outputs, scored two ways:

| Scorer | Engine A (writes digits) | Engine B (writes words) |
|:--|--:|--:|
| naive (`basic`) | 9.6% | 3.7% |
| reconciling | 2.7% | 3.9% |

On the naive scorer, B looks 2.6× better. On the reconciling scorer, A is better. Neither
engine changed.

## 3. Why raw error counts are printed

On a 259-word corpus, a "1.9% vs 2.3% WER" result is **5 errors vs 6**. That is one word.
The report prints:

```
| Engine | Word errors | Reference words | WER (95% range) |
```

and states plainly when a gap is one-word territory. Small corpora cannot rank engines that
are nearly equal — no amount of decimal places fixes that.

The 95% range is a Wilson interval over word errors. Errors are not independent draws
(one hard word can cost two edits), so treat it as a sanity check on "is this one word?" —
not a formal significance test.

## 4. Cold vs warm latency

- **Cold** = first clip of the run, no prior traffic. For a loaded app this includes process
  start and model load; for a resident server, first-request warm-up.
- **Warm** = median of the rest. For a resident server this is what every phrase costs.

For process-per-clip CLIs the *warm* number is still not what a user feels in an app that
loads the model once, and the report says so in "Before you trust this".

Neither number includes: audio capture, VAD/silence trimming, the hotkey path, the paste
keystroke, or clipboard handling. Those are app-level and can add tens to hundreds of ms.

## 5. Corpus

Bundled reference corpus: 28 clips, 112.8 s, rendered with macOS `say` (Samantha, 170 wpm),
16 kHz mono PCM16. Text is exact ground truth because it was synthesised.

| Group | Clips | Purpose |
|:--|--:|:--|
| `main` | 19 | everyday prose — the headline |
| `numeric` | 6 | numbers, times, money — where engines differ on format |
| `stress` | 2 | acronyms and spelled letters |
| `long` | 1 | ~20 s utterance for length effects |
| `jargon` | 5 | technical/proper nouns (part of `main` in the original corpus) |
| `polluted` | 0–5 | optional: same voice with a second speaker talking over it |

Adding `--pollute` renders background-speech versions, because clean synthetic audio makes
good models look identical to each other.

`corpus.json` records provenance and SHA-256 per file; `testdata/reference` is byte-identical
to the corpus the project was developed on.

## 6. Reproducibility

- The corpus is deterministic **for a given voice and macOS version**. `say` voices changed
  between major macOS releases — record `corpus.json`, which this project writes.
- Model versions matter more than engine versions. Record them in `bench.toml` `notes`; the
  report keeps `results.json` including exact per-clip transcripts.
- The project never edits `results/`: every run writes a fresh report you can diff.

## 7. Known biases

- **Synthetic speech is easy.** All engines score better than on real speech; gaps can
  compress. `--from-clip` with your own recording is the corrective.
- **English only**, by default. Parakeet/Nemotron are multilingual; use a corpus in your
  language.
- **Short test items favour models with fixed windows.** Whisper pads to 30 s, so RTFx on
  2–4 s clips understates its cost on long files (the `long` group exists for that).
- **One machine.** Thermal state, power mode and other load all move latency by tens of
  percent. Run comparisons in one session.

# Compare two runs

`compare` answers a different question from `bench`: not "which engine wins this table?", but
"what changed between these two measurements of the same thing?"

```bash
dictation-bench compare BEFORE/results.json AFTER/results.json --out results/upgrade
```

This writes `comparison.md` and `comparison.json`. Without `--out`, Markdown goes to stdout;
`--json` prints the structured form instead. The default corpus is the bundled reference corpus.
For a personal corpus, pass the same directory used for both benchmarks:

```bash
dictation-bench compare before.json after.json --corpus corpus/mine --out comparison
```

Do not compare different audio, references or clip subsets and call the result an upgrade. New
result files contain a SHA-256 fingerprint of every clip's name, group, reference and audio bytes.
`compare` rejects a fingerprint mismatch. Files from 0.1.0 have no fingerprint: they can still be
compared by clip ID, with an explicit warning that identity could not be verified. Because 0.1.0
also omitted `--groups` and `--max-clips`, legacy comparison uses only the clip IDs recorded in
both engine results. A filtered subset produces a scope warning; unequal legacy subsets are
rejected because missing clips cannot be distinguished from failed calls.

## Which engines are paired

- One engine in each file: the two engines form the explicit before/after pair, even if you renamed
  the engine to record a model or app version. A different name produces a warning.
- Several engines: names identify the pairs. Before-only and after-only engines are listed as
  skipped. Duplicate names are rejected rather than silently overwriting one another.

An engine that was not measured successfully cannot be compared. That is a failed benchmark, not
100% word error. Individual failed clips remain visible as regressions, recoveries or continuing
failures.

## What the numbers mean

All changes are **after minus before**.

| Field | Meaning |
|:--|:--|
| Everyday WER | Main, jargon, polluted and long clips, scored again with the current reconciling normalizer. Positive pp means worse. |
| All-clip WER | The same calculation over every selected clip, including numbers and stress cases. |
| Warm median / p95 | Wall time over clips with valid warm measurements in **both** runs. Positive ms means slower. |
| Cold first phrase | The recorded cold measurement from each run, shown separately without a bootstrap interval. |
| Clip outcomes | Fixed, regressed, changed with equal edit count, unchanged, or failed in both runs. |

Everyday and all-clip WER use aggregated edits divided by aggregated reference words. They are not
averages of per-clip percentages. A failed clip scores as missed reference speech, matching the
per-clip failure treatment in `bench`.

Warm timing excludes the cold clip, failed calls, missing results, and non-positive or non-finite
timings. The before and after medians use the same paired clip set, so losing a difficult call in
one run cannot make that run look faster. The per-clip sections retain those failures.

## Paired uncertainty

The 95% intervals use 4,000 deterministic paired bootstrap resamples by default. Each resample
draws whole clips with replacement, then recalculates the WER difference or the difference of
median warm times on that sample. This preserves the fact that the same clip was measured in both
runs.

```bash
dictation-bench compare before.json after.json --resamples 10000
```

Use at least 100 resamples. Fewer than two paired clips produces no interval. An interval crossing
zero is reported as inconclusive, not as a win or regression. The interval describes sampling
uncertainty in this corpus; it does not capture every source of run-to-run variation. Background
load, thermals, network services, app settings and model updates still matter. Repeat the runs for
a decision that depends on a small latency difference.

Result files from different dictation-bench versions produce a warning and are scored again with
the current normalizer. Different CPU, architecture or RAM metadata also produces a warning. A
latency difference across machines is not solely an app regression.

## Privacy

The default Markdown and JSON include clip names, edit counts, categories and timings, but **not**
transcript text or raw engine error strings. This matters when the corpus contains personal
messages, names or private work.

To inspect exact wording and raw errors locally:

```bash
dictation-bench compare before.json after.json --show-transcripts --out private-comparison
```

Treat that output as private. Even the default comparison may reveal clip names and condition
labels; review any file before posting it publicly.

## Automation

`comparison.json` has `kind = "dictation-bench-comparison"` and a schema version. Its `pairs`
array contains the summary metrics, verdict strings, counts and per-clip records. Fields with no
valid measurement are JSON `null`, never `NaN` or infinity. There is no automatic pass/fail gate:
a statistically inconclusive change and an operationally important timeout need human judgement,
not a single exit-status rule.

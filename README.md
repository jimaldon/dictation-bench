<div align="center">

# dictation-bench

**There are dozens of good dictation apps. Benchmark them on _your_ machine, and pick one.**

Free or paid · open or closed · Whisper, Parakeet, Apple, whatever.
One command, one table, a recommendation that says what it is and what it isn't.

</div>

---

## The problem this solves

You want to type with your voice. You search, and you get a wall:

- **Wispr Flow** (paid, cloud) vs **macOS built-in dictation** (free) vs **Handy** vs
  **FluidVoice** vs **VoiceInk** vs **Superwhisper** vs **WhisperKit** vs **whisper.cpp**…
- Every page has a benchmark table. **None of them were measured on your Mac**, your
  microphone, your voice or your accent.
- The tables disagree with each other by several points for the *same* models.

That is not because people are lying. It is because:

1. **Accuracy is scored differently.** One benchmark lowercases and strips punctuation; the
   next converts "twenty twenty six" to "2026" on one side only. The same two engines can
   swap places depending on the scorer. This repo measures that gap and shows it to you.
2. **"Speed" means different things.** "120× real-time" can be true while the first phrase
   after launch still takes 1.5 seconds. What you feel is *cold* (first phrase) and *warm*
   (every phrase after).
3. **The gap between the top models is often a single word.** On a small test set, "1.9% vs
   2.3%" can mean five errors versus six. This repo prints the raw error counts so you can
   see that, instead of a fake ranking.

`dictation-bench` measures the software **installed on your machine**, in one afternoon, with
the same audio and the same scoring rules for every candidate, and gives you a table plus a
plain-language recommendation.

## What you get

Run `dictation-bench bench`, open `results/report.md`, and read
([a real sample report](examples/sample-report-m2.md), two engines on an M2):

| Engine | Everyday WER | Numbers | First phrase | After that | Resident? |
|:--|--:|--:|--:|--:|:-:|
| … your software … | 2.1% | 0.0% | 420 ms | 110 ms | yes |

…followed by:

- **Accuracy in detail** — every group separately (prose, numbers, acronyms, jargon, long
  utterances, a second person talking), with **raw word-error counts** and a 95% range.
- **Why published numbers disagree** — the same results scored three ways, side by side.
- **Pros and cons per engine** — bullet lists, not vibes.
- **What I would pick** — for "accuracy matters", "I hate waiting", "I want words while I
  speak", "I dictate jargon", with the condition that would flip the advice.
- **What this does not tell you** — stated up front, not buried.

The same data is written as `results/table.csv` and `results/results.json` if you want to
keep it, chart it, or diff it after an update.

## Quick start

Requires Python 3.10+ and, on macOS, `sox` for corpus generation (`brew install sox`).

```bash
git clone https://github.com/jimaldon/dictation-bench && cd dictation-bench
pip install -e ".[normalize]"        # [normalize] enables the Whisper-style scorer
dictation-bench doctor               # what is installed, what to run next
```

Start the software you want to compare, then either use a preset:

```bash
dictation-bench bench --preset nemo-speech-server --preset whisper.cpp-server
```

…or write a `bench.toml` (one entry per piece of software) and run:

```bash
dictation-bench init      # writes a commented starter bench.toml
dictation-bench bench     # measures everything in it and writes results/report.md
```

Every benchmark takes about one to three minutes per engine (28 clips, ~113 s of audio).

## Adding the software *you* use

Four ways in, covering essentially everything local:

| Your software gives you… | Config `type` |
|:--|:--|
| An OpenAI-compatible endpoint (`POST /v1/audio/transcriptions`) — whisper.cpp server, WhisperKit server, faster-whisper-server, NeMo-Speech, LM Studio, most wrappers | `http` |
| A command that prints text on stdout — `whisper-cli`, `whisperkit-cli`, `moonshine`, `hns`, `parakeet.cpp` | `cli` |
| A command that prints JSON per call, with a warm-repeat switch — e.g. Handy's headless batch mode | `json-cli` |
| Anything scriptable at all | `custom` |

```toml
[[engines]]
name = "whisper.cpp server"
type = "http"
url = "http://127.0.0.1:8080/v1/audio/transcriptions"
capabilities = { service = true, offline = true }
```

**A GUI-only app?** Many ship a hidden CLI or local server. If yours does not, wrap its
command in `type = "custom"`; the report marks those numbers as *your* claim, not ours.
Full guide: [`docs/adding-an-engine.md`](docs/adding-an-engine.md).

Built-in presets: whisper.cpp (server/CLI), WhisperKit (server/CLI), NeMo-Speech,
faster-whisper-server, LM Studio, Moonshine, hns, parakeet.cpp, Handy. See
`dictation-bench engines`.

## Use your own voice and microphone

The bundled corpus is synthetic speech, so it is *repeatable* but **cleaner than a real
room**. The single biggest accuracy factor is your microphone, and no public table can
measure it. Two ways to fix that:

```bash
# 1. Your own recording, as the test set (best signal)
dictation-bench corpus --from-clip my-voice.wav --ref "the exact words I said"

# 2. Your own sentences, in a synthetic voice
dictation-bench corpus --from-text-file my_sentences.txt --out corpus/mine
dictation-bench bench --corpus corpus/mine

# 3. The default corpus, plus clips with a second voice talking over you
dictation-bench corpus --from-macos-say --pollute --out corpus/party
```

> **What we measured:** moving from a wired mic to a laptop mic changes dictation accuracy
> far more than switching between the top models, and adding a second speaker pulls models
> apart that look identical on clean audio. If your numbers differ from the internet's, your
> mic is usually why.

On Windows or Linux, generate a corpus once with any TTS, or share a corpus directory
(`manifest.tsv` + 16 kHz mono WAVs). The bundled one works everywhere with no setup.

## The dictation stack, if you want to build one

If no app gives you what you want (hotkey from your window manager, no app window, a
resident model), [`docs/recipe/`](docs/recipe/) has the minimal version this project grew
out of: one resident local server under `launchd`, one ~150-line shell script, and your own
hotkey. It is deliberately not an app — copy it and keep your setup. See
[`docs/recipe/dictation.md`](docs/recipe/dictation.md).

## How it measures

| Axis | What it does | Where it can mislead you |
|:--|:--|:--|
| **Accuracy** | Word error rate on your corpus, scored with three normalisers (naive, Whisper-style, number-aware). Headline = everyday dictation (prose, jargon, long, background speech). | Synthetic speech is easy; small corpora make one word look like a trend. Both are printed. |
| **First phrase (cold)** | First clip, engine not yet used: process start + model load + shader/ANE compile. | Includes one-time app start-up; a resident app you never quit skips it. |
| **After that (warm)** | Median over the rest of the clips. | Engine time only — not audio capture or the paste keystroke. |
| **Capabilities** | Declared per engine (partials, resident, vocabulary, offline, formats). | *Declared, not measured.* The report never infers them. |

Scoring details, including why numbers are normalised identically on both sides, are in
[`docs/methodology.md`](docs/methodology.md).

## Development

```bash
git clone https://github.com/jimaldon/dictation-bench && cd dictation-bench
pip install -e ".[dev]"
python -m pytest tests -q
ruff check src tests
```

Layout: `src/dictation_bench/{corpus,normalize,adapters,evaluate,runner,report,cli}.py`,
`testdata/reference` (the bundled corpus), `docs/`, `scripts/dictbench-ptt` (the recipe).
CI runs the tests on Linux and macOS across Python 3.10–3.13, builds the wheel, and
`shellcheck`s the script.

## Honest limitations

- **This is an engine-level benchmark, not a product review.** It measures transcription
  quality and speed. UI, price, privacy policy, licensing, support and app polish are not
  measured and often matter more than the last half a percent of WER.
- **It runs the software you install.** It cannot fairly drive closed apps' GUIs, so a
  product that ships no CLI or server is out of reach unless you wrap its command.
- **One machine, one run.** Numbers are for *your* comparison. Re-running is cheap; do it
  after a model upgrade.
- **Small corpus by default.** 28 clips, ~113 s. Enough to separate engines that differ by
  points, **not** enough to rank engines that differ by one word. The report says so whenever
  that happens.

## Contributing

Most valuable contributions, in order:

1. **A preset for software you use** — especially the GUI apps people are actually choosing
   between. A `[[engines]]` block plus one paragraph on how to start it.
2. **Real recordings** (with permission, and with their exact text) — this is the scarcest
   thing in ASR benchmarking.
3. **A better normaliser rule** with a test that shows what it changes.

Keep the promises small: if a preset's capability claims are not verified, say so in its
`notes` — the report prints them as *your* claim.

## License

MIT for this project's code. Your dictation software, models and corpora keep their own
licences; this repository ships no models and redistributes no third-party software.

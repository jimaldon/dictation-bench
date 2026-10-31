<div align="center">

<img src="docs/assets/logo.svg" alt="dictation-bench" width="620">

**There are dozens of good dictation apps. Benchmark them on _your_ machine, and pick one.**

[![CI](https://github.com/jimaldon/dictation-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/jimaldon/dictation-bench/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/macOS%20·%20Linux-supported-lightgrey)](#-quick-start)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![No telemetry](https://img.shields.io/badge/telemetry-none-blueviolet)](#privacy)

[**Quick start**](#-quick-start) · [**A real example**](#️-an-example-what-it-produced-on-one-laptop) · [**Add your app**](#-what-it-can-measure) · [**Why tables disagree**](#why-published-tables-disagree)

</div>

---

## 😵 The problem

You want to type with your voice. You search, and you get a wall:

> **Wispr Flow** (paid, cloud) · **macOS built-in dictation** (free) · **Handy** · **FluidVoice** ·
> **VoiceInk** · **Superwhisper** · **Hex** · **MacParakeet** · **OpenWhispr** ·
> **WhisperKit** · **whisper.cpp** · **Parakeet** · **Moonshine** …

Every one of them has a benchmark table somewhere. **None of those numbers were measured on your
Mac**, with your microphone, in your room, with your accent. And the tables disagree with each
other about the *same* models — sometimes by several points.

That's not because everyone is lying. It's because of three things, all of which this tool fixes:

1. **🧮 Accuracy is scored differently.** One benchmark lowercases and strips punctuation; the
   next converts "twenty twenty six" to "2026" on only one side. **The same two engines can swap
   places depending on the scorer.**
2. **⏱️ "Speed" means different things.** "200× real time" can be true while the *first* phrase
   after launch still takes two seconds. What you feel is **cold** (first phrase) and **warm**
   (every phrase after).
3. **🔤 The gap between the best models is often one word.** "1.9% vs 2.3%" is five errors vs
   six on a small test set. Most tables present that as a winner.

## 🧪 What this does

`dictation-bench` runs **the software already installed on your machine**, with the *same audio*,
the *same scoring*, in one afternoon — then hands you a table, a pros/cons list per app, and a
recommendation that states what would change it.

<div align="center">
<img src="docs/assets/phrase-cost.svg" alt="Chart: time per dictation phrase. Resident servers take about 150 ms; Handy takes 0.8 to 2.0 s for the first phrase" width="820">
</div>

---

## ⚡ Quick start

**Requirements:** Python 3.10+ and `sox` (`brew install sox`). No API keys, no account, no cloud.

```bash
git clone https://github.com/jimaldon/dictation-bench && cd dictation-bench
pip install -e ".[normalize]"      # [normalize] adds the Whisper-style scorer
dictation-bench doctor             # what's installed on this machine, and what to try next
```

Then point it at the apps you actually have:

```bash
# Measure a resident server and a CLI against each other
dictation-bench bench --preset nemo-speech-server --preset whisper-cpp-cli

# Or write a bench.toml listing everything you want to compare
dictation-bench init && dictation-bench bench
```

Open **`results/report.md`**. It takes about 1–3 minutes per engine.

```text
✅ Resident (no reload per phrase)          ⚠️ Slow first phrase (1974 ms vs 353 ms): the model is
✅ Offline (no network)                        loaded per invocation, so every relaunch pays once
⚠️ Misreads numbers (35.9% on the numbers group)
```

---

## 🖥️ An example: what it produced on one laptop

**Machine:** Apple M2 MacBook Air (Mac14,2) · 24 GB unified memory · macOS 26.7.1 · AC power
**Corpus:** the 28 bundled clips (112.8 s) · 260 reference words for the headline score
**Measured:** 2026-10-31, five systems installed side by side, run one after another

| System | How it ran | Everyday WER | Numbers | First phrase | Every phrase after |
|:--|:--|--:|--:|--:|--:|
| [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) · [Parakeet TDT v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | resident server (Metal) | **1.9%** | 17.2% | **137 ms** | **146 ms** |
| [Hex 3.0.0](https://github.com/anomalyco/hex) · Parakeet v3 | resident service | **1.9%** | 17.2% | 163 ms | 161 ms |
| [Handy](https://github.com/cjpais/Handy) · Parakeet Unified EN | app binary, batch | 2.3% | 35.9% | 839 ms | 130 ms |
| [Handy](https://github.com/cjpais/Handy) · Parakeet TDT v3 | app binary, batch | 2.3% | 31.2% | 1288 ms | 235 ms |
| [Handy](https://github.com/cjpais/Handy) · [Whisper small.en](https://huggingface.co/openai/whisper-small.en) | app binary, batch | 2.3% | 35.9% | 1974 ms | 353 ms |

<div align="center">
<img src="docs/assets/accuracy.svg" alt="Chart: everyday WER is a tie at about 2 percent across all five; the numbers group splits them" width="820">
</div>

### 🧠 What that table actually says

> **On everyday dictation, all five are the same.** 5 errors vs 6 errors out of 260 words —
> a one-word difference. Anyone claiming a winner here is claiming noise.
>
> **The real differences are numbers and waiting.** Two systems (NeMo-Speech, Hex) handle written
> numbers correctly, where Handy's models mangle them (31–36% error on the numbers group). And the
> two resident servers answer in **~150 ms**, while Handy driven as a command costs **0.8–2.0 s**
> because it reloads the model each time — inside the app the model stays loaded, and it feels like
> the others.
>
> **So the decision is not "which model".** It's: do you want a menu-bar app you click (Handy), or
> a resident server you bind to a key (NeMo-Speech, Hex)? And either way — run it yourself, because
> your M1/M4 and your microphone will move these numbers.

📄 The full unedited report, with per-group accuracy, 95% ranges and per-engine pros/cons:
**[examples/report-m2-macbook-air.md](examples/report-m2-macbook-air.md)**

> ⚠️ **Read it with this caveat:** Handy's "every phrase after" is its *internal inference timer*,
> not wall time — the report says so in its own "Before you trust this" section. That is exactly
> the kind of thing the tool surfaces instead of hiding.

---

## 🔌 What it can measure

`dictation-bench` doesn't have a plugin per app. It has **four ways in**, which between them reach
almost every local dictation product — open source or not, free or paid:

| Your software gives you… | `type` | Examples |
|:--|:--|:--|
| An OpenAI-compatible endpoint (`POST /v1/audio/transcriptions`) | `http` | whisper.cpp server, WhisperKit server, NeMo-Speech, faster-whisper-server, LM Studio |
| A command that prints text on stdout | `cli` | `whisper-cli`, `whisperkit-cli`, `moonshine`, `hns`, `parakeet.cpp` |
| A command that prints JSON | `json-cli` | [Handy](https://github.com/cjpais/Handy)'s headless batch mode, [Hex](https://github.com/anomalyco/hex)'s service |
| Anything scriptable at all | `custom` | a shell wrapper around a GUI-only app |

**A GUI-only app?** Many ship a hidden CLI or a local server (Handy does). If yours doesn't, wrap
it with `type = "custom"` — the report marks those numbers as *your* claim, not ours.
📖 Full guide: **[docs/adding-an-engine.md](docs/adding-an-engine.md)**

<details>
<summary><b>Built-in presets</b> (click to expand)</summary>

whisper.cpp server · WhisperKit server · NeMo-Speech server · faster-whisper-server · LM Studio ·
whisper.cpp CLI · WhisperKit CLI · hns · Moonshine · parakeet.cpp · Handy · custom

Run `dictation-bench engines` to list them, or see [`examples/bench.example.toml`](examples/bench.example.toml).

</details>

---

## 🎤 Use your own voice and microphone

The bundled corpus is synthetic speech — repeatable, but **cleaner than a real room**. The biggest
accuracy factor is your microphone, and no public table can measure that. Three ways:

```bash
# 1. Your own recording, as ground truth (best signal)
dictation-bench corpus --from-clip my-voice.wav --ref "the exact words I said"

# 2. Your own sentences, in a synthetic voice
dictation-bench corpus --from-text-file my_sentences.txt --out corpus/mine

# 3. The default corpus, plus a second person talking over you
dictation-bench corpus --from-macos-say --pollute --out corpus/party
```

Then `dictation-bench bench --corpus corpus/mine`. This is the part every other benchmark skips —
and it's usually the reason your experience differs from the internet's.

---

## 🎯 The dictation stack, if you want to build one

If no app gives you what you want — a hotkey from *your* window manager, no app window, a model
that stays loaded — [docs/recipe/dictation.md](docs/recipe/dictation.md) has the minimal version
this project grew out of: **one resident local server under `launchd`, one ~150-line shell script,
your own hotkey.** Deliberately not an app. Copy it and keep your setup.

---

## Why published tables disagree

The report scores every engine **three ways** — naive, Whisper-style, and number-aware — because
the scorer alone can decide the ranking. It prints all three so you can see when that is happening.

In [the example above](examples/report-m2-macbook-air.md#why-published-wer-numbers-disagree) all
three scorers agree (5.9% / 9.6% for the same transcripts), meaning the difference between those
systems is **real, not a formatting artefact**. That is a result too — and you only know it because
the scorer was tested rather than assumed. Where a scorer *does* move the numbers, the report shows
it and says by how much.

Method, including why both sides are normalised identically: **[docs/methodology.md](docs/methodology.md)**.

<details>
<summary><b>How it measures</b> (click to expand)</summary>

| Axis | What it does | Where it can mislead you |
|:--|:--|:--|
| **Accuracy** | WER on your corpus, three normalisers. Headline = everyday dictation (prose, jargon, long, background speech). | Synthetic speech is easy; small corpora make one word look like a trend. Both are printed. |
| **First phrase (cold)** | First clip, engine not yet used: process start + model load + shader/ANE compile. | Includes one-time app start-up; a resident app you never quit skips it. |
| **After that (warm)** | Median over the rest of the clips. | Engine time only — not audio capture or the paste keystroke. |
| **Capabilities** | Declared per engine (partials, resident, vocabulary, offline). | *Declared, not measured.* The report never infers them. |

</details>

---

## ⚠️ Honest limitations

- **This is an engine benchmark, not a product review.** It measures transcription quality and
  speed. UI, price, privacy policy, licensing, support and polish are not measured — and often
  matter more than the last half percent of WER.
- **It runs software you install.** It can't fairly drive a closed app's GUI; a product with no
  CLI or server is out of reach unless you wrap it.
- **One machine, one run.** Numbers are for *your* comparison. Re-run after a model upgrade.
- **Small corpus by default.** 28 clips, ~113 s. Enough to separate engines that differ by points;
  **not** enough to rank engines that differ by one word — and the report says so whenever
  that happens.

## 🤝 Contributing

Most valuable contributions, in order:

1. **A preset for software you use** — especially the GUI apps people are actually choosing
   between. A `[[engines]]` block plus one paragraph on how to start it.
2. **Real recordings** (with permission, with their exact text) — the scarcest input in ASR.
3. **A better normaliser rule**, with a test showing what it changes.

Keep promises small: if a preset's capability claims aren't verified, say so in its `notes`.

<details>
<summary><b>Development</b></summary>

```bash
pip install -e ".[dev]"
python -m pytest tests -q
ruff check src tests
```

Layout: `src/dictation_bench/{corpus,normalize,adapters,evaluate,runner,report,cli}.py`,
`testdata/reference` (the bundled corpus), `docs/`, `scripts/dictbench-ptt`.
CI runs the tests on Linux and macOS across Python 3.10–3.13, builds the wheel, and
`shellcheck`s the script.

</details>

## Privacy

No telemetry, no accounts, no network calls except to the engine URL you configure (loopback by
default). `results/` is git-ignored, so benchmarking your own voice doesn't get committed by accident.

## License

[MIT](LICENSE) for this project's code. Your dictation software, models and corpora keep their own
licences; this repository ships no models and redistributes no third-party software.

<div align="center"><sub>If this saved you a week of app-hopping, ⭐ the repo — it's how the next person finds it.</sub></div>

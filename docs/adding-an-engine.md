# Adding the software you actually use

`dictation-bench` does not know your app. It knows four ways to reach one. Pick the type
that matches what your software exposes, add it to `bench.toml`, and run `dictation-bench
bench`.

If you are unsure, start with `dictation-bench doctor` and `dictation-bench engines`.

---

## First: does it have a server or a CLI?

Before writing config, check (in order):

```bash
<app> --help                 # a CLI with an "input file" flag?
lsof -nP -iTCP -sTCP:LISTEN  # does it already listen on a local port?
```

Many GUI dictation apps expose something undocumented:

- **Handy** — its main binary has a headless batch mode:
  `Handy -f clip.wav --model <id> --json --repeat 3` (verified on v0.9.8, macOS).
- **whisper.cpp** — `whisper-server` (HTTP) or `whisper-cli -nt -f` (CLI).
- **WhisperKit** — `whisperkit-cli serve` (HTTP on :50060) or `transcribe` (CLI).
- **NeMo-Speech** — `nemo-speech serve` (HTTP, OpenAI-compatible subset).
- **faster-whisper-server**, **LM Studio**, many wrappers — OpenAI-compatible HTTP.
- **Moonshine**, **hns**, **parakeet.cpp** — CLIs printing text to stdout.

If yours has none of these, use the `custom` type and wrap whatever it offers. A GUI-only
app may be drivable with `osascript` or a keystroke automation, but say so in `notes` and
treat the number as yours, not ours.

---

## Type `http` — an OpenAI-compatible endpoint

The vast majority of local servers accept:

```bash
curl -F file=@clip.wav http://127.0.0.1:PORT/v1/audio/transcriptions
```

```toml
[[engines]]
name = "whisper.cpp server"
type = "http"
url = "http://127.0.0.1:8080/v1/audio/transcriptions"
model = ""                     # optional: sent as the `model` form field
capabilities = { service = true, offline = true }
```

The response must be JSON with a `text` (or `transcript`) key. `{"text": "..."}` and
`{"result": {"text": "..."}}` are both handled.

**Start it before benchmarking.** For a resident server there is no per-call model load, so
"first phrase" measures first-request warm-up (shaders, page cache) rather than app launch.
That distinction is printed in the report.

---

## Type `cli` — a command that prints text

```toml
[[engines]]
name = "whisper.cpp CLI"
type = "cli"
command = "whisper-cli -m models/ggml-base.en.bin -nt -f {wav}"
capabilities = { offline = true }
path = "/opt/homebrew/bin/whisper-cli"   # optional fallback if not on PATH
```

`{wav}` is replaced with the clip path; `{model}` with `model` if set. stdout is the
transcript. Lines beginning with `[` (timestamps/logs) are dropped; use `-nt` / `--output-txt`
style flags where they exist.

> **Note on warm numbers:** for a process-per-clip CLI, every invocation reloads the model.
> The report uses the engine's own internal timing where available and says when the warm
> number is not a real end-to-end wait.

---

## Type `json-cli` — JSON per call, with repeats

For engines that emit structured timing (like Handy):

```toml
[[engines]]
name = "Handy (batch)"
type = "json-cli"
command = ["/Applications/Handy.app/Contents/MacOS/Handy", "-f", "{wav}",
           "--model", "{model}", "--json", "--repeat", "{repeat}"]
model = "parakeet-tdt-0.6b-v3"
json_text_key = "text"
json_load_key = "load_ms"
json_infer_key = "transcribe_ms"
repeat = 3
capabilities = { offline = true }
```

`{repeat}` lets one process run inference N times, which separates model load from
inference — the difference between "a beat" and "instant".

---

## Type `custom` — any command

```toml
[[engines]]
name = "My wrapper"
type = "custom"
command = "my-transcriber --input {wav}"
capabilities = { offline = true }
notes = "Unverified wrapper; numbers are mine, not the project's."
```

Runs under `sh -c`. Anything on stdout is the transcript. This is the escape hatch — use it
rather than skipping an app you care about.

---

## Capabilities: declare, don't assume

Capabilities are **claims about software**, which the tool cannot verify:

| key | meaning | typical evidence |
|:--|:--|:--|
| `partials` | shows words while you speak | you have seen it do so |
| `service` | stays resident between phrases | it runs as a server/daemon |
| `vocab` | custom vocabulary or word boosting | documented feature |
| `formats` | accepts mp3/m4a/etc. directly | documented feature |
| `faster_than_realtime` | keeps up on long files | your own long-file test |
| `offline` | needs no network | you have used it offline |

Leaving a key out means "unknown", and the report will not claim it either way.

---

## Checking your work

```bash
dictation-bench doctor            # shows ✓/✗ per configured engine
dictation-bench bench --groups main --max-clips 3   # quick smoke run (~20 s)
```

A good preset should: show ✓ in `doctor`, produce sensible transcripts in the smoke run,
and state in `notes` anything you could not verify.

# Adding the software you actually use

`dictation-bench` does not know your app. It knows four ways to reach one. Pick the type that
matches what your software exposes, add it to `bench.toml`, and run `dictation-bench bench`.

If you are unsure where to start, run `dictation-bench doctor` and `dictation-bench engines`.

## First: does it have a server or a CLI?

Check in this order before writing any config:

```bash
<app> --help                 # a CLI with an input-file flag?
lsof -nP -iTCP -sTCP:LISTEN  # is it already listening on a local port?
```

Several GUI dictation apps expose something undocumented:

- **Handy**: its main binary has a headless batch mode,
  `Handy -f clip.wav --model <id> --json --repeat 3`. Verified on v0.9.8 for macOS.
- **whisper.cpp**: `whisper-server` for HTTP, or `whisper-cli -nt -f` for a CLI.
- **WhisperKit**: `whisperkit-cli serve` listens on port 50060; `whisperkit-cli transcribe` is the CLI.
- **NeMo-Speech**: `nemo-speech serve` exposes an OpenAI-compatible subset.
- **faster-whisper-server**, **LM Studio** and most wrappers: OpenAI-compatible HTTP.
- **Moonshine**, **hns**, **parakeet.cpp**: CLIs that print text to stdout.

If there is none of the above, use the `custom` type and wrap whatever the app offers. A GUI-only
app can sometimes be driven with `osascript` or a keystroke automation. Say so in `notes` if you do
that, because the number is then yours rather than the project's.

## Type `http`: an OpenAI-compatible endpoint

Most local servers accept this:

```bash
curl -F file=@clip.wav http://127.0.0.1:PORT/v1/audio/transcriptions
```

```toml
[[engines]]
name = "whisper.cpp server"
type = "http"
url = "http://127.0.0.1:8080/v1/audio/transcriptions"
model = ""                     # optional, sent as the `model` form field
capabilities = { service = true, offline = true }
```

The response needs JSON with a `text` or `transcript` key. Both `{"text": "..."}` and
`{"result": {"text": "..."}}` are handled.

Start the server before benchmarking. For a resident server there is no per-call model load, so
"first phrase" measures first-request warm-up such as shaders or page cache rather than app launch.
The report prints that distinction.

## Type `cli`: a command that prints text

```toml
[[engines]]
name = "whisper.cpp CLI"
type = "cli"
command = "whisper-cli -m models/ggml-base.en.bin -nt -f {wav}"
capabilities = { offline = true }
path = "/opt/homebrew/bin/whisper-cli"   # optional fallback if not on PATH
```

`{wav}` becomes the clip path and `{model}` becomes the `model` field if one is set. stdout is the
transcript. Lines beginning with `[` are dropped as timestamps or logs, and flags like `-nt` remove
them at the source where they exist.

For a process-per-clip CLI, every invocation reloads the model. The report uses the engine's own
internal timing where it provides one, and says when the warm number is not a real end-to-end wait.

## Type `json-cli`: JSON per call, with repeats

Use this for engines that emit structured timing, such as Handy:

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

`{repeat}` runs inference several times inside one process, which separates model load from
inference. That is the difference between a beat and instant.

## Type `custom`: any command

```toml
[[engines]]
name = "My wrapper"
type = "custom"
command = "my-transcriber --input {wav}"
capabilities = { offline = true }
notes = "Unverified wrapper. These numbers are mine, not the project's."
```

Runs under `sh -c`, and anything on stdout is the transcript. Use this rather than leaving out an
app you care about.

## Capabilities: declare, don't assume

Capabilities are claims about software that the tool cannot verify:

| Key | Meaning | Typical evidence |
|:--|:--|:--|
| `partials` | shows words while you speak | you have seen it do so |
| `service` | stays resident between phrases | it runs as a server or daemon |
| `vocab` | custom vocabulary or word boosting | documented feature |
| `formats` | accepts mp3, m4a and so on directly | documented feature |
| `faster_than_realtime` | keeps up on long files | your own long-file test |
| `offline` | works without a network | you have used it offline |

Leaving a key out means unknown, and the report will not claim it either way.

## Checking your work

```bash
dictation-bench doctor                                 # per-engine check marks
dictation-bench bench --groups main --max-clips 3      # smoke run, about 20 seconds
```

A working preset shows up in `doctor`, produces sensible transcripts in the smoke run, and states
in `notes` anything you could not verify.

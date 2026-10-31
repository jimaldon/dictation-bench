# A minimal local dictation stack

`dictation-bench` started as a way to choose between dictation engines. The setup that won on the
machine it ran on was not an app. It was a hotkey daemon calling a script, and the script talking to
a server that keeps the model loaded:

```
your hotkey daemon  ->  scripts/dictbench-ptt  ->  resident local ASR server
                        record, POST, paste       model stays in memory
```

Why this shape:

- With a resident server a phrase costs one inference, around 100 to 300 ms, instead of a model load.
- The script only records, makes one HTTP call and pastes. It does not own the keyboard, so it works
  with whatever hotkey system you already run: skhd, Hammerspoon, GNOME or KDE shortcuts, a macro pad.
- The server binds `127.0.0.1`, so audio does not leave the machine.
- It is about 150 lines you can read in one sitting, and it beeps and notifies instead of failing
  silently on an empty recording, a dead server or an empty transcript.

This is deliberately not an app. If you want a menu bar, a settings window and model management, use
one of the packaged apps and benchmark it to find out what it is actually running.

## Before you pick an engine

Run the benchmark first. It takes minutes rather than hours, and the result depends on your machine:

```bash
dictation-bench bench --preset nemo-speech-server --preset whisperkit-server
dictation-bench bench --preset whisper.cpp-server
```

Then use the matching `serve` command below.

## What the pieces cost

Measured on one Apple M2. Your numbers will differ, which is the reason to re-run.

| Behaviour | Why it matters |
|:--|:--|
| First phrase after launch takes about 1.5 to 2 s, for model load and shader compile | Start the server at login with `launchd` so you are never paying this mid-sentence. |
| Every later phrase takes about 100 to 250 ms | This is what makes it feel instant. |
| Audio must be 16-bit | CoreAudio can hand `sox` 32-bit samples, and some servers reject 32-bit WAV with `unsupported WAV encoding`. The script forces `-b 16`. |
| The start beep takes about 0.3 s, sometimes 0.85 s | That is `afplay` process and audio start-up jitter. It is only feedback, so it runs in the background and never delays the transcript. |
| A leftover recorder holds the microphone | A stuck `sox` from an earlier session writes a very large WAV. `dictbench-ptt status` reports it, and `kill -INT` flushes the file cleanly. |

## Setup

### 1. Install the tools

```bash
brew install sox jq
```

### 2. Put the script on your PATH

```bash
mkdir -p ~/.local/bin
cp scripts/dictbench-ptt ~/.local/bin/
chmod +x ~/.local/bin/dictbench-ptt
```

### 3. Start a resident server

Use whichever engine won your benchmark. Two examples:

```bash
# NeMo-Speech.cpp with Parakeet TDT v3, Metal on Apple silicon
nemo-speech serve --asr-model parakeet-tdt --host 127.0.0.1 --port 50060 --no-ui

# whisper.cpp
whisper-server --model models/ggml-base.en.bin --host 127.0.0.1 --port 50060
```

Confirm it answers:

```bash
curl -sS http://127.0.0.1:50060/health || curl -sS http://127.0.0.1:50060/v1/models
```

### 4. Keep it running across logout and reboot (macOS)

Copy `docs/recipe/com.example.dictbench-server.plist` into `~/Library/LaunchAgents/`, replace
`YOUR_USER`, the label and the serve command, then load it:

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.example.dictbench-server.plist
curl -sS http://127.0.0.1:50060/health
```

If the whole thing stops working after a reboot with no sound at all, suspect the hotkey and not the
server. Check `System Settings > General > Login Items & Extensions > Allow in the Background`,
because a disallowed item is skipped at login without an error.

### 5. Bind a key

Use whatever you already run. With [skhd](https://github.com/koekeishiya/skhd):

```
# ~/.config/skhd/skhdrc
alt - f19 : ~/.local/bin/dictbench-ptt toggle
```

Then `skhd --restart-service`. On Linux, bind the same command in your desktop shortcut. `toggle`
starts and stops on separate taps, with no hold mode on purpose, so key repeat, a lost key-up and
switching apps mid-phrase do not leave the recorder running.

### 6. Grant permissions (macOS, first run only)

Microphone access goes to the process that runs the script, usually your hotkey daemon. Tap the key,
speak, stop; if you get the error beep, check `System Settings > Privacy & Security > Microphone`.

Accessibility goes to the process that runs `osascript`, again usually the daemon, so the paste
keystroke is allowed. Without it the paste silently does nothing, but the text is on the clipboard
and Command-V works by hand.

Diagnose without touching the keyboard:

```bash
dictbench-ptt ping      # is the server up?
dictbench-ptt status    # is it recording now?
dictbench-ptt log       # last 30 lines, including the transcript it produced
```

## Configuration

| Variable | Default | Use |
|:--|:--|:--|
| `DICTBENCH_URL` | `http://127.0.0.1:50060` | server base URL |
| `DICTBENCH_FIELD` | none | extra multipart field, for example `automatic_punctuation=true` |
| `DICTBENCH_AGENT` | none | launchctl label to kickstart if the server died |
| `DICTBENCH_STATE` | `${TMPDIR:-/tmp}/dictbench-ptt-$UID` | state directory for pid, wav and log |
| `DICTBENCH_NO_PASTE` | `0` | set to `1` to copy only and never synthesise Command-V |

Point it at any OpenAI-compatible server. Nothing in the script is specific to one engine.

## When it goes wrong

| Symptom | Likely cause | Fix |
|:--|:--|:--|
| Error beep, "No audio" | no microphone permission for the daemon | re-grant microphone access, restart the daemon |
| Error beep, "server unavailable" | server down or port taken | `dictbench-ptt ping`, `lsof -nP -iTCP:50060` |
| Error beep, "Empty transcript" | server rejected the WAV, or there was only silence | `dictbench-ptt log` prints the server's reply |
| Beep but nothing pasted | no Accessibility permission for `osascript` | paste by hand, then grant Accessibility to the daemon |
| No beep at all | the hotkey is not reaching the script | run the script from a terminal to isolate it |
| Two beeps, last word missing | stop was pressed before the last word | say the final word, then stop |

## Scope

In scope: one microphone, one engine, one hotkey, tap to toggle, paste into the focused app.

Out of scope: streaming partials (many engines cannot do it, and those that can need a WebSocket
client rather than this script), history, per-app formatting and meeting transcription. Those are
app features.

# A minimal, local dictation stack (the recipe this project grew out of)

`dictation-bench` started as a tool for choosing between dictation engines. The stack that
won, on the machine it ran on, was not an app. It was:

```
your hotkey daemon  →  scripts/dictbench-ptt  →  resident local ASR server
                         (record, POST, paste)      (model stays loaded)
```

**Why this shape:**

- A resident server means a phrase costs one inference (~100–300 ms), not a model load.
- The script owns nothing but recording, one HTTP call, and a paste — so it works with
  whatever hotkey system you already use (skhd, Hammerspoon, GNOME/KDE shortcuts, a macro
  pad) instead of fighting it for the keyboard.
- Nothing leaves the machine: the server binds `127.0.0.1`.
- It is ~150 lines you can read in one sitting, and it fails loudly (beep + notification) on
  an empty recording, a dead server, or an empty transcript.

This is deliberately **not an app**. If you want a menu bar, settings UI, history and model
manager, use one of the packaged apps (`dictation-bench engines` names several you can
benchmark) — and then come back here when you want to know what to put in it.

## Before you pick an engine

Run the benchmark first; it takes minutes, not hours, and the result depends on your machine:

```bash
dictation-bench bench --preset nemo-speech-server --preset whisperkit-server
dictation-bench bench --preset whisper.cpp-server
```

Pick whichever is accurate enough *for you* and fastest *on your machine*. Then use the
matching `serve` command below.

## What the pieces actually cost (measured, one Apple M2)

Numbers from the project's own runs; yours will differ. Re-run on your hardware.

| Behaviour | Why it matters |
|:--|:--|
| **First phrase after launch: ~1.5–2 s** (model load + shader compile) | Use `KeepAlive`, or start the server at login with `launchd`, so you are never paying this mid-sentence. |
| **Every later phrase: ~100–250 ms** | This is what makes it feel instant. |
| **Audio format must be 16-bit** | macOS CoreAudio can hand `sox` 32-bit samples; some servers reject 32-bit WAV with `unsupported WAV encoding`. The script forces `-b 16`. |
| **Start beep: ~0.3 s, sometimes ~0.85 s** | `afplay` process/audio-startup jitter. It is only feedback, so it runs in the background — it never delays the transcript. |
| **Leftover recorder** | A stuck `sox` from an earlier session holds the mic and writes a huge WAV. `dictbench-ptt status` tells you; `kill -INT` flushes cleanly. |

## Setup

### 1. Install tools

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

Pick the engine that won your benchmark. Examples:

```bash
# NeMo-Speech.cpp (Parakeet TDT v3, Metal/GPU on Apple silicon)
nemo-speech serve --asr-model parakeet-tdt --host 127.0.0.1 --port 50060 --no-ui

# whisper.cpp
whisper-server --model models/ggml-base.en.bin --host 127.0.0.1 --port 50060
```

Check it answers:

```bash
curl -sS http://127.0.0.1:50060/health || curl -sS http://127.0.0.1:50060/v1/models
```

### 4. Make it survive logout/reboot (macOS)

Copy `docs/recipe/com.example.dictbench-server.plist` to
`~/Library/LaunchAgents/`, replace `YOUR_USER`/the label/the serve command, then:

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.example.dictbench-server.plist
curl -sS http://127.0.0.1:50060/health
```

> **If it stops working after a reboot** with no sound at all → the hotkey, not the server:
> check `System Settings → General → Login Items & Extensions → Allow in the Background`.
> A disallowed item is silently skipped at login. (Yes, this bit us.)

### 5. Bind a key

Whatever you already run. With [skhd](https://github.com/koekeishiya/skhd):

```
# ~/.config/skhd/skhdrc
alt - f19 : ~/.local/bin/dictbench-ptt toggle
```

Then `skhd --restart-service`. On Linux with a compositor shortcut, bind the same command.
`toggle` is tap-to-start, tap-to-stop; there is no "hold" mode on purpose (it survives
key-repeat, lost key-up events and switching apps mid-phrase).

### 6. Permissions (macOS, first run only)

- **Microphone** — for the process that runs the script (typically your hotkey daemon).
  Approve once: tap the key, speak, stop; if you get the error beep, check
  `System Settings → Privacy & Security → Microphone`.
- **Accessibility** — for the process that runs `osascript` (again, usually the daemon), so
  the paste keystroke is allowed. Without it the paste silently no-ops — but the text is on
  your clipboard, so ⌘V works by hand.

Diagnose without a keyboard:

```bash
dictbench-ptt ping      # is the server up?
dictbench-ptt status    # is it currently recording?
dictbench-ptt log       # last 30 lines, including the transcript it produced
```

## Configuration

| Variable | Default | Use |
|:--|:--|:--|
| `DICTBENCH_URL` | `http://127.0.0.1:50060` | server base URL |
| `DICTBENCH_FIELD` | — | extra multipart field, e.g. `automatic_punctuation=true` |
| `DICTBENCH_AGENT` | — | launchctl label to kickstart if the server died |
| `DICTBENCH_STATE` | `${TMPDIR:-/tmp}/dictbench-ptt-$UID` | state dir (pid, wav, log) |
| `DICTBENCH_NO_PASTE` | `0` | `1` = copy only, never synthesise ⌘V |

Point it at any OpenAI-compatible server; nothing in the script is NeMo-specific.

## When it goes wrong

| Symptom | Likely cause | Fix |
|:--|:--|:--|
| Error beep, "No audio" | microphone permission for the daemon | re-grant mic permission, restart the daemon |
| Error beep, "server unavailable" | server down / port taken | `dictbench-ptt ping`, `lsof -nP -iTCP:50060` |
| Error beep, "Empty transcript" | server rejected the WAV, or silence | check `dictbench-ptt log` — it prints the server's reply |
| Beep but nothing pasted | Accessibility missing for `osascript` | paste by hand with ⌘V; grant Accessibility to the daemon |
| No beep at all | hotkey not reaching the script (remap, BTM, WM config) | test the script directly from a terminal |
| Two beeps, one word missing | you pressed stop before the last word | say the last word, then stop |

## Scope

In: one mic, one engine, one hotkey, tap-to-toggle, paste into the focused app.
Out: streaming partials (many engines can't do it; those that can need a WebSocket client,
not this script), history, per-app formatting, meeting transcription. Those are app
features — use an app for them.

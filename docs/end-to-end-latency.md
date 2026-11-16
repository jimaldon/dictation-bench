# End-to-end latency (experimental)

`bench` measures engines the way a developer does: hand a file to a command, time the answer. A
dictation **app** is experienced differently — you release the key and wait for words to appear in
the app you were typing in. `e2e` measures that second thing.

```bash
dictation-bench e2e --app Handy --stop-keys 'cmd+`' --out results/e2e
```

**This command is experimental and needs a Mac with a GUI session.** It drives a real installed app
through the macOS Accessibility APIs. It cannot run in CI, over SSH, or headless, and it does not
work on Linux.

## What is actually timed

> **Recording end → final text in a controlled editor.**

- **Start of the clock:** the app's audio capture stops, i.e. the moment the stop shortcut is sent.
- **End of the clock:** the editor's text has stopped changing for 300 ms.
- **Not measured:** model load time on its own, inference time reported by the app, time to the
  first partial word, or anything about on-screen rendering.

Apps that type while you speak finish before you stop, so their stop-to-text time is near zero and
means nothing. Any measurement that claims otherwise is measuring keystrokes, not latency. Keep that
in mind when comparing an app that streams text with one that inserts a block at the end: this
harness measures the wait after you finish, which is the number people complain about.

## How a trial works

1. The clip is played into **BlackHole 2ch**, a virtual audio device that loops its output back as a
   microphone. The app is set to use it, so every app receives identical samples.
2. The stop shortcut is sent through System Events. The clock starts.
3. The controlled editor — a TextEdit document with autocorrect, smart quotes and text replacement
   off — is read every 10 ms through Accessibility.
4. The first non-empty text and the settled final text are both recorded.
5. A trial that produces nothing within `--timeout` (default 12 s) is recorded as `no_text` or
   `timeout`. It is **counted** in the report, never dropped.

Clips whose audio is loud right at the start or end are flagged: "recording ended" is then a poor
stand-in for "speech ended", and the note says so.

## Preconditions

```bash
dictation-bench e2e --dry-run
```

prints the plan and everything this machine is missing, without playing audio. A real run needs:

| Requirement | Why |
|:--|:--|
| macOS with a signed-in, unlocked GUI session | The app and the editor must be real windows |
| `brew install blackhole-2ch`, then a re-login | The virtual microphone every app shares |
| The app configured to use BlackHole as its input | Otherwise it records your room, not the clip |
| Accessibility permission for your terminal | To send the stop shortcut and read the editor |
| Automation permission for TextEdit (macOS may prompt) | To read and clear the editor |
| Text input aids off (autocorrect, smart quotes, replacement, predictive) | They change the text being timed |
| `--app` installed and past onboarding | The harness drives it; it cannot set it up |
| On power, Do Not Disturb, nothing else open | Fan noise and background load change the number |

If any of these is missing, the command stops with the full list rather than producing a number that
cannot be reproduced.

## Setting the stop shortcut

Only two arguments are app-specific: `--app` and `--stop-keys`. The shortcut must be a **plain
keystroke combination** that ends recording in the app you chose:

```bash
dictation-bench e2e --app Handy --stop-keys 'cmd+`'
```

`--stop-keys` accepts `cmd`, `shift`, `opt` and `ctrl` joined with `+`, and is sent as a keystroke
through System Events. Two things therefore will **not** work through it:

- pressing and releasing a modifier alone (an `fn` or lone `Right Option` toggle);
- an app whose stop action is a URL scheme, such as `superwhisper://stop`.

If your app stops on a single modifier, bind the stop action to an ordinary key combination in the
app's own settings for the run, and record that choice in your notes. A measurement whose trigger
you cannot describe exactly should not be published.

Record the app version and settings with the run (`--app` is in the JSON; note the version and
model yourself). A latency number without both is not comparable with anyone else's.

## Reading the output

`results/e2e/e2e.md` gives final and first-text p50/p95 plus the counts of trials that produced no
text or timed out. `results/e2e/e2e.json` has every trial and the exact settings.

Percentiles from fewer than ten trials are decoration. Use `--max-clips 10` or more, run the whole
thing twice, and treat a difference smaller than run-to-run variation as noise.

Transcript text is stored in the JSON (it is the only way to check a wrong result) and deliberately
left out of the Markdown, because the corpus may be your own voice saying private things.

## Why this is separate from `bench`

`bench` numbers are comparable across machines and reproducible in CI; these are not. Mixing them in
one table would imply a precision this measurement does not have. The two reports are meant to be
read together: `bench` tells you which engine is accurate and fast per phrase, `e2e` tells you what
that engine's app feels like between releasing the key and seeing words.

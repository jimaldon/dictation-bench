# Record your own corpus

The synthetic reference corpus measures the model. It does not measure **your** voice, **your**
microphone or the room you actually dictate in. A short recording session fixes that:

```bash
dictation-bench corpus record --out corpus/mine
```

Ten prompts, about two minutes. Then:

```bash
dictation-bench bench --corpus corpus/mine
```

## What a session looks like

For every prompt the recorder:

1. **Shows the sentence** to read. `--freeform` skips this: you dictate whatever you like.
2. **Waits for Enter**, then records until you press **Ctrl-C**. Ctrl-C ends that take; it does not
   quit the session or lose the audio.
3. **Measures the take** and reports duration, peak level and level, and flags clipping or a take
   that is too quiet.
4. **Offers `[p]` play, `[r]` re-record or `[s]` skip** before you commit to it.
5. **Asks for the exact words** if the prompt was not quite what you said. This is the only ground
   truth the benchmark ever sees, so a corrected transcript matters more than a neat recording.
6. Asks for a **group** (`main`, `numeric`, `jargon`, `stress`, `long`, `freeform`).

At the end it asks once for condition labels — room, background noise, microphone type — and writes
the corpus. `dictation-bench bench --corpus corpus/mine` runs immediately afterwards.

## Prompts

```bash
dictation-bench corpus record --list                 # every prompt, grouped
dictation-bench corpus record --list --groups numeric
dictation-bench corpus record --out corpus/mine --prompt m01,n03,j02
dictation-bench corpus record --out corpus/mine --groups main --count 5
```

Ids (`m01`, `n03`, `j02`, `s01`, `L01`) are permanent. Recording the same prompt again later —
after a microphone change, or a month later — gives clips that are directly comparable, and
`dictation-bench compare` will report the change per clip.

`--count` alone takes the first prompts of the selected groups, so two sessions with the same
arguments cover the same sentences.

## Microphones

The default is whatever macOS uses for input. To see the others:

```bash
dictation-bench corpus record --list-mics
dictation-bench corpus record --out corpus/mine --mic 2
```

Listing and selecting a specific device needs `ffmpeg`; plain recording needs only SoX. If the
terminal has never been granted microphone access, the first take records silence — macOS shows a
permission prompt, and `System Settings > Privacy & Security > Microphone` fixes it if you dismissed
it. The recorder reports "no audio" rather than writing an empty clip.

The **microphone type** answer (`builtin`, `headset`, `external`) is what lets you tell later
whether a clip came from a headset you were wearing or the laptop's built-in mic.

## Levels are reported, never fixed

The recorder never normalizes, compresses or gates the audio. Changing the audio would change the
thing being measured. Instead it reports and advises:

| Report | Meaning | What to do |
|:--|:--|:--|
| peak near 0 dBFS, clipped samples | The input is saturating | Move back, or lower the input level in macOS Sound settings |
| level below −34 dBFS | Too quiet; engines do badly on it | Move closer to the microphone |
| otherwise | A usable take | Keep it |

Clipped audio is the one condition that measurably breaks every engine, so re-record rather than
keep it. A quiet take is worth keeping only if a quiet take is genuinely how you dictate.

## What lands on disk

```
corpus/mine/
  manifest.tsv      clip, group, exact text, wav
  u01.wav ...       16 kHz mono PCM16
  corpus.json       conditions per take, duration, peak/RMS levels, clipping counts
  conditions.json   the session labels
```

`corpus.json` keeps the measured level of every take, so a later accuracy change can be traced to
audio quality instead of guessed at. The exact words of each clip are also recorded there, which is
why a corpus directory is **private** — review it before sharing or posting it.

## Recording more clips later

Running the recorder again on an existing directory **adds** clips with fresh ids. It never
overwrites a clip that already exists: re-recording a sentence produces `u07` next to `u03`, and
both stay in the corpus. That is deliberate — replacing audio in place would silently change what a
past result measured.

To replace a clip deliberately, remove its WAV file and its line from `manifest.tsv` before recording
again. A corpus whose clips change gets a new fingerprint, so `compare` refuses to mix a run made
before with a run made after — the right answer is to record the added clip and re-benchmark, not to
compare across a corpus edit.

## Limits worth knowing

- Recording happens in the terminal. There is no GUI, and no level meter while you speak.
- One microphone at a time; switching mid-session means a new session, since conditions are asked
  once.
- A typo in the transcript becomes permanent ground truth for that clip. Re-listen before accepting.
- Engine accuracy on real voices is usually **worse** than on the synthetic corpus. Numbers from
  different people's recordings are not comparable with each other.
- File format support beyond WAV for existing audio still goes through `--from-clip`.

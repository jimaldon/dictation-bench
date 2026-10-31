"""Corpus loading and generation.

A corpus is a directory holding:

- ``manifest.tsv``: ``clip<TAB>group<TAB>reference text<TAB>path-to-wav``
  (a fourth column is optional; when absent the wav is ``<clip>.wav``)
- the WAV files themselves, 16 kHz mono PCM16
- ``corpus.json`` (optional): how it was made — source, voice, rate, hashes

Two ways to get one:

1. ``dictation-bench corpus --from-macos-say`` renders a reference corpus on a
   Mac.  It is deterministic for a given voice and rate, which is what makes
   published numbers repeatable.
2. ``dictation-bench corpus --from-clip recording.wav --ref "the text"`` makes
   short clips from your own recording.  Splitting is by silence when the clip
   is long; a short clip becomes one test item.

The *default* reference corpus lives in ``testdata/reference``.  It is a
byte-for-byte image of the corpus the benchmark was originally developed on,
so older results stay comparable, and it works on any OS.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CorpusError


@dataclass
class Clip:
    name: str
    group: str
    reference: str
    wav: Path

    @property
    def duration_s(self) -> float:
        try:
            with wave.open(str(self.wav), "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:
            return 0.0


@dataclass
class Corpus:
    clips: list[Clip]
    root: Path
    meta: dict = field(default_factory=dict)

    def groups(self) -> list[str]:
        seen: list[str] = []
        for c in self.clips:
            if c.group not in seen:
                seen.append(c.group)
        return seen

    def __len__(self) -> int:
        return len(self.clips)


MANIFEST = "manifest.tsv"


def load(root: Path) -> Corpus:
    root = Path(root)
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise CorpusError(
            f"no {MANIFEST} in {root}. Pass --corpus, or run "
            f"`dictation-bench corpus --from-macos-say reference/` to create one."
        )
    clips: list[Clip] = []
    for lineno, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            raise CorpusError(
                f"{manifest}:{lineno}: need clip<TAB>group<TAB>reference text"
            )
        name, group, ref = parts[0], parts[1], parts[2]
        wav = Path(parts[3]) if len(parts) > 3 and parts[3] else Path(f"{name}.wav")
        if not wav.is_absolute():
            wav = root / wav
        if not wav.is_file():
            raise CorpusError(f"{manifest}:{lineno}: missing audio {wav}")
        clips.append(Clip(name, group, ref, wav))
    if not clips:
        raise CorpusError(f"{manifest} lists no clips")
    meta = {}
    meta_path = root / "corpus.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return Corpus(clips, root, meta)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #

#: The reference corpus.  Group meanings:
#: ``main``      everyday dictation prose — the headline number
#: ``numeric``   numbers, times, money — where engines disagree most on format
#: ``stress``    acronyms and spelled-out letters
#: ``long``      one ~20 s utterance, for how cost grows with length
#: ``jargon``    proper nouns and technical terms (the usual real-world failures)
REFERENCE_LINES: list[tuple[str, str, str]] = [
    ("main", "the quick brown fox jumps over the lazy dog", "Prose"),
    ("main", "please refactor the authentication middleware and add unit tests", "Prose"),
    ("main", "can you explain how the cache aware streaming encoder reuses hidden states across chunks", "Prose"),
    ("main", "Nemotron and Parakeet are speech recognition models from Nvidia", "Prose"),
    ("main", "Alacritty is a gpu accelerated terminal emulator written in rust", "Jargon"),
    ("main", "WhisperKit runs the encoder on the apple neural engine to save battery", "Prose"),
    ("main", "summarize the last commit and list any files that changed in the pull request", "Prose"),
    ("main", "schedule a reminder to call the dentist tomorrow morning", "Prose"),
    ("main", "the deployment failed because the database migration timed out", "Prose"),
    ("main", "please commit these changes and push them to the feature branch", "Prose"),
    ("main", "add error handling around the network request and log the response", "Prose"),
    ("main", "the accessibility audit found two buttons without labels", "Prose"),
    ("main", "run the full test suite before merging the pull request", "Prose"),
    ("main", "convert the image to grayscale and resize it before uploading", "Prose"),
    ("main", "the server responded with a not found status code", "Prose"),
    ("main", "my wifi password contains an uppercase letter and a special symbol", "Prose"),
    ("main", "remind me to buy milk eggs and bread on the way home", "Prose"),
    ("main", "what is the weather like in san francisco this weekend", "Prose"),
    ("main", "the coffee grinder needs a new burr set soon", "Prose"),
    ("numeric", "the meeting is scheduled for twenty twenty six at three thirty in the afternoon", "Numbers"),
    ("numeric", "add three point one four as the value of pi in the constant", "Numbers"),
    ("numeric", "the invoice total is one thousand two hundred and fifty dollars", "Numbers"),
    ("numeric", "call me at five forty five in the evening", "Numbers"),
    ("numeric", "there were ninety nine bottles of beer on the wall", "Numbers"),
    ("numeric", "the answer to everything is forty two", "Numbers"),
    ("long", "I want to add a new keyboard shortcut that starts a local speech to text server keeps the model resident in memory and pastes the result into whichever application currently has focus without ever sending any audio off the machine and I also want the text to appear while I am still speaking instead of only after I press the key a second time", "Long utterance"),
    ("stress", "run skhd and check whether the f nineteen key binding still works", "Acronyms"),
    ("stress", "use the c l i to transcribe a wav file and print the text to standard output", "Acronyms"),
]

#: Voices that ship with macOS, for ``--voice`` choices.  Any installed voice
#: name works; these are just the common ones.
MACOS_VOICES = ["Samantha", "Alex", "Karen", "Daniel", "Moira", "Tessa"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_16k_mono(src: Path, dst: Path) -> None:
    """Convert any audio to 16 kHz mono PCM16 with sox."""
    if not shutil.which("sox"):
        raise CorpusError("sox is required for audio conversion (brew install sox)")
    subprocess.run(
        ["sox", str(src), "-r", "16000", "-c", "1", "-b", "16", str(dst)],
        check=True,
        capture_output=True,
    )


def _split_by_silence(wav: Path, min_s: float = 0.6, max_s: float = 20.0) -> list[float]:
    """Return (start, end) pairs split on silence, using sox silence detection.

    Falls back to one clip when sox cannot split it usefully.  Timings are
    approximate; the caller re-transcribes each slice and keeps it only if the
    total reference text can be consumed, which is checked by the caller.
    """
    import re

    proc = subprocess.run(
        ["sox", str(wav), "-n", "silence", "1", "0.3", "2%", "1", "0.25", "2%"],
        capture_output=True,
        text=True,
    )
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    with wave.open(str(wav), "rb") as w:
        total = w.getnframes() / float(w.getframerate())
    top = min(total, max_s)
    bounds: list[tuple[float, float]] = []
    for s in starts:
        if s >= top:
            break
        e = next((x for x in ends if x > s), top)
        e = min(e, top)
        if e - s >= min_s:
            bounds.append((s, e))
    return bounds


def from_text_file(
    text_file: Path,
    out_dir: Path,
    *,
    voice: str = "Samantha",
    rate: int = 170,
    only: set[str] | None = None,
) -> Corpus:
    """Render one clip per line of ``text_file`` with macOS ``say``.

    Lines may be ``text`` or ``group<TAB>text``.  This is how a Windows user's
    existing corpus, or a blog's sentence list, becomes a local test set.
    """
    if not shutil.which("say"):
        raise CorpusError(
            "macOS `say` is not available; it is the only built-in renderer. "
            "Use --corpus with a pre-built corpus instead."
        )
    rows: list[tuple[str, str]] = []
    for raw in text_file.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            group, text = raw.split("\t", 1)
        else:
            group, text = "main", raw
        rows.append((group.strip(), text.strip()))
    if only:
        rows = [r for r in rows if r[0] in only]
    if not rows:
        raise CorpusError(f"no usable lines in {text_file}")
    return _render(rows, out_dir, voice=voice, rate=rate,
                   source={"type": "text-file", "path": str(text_file)})


def from_single_recording(
    wav: Path,
    reference: str,
    out_dir: Path,
    *,
    max_clip_s: float = 12.0,
) -> Corpus:
    """Build a corpus from one (or a few) clips of your own recording.

    The point is to test *your* mic and *your* voice, not a synthetic voice.
    For long recordings, split at silence and assign consecutive reference
    lines; the caller should verify lengths line up.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    norm_src = out_dir / "_source16k.wav"
    _to_16k_mono(wav, norm_src)
    with wave.open(str(norm_src), "rb") as w:
        total = w.getnframes() / float(w.getframerate())

    rows = [tuple(r.split("\t", 1)) if "\t" in r else ("main", r)
            for r in reference.strip().splitlines() if r.strip()]
    rows = [(str(r[0]), str(r[1])) for r in rows]

    bounds = _split_by_silence(norm_src) if total > max_clip_s else [(0.0, total)]
    if total <= max_clip_s:
        bounds = [(0.0, total)]
    if len(bounds) != len(rows):
        raise CorpusError(
            f"found {len(bounds)} segment(s) in {wav} but {len(rows)} reference "
            f"line(s). For a long recording, give one reference line per segment "
            f"(silence-split), or set reference to a single line for a single clip."
        )
    rendered: list[tuple[str, str]] = []
    meta_clips = []
    for idx, (start, end) in enumerate(bounds, 1):
        group, text = rows[idx - 1]
        name = f"u{idx:02d}"
        out = out_dir / f"{name}.wav"
        subprocess.run(
            ["sox", str(norm_src), str(out), "trim", f"{start:.3f}", f"{end - start:.3f}"],
            check=True, capture_output=True,
        )
        rendered.append((group, text))
        meta_clips.append({"clip": name, "start_s": round(start, 3),
                           "end_s": round(end, 3), "group": group})
    corpus = _write_manifest(rendered, out_dir, names=[m["clip"] for m in meta_clips])
    corpus.meta = {
        "source": {"type": "recording", "path": str(wav), "sha256": _sha256(wav)},
        "segments": meta_clips,
        "note": "Real voice + real microphone. Ground truth is whatever you typed.",
    }
    (out_dir / "corpus.json").write_text(json.dumps(corpus.meta, indent=2) + "\n")
    return corpus


def from_macos_say(
    out_dir: Path,
    *,
    voice: str = "Samantha",
    rate: int = 170,
    only: set[str] | None = None,
    pollute: bool = False,
    seed: int = 0,
) -> Corpus:
    """Render the built-in reference corpus with macOS ``say``."""
    if not shutil.which("say"):
        raise CorpusError(
            "macOS `say` is not available. The reference corpus in testdata/reference "
            "works everywhere; this flag is only for rendering a fresh copy."
        )
    rows = REFERENCE_LINES
    if only:
        rows = [r for r in rows if r[0] in only]
    corpus = _render(rows, out_dir, voice=voice, rate=rate,
                     source={"type": "macos-say", "voice": voice, "rate": rate})
    if pollute:
        _add_polluted_clips(corpus, out_dir, seed=seed)
    return corpus


def _render(
    rows: list[tuple[str, str, str]],
    out_dir: Path,
    *,
    voice: str,
    rate: int,
    source: dict,
) -> Corpus:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not shutil.which("sox"):
        raise CorpusError("sox is required (brew install sox)")
    # Number main clips per prefix so ids stay stable across partial renders.
    counts: dict[str, int] = {}
    rendered: list[tuple[str, str]] = []
    names: list[str] = []
    tmp = out_dir / "_tmp.aiff"
    for group, text, _label in rows:
        prefix = {"main": "m", "numeric": "n", "long": "L", "stress": "s",
                  "jargon": "j", "polluted": "p"}.get(group, "x")
        counts[prefix] = counts.get(prefix, 0) + 1
        idx = counts[prefix]
        name = f"{prefix}{idx:02d}" if prefix != "L" else f"L{idx:02d}"
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(tmp), text],
                       check=True, capture_output=True)
        _to_16k_mono(tmp, out_dir / f"{name}.wav")
        rendered.append((group, text))
        names.append(name)
        print(f"  {name:5s} {group:9s} {text[:60]}")
    if tmp.exists():
        tmp.unlink()
    corpus = _write_manifest(rendered, out_dir, names=names)
    corpus.meta = {
        "source": source,
        "labels": {g: lab for g, _t, lab in rows},
        "note": "Synthetic voice: text is exact ground truth. See README 'What this does not show'.",
    }
    (out_dir / "corpus.json").write_text(json.dumps(corpus.meta, indent=2) + "\n")
    return corpus


def _write_manifest(rendered: list[tuple[str, str]], out_dir: Path,
                    names: list[str]) -> Corpus:
    lines = ["# clip\tgroup\treference text\twav"]
    clips = []
    for name, (group, text) in zip(names, rendered, strict=True):
        wav = out_dir / f"{name}.wav"
        lines.append(f"{name}\t{group}\t{text}\t{name}.wav")
        clips.append(Clip(name, group, text, wav))
    (out_dir / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Corpus(clips, out_dir)


def _add_polluted_clips(corpus: Corpus, out_dir: Path, seed: int = 0) -> None:
    """Add same-voice babble versions of some clips.

    Rationale: a model swap rarely changes quality on clean synthetic speech —
    the benchmark showed models converging within about one word.  A second
    speaker talking over you usually *does* separate them.  These clips are
    marked ``polluted`` and reported as their own group.
    """
    rng = random.Random(seed)
    sources = [c for c in corpus.clips if c.group == "main"][:5]
    babble_lines = [
        "we should probably schedule that meeting for next week",
        "I already sent the invoice to the accounting team",
        "can you pick up some coffee on your way back",
    ]
    babble_aiff = out_dir / "_babble.aiff"
    parts = []
    for i, line in enumerate(babble_lines):
        p = out_dir / f"_b{i}.aiff"
        subprocess.run(["say", "-v", rng.choice(MACOS_VOICES), "-r", "165",
                        "-o", str(p), line], check=True, capture_output=True)
        parts.append(p)
    concat = out_dir / "_babble_list.txt"
    concat.write_text("\n".join(str(p) for p in parts))
    subprocess.run(["sox"] + [str(p) for p in parts] + [str(babble_aiff)],
                   check=True, capture_output=True)
    babble = out_dir / "_babble.wav"
    _to_16k_mono(babble_aiff, babble)
    for i, clip in enumerate(sources, 1):
        name = f"p{i:02d}"
        out = out_dir / f"{name}.wav"
        # Babble at roughly 0 dB SNR: speech and second voice about equally loud.
        subprocess.run(
            ["sox", "-m", str(clip.wav), "-v", "1.0", str(babble), str(out)],
            check=True, capture_output=True,
        )
        corpus.clips.append(Clip(name, "polluted", clip.reference, out))
    for p in parts + [concat, babble_aiff]:
        if p.exists():
            p.unlink()

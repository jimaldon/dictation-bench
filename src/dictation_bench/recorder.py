"""Guided recording: build a corpus from your own voice.

The recorder is deliberately thin.  It records one take at a time, measures the
level, lets you replay or redo it, asks for the exact words, and only then saves
the clip.  The rules that decide what a corpus contains (naming, level advice,
manifest writing, prompt selection) live here as plain functions so they can be
tested without a microphone or a person in front of them.
"""

from __future__ import annotations

import contextlib
import json
import math
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import prompt_bank
from .corpus import MANIFEST, Clip, Corpus, _to_16k_mono, load
from .errors import CorpusError

#: Written alongside ``manifest.tsv`` so a run knows how the audio was made.
CONDITIONS = "conditions.json"

#: Groups a recorded clip may belong to.  Matches the reference corpus plus a
#: catch-all so freeform speech does not have to pretend to be prose.
RECORD_GROUPS = ("main", "numeric", "jargon", "stress", "long", "freeform")

QUIET_RMS_DBFS = -34.0


@dataclass
class Mic:
    index: int
    name: str


@dataclass
class Level:
    """What the recorded audio looks like, in terms a person can act on."""

    duration_s: float
    peak_dbfs: float
    rms_dbfs: float
    clipped_samples: int

    @property
    def clipped(self) -> bool:
        return self.clipped_samples > 0

    @property
    def too_quiet(self) -> bool:
        return self.rms_dbfs < QUIET_RMS_DBFS

    @property
    def summary(self) -> str:
        bits = [f"{self.duration_s:.1f} s", f"peak {self.peak_dbfs:.0f} dBFS",
                f"level {self.rms_dbfs:.0f} dBFS"]
        if self.clipped:
            bits.append(f"{self.clipped_samples} clipped samples")
        return ", ".join(bits)

    @property
    def advice(self) -> str:
        if self.clipped:
            return ("Peak hit the ceiling. Move back a little or lower the input "
                    "level in System Settings > Sound > Input, then record again.")
        if self.too_quiet:
            return ("The level is low and dictation engines handle quiet audio "
                    "badly. Move closer to the microphone, then record again.")
        return ""


def analyze(wav: Path) -> Level:
    """Measure duration, peak, RMS and clipping on any 16-bit PCM WAV."""
    import array

    try:
        with wave.open(str(wav), "rb") as w:
            if w.getsampwidth() != 2:
                raise CorpusError(f"{wav} is not 16-bit PCM")
            frames = w.getnframes()
            rate = w.getframerate()
            samples = array.array("h", w.readframes(frames))
    except wave.Error as exc:
        raise CorpusError(f"cannot read {wav.name} as a WAV file: {exc}") from exc
    duration = frames / float(rate) if rate else 0.0
    if not samples:
        return Level(duration, -120.0, -120.0, 0)
    peak = max(abs(min(samples)), abs(max(samples)))
    clipped = sum(1 for s in samples if s in (-32768, 32767))
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    peak_dbfs = 20 * math.log10(peak / 32768.0) if peak else -120.0
    rms_dbfs = 20 * math.log10(rms / 32768.0) if rms else -120.0
    return Level(duration, peak_dbfs, rms_dbfs, clipped)


def list_devices() -> list[Mic]:
    """Input devices ``ffmpeg`` reports, for choosing a non-default mic.

    SoX records from the system default and has no device picker, so a multi-mic
    user selects one here first.  An empty list means "use the default" and is
    not an error: most people never need this.
    """
    if not shutil.which("ffmpeg"):
        return []
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true",
         "-i", ""],
        capture_output=True, text=True,
    )
    micros: list[Mic] = []
    in_audio = False
    for line in proc.stderr.splitlines():
        if "AVFoundation video devices" in line:
            in_audio = False
            continue
        if "AVFoundation audio devices" in line:
            in_audio = True
            continue
        if not in_audio or "] " not in line:
            continue
        tail = line.split("] ")[-1]
        try:
            index, name = tail.split("] ", 1)
            micros.append(Mic(int(index.strip()[1:].strip()), name.strip()))
        except ValueError:
            continue
    return micros


def record_argv(output: Path, mic_index: int | None, seconds: float | None) -> list[str]:
    """The command line that writes one take, already at 16 kHz mono."""
    if mic_index is None:
        # SoX.  A fixed duration is the `trim` effect, placed after the output
        # file; it stops cleanly on Ctrl-C when there is no fixed duration.
        if not shutil.which("sox"):
            raise CorpusError("recording needs SoX (`brew install sox`)")
        # `-d` is the default input device; SoX names it per platform.
        argv = ["sox", "-q", "-d", "-c", "1", "-r", "16000", "-b", "16", str(output)]
        if seconds is not None:
            argv += ["trim", "0", f"{seconds:g}"]
        return argv
    if not shutil.which("ffmpeg"):
        raise CorpusError("choosing a microphone needs ffmpeg (`brew install ffmpeg`)")
    limit = ["-t", f"{seconds:g}"] if seconds is not None else []
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "avfoundation", "-i", f":{mic_index}", *limit,
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output)]


def record(
    output: Path,
    *,
    mic_index: int | None = None,
    seconds: float | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    """Record one take. Ctrl-C is the normal stop and still writes the file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = record_argv(output, mic_index, seconds)
    # The terminal delivers Ctrl-C to the whole process group, so the recorder
    # gets its own too and exits cleanly, finalising the WAV.  We also catch it
    # ourselves so a take ends this prompt instead of quitting dictation-bench.
    with contextlib.suppress(KeyboardInterrupt):
        runner(argv, check=False)
    if not output.is_file() or output.stat().st_size <= 44:
        raise CorpusError(
            "no audio was recorded. Check microphone permission for your terminal "
            "in System Settings > Privacy & Security > Microphone."
        )
    return output


def play(wav: Path, runner: Callable[..., object] = subprocess.run) -> None:
    """Play a take back. Missing players are not an error; the level report stands."""
    for argv in (["afplay", str(wav)], ["play", "-q", str(wav)]):
        if shutil.which(argv[0]):
            runner(argv, check=False)
            return


@dataclass
class Take:
    """One accepted recording and everything needed to publish it."""

    wav: Path
    group: str
    reference: str
    level: Level
    meta: dict = field(default_factory=dict)


def next_clip_name(existing: list[str], source: str = "") -> str:
    """Stable, sortable clip id: one letter per source plus a counter."""
    prefix = "u" if source in ("", "mine", "freeform", "guided") else source[0].lower()
    used = set(existing)
    index = 1
    while f"{prefix}{index:02d}" in used:
        index += 1
    return f"{prefix}{index:02d}"


def validate_reference(text: str) -> None:
    if not text.strip():
        raise CorpusError("a clip needs the exact words it contains")
    if "\t" in text or "\n" in text or "\r" in text:
        raise CorpusError("the exact text cannot contain a tab or a line break")


def save_corpus(
    takes: list[Take],
    out_dir: Path,
    *,
    conditions: dict,
    replace_clips: list[str] | None = None,
) -> Corpus:
    """Write ``manifest.tsv``, the WAVs and condition metadata for ``takes``.

    ``replace_clips`` names existing clips whose audio is being deliberately
    redone.  Their files are removed and the replacement is recorded, so a
    half-finished re-record cannot leave a corpus with two front doors.  A
    corpus that is merely being extended keeps every existing clip.
    """
    if not takes:
        raise CorpusError("no recorded clips to save")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    replaced = set(replace_clips or ())
    existing: list[Clip] = []
    existing_records: list[dict] = []
    manifest_path = out_dir / MANIFEST
    if manifest_path.is_file():
        old = load(out_dir)
        existing = [c for c in old.clips if c.name not in replaced]
        existing_records = [
            r for r in old.meta.get("clips", [])
            if r.get("clip") not in replaced
        ]
        # A name may be reused by the take that deliberately replaces it.
        taken_names = {c.name for c in existing} - replaced
    else:
        taken_names = set()
    rows = ["# clip\tgroup\treference text\twav"]
    new_rows: list[str] = []
    new_clips: list[Clip] = []
    new_records: list[dict] = []
    for take in takes:
        validate_reference(take.reference)
        name = take.meta.get("name") or next_clip_name(sorted(taken_names))
        if name in taken_names:
            raise CorpusError(
                f"clip {name} already exists in {out_dir}; pick a new name instead of "
                "overwriting existing audio"
            )
        taken_names.add(name)
        dst = out_dir / f"{name}.wav"
        _to_16k_mono(take.wav, dst)
        new_rows.append(f"{name}\t{take.group}\t{take.reference}\t{name}.wav")
        new_clips.append(Clip(name, take.group, take.reference, dst))
        new_records.append({
            "clip": name,
            "group": take.group,
            "words": take.reference,
            "duration_s": round(take.level.duration_s, 3),
            "peak_dbfs": round(take.level.peak_dbfs, 1),
            "rms_dbfs": round(take.level.rms_dbfs, 1),
            "clipped_samples": take.level.clipped_samples,
            "conditions": take.meta.get("conditions", {}),
        })
    for clip in existing:
        rows.append(f"{clip.name}\t{clip.group}\t{clip.reference}\t{clip.wav.name}")
    (out_dir / MANIFEST).write_text(
        "\n".join(rows + new_rows) + "\n", encoding="utf-8"
    )
    all_conditions = dict(conditions)
    conditions_path = out_dir / CONDITIONS
    if manifest_path.is_file() and conditions_path.is_file():
        # Keep earlier takes' labels: they describe audio that is still here.
        try:
            earlier = json.loads(conditions_path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError):
            earlier = {}
        if isinstance(earlier, dict):
            all_conditions = {**earlier, **conditions}
    meta = {
        "source": {"type": "guided-recording"},
        "conditions": all_conditions,
        "clips": existing_records + new_records,
        "note": ("Real voice and microphone. Condition labels describe each take, so "
                 "clips recorded in different conditions stay distinguishable."),
    }
    (out_dir / "corpus.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out_dir / CONDITIONS).write_text(json.dumps(all_conditions, indent=2) + "\n")
    return Corpus(existing + new_clips, out_dir, meta)


def prompt_indices(chosen: list[str] | None, count: int,
                   groups: list[str] | None) -> list[int]:
    """Positions into the prompt bank for the requested selection."""
    bank = prompt_bank.all_prompts(groups)
    if chosen is None:
        if count > len(bank):
            raise CorpusError(
                f"asked for {count} prompts but only {len(bank)} match those groups"
            )
        return list(range(count))
    wanted = [c.strip() for c in chosen if c.strip()]
    indices: list[int] = []
    for wanted_text in wanted:
        match = next((i for i, p in enumerate(bank) if p.id == wanted_text), None)
        if match is None:
            match = next(
                (i for i, p in enumerate(bank)
                 if p.text.lower() == wanted_text.lower()), None,
            )
        if match is None:
            raise CorpusError(
                f"no prompt with id or text {wanted_text!r}; "
                "run `dictation-bench corpus record --list`"
            )
        indices.append(match)
    if not indices:
        raise CorpusError("--prompt was empty")
    return indices


def list_prompts(groups: list[str] | None = None) -> str:
    lines = ["Prompts available for `corpus record` (use the id with --prompt):", ""]
    for group, loaded in prompt_bank.grouped(groups).items():
        lines.append(f"# {group}")
        for prompt in loaded:
            lines.append(f"{prompt.id}\t{prompt.text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _ask(prompt: str, default: str = "") -> str:
    try:
        text = input(prompt)
    except EOFError:
        return default
    return text.strip() or default


def _ask_group(default: str = "main") -> str:
    while True:
        group = _ask(f"  Group ({' / '.join(RECORD_GROUPS)}), [{default}]: ", default)
        if group in RECORD_GROUPS:
            return group
        print(f"  Unknown group {group!r}; pick one of {', '.join(RECORD_GROUPS)}.")


def run_interactive(  # pragma: no cover - needs a microphone and a person
    out_dir: Path,
    *,
    groups: list[str] | None = None,
    count: int = 10,
    prompts: list[str] | None = None,
    freeform: bool = False,
    mic_index: int | None = None,
    default_group: str = "main",
) -> Corpus:
    """The human loop. Deliberately thin: the rules above are the tested part."""
    conditions = {
        "microphone": ("system default input" if mic_index is None
                       else f"index {mic_index}"),
        "room": _ask("Room or session label (e.g. 'office quiet'), [office]: ",
                     "office"),
        "noise": _ask("Background noise (quiet / fan / street / cafe), [quiet]: ",
                      "quiet"),
        "device": _ask("Microphone type (builtin / headset / external), [builtin]: ",
                       "builtin"),
    }
    if freeform:
        items: list[str | None] = [None] * count
    else:
        bank = prompt_bank.all_prompts(groups)
        items = [bank[i].text for i in prompt_indices(prompts, count, groups)]

    existing_names: list[str] = []
    if (Path(out_dir) / MANIFEST).is_file():
        existing_names = [clip.name for clip in load(out_dir).clips]
    takes: list[Take] = []
    scratch = Path(tempfile.mkdtemp(prefix="dictation-bench-rec-"))
    keep_scratch = False
    try:
        print(f"\nRecording {len(items)} clip(s). For each one press Enter, speak, "
              "then Ctrl-C to stop the take.\n")
        for number, text in enumerate(items, 1):
            while True:
                if text is None:
                    text = _ask(f"[{number}/{len(items)}] Say whatever you would "
                                "dictate, then type exactly what you said: ")
                    if not text:
                        print("  Nothing typed; skipping this clip.")
                        break
                else:
                    print(f"[{number}/{len(items)}] Say: {text}")
                _ask("  Press Enter, then Ctrl-C when you finish speaking…")
                raw = scratch / f"take{number:02d}.wav"
                record(raw, mic_index=mic_index)
                try:
                    level = analyze(raw)
                except CorpusError as exc:
                    print(f"  ! {exc}")
                    continue
                print(f"  {level.summary}")
                if level.advice:
                    print(f"  ! {level.advice}")
                choice = _ask("  [Enter] keep  [p] play  [r] re-record  [s] skip: ",
                              "keep").lower()[:1] or "k"
                if choice == "p":
                    play(raw)
                    choice = _ask("  After listening: [Enter] keep  [r] re-record: ",
                                  "keep").lower()[:1] or "k"
                if choice == "r":
                    continue
                if choice == "s":
                    break
                spoken = text if freeform else _ask(
                    "  Type the exact words you said if they differ from the prompt, "
                    "or press Enter if the prompt is exact: ", "")
                spoken = spoken or text
                if not spoken:
                    print("  A clip needs the words it contains; skipping.")
                    break
                group = _ask_group("freeform" if freeform else default_group)
                name = next_clip_name(existing_names + [
                    t.meta.get("name", "") for t in takes
                ])
                takes.append(Take(
                    wav=raw, group=group, reference=spoken, level=level,
                    meta={"conditions": dict(conditions), "name": name},
                ))
                print(f"  kept as {takes[-1].meta['name']}\n")
                break
        if not takes:
            raise CorpusError("no clips were kept")
        print("Writing the corpus…")
        corpus = save_corpus(takes, out_dir, conditions=conditions)
        keep_scratch = True
        print(f"\nWrote {len(corpus)} clips to {out_dir} "
              f"({len(takes)} new, {len(existing_names)} existing kept)")
        print(f"Next: dictation-bench bench --corpus {out_dir}")
        return corpus
    finally:
        if keep_scratch or not takes:
            shutil.rmtree(scratch, ignore_errors=True)

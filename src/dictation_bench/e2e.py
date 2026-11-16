"""Experimental end-to-end latency for local dictation apps (macOS).

What is measured: **the time from "recording ended" to the final text being in a
controlled editor**.  That is the wait a person actually experiences.  It is not
inference time, not time-to-first-token, and not how fast the words appear on
screen while you are still talking.

Why it is a separate command from ``bench``:

- It needs a GUI app, a virtual microphone (BlackHole 2ch) and Accessibility
  permission, so it cannot run in CI, on Linux, or over SSH.
- It drives *the user's* installed app with real keyboard shortcuts, which is
  inherently a little fragile.  Every run records what it did so a number can be
  traced to the conditions that produced it.

Design rules that keep the numbers honest:

1. The trigger is a real stop of the audio input; the clock starts when the
   capture ends, not when a keystroke is dispatched.
2. Only settled text counts.  Two identical Accessibility reads 300 ms apart
   make the text final, so a flickering partial does not become the timestamp.
3. A trial that never produces text is recorded as ``no_text`` and a timeout,
   never silently dropped.  Its zero is included in the report.
4. Live-typing apps are timed from the end of speech instead, and say so.
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import BenchError

#: How long after the stop to keep polling before the trial is a timeout.
DEFAULT_TIMEOUT_S = 12.0
#: Text must be unchanged for this long to count as final.
DEFAULT_SETTLE_S = 0.3
#: How often the editor is read.
DEFAULT_POLL_S = 0.01


@dataclass
class Timing:
    """The latency of one trial, in seconds, relative to the stop."""

    stop_s: float | None
    first_text_s: float | None
    final_text_s: float | None
    text: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.text.strip()) and not self.timed_out


def wait_for_final_text(
    read_text: Callable[[], str],
    *,
    stop_s: float,
    clock: Callable[[], float] = time.monotonic,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    settle_s: float = DEFAULT_SETTLE_S,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], None] = time.sleep,
) -> Timing:
    """Poll an editor until its text stops changing, or the timeout elapses.

    ``read_text`` is injected so this function is the same code in a real run
    and in a test with a scripted editor.  Silence is not settled text: a blank
    editor keeps being polled until the timeout, which is what turns a dead app
    into a visible ``no_text`` result instead of a suspiciously fast one.
    """
    deadline = stop_s + timeout_s
    previous = read_text()
    previous_at = clock()
    first_text_s: float | None = None
    if previous.strip():
        first_text_s = previous_at
    while True:
        now = clock()
        if now >= deadline:
            return Timing(
                stop_s=stop_s,
                first_text_s=first_text_s,
                final_text_s=None,
                text=previous,
                timed_out=True,
            )
        sleep(poll_s)
        current = read_text()
        now = clock()
        if current != previous:
            previous = current
            previous_at = now
            if first_text_s is None and current.strip():
                first_text_s = now
            continue
        if previous.strip() and now - previous_at >= settle_s:
            return Timing(
                stop_s=stop_s,
                first_text_s=first_text_s,
                final_text_s=previous_at,
                text=previous,
            )


def speech_avoids_the_edges(wav: Path) -> bool:
    """True when the recording neither starts nor ends near full scale.

    A clip that begins mid-word, or that carries a loud click at the end, makes
    "capture ended" a poor stand-in for "speech ended" and distorts the result.
    This check is deliberately cheap; it does not try to be voice activity
    detection.
    """
    import array
    import wave

    with wave.open(str(wav), "rb") as w:
        if w.getsampwidth() != 2:
            return False
        frames = w.getnframes()
        samples = array.array("h", w.readframes(frames))
    if not samples:
        return False
    window = max(1, len(samples) // 50)  # 2% of the clip at each end
    head = max(abs(s) for s in samples[:window])
    tail = max(abs(s) for s in samples[-window:])
    loud = max(1, max(abs(s) for s in samples)) // 4
    return head < loud and tail < loud


@dataclass
class Trial:
    clip: str
    state: str  # ok | no_text | timeout
    final_latency_s: float | None
    first_text_latency_s: float | None
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "clip": self.clip,
            "state": self.state,
            "final_latency_ms": (
                None if self.final_latency_s is None
                else round(1000 * self.final_latency_s, 1)
            ),
            "first_text_latency_ms": (
                None if self.first_text_latency_s is None
                else round(1000 * self.first_text_latency_s, 1)
            ),
            # Transcript text is personal audio content; the report keeps it in
            # the per-trial records only, and the Markdown never prints it.
            "text": self.text,
        }


@dataclass
class Run:
    app: str
    kind: str
    trials: list[Trial] = field(default_factory=list)
    trigger: str = ""
    version: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        ok = [t for t in self.trials if t.state == "ok"]
        finals = [t.final_latency_s for t in ok if t.final_latency_s is not None]
        firsts = [t.first_text_latency_s for t in ok if t.first_text_latency_s is not None]
        return {
            "app": self.app,
            "kind": self.kind,
            "trigger": self.trigger,
            "version": self.version,
            "trials": len(self.trials),
            "ok": len(ok),
            "no_text": sum(1 for t in self.trials if t.state == "no_text"),
            "timeout": sum(1 for t in self.trials if t.state == "timeout"),
            "final_median_ms": _ms(_median(finals)),
            "final_p95_ms": _ms(_p95(finals)),
            "first_text_median_ms": _ms(_median(firsts)),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "dictation-bench-e2e",
            "measurement": (
                "recording end to final text in a controlled editor; "
                "not inference time and not time-to-first-token"
            ),
            "summary": self.summary(),
            "settings": self.settings,
            "environment": self.environment,
            "notes": self.notes,
            "trials": [t.as_dict() for t in self.trials],
        }


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    position = 0.95 * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _ms(value: float | None) -> float | None:
    return None if value is None else round(1000 * value, 1)


# --------------------------------------------------------------------------- #
# Preflight: refuse to measure what cannot be measured honestly
# --------------------------------------------------------------------------- #

def blackhole_present(devices: list[str]) -> str | None:
    """The BlackHole loopback device name, or None when it is not installed."""
    return next((d for d in devices if "blackhole" in d.lower()), None)


def preflight(
    *, devices: list[str], platform_name: str, app_installed: bool,
) -> list[str]:
    """Everything wrong with this machine for an end-to-end run.

    Returned as a list so the user sees all blockers at once instead of fixing
    one per attempt.
    """
    problems: list[str] = []
    if platform_name != "Darwin":
        problems.append(
            "end-to-end latency needs macOS: it drives a GUI app through "
            "Accessibility. Use `dictation-bench bench` for CLI engines elsewhere."
        )
    if blackhole_present(devices) is None:
        problems.append(
            "no BlackHole 2ch virtual microphone found. Install it with "
            "`brew install blackhole-2ch`, set the app to use BlackHole as its "
            "microphone, and log in again after the driver installs."
        )
    if not app_installed:
        problems.append(
            "the dictation app under test is not installed or its name does not "
            "match; pass --app with the name shown in /Applications."
        )
    return problems


def platform_name() -> str:
    """The OS the measurement would run on: 'Darwin' on macOS."""
    return _platform()


def audio_devices() -> list[str]:
    """Input device names, via system_profiler, without third-party Python."""
    if not shutil.which("system_profiler"):
        return []
    proc = subprocess.run(
        ["system_profiler", "SPAudioDataType", "-json"],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(proc.stdout or "{}")
        items = data["SPAudioDataType"][0]["_items"]
    except (KeyError, IndexError, json.JSONDecodeError):
        return []
    return [
        item["_name"] for item in items
        if item.get("coreaudio_device_input") or "input" in
        str(item.get("coreaudio_input_source", ""))
    ]


def require_e2e_available() -> None:
    """Raise one actionable error rather than a traceback from an AppleScript."""
    problems = preflight(
        devices=audio_devices(),
        platform_name=_platform(),
        app_installed=True,
    )
    if problems:
        raise BenchError(
            "end-to-end latency cannot run on this machine:\n- "
            + "\n- ".join(problems)
        )


def _platform() -> str:
    import platform as _p

    return _p.system()


def e2e_available() -> tuple[bool, str]:
    """Whether a real run could start here, and why not."""
    problems = preflight(
        devices=audio_devices(), platform_name=_platform(), app_installed=True,
    )
    return (not problems, "; ".join(problems))


# --------------------------------------------------------------------------- #
# Driving a real app
# --------------------------------------------------------------------------- #

def play_to_device(wav: Path, device: str, runner: Callable[..., Any] = subprocess.run) -> None:
    """Play a clip into the loopback device so the app receives it as input."""
    if not shutil.which("sox"):
        raise BenchError("playing audio needs SoX (`brew install sox`)")
    runner(["sox", "-q", str(wav), "-t", "coreaudio", device], check=False)


def send_stop(keys: str, runner: Callable[..., Any] = subprocess.run) -> None:
    """Press the app's stop shortcut through System Events.

    This is the moment the app's recording ends, and therefore the moment the
    clock starts.  It needs Accessibility permission for the terminal.
    """
    script = (
        'tell application "System Events" to keystroke '
        + json.dumps(keys) + ' using ' + _modifiers(keys)
    )
    proc = runner(["osascript", "-e", script], capture_output=True, text=True, check=False)
    if getattr(proc, "returncode", 0) != 0:
        raise BenchError(
            "could not send the stop shortcut. Grant Accessibility permission to "
            "your terminal in System Settings > Privacy & Security > Accessibility.\n"
            f"{getattr(proc, 'stderr', '')[:300]}"
        )


def _modifiers(keys: str) -> str:
    """Translate a friendlier 'cmd+backtick' style into AppleScript modifiers."""
    names = {
        "cmd": "command down", "command": "command down", "shift": "shift down",
        "opt": "option down", "option": "option down", "ctrl": "control down",
    }
    parts = [names.get(p.strip().lower()) for p in keys.split("+")]
    mods = [p for p in parts[:-1] if p]
    return "{" + ", ".join(mods) + "}" if mods else '{}'


def read_editor(app: str, runner: Callable[..., Any] = subprocess.run) -> str:
    """Read the controlled editor's text, without changing it."""
    script = f'tell application {json.dumps(app)} to get text of document 1'
    proc = runner(["osascript", "-e", script], capture_output=True, text=True, check=False)
    if getattr(proc, "returncode", 0) != 0:
        raise BenchError(
            f"could not read {app}. Allow Automation of {app} when macOS asks, and "
            "keep one document open."
        )
    return proc.stdout


def clear_editor(app: str, runner: Callable[..., Any] = subprocess.run) -> None:
    script = (
        f'tell application {json.dumps(app)} to set text of document 1 to ""'
    )
    runner(["osascript", "-e", script], capture_output=True, text=True, check=False)


def run_clips(
    clips: list[Path],
    *,
    device: str,
    stop_keys: str,
    editor_app: str,
    app: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
    runner: Callable[..., Any] = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
) -> Run:
    """One trial per clip, with a real app in the loop.

    Not unit-tested directly (it needs the GUI); the settlement logic it calls
    is, through :func:`wait_for_final_text`.
    """
    run = Run(
        app=app,
        kind="e2e",
        trigger=f"stop shortcut {stop_keys}",
        settings={
            "timeout_s": timeout_s,
            "settle_s": DEFAULT_SETTLE_S,
            "virtual_microphone": device,
            "editor": editor_app,
        },
    )
    for clip in clips:
        if not speech_avoids_the_edges(clip):
            run.notes.append(
                f"{clip.name} starts or ends at a loud level; it is measured but its "
                "stop-to-text time includes audio the app never heard as speech."
            )
        clear_editor(editor_app, runner)
        play_to_device(clip, device, runner)
        sleep(0.5)  # the app must be listening before recording stops
        stop_at = clock()
        send_stop(stop_keys, runner)
        timing = wait_for_final_text(
            lambda: read_editor(editor_app, runner),
            stop_s=stop_at, clock=clock, timeout_s=timeout_s, sleep=sleep,
        )
        if timing.timed_out and not timing.text.strip():
            state = "no_text"
        elif timing.timed_out:
            state = "timeout"
        else:
            state = "ok"
        run.trials.append(Trial(
            clip=clip.name,
            state=state,
            final_latency_s=(
                None if timing.final_text_s is None else timing.final_text_s - stop_at
            ),
            first_text_latency_s=(
                None if timing.first_text_s is None else timing.first_text_s - stop_at
            ),
            text=timing.text.strip(),
        ))
        sleep(0.5)
    return run


def render_markdown(run: Run) -> str:
    """The human summary. Never prints transcript text, which may be private."""
    summary = run.summary()
    failures = summary["no_text"] + summary["timeout"]
    lines = [
        f"# End-to-end latency: {run.app}",
        "",
        "**Experimental.** Measured from the end of recording to the final text in "
        f"the controlled editor (`{run.settings.get('editor', 'editor')}`), with a real "
        f"virtual microphone (`{run.settings.get('virtual_microphone', 'device')}`). "
        "This is what a person waits, not inference time and not time-to-first-token.",
        "",
        "| Trials | Text produced | No text | Timed out | Final p50 | Final p95 | First text p50 |",
        "|--:|--:|--:|--:|--:|--:|--:|",
        f"| {summary['trials']} | {summary['ok']} | {summary['no_text']} | "
        f"{summary['timeout']} | {_fmt(summary['final_median_ms'])} | "
        f"{_fmt(summary['final_p95_ms'])} | {_fmt(summary['first_text_median_ms'])} |",
        "",
    ]
    if failures:
        lines.extend([
            f"**{failures} of {summary['trials']} trials produced no usable text.** Those "
            "are counted as failures, not excluded from the timing table.",
            "",
        ])
    lines.extend([
        "Trigger: " + (run.trigger or "not recorded")
        + (f". Version: {run.version}." if run.version else "."),
        "",
    ])
    for note in run.notes:
        lines.append(f"> **Note:** {note}")
    if run.notes:
        lines.append("")
    lines.extend([
        "## Limits",
        "",
        "- One app, one editor, one run per invocation. Compare runs on the same "
        "machine, on power, with the same settings.",
        "- Percentiles from a handful of trials are coarse; run at least 10 clips.",
        "- Transcript text is stored in the JSON and deliberately left out of this page.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f} ms"

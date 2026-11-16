"""End-to-end latency: settlement logic, failures, preflight and reporting.

The GUI driver itself is not exercised here (it needs a signed-in macOS app and a
virtual microphone).  Everything that decides what a number *means* is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dictation_bench import e2e
from dictation_bench.e2e import (
    Run,
    Trial,
    preflight,
    render_markdown,
    speech_avoids_the_edges,
    wait_for_final_text,
)


class FakeClock:
    """A clock that advances only when the code under test sleeps."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ScriptedEditor:
    """An editor that reveals text over time, like a real app streaming a result."""

    def __init__(self, states: list[str], clock: FakeClock):
        self.states = states
        self.index = 0
        self.clock = clock

    def __call__(self) -> str:
        # Each read advances the script; the first read answers immediately.
        value = self.states[min(self.index, len(self.states) - 1)]
        self.index += 1
        return value


def collect_final_latency(states: list[str], timeout_s: float = 5.0) -> e2e.Timing:
    clock = FakeClock()
    editor = ScriptedEditor(states, clock)
    return wait_for_final_text(
        editor, stop_s=clock.now, clock=clock, timeout_s=timeout_s,
        settle_s=0.3, poll_s=0.01, sleep=clock.sleep,
    )


def test_text_that_stops_changing_is_final():
    # 5 reads of nothing, then the word arrives and stays.
    timing = collect_final_latency([""] * 3 + ["hello"] * 200)
    assert timing.ok
    assert timing.final_text_s is not None
    assert timing.final_text_s == pytest.approx(100.0 + 2 * 0.01, abs=0.05)


def test_streaming_partials_do_not_become_the_answer():
    timing = collect_final_latency(["", "he", "hello", "hello world"] + ["hello world"] * 100)
    assert timing.text == "hello world"
    assert timing.first_text_s is not None and timing.final_text_s is not None
    assert timing.first_text_s < timing.final_text_s


def test_blank_editor_times_out_instead_of_reporting_a_fast_zero():
    timing = collect_final_latency([""] * 5000, timeout_s=1.0)
    assert timing.timed_out
    assert timing.final_text_s is None
    assert timing.first_text_s is None


def test_text_arriving_after_the_deadline_is_a_timeout():
    clock = FakeClock()
    editor = ScriptedEditor([""] * 300, clock)
    timing = wait_for_final_text(
        editor, stop_s=clock.now, clock=clock, timeout_s=1.0,
        settle_s=0.3, poll_s=0.01, sleep=clock.sleep,
    )
    assert timing.timed_out and timing.text == ""


def test_a_quiet_gap_before_more_text_is_not_treated_as_final():
    """The app inserts a partial, pauses, then inserts the rest.

    Without a settle window the partial would be timestamped as the answer and
    the later text ignored, which under-reports latency and records the wrong
    transcript.
    """
    clock = FakeClock()
    # 20 reads of the partial (200 ms, shorter than the 300 ms settle), then more.
    states = ["hello"] * 20 + ["hello world"] * 200
    timing = wait_for_final_text(
        ScriptedEditor(states, clock), stop_s=clock.now, clock=clock,
        timeout_s=5.0, settle_s=0.3, poll_s=0.01, sleep=clock.sleep,
    )
    assert timing.text == "hello world"
    assert timing.final_text_s is not None
    assert timing.final_text_s >= 100.0 + 19 * 0.01


def test_one_unstable_read_does_not_reset_a_settled_result_forever():
    # A trailing caret flash that ends back at the same text must not loop.
    states = ["done"] * 50
    timing = collect_final_latency(states)
    assert timing.ok and timing.text == "done"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("ok", 1), ("no_text", 1), ("timeout", 1),
    ],
)
def test_every_trial_appears_in_the_run(state, expected):
    run = Run(app="App", kind="e2e", trials=[
        Trial("c1", state, 0.5 if state == "ok" else None, 0.2, "x"),
    ])
    summary = run.summary()
    assert summary["trials"] == expected
    assert summary["ok"] == (1 if state == "ok" else 0)


def test_failures_are_counted_and_named_not_hidden():
    run = Run(app="App", kind="e2e", trials=[
        Trial("c1", "ok", 1.0, 0.2, "text one"),
        Trial("c2", "ok", 3.0, 0.3, "text two"),
        Trial("c3", "no_text", None, None, ""),
        Trial("c4", "timeout", None, None, "partial"),
    ])
    summary = run.summary()
    assert summary["no_text"] == 1 and summary["timeout"] == 1
    assert summary["final_median_ms"] == 2000.0
    md = render_markdown(run)
    assert "2 of 4 trials produced no usable text" in md
    assert "text one" not in md  # transcripts stay out of the report


def test_percentiles_with_a_single_trial_do_not_invent_a_spread():
    run = Run(app="App", kind="e2e", trials=[Trial("c1", "ok", 0.5, 0.4, "x")])
    summary = run.summary()
    assert summary["final_median_ms"] == 500.0
    assert summary["final_p95_ms"] == 500.0


def test_json_is_strict_and_records_the_measurement_definition():
    run = Run(app="Handy", kind="e2e", trials=[
        Trial("c1", "no_text", None, None, ""),
    ])
    payload = json.loads(json.dumps(run.as_dict(), allow_nan=False))
    assert payload["kind"] == "dictation-bench-e2e"
    assert "recording end to final text" in payload["measurement"]
    assert payload["trials"][0]["final_latency_ms"] is None


def test_preflight_collects_every_blocker_at_once():
    problems = preflight(devices=["MacBook Air Microphone"], platform_name="Linux",
                         app_installed=False)
    assert len(problems) == 3
    joined = " ".join(problems)
    assert "macOS" in joined and "BlackHole" in joined and "--app" in joined


def test_preflight_passes_when_the_machine_is_ready():
    assert preflight(devices=["BlackHole 2ch", "MacBook Air Microphone"],
                     platform_name="Darwin", app_installed=True) == []


def test_blackhole_is_found_case_insensitively():
    assert e2e.blackhole_present(["blackhole 16ch"]) == "blackhole 16ch"
    assert e2e.blackhole_present(["MacBook Air Microphone"]) is None


def write_wav(path: Path, samples: list[int]) -> Path:
    import array
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(array.array("h", samples).tobytes())
    return path


def test_clip_with_loud_edges_is_flagged(tmp_path):
    loud = [20000] * 16000
    quiet_edges = [0] * 400 + [20000] * 800 + [0] * 400
    assert not speech_avoids_the_edges(write_wav(tmp_path / "a.wav", loud))
    assert speech_avoids_the_edges(write_wav(tmp_path / "b.wav", quiet_edges))


def test_stop_shortcut_modifiers_are_translated():
    assert e2e._modifiers("cmd+`") == "{command down}"
    assert e2e._modifiers("shift+cmd+r") == "{shift down, command down}"
    assert e2e._modifiers("r") == "{}"


def test_stop_failure_names_the_permission_to_fix(monkeypatch):
    class Result:
        returncode = 1
        stderr = "not authorized to send Apple events"

    with pytest.raises(Exception) as caught:
        e2e.send_stop("cmd+`", runner=lambda *a, **k: Result())
    assert "Accessibility" in str(caught.value)

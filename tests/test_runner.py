"""Runner: cold must be measured once and survive into the report (regression)."""

from __future__ import annotations

import time
from pathlib import Path

from dictation_bench.adapters import Adapter, Result
from dictation_bench.corpus import load
from dictation_bench.evaluate import evaluate, headline
from dictation_bench.runner import latency_summary, run_engine

CORPUS = Path(__file__).resolve().parent.parent / "testdata" / "reference"


class FakeAdapter(Adapter):
    """Correct transcripts, with a deliberately slow first call."""

    def __init__(self, name="fake", first_delay=0.30, normal_delay=0.01):
        super().__init__(name, "http", {"service": True})
        self.calls = 0
        self.first_delay = first_delay
        self.normal_delay = normal_delay
        self.default = {c.name: c.reference for c in load(CORPUS).clips}

    def available(self):
        return True, ""

    def transcribe(self, wav, cold):
        self.calls += 1
        delay = self.first_delay if self.calls <= 2 else self.normal_delay
        time.sleep(delay)
        return Result(wav.stem, text=self.default.get(wav.stem, ""), wall_s=delay, cold=cold)


def _run(max_clips=5):
    corpus = load(CORPUS)
    corpus.clips = corpus.clips[:max_clips]
    return corpus, run_engine(FakeAdapter(), corpus, warmup=True, quiet=True)


def test_cold_is_recorded_and_not_nan():
    corpus, run = _run()
    stats = latency_summary(run, corpus)
    assert stats["cold_s"] == stats["cold_s"], "cold_s must not be NaN"
    assert stats["cold_s"] > 0.2


def test_cold_is_the_first_attempt_not_the_last():
    corpus, run = _run()
    stats = latency_summary(run, corpus)
    assert stats["cold_s"] > stats["warm_median_s"] * 3


def test_cold_clip_is_excluded_from_warm():
    corpus, run = _run()
    stats = latency_summary(run, corpus)
    # warm median should be near the fast path, not dragged up by the cold clip
    assert stats["warm_median_s"] < 0.1


def test_engine_run_dict_round_trips_cold():
    _corpus, run = _run(3)
    assert run.as_dict()["cold_s"] == run.cold_s
    assert run.cold_clip


def test_perfect_adapter_scores_zero():
    corpus, run = _run()
    ev = evaluate(run, corpus)
    assert headline(ev)["wer_pct"] == 0.0

"""The report is the product: test the judgements, not the layout."""

from __future__ import annotations

from dictation_bench.evaluate import EngineEval, headline
from dictation_bench.normalize import ClipScore
from dictation_bench.report import (
    gap_note,
    normalizer_note,
    pros_cons,
    recommendations,
    render_markdown,
    render_table,
    sanity_checks,
)


def make_eval(name, *, group_edits, ref_words=None, cold=0.5, warm=0.2,
              caps=None, kind="http", ok=True) -> EngineEval:
    ref_words = ref_words or {"main": 200, "numeric": 50, "jargon": 30, "polluted": 30}
    clips = []
    for group, words in ref_words.items():
        edits = group_edits.get(group, 0)
        clips.append(ClipScore(f"{group}01", group, words, edits, 0, 0, edits))
    ev = EngineEval(name, kind, caps or {"service": True, "partials": False},
                    "", ok, "")
    ev.by_norm["reconciling"] = clips
    ev.by_norm["basic"] = clips
    ev.by_norm["whisper"] = clips
    ev.latency = {"cold_s": cold, "warm_median_s": warm}
    return ev


def test_table_has_one_row_per_engine():
    a = make_eval("Alpha", group_edits={"main": 4})
    b = make_eval("Beta", group_edits={"main": 8})
    table = render_table([a, b])
    assert table.count("| Alpha |") == 1
    assert table.count("| Beta |") == 1


def test_headline_excludes_numbers_and_acronyms():
    ev = make_eval("A", group_edits={"main": 2, "numeric": 40})
    h = headline(ev)
    # 2 edits over main+jargon+polluted = 260 words; the 40 numeric errors ignored
    assert h["edits"] == 2
    assert h["ref_words"] == 260


def test_gap_note_calls_one_word_a_tie():
    a = make_eval("Good", group_edits={"main": 5})
    b = make_eval("AlsoGood", group_edits={"main": 6})
    note = gap_note([a, b])
    assert "one-word" in note.lower()
    assert "tied" in note.lower()


def test_gap_note_reports_larger_gaps_plainly():
    a = make_eval("Good", group_edits={"main": 2})
    b = make_eval("Bad", group_edits={"main": 20})
    note = gap_note([a, b])
    assert "one-word territory" not in note.lower()
    assert "18" in note


def test_normalizer_note_flags_a_formatting_artefact():
    a = make_eval("DigitWriter", group_edits={"main": 2})
    a.by_norm["basic"] = [ClipScore("n01", "numeric", 50, 20, 0, 0, 20)]
    a.by_norm["reconciling"] = [ClipScore("n01", "numeric", 50, 0, 0, 0, 0)]
    a.by_norm["whisper"] = a.by_norm["reconciling"]
    # keep headline clips present in the basic layer too
    a.by_norm["basic"] += [ClipScore(f"{g}01", g, w, 2 if g == "main" else 0, 0, 0,
                                     2 if g == "main" else 0)
                           for g, w in {"main": 200, "jargon": 30, "polluted": 30}.items()]
    note = normalizer_note([a, a])
    assert "Scoring choice moves" in note


def test_pros_cons_marks_not_resident():
    ev = make_eval("Cli", group_edits={"main": 5}, caps={"service": False})
    pros, cons = pros_cons(ev, [ev])
    assert any("Not resident" in c for c in cons)


def test_pros_cons_cold_start_reasoning_resident_vs_cli():
    resident = make_eval("Server", group_edits={"main": 1}, cold=2.0, warm=0.1,
                         caps={"service": True})
    cli = make_eval("Cli", group_edits={"main": 1}, cold=2.0, warm=0.1,
                    caps={"service": False}, kind="cli")
    _p, cons_resident = pros_cons(resident, [resident])
    _p, cons_cli = pros_cons(cli, [cli])
    assert any("one-time" in c for c in cons_resident)
    assert any("per invocation" in c for c in cons_cli)


def test_recommendations_single_engine_does_not_pretend_to_rank():
    ev = make_eval("Only", group_edits={"main": 3})
    text = recommendations([ev])
    assert "nothing to compare" in text


def test_recommendations_prefers_tied_faster_engine():
    accurate_slow = make_eval("Accurate", group_edits={"main": 5}, warm=0.30)
    tied_fast = make_eval("Fast", group_edits={"main": 5}, warm=0.10)
    text = recommendations([accurate_slow, tied_fast])
    assert "Fast" in text


def test_recommendations_flags_no_partials():
    ev = make_eval("A", group_edits={"main": 1}, caps={"service": True, "partials": False})
    assert "shows words while you speak" in recommendations([ev])


def test_sanity_checks_reports_unmeasured_engine():
    broken = EngineEval("Broken", "http", {}, "", False, "connection refused")
    checks = sanity_checks([broken])
    assert any("Broken" in c for c in checks)


def test_sanity_checks_flags_internal_timer_misuse():
    ev = make_eval("Cli", group_edits={"main": 1}, cold=0.1, warm=1.0, kind="cli")
    checks = sanity_checks([ev])
    assert any("internal inference time" in c for c in checks)


def test_render_markdown_is_complete():
    from pathlib import Path

    from dictation_bench.corpus import load

    corpus = load(Path(__file__).resolve().parent.parent / "testdata" / "reference")
    ev = make_eval("Alpha", group_edits={"main": 4})
    md = render_markdown([ev], corpus)
    for heading in ("## The table", "## Accuracy in detail", "## Pros and cons",
                    "## What I would pick", "## What this does not tell you"):
        assert heading in md
    assert "Alpha" in md


def test_number_disadvantage_is_labelled_as_accuracy_not_scoring():
    """A real numeric miss is an accuracy con, worded as such (regression)."""
    ev = make_eval("Digits", group_edits={"main": 2, "numeric": 8})
    _pros, cons = pros_cons(ev, [ev])
    assert any("Misreads numbers" in c for c in cons)
    assert not any("trips naive scoring" in c for c in cons)


def test_number_strength_shows_as_pro_when_prose_is_worse():
    ev = make_eval("Words", group_edits={"main": 10, "numeric": 0})
    pros, _cons = pros_cons(ev, [ev])
    assert any("Writes numbers correctly" in c for c in pros)


def test_streaming_encoder_without_measured_partials_is_caveated():
    ev = make_eval("NeMo", group_edits={"main": 3},
                   caps={"service": True, "streaming_encoder": True})
    _pros, cons = pros_cons(ev, [ev])
    assert any("batch endpoint" in c for c in cons)


def test_recommendation_names_the_deciding_axis():
    a = make_eval("Accurate", group_edits={"main": 5}, warm=0.20)
    b = make_eval("Quick", group_edits={"main": 20}, warm=0.08)
    text = recommendations([a, b])
    assert "What decides it" in text
    assert "Accurate" in text

"""The normaliser is the core claim of the project: prove the layers behave."""

from __future__ import annotations

from dictation_bench.normalize import (
    aggregate,
    count_errors,
    edit_distance,
    get_normalizers,
    significance,
)


def test_basic_strips_punctuation_and_case():
    n = get_normalizers()["basic"]
    assert n("Hello, World!") == "hello world"


def test_basic_penalises_digits_vs_words():
    """The artefact: a naive scorer counts a correct number as three errors."""
    n = get_normalizers()["basic"]
    ref = "the meeting is at three thirty"
    hyp = "the meeting is at 3:30"
    s = count_errors(ref, hyp, n)
    assert s.edits > 0


def test_reconciling_removes_the_digit_word_gap():
    n = get_normalizers()["reconciling"]
    s = count_errors("the meeting is at three thirty", "the meeting is at 3:30", n)
    assert s.edits == 0, f"reconciling should treat both forms as equal, got {s}"


def test_reconciling_handles_thousands_separator():
    n = get_normalizers()["reconciling"]
    assert count_errors("one thousand two hundred and fifty dollars", "$1,250", n).edits == 0


def test_reconciling_handles_years_and_spelled_digits():
    n = get_normalizers()["reconciling"]
    assert count_errors("twenty twenty six", "2026", n).edits == 0


def test_letter_number_join_acronyms():
    n = get_normalizers()["reconciling"]
    # "f nineteen" vs "F19" should not cost a word once joined.
    assert count_errors("press f nineteen", "press f19", n).edits == 0


def test_real_word_error_still_counts():
    n = get_normalizers()["reconciling"]
    s = count_errors("the coffee grinder needs a new burr set", "the coffee grinder needs a new burset", n)
    assert s.edits >= 1


def test_normalisers_applied_identically_to_both_sides():
    """Whatever the layer, normalising ref and hyp must be symmetric."""
    for name, n in get_normalizers().items():
        text = "Hello, World! 42"
        assert count_errors(text, text, n).edits == 0, f"{name} is not idempotent"


def test_edit_distance_mix():
    subs, dels, ins, total = edit_distance(["a", "b", "c"], ["a", "x", "c"])
    assert (subs, dels, ins, total) == (1, 0, 0, 1)


def test_edit_distance_deletion_and_insertion():
    assert edit_distance(["a", "b"], ["a"])[1] == 1
    assert edit_distance(["a"], ["a", "b"])[2] == 1


def test_aggregate_is_weighted_not_averaged():
    """Corpus WER must be total edits over total words, not mean of clip WERs."""
    n = get_normalizers()["basic"]
    long_clip = count_errors("one two three four five six seven eight nine ten",
                             "one two three four five six seven eight nine ten", n)
    short_clip = count_errors("a b", "x y", n)
    agg = aggregate([long_clip, short_clip])
    assert agg["ref_words"] == 12
    assert agg["edits"] == 2
    assert round(agg["wer_pct"], 2) == round(100 * 2 / 12, 2)


def test_significance_widens_on_small_samples():
    lo_small, hi_small = significance(1, 20)
    lo_big, hi_big = significance(25, 500)
    assert (hi_small - lo_small) > (hi_big - lo_big)


def test_empty_hypothesis_is_a_total_miss():
    n = get_normalizers()["basic"]
    s = count_errors("a b c", "", n)
    assert s.edits == 3

"""Saved-run comparison: alignment, uncertainty, failures and privacy."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from dictation_bench.cli import main
from dictation_bench.compare import compare_runs, render_markdown
from dictation_bench.corpus import fingerprint, load
from dictation_bench.errors import ComparisonError


def make_corpus(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        ("m01", "main", "alpha beta"),
        ("m02", "main", "gamma delta"),
        ("n01", "numeric", "twenty two"),
    ]
    for name, _group, _reference in rows:
        with wave.open(str(root / f"{name}.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 1600)
    (root / "manifest.tsv").write_text(
        "".join(f"{name}\t{group}\t{reference}\n" for name, group, reference in rows)
    )
    return load(root)


def make_run(corpus, name, texts, *, walls=None, failures=(), ok=True, identified=True):
    walls = walls or {}
    results = {}
    for clip in corpus.clips:
        failed = clip.name in failures
        results[clip.name] = {
            "text": "" if failed else texts.get(clip.name, clip.reference),
            "ok": not failed,
            "error": "/private/sensitive/engine.log" if failed else "",
            "wall_s": walls.get(clip.name, 0.2),
            "cold": clip.name == "m01",
        }
    run = {
        "engines": [{
            "name": name,
            "ok": ok,
            "error": "" if ok else "not measured",
            "cold_clip": "m01",
            "cold_s": 0.8,
            "results": results,
        }]
    }
    if identified:
        run["corpus_fingerprint"] = fingerprint(corpus)
    return run


def test_improvement_uses_after_minus_before_and_paired_warm_clips(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(
        corpus, "Engine", {"m01": "alpha wrong"},
        walls={"m01": 2.0, "m02": 0.2, "n01": 0.4},
    )
    after = make_run(
        corpus, "Engine", {}, walls={"m01": 1.0, "m02": 0.1, "n01": 0.2},
    )
    result = compare_runs(before, after, corpus, resamples=200)
    pair = result["pairs"][0]
    assert pair["everyday_wer"]["before_wer_pct"] == 25.0
    assert pair["everyday_wer"]["after_wer_pct"] == 0.0
    assert pair["everyday_wer"]["delta_pp"] == -25.0
    assert pair["counts"] == {"fixed": 1, "regressed": 0, "changed": 0,
                              "unchanged": 2, "failed": 0}
    # m01 is cold and excluded even though its timing improved by a second.
    assert pair["warm_latency"]["paired_clips"] == 2
    assert pair["warm_latency"]["before_median_ms"] == pytest.approx(300.0)
    assert pair["warm_latency"]["after_median_ms"] == pytest.approx(150.0)
    assert pair["warm_latency"]["delta_median_ms"] == pytest.approx(-150.0)


def test_failure_after_is_a_regression_not_a_hidden_warm_speedup(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {})
    after = make_run(corpus, "Engine", {}, failures=("m02",))
    pair = compare_runs(before, after, corpus, resamples=100)["pairs"][0]
    clip = next(c for c in pair["clips"] if c["clip"] == "m02")
    assert clip["category"] == "regressed"
    assert pair["counts"]["regressed"] == 1
    assert pair["everyday_wer"]["after_edits"] == 2
    assert pair["warm_latency"]["paired_clips"] == 1
    assert pair["warm_latency"]["delta_median_ci_ms"] is None


def test_recovery_is_fixed_and_both_failed_stays_failed(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {}, failures=("m01", "m02"))
    after = make_run(corpus, "Engine", {}, failures=("m02",))
    pair = compare_runs(before, after, corpus, resamples=100)["pairs"][0]
    categories = {c["clip"]: c["category"] for c in pair["clips"]}
    assert categories["m01"] == "fixed"
    assert categories["m02"] == "failed"


def test_unmeasured_engine_is_not_scored_as_total_miss(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {}, ok=False)
    after = make_run(corpus, "Engine", {})
    with pytest.raises(ComparisonError, match="not 100% word error"):
        compare_runs(before, after, corpus, resamples=100)


def test_corpus_fingerprint_mismatch_is_rejected(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {})
    after = make_run(corpus, "Engine", {})
    after["corpus_fingerprint"] = "0" * 64
    with pytest.raises(ComparisonError, match="different corpus"):
        compare_runs(before, after, corpus, resamples=100)


def test_legacy_files_warn_and_match_by_clip_name(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Old name", {}, identified=False)
    after = make_run(corpus, "New name", {}, identified=False)
    result = compare_runs(before, after, corpus, resamples=100)
    assert len(result["warnings"]) == 3  # two legacy files and the explicit rename
    assert result["pairs"][0]["before"] == "Old name"
    assert result["pairs"][0]["after"] == "New name"


def test_legacy_filtered_runs_compare_only_their_recorded_subset(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {"m01": "alpha wrong"}, identified=False)
    after = make_run(corpus, "Engine", {}, identified=False)
    for run in (before, after):
        results = run["engines"][0]["results"]
        run["engines"][0]["results"] = {"m01": results["m01"]}
    result = compare_runs(before, after, corpus, resamples=100)
    pair = result["pairs"][0]
    assert pair["compared_clips"] == 1
    assert pair["everyday_wer"]["delta_pp"] == -50.0
    assert pair["everyday_wer"]["delta_ci_pp"] is None
    assert pair["counts"]["unchanged"] == 0
    assert "1 of 3" in pair["warnings"][0]


def test_legacy_runs_with_unequal_subsets_are_rejected(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {}, identified=False)
    after = make_run(corpus, "Engine", {}, identified=False)
    before["engines"][0]["results"].pop("m02")
    after["engines"][0]["results"].pop("n01")
    with pytest.raises(ComparisonError, match="different clip sets"):
        compare_runs(before, after, corpus, resamples=100)


def test_multi_engine_pairs_by_name_and_reports_unmatched(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "A", {})
    before["engines"].append(make_run(corpus, "B", {})["engines"][0])
    after = make_run(corpus, "A", {})
    after["engines"].append(make_run(corpus, "C", {})["engines"][0])
    result = compare_runs(before, after, corpus, resamples=100)
    assert len(result["pairs"]) == 1
    assert any("Before-only" in w for w in result["warnings"])
    assert any("After-only" in w for w in result["warnings"])


def test_duplicate_engine_names_are_rejected(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "A", {})
    before["engines"].append(make_run(corpus, "A", {})["engines"][0])
    after = make_run(corpus, "A", {})
    with pytest.raises(ComparisonError, match="duplicate"):
        compare_runs(before, after, corpus, resamples=100)


def test_private_text_and_raw_errors_are_opt_in(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {"m01": "private wrong"}, failures=("m02",))
    after = make_run(corpus, "Engine", {})
    public = compare_runs(before, after, corpus, resamples=100)
    blob = json.dumps(public)
    assert "private wrong" not in blob
    assert "/private/sensitive" not in blob
    md = render_markdown(public)
    assert "private wrong" not in md
    assert "hidden by default" in md

    private = compare_runs(before, after, corpus, resamples=100, include_private=True)
    assert "private wrong" in json.dumps(private)
    assert "/private/sensitive" in json.dumps(private)
    assert "Before: private wrong" in render_markdown(private)


def test_non_finite_or_malformed_timings_do_not_leak_into_json(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {}, walls={"m02": float("inf"), "n01": "bad"})
    after = make_run(corpus, "Engine", {})
    before["engines"][0]["cold_s"] = float("nan")
    result = compare_runs(before, after, corpus, resamples=100)
    assert result["pairs"][0]["warm_latency"]["paired_clips"] == 0
    assert result["pairs"][0]["cold_latency"]["before_ms"] is None
    json.dumps(result, allow_nan=False)


def test_tool_and_hardware_changes_are_visible(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {})
    after = make_run(corpus, "Engine", {})
    before["tool"] = "0.1.0"
    after["tool"] = "0.2.0"
    before["machine"] = {"machine": "arm64", "cpu": "M2", "ram_gb": 24}
    after["machine"] = {"machine": "arm64", "cpu": "M4", "ram_gb": 24}
    result = compare_runs(before, after, corpus, resamples=100)
    assert any("0.1.0 and 0.2.0" in w for w in result["warnings"])
    assert any("Hardware differs" in w for w in result["warnings"])


@pytest.mark.parametrize(
    ("old_machine", "new_machine", "label"),
    [
        ({"cpu": "Intel A"}, {"cpu": "Intel B"}, "CPU"),
        ({"machine": "x86_64"}, {"machine": "arm64"}, "architecture"),
    ],
)
def test_partial_hardware_metadata_still_warns(
    tmp_path, old_machine, new_machine, label,
):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {})
    after = make_run(corpus, "Engine", {})
    before["machine"] = old_machine
    after["machine"] = new_machine
    result = compare_runs(before, after, corpus, resamples=100)
    assert any(label in w and "Hardware differs" in w for w in result["warnings"])


def test_bootstrap_is_deterministic(tmp_path):
    corpus = make_corpus(tmp_path)
    before = make_run(corpus, "Engine", {"m01": "alpha wrong"})
    after = make_run(corpus, "Engine", {})
    a = compare_runs(before, after, corpus, resamples=200, seed=42)
    b = compare_runs(before, after, corpus, resamples=200, seed=42)
    assert a == b


def test_cli_writes_markdown_and_strict_json(tmp_path):
    corpus = make_corpus(tmp_path / "corpus")
    before = make_run(corpus, "Engine", {"m01": "alpha wrong"}, identified=False)
    after = make_run(corpus, "Engine", {}, identified=False)
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps(before))
    after_path.write_text(json.dumps(after))
    out = tmp_path / "out"
    code = main([
        "compare", str(before_path), str(after_path), "--corpus", str(corpus.root),
        "--out", str(out), "--resamples", "100",
    ])
    assert code == 0
    payload = json.loads((out / "comparison.json").read_text())
    assert payload["kind"] == "dictation-bench-comparison"
    assert "# Dictation run comparison" in (out / "comparison.md").read_text()

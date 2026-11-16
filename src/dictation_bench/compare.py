"""Compare two saved benchmark runs without re-running the engines.

All deltas are *after minus before*.  Accuracy is scored on the same clips in
both runs and uncertainty comes from a paired clip-level bootstrap.  Latency
uses the intersection of valid warm measurements so a failed or cold call in
one run cannot masquerade as a speed-up in the other.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

from .corpus import Corpus, fingerprint
from .errors import ComparisonError
from .evaluate import HEADLINE_GROUPS
from .normalize import ClipScore, count_errors, get_normalizers

SCHEMA_VERSION = 1
DEFAULT_RESAMPLES = 4000


def load_result(path: Path) -> dict[str, Any]:
    """Read and minimally validate a results.json file."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ComparisonError(f"results file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"cannot read results file {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("engines"), list):
        raise ComparisonError(f"{path} is not a dictation-bench results.json file")
    if any(not isinstance(e, dict) or not e.get("name") for e in data["engines"]):
        raise ComparisonError(f"{path} contains an engine without a name")
    return data


def _check_corpus(before: dict, after: dict, corpus: Corpus) -> tuple[str, list[str]]:
    expected = fingerprint(corpus)
    warnings: list[str] = []
    for label, run in (("before", before), ("after", after)):
        declared = run.get("corpus_fingerprint")
        if declared and declared != expected:
            raise ComparisonError(
                f"the {label} run used a different corpus. Select the corpus that "
                "produced that run with --corpus; comparing different audio or "
                "references is not a valid regression test."
            )
        if not declared:
            warnings.append(
                f"The {label} run predates corpus fingerprints. Its clips are matched "
                "by recorded clip ID against the selected corpus; audio and reference "
                "identity cannot be verified."
            )
    return expected, warnings


def _pair_engines(before: dict, after: dict) -> tuple[list[tuple[dict, dict]], list[str]]:
    old = before["engines"]
    new = after["engines"]
    warnings: list[str] = []
    for label, engines in (("before", old), ("after", new)):
        names = [e["name"] for e in engines]
        if len(names) != len(set(names)):
            raise ComparisonError(f"the {label} run contains duplicate engine names")
    if len(old) == len(new) == 1:
        if old[0]["name"] != new[0]["name"]:
            warnings.append(
                "The single-engine runs have different names; they are compared as the "
                "explicit before/after pair you supplied."
            )
        return [(old[0], new[0])], warnings

    after_by_name = {e["name"]: e for e in new}
    pairs = [(e, after_by_name[e["name"]]) for e in old if e["name"] in after_by_name]
    if not pairs:
        old_names = ", ".join(e["name"] for e in old) or "none"
        new_names = ", ".join(e["name"] for e in new) or "none"
        raise ComparisonError(
            "no engines with matching names. With several engines per file, names "
            f"identify the pairs (before: {old_names}; after: {new_names})."
        )
    matched_old = {id(a) for a, _ in pairs}
    matched_new = {id(b) for _, b in pairs}
    skipped_old = [e["name"] for e in old if id(e) not in matched_old]
    skipped_new = [e["name"] for e in new if id(e) not in matched_new]
    if skipped_old:
        warnings.append("Before-only engines not compared: " + ", ".join(skipped_old) + ".")
    if skipped_new:
        warnings.append("After-only engines not compared: " + ", ".join(skipped_new) + ".")
    return pairs, warnings


def _result(engine: dict, clip: str) -> dict[str, Any]:
    value = (engine.get("results") or {}).get(clip) or {}
    return value if isinstance(value, dict) else {}


def _ok(engine: dict, result: dict) -> bool:
    return bool(engine.get("ok", True) and result.get("ok", False))


def _score_clip(corpus_clip, engine: dict) -> tuple[ClipScore, dict, str, bool]:
    result = _result(engine, corpus_clip.name)
    ok = _ok(engine, result)
    text = str(result.get("text") or "") if ok else ""
    score = count_errors(
        corpus_clip.reference,
        text,
        get_normalizers()["reconciling"],
        corpus_clip.name,
        corpus_clip.group,
    )
    return score, result, text, ok


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _interval(values: list[float]) -> list[float] | None:
    if not values:
        return None
    return [_percentile(values, 0.025), _percentile(values, 0.975)]


def _wer_metric(
    old: list[ClipScore], new: list[ClipScore], groups: tuple[str, ...] | None,
    rng: random.Random, resamples: int,
) -> dict[str, Any]:
    pairs = [
        (a, b) for a, b in zip(old, new, strict=True)
        if groups is None or a.group in groups
    ]
    old_edits = sum(a.edits for a, _ in pairs)
    new_edits = sum(b.edits for _, b in pairs)
    words = sum(a.ref_words for a, _ in pairs)
    if not words:
        return {
            "clips": len(pairs), "ref_words": 0,
            "before_wer_pct": None, "after_wer_pct": None,
            "delta_pp": None, "delta_ci_pp": None,
        }
    before_wer = 100.0 * old_edits / words
    after_wer = 100.0 * new_edits / words
    deltas = [b.edits - a.edits for a, b in pairs]
    refs = [a.ref_words for a, _ in pairs]
    boot: list[float] = []
    if len(pairs) >= 2:
        for _ in range(resamples):
            indices = [rng.randrange(len(pairs)) for _ in pairs]
            sample_words = sum(refs[i] for i in indices)
            if sample_words:
                boot.append(100.0 * sum(deltas[i] for i in indices) / sample_words)
    return {
        "clips": len(pairs),
        "ref_words": words,
        "before_edits": old_edits,
        "after_edits": new_edits,
        "before_wer_pct": before_wer,
        "after_wer_pct": after_wer,
        "delta_pp": after_wer - before_wer,
        "delta_ci_pp": _interval(boot),
        "resamples": resamples,
    }


def _warm_seconds(engine: dict, clip: str, result: dict, ok: bool) -> float | None:
    if not ok or result.get("cold", False) or engine.get("cold_clip") == clip:
        return None
    try:
        value = float(result.get("wall_s") or 0.0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 and math.isfinite(value) else None


def _latency_metric(
    pairs: list[tuple[float, float]], rng: random.Random, resamples: int,
) -> dict[str, Any]:
    old = [a for a, _ in pairs]
    new = [b for _, b in pairs]
    if not pairs:
        return {
            "paired_clips": 0, "before_median_ms": None, "after_median_ms": None,
            "delta_median_ms": None, "delta_median_ci_ms": None,
            "before_p95_ms": None, "after_p95_ms": None,
        }
    boot: list[float] = []
    if len(pairs) >= 2:
        for _ in range(resamples):
            sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
            boot.append(1000.0 * (
                statistics.median(b for _, b in sample) - statistics.median(a for a, _ in sample)
            ))
    return {
        "paired_clips": len(pairs),
        "before_median_ms": 1000.0 * statistics.median(old),
        "after_median_ms": 1000.0 * statistics.median(new),
        "delta_median_ms": 1000.0 * (statistics.median(new) - statistics.median(old)),
        "delta_median_ci_ms": _interval(boot),
        "before_p95_ms": 1000.0 * (_percentile(old, 0.95) or 0.0),
        "after_p95_ms": 1000.0 * (_percentile(new, 0.95) or 0.0),
        "resamples": resamples,
    }


def _cold_delta(before: dict, after: dict) -> dict[str, Any]:
    def value(run: dict) -> float | None:
        try:
            seconds = float(run.get("cold_s") or 0.0)
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 and math.isfinite(seconds) else None

    old = value(before)
    new = value(after)
    return {
        "before_ms": 1000.0 * old if old is not None else None,
        "after_ms": 1000.0 * new if new is not None else None,
        "delta_ms": 1000.0 * (new - old) if old is not None and new is not None else None,
    }


def _verdict(delta: float | None, interval: list[float] | None, subject: str) -> str:
    if delta is None or interval is None:
        return f"{subject}: not enough paired data."
    lo, hi = interval
    if lo > 0:
        return f"{subject} regressed; the 95% paired interval excludes no change."
    if hi < 0:
        return f"{subject} improved; the 95% paired interval excludes no change."
    return f"{subject} change is inconclusive; the 95% paired interval includes no change."


def _legacy_pair_corpus(before: dict, after: dict, corpus: Corpus) -> tuple[Corpus, list[str]]:
    """Do not turn clips absent from an old filtered run into failed calls.

    0.1.0 recorded neither --groups nor --max-clips.  The result keys are the
    only reliable scope left, and they are valid only when both runs agree.
    """
    if before.get("corpus_fingerprint") and after.get("corpus_fingerprint"):
        return corpus, []
    old_ids = set((before.get("results") or {}).keys())
    new_ids = set((after.get("results") or {}).keys())
    if old_ids != new_ids:
        old_only = ", ".join(sorted(old_ids - new_ids)) or "none"
        new_only = ", ".join(sorted(new_ids - old_ids)) or "none"
        raise ComparisonError(
            f"legacy engine {before['name']} → {after['name']} recorded different "
            f"clip sets (before-only: {old_only}; after-only: {new_only}). Cannot "
            "distinguish filtered clips from failures; select matching runs."
        )
    selected = [clip for clip in corpus.clips if clip.name in old_ids]
    if not selected or len(selected) != len(old_ids):
        raise ComparisonError(
            f"legacy engine {before['name']} → {after['name']} has no complete set "
            "of clip IDs in the selected corpus"
        )
    if len(selected) == len(corpus):
        return corpus, []
    scoped = Corpus(selected, corpus.root, dict(corpus.meta))
    return scoped, [
        f"Legacy results cover {len(selected)} of {len(corpus)} selected clips. "
        "Only the recorded clip IDs are compared; clips omitted by old filtering "
        "options are not treated as failures."
    ]


def _compare_pair(
    before: dict, after: dict, corpus: Corpus, *, resamples: int, seed: int,
    include_private: bool,
) -> dict[str, Any]:
    if not before.get("ok", True) or not after.get("ok", True):
        raise ComparisonError(
            f"cannot compare {before['name']} → {after['name']}: an engine was not "
            "measured successfully. Fix the failed benchmark first; an unmeasured "
            "engine is not 100% word error."
        )
    pair_corpus, pair_warnings = _legacy_pair_corpus(before, after, corpus)
    old_scores: list[ClipScore] = []
    new_scores: list[ClipScore] = []
    changes: list[dict[str, Any]] = []
    warm_pairs: list[tuple[float, float]] = []
    counts = {"fixed": 0, "regressed": 0, "changed": 0, "unchanged": 0, "failed": 0}

    for clip in pair_corpus.clips:
        old_score, old_result, old_text, old_ok = _score_clip(clip, before)
        new_score, new_result, new_text, new_ok = _score_clip(clip, after)
        old_scores.append(old_score)
        new_scores.append(new_score)
        old_warm = _warm_seconds(before, clip.name, old_result, old_ok)
        new_warm = _warm_seconds(after, clip.name, new_result, new_ok)
        if old_warm is not None and new_warm is not None:
            warm_pairs.append((old_warm, new_warm))

        if not old_ok and not new_ok:
            category = "failed"
        elif not old_ok:
            category = "fixed"  # failed before, recovered after
        elif not new_ok:
            category = "regressed"  # valid before, failed after
        elif new_score.edits < old_score.edits:
            category = "fixed"
        elif new_score.edits > old_score.edits:
            category = "regressed"
        elif new_text != old_text:
            category = "changed"
        else:
            category = "unchanged"
        counts[category] += 1
        changes.append({
            "clip": clip.name,
            "group": clip.group,
            "category": category,
            "before_ok": old_ok,
            "after_ok": new_ok,
            "before_error": (
                str(old_result.get("error") or "")[:300]
                if include_private and not old_ok else ""
            ),
            "after_error": (
                str(new_result.get("error") or "")[:300]
                if include_private and not new_ok else ""
            ),
            "before_edits": old_score.edits,
            "after_edits": new_score.edits,
            "before_text": old_text if include_private else "",
            "after_text": new_text if include_private else "",
            "before_warm_ms": 1000.0 * old_warm if old_warm is not None else None,
            "after_warm_ms": 1000.0 * new_warm if new_warm is not None else None,
            "delta_warm_ms": (
                1000.0 * (new_warm - old_warm)
                if old_warm is not None and new_warm is not None else None
            ),
        })

    rng = random.Random(seed)
    everyday = _wer_metric(old_scores, new_scores, HEADLINE_GROUPS, rng, resamples)
    overall = _wer_metric(old_scores, new_scores, None, rng, resamples)
    warm = _latency_metric(warm_pairs, rng, resamples)
    return {
        "before": before["name"],
        "after": after["name"],
        "before_ok": bool(before.get("ok", True)),
        "after_ok": bool(after.get("ok", True)),
        "before_error": str(before.get("error") or "")[:300] if include_private else "",
        "after_error": str(after.get("error") or "")[:300] if include_private else "",
        "compared_clips": len(pair_corpus),
        "warnings": pair_warnings,
        "everyday_wer": everyday,
        "all_wer": overall,
        "warm_latency": warm,
        "cold_latency": _cold_delta(before, after),
        "counts": counts,
        "clips": changes,
        "verdicts": [
            _verdict(everyday["delta_pp"], everyday["delta_ci_pp"], "Everyday accuracy"),
            _verdict(warm["delta_median_ms"], warm["delta_median_ci_ms"], "Warm latency"),
        ],
    }


def _context_warnings(before: dict, after: dict) -> list[str]:
    warnings: list[str] = []
    old_tool = before.get("tool")
    new_tool = after.get("tool")
    if old_tool and new_tool and old_tool != new_tool:
        warnings.append(
            f"The result files came from dictation-bench {old_tool} and {new_tool}. "
            "Both are scored again with this installation's reconciling normalizer."
        )
    old_machine = before.get("machine") or {}
    new_machine = after.get("machine") or {}
    labels = {"machine": "architecture", "cpu": "CPU", "ram_gb": "RAM"}
    changed = [
        label for key, label in labels.items()
        if old_machine.get(key) is not None
        and new_machine.get(key) is not None
        and old_machine[key] != new_machine[key]
    ]
    if changed:
        warnings.append(
            "Hardware differs between runs (" + ", ".join(changed) + "). Latency "
            "changes include that hardware difference and are not solely an app or model change."
        )
    return warnings


def compare_runs(
    before: dict, after: dict, corpus: Corpus, *,
    resamples: int = DEFAULT_RESAMPLES, seed: int = 20261115,
    include_private: bool = False,
) -> dict[str, Any]:
    """Return a JSON-serialisable comparison of two saved runs."""
    if resamples < 100:
        raise ComparisonError("resamples must be at least 100")
    corpus_id, warnings = _check_corpus(before, after, corpus)
    warnings.extend(_context_warnings(before, after))
    engine_pairs, pair_warnings = _pair_engines(before, after)
    warnings.extend(pair_warnings)
    pairs = [
        _compare_pair(
            old, new, corpus, resamples=resamples, seed=seed + 1009 * index,
            include_private=include_private,
        )
        for index, (old, new) in enumerate(engine_pairs, 1)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "dictation-bench-comparison",
        "private_details_included": include_private,
        "corpus": {"clips": len(corpus), "fingerprint": corpus_id},
        "normalizer": "reconciling",
        "delta_semantics": "after minus before",
        "warnings": warnings,
        "pairs": pairs,
    }


def _number(value: float | None, digits: int = 2, suffix: str = "") -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def _delta(value: float | None, digits: int = 2, suffix: str = "") -> str:
    return "—" if value is None else f"{value:+.{digits}f}{suffix}"


def _ci(interval: list[float] | None, digits: int = 2, suffix: str = "") -> str:
    if interval is None:
        return "—"
    return f"[{interval[0]:+.{digits}f}, {interval[1]:+.{digits}f}]{suffix}"


def _text(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip() or "_(no text)_"


def render_markdown(comparison: dict[str, Any]) -> str:
    """Render the complete comparison, including every changed clip."""
    lines = [
        "# Dictation run comparison",
        "",
        "Changes are **after minus before**: positive WER is worse; positive latency is slower.",
        "Warm latency uses only clips with valid warm measurements in both runs. Intervals are "
        "95% paired clip-bootstrap intervals, not guarantees about a different machine or day.",
        "",
        f"Corpus: **{comparison['corpus']['clips']} clips**, fingerprint "
        f"`{comparison['corpus']['fingerprint'][:16]}…`.",
        "",
    ]
    for warning in comparison["warnings"]:
        lines.extend([f"> **Warning:** {warning}", ""])

    for pair in comparison["pairs"]:
        lines.extend([f"## {pair['before']} → {pair['after']}", ""])
        for warning in pair["warnings"]:
            lines.extend([f"> **Warning:** {warning}", ""])
        if pair["before_error"] or pair["after_error"]:
            lines.extend([
                f"> Engine errors — before: {pair['before_error'] or 'none'}; "
                f"after: {pair['after_error'] or 'none'}. Failed clips score as missed speech.",
                "",
            ])
        everyday = pair["everyday_wer"]
        overall = pair["all_wer"]
        warm = pair["warm_latency"]
        cold = pair["cold_latency"]
        lines.extend([
            "| Measure | Before | After | Change | 95% paired interval |",
            "|:--|--:|--:|--:|--:|",
            f"| Everyday WER ({everyday['clips']} clips) | "
            f"{_number(everyday['before_wer_pct'], 2, '%')} | "
            f"{_number(everyday['after_wer_pct'], 2, '%')} | "
            f"{_delta(everyday['delta_pp'], 2, ' pp')} | {_ci(everyday['delta_ci_pp'], 2, ' pp')} |",
            f"| All-clip WER ({overall['clips']} clips) | "
            f"{_number(overall['before_wer_pct'], 2, '%')} | "
            f"{_number(overall['after_wer_pct'], 2, '%')} | "
            f"{_delta(overall['delta_pp'], 2, ' pp')} | {_ci(overall['delta_ci_pp'], 2, ' pp')} |",
            f"| Warm median ({warm['paired_clips']} paired clips) | "
            f"{_number(warm['before_median_ms'], 0, ' ms')} | "
            f"{_number(warm['after_median_ms'], 0, ' ms')} | "
            f"{_delta(warm['delta_median_ms'], 0, ' ms')} | "
            f"{_ci(warm['delta_median_ci_ms'], 0, ' ms')} |",
            f"| Warm p95 (same paired clips) | {_number(warm['before_p95_ms'], 0, ' ms')} | "
            f"{_number(warm['after_p95_ms'], 0, ' ms')} | — | — |",
            f"| Cold first phrase | {_number(cold['before_ms'], 0, ' ms')} | "
            f"{_number(cold['after_ms'], 0, ' ms')} | {_delta(cold['delta_ms'], 0, ' ms')} | — |",
            "",
        ])
        counts = pair["counts"]
        lines.extend([
            f"Clip outcomes: **{counts['fixed']} fixed · {counts['regressed']} regressed · "
            f"{counts['changed']} changed with equal edits · {counts['unchanged']} unchanged · "
            f"{counts['failed']} failed/missing**.",
            "",
        ])
        lines.extend([f"- {v}" for v in pair["verdicts"]])
        lines.append("")
        changed = [c for c in pair["clips"] if c["category"] != "unchanged"]
        if not changed:
            lines.extend(["Every clip had identical text in both runs.", ""])
            continue
        lines.extend(["### Changed clips", ""])
        if not comparison["private_details_included"]:
            lines.extend([
                "Transcripts and raw error strings are hidden by default because personal "
                "corpora may contain private speech. Re-run with `--show-transcripts` "
                "to include them.",
                "",
            ])
        for clip in changed:
            lines.extend([
                f"#### `{clip['clip']}` ({clip['group']}) — {clip['category']}",
                "",
                f"Edits: **{clip['before_edits']} → {clip['after_edits']}**.",
                "",
                f"Warm latency: **{_number(clip['before_warm_ms'], 0, ' ms')} → "
                f"{_number(clip['after_warm_ms'], 0, ' ms')}** "
                f"({_delta(clip['delta_warm_ms'], 0, ' ms')}).",
                "",
            ])
            if comparison["private_details_included"]:
                lines.extend([
                    f"Before: {_text(clip['before_text'])}",
                    "",
                    f"After: {_text(clip['after_text'])}",
                    "",
                ])
            if clip["before_error"] or clip["after_error"]:
                lines.extend([
                    f"Errors — before: {clip['before_error'] or 'none'}; "
                    f"after: {clip['after_error'] or 'none'}.",
                    "",
                ])
    return "\n".join(lines).rstrip() + "\n"

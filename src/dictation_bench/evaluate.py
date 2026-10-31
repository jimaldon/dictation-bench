"""Turn raw engine runs into per-engine quality and latency facts.

Kept separate from ``report`` (which turns facts into a *table with advice*)
so the numbers can be inspected, tested and re-used without re-running
anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .corpus import Corpus
from .normalize import ClipScore, aggregate, count_errors, get_normalizers, significance
from .runner import EngineRun, latency_summary


@dataclass
class EngineEval:
    name: str
    kind: str
    caps: dict[str, bool]
    notes: str
    ok: bool
    error: str
    #: normalizer name -> per-clip scores
    by_norm: dict[str, list[ClipScore]] = field(default_factory=dict)
    latency: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    # ---- convenience accessors used by the report ----
    def clips(self, norm: str = "reconciling") -> list[ClipScore]:
        return self.by_norm.get(norm, [])

    def group_wer(self, group: str, norm: str = "reconciling") -> dict[str, Any]:
        scores = [s for s in self.clips(norm) if s.group == group]
        return aggregate(scores)

    def overall(self, norm: str = "reconciling") -> dict[str, Any]:
        return aggregate(self.clips(norm))


#: Groups excluded from the headline "everyday dictation" score.
HEADLINE_GROUPS = ("main", "jargon", "polluted", "long")


def evaluate(run: EngineRun, corpus: Corpus, normalizer: str = "reconciling") -> EngineEval:
    norms = get_normalizers()
    ev = EngineEval(run.name, run.kind, _public_caps(run.capabilities), run.notes,
                    run.ok, run.error)
    if not run.ok:
        return ev
    ev.latency = latency_summary(run, corpus)
    for name, nz in norms.items():
        scores: list[ClipScore] = []
        for clip in corpus.clips:
            res = run.results.get(clip.name)
            if res is None or not res.ok:
                ev.failures.append(f"{clip.name}: {(res.error if res else 'missing')[:80]}")
                # A hard failure is a total miss, not a skipped clip: score it
                # as the reference deleted, which is what the user experienced.
                scores.append(count_errors(clip.reference, "", nz, clip.name, clip.group))
                continue
            scores.append(count_errors(clip.reference, res.text, nz, clip.name, clip.group))
        ev.by_norm[name] = scores
    return ev


def _public_caps(caps: dict[str, bool]) -> dict[str, bool]:
    return {k: bool(v) for k, v in caps.items() if not k.startswith("_")}


def headline(eval_: EngineEval, norm: str = "reconciling") -> dict[str, Any]:
    """The everyday-dictation score: main + jargon + polluted + long clips."""
    scores = [s for s in eval_.clips(norm) if s.group in HEADLINE_GROUPS]
    agg = aggregate(scores)
    lo, hi = significance(agg["edits"], agg["ref_words"])
    agg["ci_low"], agg["ci_high"] = lo, hi
    return agg


def normalizer_effect(eval_: EngineEval) -> float:
    """Difference in ALL-clip WER between the crudest and the reconciling layer.

    A large number means the engine writes numbers/formats in a way that a naive
    scorer would punish; that is an *artefact*, not an accuracy problem.
    """
    basic = eval_.overall("basic")["wer_pct"]
    rec = eval_.overall("reconciling")["wer_pct"]
    if basic != basic or rec != rec:
        return float("nan")
    return basic - rec

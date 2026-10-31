"""Text normalisation and error counting.

Three normaliser layers, applied *identically* to reference and hypothesis:

``basic``
    lowercase, keep ``[a-z0-9']``, collapse whitespace.  This is what most
    quick benchmarks do, and it is the layer that produces the classic
    digit-vs-word artefact.

``whisper``
    ``basic`` plus OpenAI Whisper's ``EnglishTextNormalizer`` (when the
    optional ``whisper-normalizer`` package is installed).  This is the
    normaliser the Open ASR Leaderboard and most published WER numbers use.

``reconciling``
    ``basic`` plus explicit number/format reconciliation: spelled numbers to
    digits, thousands separators, clock forms, spaced digit runs and
    letter+digit joins.  This layer is the default for the decision table
    because it removes formatting choices from the score.

The point of having all three is the *artefact*: the same two engines can swap
rank depending on which layer scores them.  ``count_errors`` reports the raw
edit counts as well as the percentage, because on small corpora a one-word gap
is not a result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Normalizers:
    """A labelled normaliser callable."""

    name: str
    label: str
    fn: object  # Callable[[str], str]

    def __call__(self, text: str) -> str:  # pragma: no cover - trivial
        return self.fn(text)


_NORM = re.compile(r"[^a-z0-9' ]+")
_SPACES = re.compile(r"\s+")
_SENTENCE_END = ".!?;:"
_CLOCK = re.compile(r"(?<=\d)[:.](?=\d)")
_COMMA_GROUP = re.compile(r"(?<=\d),(?=\d)")
_SPACED_DIGITS = re.compile(r"\b(\d{1,2}) (\d{2})\b")
_LETTER_NUM = re.compile(r"\b([a-z]) (?=\d)")


def _basic(text: str) -> str:
    return _SPACES.sub(" ", _NORM.sub(" ", text.lower())).strip()


def _make_reconciling():
    try:  # optional dependency; reconciling degrades to basic if missing
        from whisper_normalizer.english import EnglishNumberNormalizer

        num = EnglishNumberNormalizer()
    except Exception:  # pragma: no cover - environment dependent
        num = None

    def reconciling(text: str) -> str:
        t = text.lower().strip()
        t = t.rstrip(_SENTENCE_END)
        t = _COMMA_GROUP.sub("", t)
        if num is not None:
            t = num(t)
        t = _CLOCK.sub("", t)
        t = _SPACED_DIGITS.sub(r"\1\2", t)
        t = _LETTER_NUM.sub(r"\1", t)
        return _basic(t)

    return reconciling


def _make_whisper():
    try:
        from whisper_normalizer.english import EnglishTextNormalizer

        base = EnglishTextNormalizer()
    except Exception:  # pragma: no cover - environment dependent
        base = None

    def whisper(text: str) -> str:
        return _basic(base(text)) if base is not None else _basic(text)

    return whisper


def get_normalizers() -> dict[str, Normalizers]:
    """All three layers, keyed by the name a preset can use."""
    return {
        "basic": Normalizers("basic", "basic", _basic),
        "whisper": Normalizers("whisper", "whisper text normalizer", _make_whisper()),
        "reconciling": Normalizers("reconciling", "reconciling", _make_reconciling()),
    }


# --------------------------------------------------------------------------- #
# Edit distance.  Small corpora: O(n*m) over words is fine and dependency-free.
# --------------------------------------------------------------------------- #


def edit_distance(ref: list[str], hyp: list[str]) -> tuple[int, int, int, int]:
    """Return (substitutions, deletions, insertions, total_edits)."""
    n, m = len(ref), len(hyp)
    # Track operation counts with a cost matrix; ties prefer substitution.
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur[j] = prev[j - 1]
            else:
                cur[j] = 1 + min(prev[j - 1], prev[j], cur[j - 1])
        prev = cur
    total = prev[m]

    # Second pass for the op mix (S/D/I). Same DP, explicit traceback.
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
    for j in range(1, m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = 1 + min(d[i - 1][j - 1], d[i - 1][j], d[i][j - 1])
    subs = dels = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and d[i][j] == d[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + 1:
            subs += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return subs, dels, ins, total


@dataclass(frozen=True)
class ClipScore:
    clip: str
    group: str
    ref_words: int
    subs: int
    dels: int
    ins: int
    edits: int

    @property
    def wer_pct(self) -> float:
        return 100.0 * self.edits / self.ref_words if self.ref_words else float("nan")


def count_errors(
    ref_text: str, hyp_text: str, normalize, clip: str = "", group: str = ""
) -> ClipScore:
    """Score one hypothesis with one normaliser."""
    ref = normalize(ref_text).split()
    hyp = normalize(hyp_text or "").split()
    s, d, i, total = edit_distance(ref, hyp)
    return ClipScore(clip, group, len(ref), s, d, i, total)


def aggregate(scores: list[ClipScore]) -> dict:
    """Corpus-level WER = aggregated edits / aggregated reference words."""
    words = sum(s.ref_words for s in scores)
    edits = sum(s.edits for s in scores)
    subs = sum(s.subs for s in scores)
    dels = sum(s.dels for s in scores)
    ins = sum(s.ins for s in scores)
    return {
        "clips": len(scores),
        "ref_words": words,
        "subs": subs,
        "dels": dels,
        "ins": ins,
        "edits": edits,
        "wer_pct": (100.0 * edits / words) if words else float("nan"),
    }


def significance(edits: int, ref_words: int) -> tuple[float, float]:
    """WER% with a 95 % Wilson interval, as a rough "how firm is this?".

    Word errors are not independent draws (one hard word can cost two edits),
    so treat this as a sanity check on "is the difference one word?", not as a
    rigorous test.  It exists so the report can say *by how much* a lead is
    inside the noise.
    """
    p = edits / ref_words if ref_words else 0.0
    n = ref_words
    if n == 0:
        return 0.0, 0.0
    z = 1.96
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    lo = max(0.0, centre - margin)
    hi = min(1.0, centre + margin)
    return lo * 100.0, hi * 100.0

"""Corpus loading must fail loudly and never silently mis-associate audio."""

from __future__ import annotations

from pathlib import Path

import pytest

from dictation_bench.corpus import REFERENCE_LINES, load
from dictation_bench.errors import CorpusError

REPO = Path(__file__).resolve().parent.parent
BUNDLED = REPO / "testdata" / "reference"


def test_bundled_reference_corpus_loads():
    corpus = load(BUNDLED)
    assert len(corpus) == 28
    groups = set(corpus.groups())
    assert groups == {"main", "numeric", "long", "stress"}
    assert all(c.duration_s > 0 for c in corpus.clips)


def test_bundled_manifest_matches_reference_lines():
    """The shipped corpus must be the corpus the README describes."""
    corpus = load(BUNDLED)
    shipped = [(c.group, c.reference) for c in corpus.clips]
    declared = [(group, text) for group, text, _label in REFERENCE_LINES]
    assert sorted(shipped) == sorted(declared)


def test_missing_manifest_says_what_to_do(tmp_path):
    with pytest.raises(CorpusError, match="dictation-bench corpus"):
        load(tmp_path)


def test_missing_audio_is_an_error(tmp_path):
    (tmp_path / "manifest.tsv").write_text("m01\tmain\thello\tm01.wav\n")
    with pytest.raises(CorpusError, match="missing audio"):
        load(tmp_path)


def test_bad_manifest_line_is_an_error(tmp_path):
    (tmp_path / "manifest.tsv").write_text("only-two\tcolumns\n")
    with pytest.raises(CorpusError, match="clip<TAB>group"):
        load(tmp_path)


def test_manifest_with_explicit_audio_path(tmp_path):
    import shutil

    shutil.copy(BUNDLED / "m01.wav", tmp_path / "renamed.wav")
    (tmp_path / "manifest.tsv").write_text("m01\tmain\thello\trenamed.wav\n")
    corpus = load(tmp_path)
    assert corpus.clips[0].wav.name == "renamed.wav"

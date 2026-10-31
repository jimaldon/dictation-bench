"""Error types shared across the package."""

from __future__ import annotations


class BenchError(Exception):
    """A user-facing failure. The CLI prints the message and exits 1."""


class AdapterError(BenchError):
    """An engine could not be reached, started or parsed."""


class CorpusError(BenchError):
    """The corpus is missing, malformed or incomplete."""

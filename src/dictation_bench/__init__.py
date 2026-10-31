"""dictation-bench — measure local dictation software on your own machine.

The public surface is the CLI (``python -m dictation_bench``); the modules
below are the pieces a contributor would touch:

- ``corpus``     : corpus loading, generation (macOS ``say``) and integrity
- ``adapters``   : one thin class per way to reach a dictation engine
- ``metrics``    : WER scoring (three normalizer layers) and latency stats
- ``report``     : turn raw results into a decision table with pros and cons
- ``app``        : the per-software measurement orchestration
"""

__version__ = "0.1.0"

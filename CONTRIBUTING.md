# Contributing

Useful contributions, roughly in order of value:

1. **A preset for software you use.** This is the biggest gap. The GUI apps people actually choose
   between mostly need someone who runs them to find the CLI or local server hiding underneath. Add
   a `[[engines]]` block to `src/dictation_bench/presets.py`, plus one paragraph on how to start it.
2. **Real recordings with their exact text.** The scarcest input in speech recognition. Only send
   audio you have permission to share, and only your own voice.
3. **A normaliser rule with a test that shows what it changes.** If a scoring rule moves a number,
   say by how much and on which clips.

Open an issue before starting anything large, so two people don't write the same preset.

## Keeping the promises small

The project's value is that its numbers can be trusted. Two rules follow from that:

- If you add a preset you have not run, say so in its `notes`. The report prints those as the
  contributor's claim, not the project's.
- If a capability is not verified, leave it out of the `capabilities` map rather than guessing.
  Unknown is a valid answer and the report handles it.

## Running the checks

```bash
pip install -e ".[dev]"
python -m pytest tests -q
ruff check src tests
```

CI runs the same tests on Linux and macOS for Python 3.10 through 3.13, builds the wheel, and runs
shellcheck on `scripts/dictbench-ptt`. Pull requests that change scoring behaviour should come with
a test that fails without the change.

## Reporting a wrong number

That is the most valuable issue you can open. Include `results/results.json` if you can. It records
the exact per-clip transcripts and timings, and deliberately contains no hostname or absolute path,
so it is safe to paste publicly.

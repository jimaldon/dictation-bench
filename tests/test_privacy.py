"""Output must be safe to paste into a public issue.

These guard against regressions where a personal detail lands in `results.json`
or the report and the user shares it without noticing.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

from dictation_bench.runner import machine_info

REPO = Path(__file__).resolve().parent.parent


def test_machine_info_has_no_hostname():
    info = machine_info()
    assert "hostname" not in info
    assert platform.node() not in json.dumps(info)


def test_machine_info_contains_only_hardware_facts():
    allowed = {"platform", "machine", "processor", "python", "at", "cpu", "ram_gb"}
    assert set(machine_info()) <= allowed


def test_engine_run_keeps_probe_timing_out_of_capabilities():
    """Capabilities are claims about software; timing is not a capability."""
    from dictation_bench.runner import EngineRun

    run = EngineRun("x", "cli", {"offline": True}, "")
    assert not any(k.startswith("_") for k in run.capabilities)
    dumped = run.as_dict()
    assert "warm_probe_s" in dumped and "cold_probe_s" in dumped


def test_results_json_contains_no_absolute_paths_or_hostname(tmp_path):
    """End to end: run a benchmark with a fake engine and inspect the output."""
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import json,sys\n"
        "print(json.dumps({'text':'hi','load_ms':10,'transcribe_ms':[5]}))\n"
    )
    spec = json.dumps({
        "name": "Fake", "type": "json-cli",
        "command": [sys.executable, str(fake), "-f", "{wav}"],
        "json_load_key": "load_ms", "json_infer_key": "transcribe_ms",
    })
    out = tmp_path / "out"
    env = {"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"}
    import os

    env = {**os.environ, **env}
    proc = subprocess.run(
        [sys.executable, "-m", "dictation_bench", "bench", "--engine-json", spec,
         "--groups", "main", "--max-clips", "2", "--out", str(out), "--quiet"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    blob = (out / "results.json").read_text()
    assert platform.node() not in blob
    assert str(Path.home()) not in blob
    assert "/Users/" not in blob
    assert "/private/" not in blob

    report = (out / "report.md").read_text()
    assert platform.node() not in report
    assert str(Path.home()) not in report

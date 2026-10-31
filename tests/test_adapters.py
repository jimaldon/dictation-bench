"""Adapters: what a user's software looks like to the benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dictation_bench.adapters import (
    CliAdapter,
    HttpAdapter,
    JsonCliAdapter,
    RawCommandAdapter,
    _clean_stdout,
    _expand,
    make_engine,
)

WAV = Path(__file__).resolve().parent.parent / "testdata" / "reference" / "m01.wav"


def test_expand_substitutes_wav_and_model():
    argv = _expand(["cmd", "{wav}", "--model", "{model}"], WAV, "small.en")
    assert argv == ["cmd", str(WAV), "--model", "small.en"]


def test_expand_leaves_unknown_placeholders_alone():
    argv = _expand(["cmd", "{repeat}"], WAV, None)
    assert argv == ["cmd", "{repeat}"]


def test_clean_stdout_strips_log_lines_and_timestamps():
    raw = "[00:00:00.000 --> 00:00:03.000]  hello there\n\nhello there\n"
    assert _clean_stdout(raw) == "hello there"


def test_clean_stdout_can_read_a_json_key():
    raw = json.dumps({"text": " hello "})
    assert _clean_stdout(raw, json_key="text") == "hello"


def test_cli_adapter_reports_missing_binary():
    ad = CliAdapter("nope", "definitely-not-a-real-binary-xyz {wav}")
    ok, why = ad.available()
    assert not ok
    assert "not found" in why


def test_cli_adapter_runs_a_real_command(tmp_path):
    ad = CliAdapter("echo", [sys.executable, "-c", "print('hello world')"])
    ok, _ = ad.available()
    assert ok
    res = ad.transcribe(WAV, cold=True)
    assert res.ok and res.text == "hello world"
    assert res.wall_s > 0


def test_cli_adapter_reports_nonzero_exit(tmp_path):
    ad = CliAdapter("fail", [sys.executable, "-c", "raise SystemExit('boom')"])
    res = ad.transcribe(WAV, cold=True)
    assert not res.ok


def test_json_cli_adapter_extracts_text_load_and_infer(tmp_path):
    script = tmp_path / "fake.py"
    script.write_text(
        "import json,sys\n"
        "print(json.dumps({'text':'hi there','load_ms':900,"
        "'transcribe_ms':[120,80]}))\n"
    )
    ad = JsonCliAdapter("fake", [sys.executable, str(script), "-f", "{wav}"],
                        json_text_key="text", json_load_key="load_ms",
                        json_infer_key="transcribe_ms", repeat=2)
    res = ad.transcribe(WAV, cold=False)
    assert res.ok
    assert res.text == "hi there"
    assert res.load_s == pytest.approx(0.9)
    assert res.infer_s == pytest.approx(0.080)  # min of the runs = warm run


def test_json_cli_adapter_survives_garbage(tmp_path):
    script = tmp_path / "bad.py"
    script.write_text("print('not json')\n")
    ad = JsonCliAdapter("bad", [sys.executable, str(script)], json_text_key="text")
    res = ad.transcribe(WAV, cold=True)
    assert not res.ok
    assert "JSON" in res.error


def test_json_cli_adapter_repeat_substitution(tmp_path):
    script = tmp_path / "rep.py"
    script.write_text("import sys,json; print(json.dumps({'text':sys.argv[1]}))\n")
    ad = JsonCliAdapter("rep", [sys.executable, str(script), "{repeat}"],
                        json_text_key="text", repeat=4)
    argv = ad._argv()
    assert argv is not None and argv[-1] == "4"


def test_raw_command_adapter_uses_sh_c():
    ad = RawCommandAdapter("custom", "printf 'transcript'")
    assert ad.kind == "custom"
    res = ad.transcribe(WAV, cold=True)
    assert res.ok and res.text == "transcript"


def test_http_adapter_reports_nothing_listening():
    ad = HttpAdapter("dead", "http://127.0.0.1:9/v1/audio/transcriptions")
    ok, why = ad.available()
    assert not ok


def test_make_engine_dispatches_every_type():
    assert isinstance(make_engine({"name": "h", "type": "http", "url": "http://x/v1"}), HttpAdapter)
    assert isinstance(make_engine({"name": "c", "type": "cli", "command": "x {wav}"}), CliAdapter)
    assert isinstance(make_engine({"name": "j", "type": "json-cli", "command": "x"}), JsonCliAdapter)
    assert isinstance(make_engine({"name": "r", "type": "custom", "command": "x"}), RawCommandAdapter)


def test_make_engine_rejects_unknown_type():
    from dictation_bench.errors import AdapterError

    with pytest.raises(AdapterError):
        make_engine({"name": "?", "type": "telepathy"})


def test_inline_engine_and_preset_specs_are_both_kept(tmp_path, monkeypatch):
    """Regression: --preset must not discard inline --engine-json entries."""
    from dictation_bench import cli

    parser = cli.build_parser()
    args = parser.parse_args(["bench", "--preset", "whisper.cpp-server",
                              "--engine-json", '{"name":"mine","type":"cli","command":"x"}'])
    assert args.preset == ["whisper.cpp-server"]
    assert args.engine and "mine" in args.engine


def test_bad_engine_spec_is_an_error_not_a_silent_skip():
    from dictation_bench import cli
    from dictation_bench.errors import BenchError

    parser = cli.build_parser()
    args = parser.parse_args(["bench", "--engine-json", '{"name":"broken"}',
                              "--max-clips", "1", "--quiet"])
    # Missing url/command must raise, not vanish from the comparison.
    import pytest as _pytest

    with _pytest.raises(BenchError):
        cli.cmd_bench(args)


def test_engine_specs_missing_required_keys_say_what_is_missing():
    from dictation_bench.errors import AdapterError

    for spec in ({"name": "h", "type": "http"},
                 {"name": "c", "type": "cli"},
                 {"name": "j", "type": "json-cli"},
                 {"name": "r", "type": "custom"}):
        with pytest.raises(AdapterError, match="no `"):
            make_engine(spec)

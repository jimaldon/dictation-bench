"""Guided recording: level advice, prompt selection, and what a corpus holds."""

from __future__ import annotations

import array
import json
import math
import wave
from pathlib import Path

import pytest

from dictation_bench import prompt_bank, recorder
from dictation_bench.corpus import load
from dictation_bench.errors import CorpusError, PromptError


def write_wav(path: Path, samples: list[int], rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array.array("h", samples).tobytes())
    return path


def sine(amplitude: int, seconds: float = 1.0, rate: int = 16000) -> list[int]:
    n = int(seconds * rate)
    return [int(amplitude * math.sin(2 * math.pi * 220 * i / rate)) for i in range(n)]


def test_level_reports_duration_peak_and_rms(tmp_path):
    wav = write_wav(tmp_path / "a.wav", sine(3000))
    level = recorder.analyze(wav)
    assert level.duration_s == pytest.approx(1.0)
    assert level.peak_dbfs == pytest.approx(20 * math.log10(3000 / 32768), abs=0.5)
    # A full-scale sine's RMS is its peak over the square root of two.
    assert level.rms_dbfs == pytest.approx(
        20 * math.log10((3000 / math.sqrt(2)) / 32768), abs=0.5,
    )

    assert not level.clipped and not level.too_quiet and level.advice == ""
    assert "1.0 s" in level.summary


def test_quiet_take_gets_actionable_advice(tmp_path):
    level = recorder.analyze(write_wav(tmp_path / "q.wav", sine(60)))
    assert level.too_quiet
    assert "Move closer" in level.advice
    assert "dBFS" in level.summary


def test_clipped_take_is_flagged_before_it_becomes_a_clip(tmp_path):
    samples = sine(3000)
    samples[100] = 32767
    samples[200] = -32768
    level = recorder.analyze(write_wav(tmp_path / "c.wav", samples))
    assert level.clipped and level.clipped_samples == 2
    assert "Move back" in level.advice
    assert "clipped samples" in level.summary


def test_empty_audio_does_not_crash_analysis(tmp_path):
    level = recorder.analyze(write_wav(tmp_path / "e.wav", []))
    assert level.peak_dbfs == -120.0 and level.duration_s == 0.0


def test_non_wav_input_is_a_clear_error(tmp_path):
    bad = tmp_path / "x.wav"
    bad.write_text("not audio")
    with pytest.raises(CorpusError, match="cannot read"):
        recorder.analyze(bad)


def test_prompt_bank_ids_are_unique_and_stable():
    ids = [p.id for p in prompt_bank.PROMPTS]
    assert len(ids) == len(set(ids))
    assert prompt_bank.all_prompts(["numeric"])[0].id == "n01"
    assert {"main", "jargon", "numeric", "stress", "long"} == {
        p.group for p in prompt_bank.PROMPTS
    }


def test_unknown_prompt_group_explains_the_choices():
    with pytest.raises(PromptError, match="choose from"):
        prompt_bank.all_prompts(["nonsense"])


def test_prompt_selection_accepts_ids_and_exact_text():
    by_id = recorder.prompt_indices(["m01", "n03"], 2, None)
    texts = prompt_bank.all_prompts(None)
    assert [texts[i].id for i in by_id] == ["m01", "n03"]
    by_text = recorder.prompt_indices(
        ["Let's sync on the release plan after lunch."], 1, None,
    )
    assert texts[by_text[0]].id == "m01"


def test_prompt_selection_never_silently_substitutes():
    with pytest.raises(CorpusError, match="no prompt with id or text"):
        recorder.prompt_indices(["m99"], 1, None)
    with pytest.raises(CorpusError, match="only"):
        recorder.prompt_indices(None, 99, ["numeric"])


def test_clip_names_stay_unique_and_sortable():
    assert recorder.next_clip_name([]) == "u01"
    assert recorder.next_clip_name(["u01", "u02"]) == "u03"
    assert recorder.next_clip_name(["m01"], "mine") == "u01"


def test_reference_text_cannot_break_the_manifest():
    with pytest.raises(CorpusError, match="needs the exact words"):
        recorder.validate_reference("   ")
    with pytest.raises(CorpusError, match="tab or a line break"):
        recorder.validate_reference("two\tcolumns")


def make_take(tmp_path: Path, name: str, text: str, group: str = "main"):
    wav = write_wav(tmp_path / f"raw_{name}.wav", sine(4000))
    return recorder.Take(
        wav=wav, group=group, reference=text, level=recorder.analyze(wav),
        meta={"name": name, "conditions": {"room": "office", "noise": "fan"}},
    )


def test_saved_corpus_round_trips_through_the_loader(tmp_path):
    takes = [
        make_take(tmp_path, "u01", "twenty two doors", "numeric"),
        make_take(tmp_path, "u02", "Remind me to renew the domain."),
    ]
    out = tmp_path / "corpus"
    conditions = {"microphone": "system default input", "room": "office",
                  "noise": "fan", "device": "headset"}
    corpus = recorder.save_corpus(takes, out, conditions=conditions)
    reloaded = load(out)
    assert [(c.name, c.group, c.reference) for c in reloaded.clips] == [
        ("u01", "numeric", "twenty two doors"),
        ("u02", "main", "Remind me to renew the domain."),
    ]
    assert all(c.duration_s > 0 for c in reloaded.clips)
    meta = json.loads((out / "corpus.json").read_text())
    assert meta["conditions"] == conditions
    assert meta["clips"][0]["conditions"]["noise"] == "fan"
    assert meta["clips"][0]["peak_dbfs"] < 0
    assert json.loads((out / recorder.CONDITIONS).read_text()) == conditions
    assert corpus.meta["source"]["type"] == "guided-recording"


def test_freeform_clips_get_their_own_group(tmp_path):
    take = make_take(tmp_path, "u01", "anything at all", "freeform")
    corpus = recorder.save_corpus([take], tmp_path / "out", conditions={})
    assert load(corpus.root).clips[0].group == "freeform"


def test_saving_nothing_is_an_error(tmp_path):
    with pytest.raises(CorpusError, match="no recorded clips"):
        recorder.save_corpus([], tmp_path / "out", conditions={})


def test_recording_more_clips_extends_a_corpus_instead_of_replacing_it(tmp_path):
    out = tmp_path / "corpus"
    recorder.save_corpus(
        [make_take(tmp_path, "u01", "first take", "main")], out,
        conditions={"room": "office"},
    )
    before = load(out)
    added = make_take(tmp_path, "u02", "second take", "jargon")
    recorder.save_corpus([added], out, conditions={"noise": "fan"})
    after = load(out)
    assert [c.name for c in after.clips] == ["u01", "u02"]
    assert before.clips[0].wav.read_bytes() == after.clips[0].wav.read_bytes()
    meta = json.loads((out / "corpus.json").read_text())
    assert meta["conditions"] == {"room": "office", "noise": "fan"}
    assert [c["clip"] for c in meta["clips"]] == ["u01", "u02"]


def test_overwriting_an_existing_clip_is_refused(tmp_path):
    out = tmp_path / "corpus"
    recorder.save_corpus([make_take(tmp_path, "u01", "first", "main")], out,
                         conditions={})
    original = (out / "u01.wav").read_bytes()
    with pytest.raises(CorpusError, match="already exists"):
        recorder.save_corpus([make_take(tmp_path, "u01", "second", "main")], out,
                             conditions={})
    assert (out / "u01.wav").read_bytes() == original


def test_explicit_replacement_swaps_one_clip_and_keeps_the_rest(tmp_path):
    out = tmp_path / "corpus"
    recorder.save_corpus(
        [make_take(tmp_path, "u01", "first", "main"),
         make_take(tmp_path, "u02", "keep me", "main")],
        out, conditions={},
    )
    kept = (out / "u02.wav").read_bytes()
    recorder.save_corpus(
        [make_take(tmp_path, "u01", "first again", "main")], out,
        conditions={}, replace_clips=["u01"],
    )
    corpus = load(out)
    assert [c.name for c in corpus.clips] == ["u02", "u01"]
    assert corpus.clips[1].reference == "first again"
    assert (out / "u02.wav").read_bytes() == kept
    meta = json.loads((out / "corpus.json").read_text())
    assert [c["clip"] for c in meta["clips"]] == ["u02", "u01"]


def test_record_command_is_16k_mono_and_supports_a_chosen_mic(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.shutil, "which", lambda name: f"/usr/bin/{name}")
    default = recorder.record_argv(tmp_path / "a.wav", None, None)
    assert default[0] == "sox" and "-d" in default
    assert default[default.index("-r") + 1] == "16000"
    assert "trim" not in default
    fixed = recorder.record_argv(tmp_path / "a.wav", None, 2.0)
    # The duration is the trim effect after the output file, not a -t format flag.
    assert fixed[-3:] == ["trim", "0", "2"] and fixed[-4].endswith("a.wav")
    chosen = recorder.record_argv(tmp_path / "b.wav", 2, 3.0)
    assert chosen[0] == "ffmpeg" and ":2" in chosen
    assert chosen[chosen.index("-t") + 1] == "3"


def test_missing_audio_from_the_recorder_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_runner(argv, check=False):
        Path(argv[-1]).touch()

    with pytest.raises(CorpusError, match="microphone permission"):
        recorder.record(tmp_path / "a.wav", runner=fake_runner)


def test_recording_is_imported_into_the_interactive_flow(tmp_path, monkeypatch):
    """The whole human loop, with the microphone and questions stubbed out."""
    answers = iter([
        "office quiet", "quiet", "headset",   # conditions
        "",                                   # press enter to record
        "keep",                               # [Enter] keep
        "",                                   # prompt text is exact
        "main",                               # group
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers, ""))

    def fake_record(output, mic_index=None, seconds=None):
        output.parent.mkdir(parents=True, exist_ok=True)
        write_wav(output, sine(4000))
        return output

    monkeypatch.setattr(recorder, "record", fake_record)
    monkeypatch.setattr(recorder, "play", lambda path: None)
    out = tmp_path / "corpus"
    corpus = recorder.run_interactive(out, count=1, prompts=["m01"])
    reloaded = load(out)
    assert len(reloaded) == 1
    assert reloaded.clips[0].reference == "Let's sync on the release plan after lunch."
    assert reloaded.clips[0].group == "main"
    assert corpus.meta["conditions"]["room"] == "office quiet"


def test_a_take_hitting_ctrl_c_still_publishes_its_audio(tmp_path):
    """SoX finalises the WAV and raises KeyboardInterrupt; the take must survive."""
    def interrupting_runner(argv, check=False):
        write_wav(Path(argv[-1]), sine(4000))
        raise KeyboardInterrupt

    path = recorder.record(tmp_path / "take.wav", runner=interrupting_runner)
    assert path.is_file() and recorder.analyze(path).duration_s == pytest.approx(1.0)

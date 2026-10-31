"""Presets: starting points for common local dictation software.

These are *starting points*, not claims.  Each entry says what to try and what
was verified, so a preset that does not work on your version fails loudly with
a clear message instead of silently producing wrong numbers.

Anything here can be overridden in ``bench.toml``; see ``docs/adding-an-engine.md``.
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    # ---------------------------------------------------------------- servers
    "whisper.cpp-server": {
        "type": "http",
        "url": "http://127.0.0.1:8080/v1/audio/transcriptions",
        "capabilities": {"service": True, "partials": False, "offline": True},
        "notes": "Start with: whisper-server --model models/ggml-base.en.bin --host 127.0.0.1 --port 8080",
    },
    "whisperkit-server": {
        "type": "http",
        "url": "http://127.0.0.1:50060/v1/audio/transcriptions",
        "model": "small.en",
        "capabilities": {"service": True, "partials": False, "offline": True},
        "notes": "Start with: whisperkit-cli serve --model small.en --port 50060",
    },
    "nemo-speech-server": {
        "type": "http",
        "url": "http://127.0.0.1:50060/v1/audio/transcriptions",
        "capabilities": {"service": True, "partials": False, "offline": True},
        "notes": "Start with: nemo-speech serve --asr-model parakeet-tdt --host 127.0.0.1 --port 50060 --no-ui",
    },
    "faster-whisper-server": {
        "type": "http",
        "url": "http://127.0.0.1:8000/v1/audio/transcriptions",
        "capabilities": {"service": True, "partials": False, "offline": True},
        "notes": "Start with: faster-whisper-server --model small --host 127.0.0.1",
    },
    "lm-studio": {
        "type": "http",
        "url": "http://127.0.0.1:1234/v1/audio/transcriptions",
        "capabilities": {"service": True, "partials": False, "offline": True},
        "notes": "Enable the local server in LM Studio and load an audio-capable model.",
    },
    # ------------------------------------------------------------------ CLIs
    "whisper-cpp-cli": {
        "type": "cli",
        "command": "whisper-cli -m models/ggml-base.en.bin -nt -f {wav}",
        "capabilities": {"partials": False, "service": False, "offline": True},
        "notes": "whisper.cpp prints the transcript to stdout; -nt removes timestamps.",
        "path_hint": "/opt/homebrew/bin/whisper-cli",
    },
    "whisperkit-cli": {
        "type": "cli",
        "command": "whisperkit-cli transcribe --audio-path {wav} --model small.en",
        "capabilities": {"partials": False, "service": False, "offline": True},
        "notes": "WhisperKit's CLI loads the model per invocation.",
    },
    "hns": {
        "type": "cli",
        "command": "hns -f {wav}",
        "capabilities": {"partials": False, "service": False, "offline": True},
        "notes": "hns is a thin CLI around faster-whisper.",
    },
    "moonshine": {
        "type": "cli",
        "command": "moonshine transcribe {wav}",
        "capabilities": {"partials": False, "service": False, "offline": True},
        "notes": "Moonshine Voice CLI; check `moonshine --help` for the subcommand name on your version.",
    },
    "parakeet-cpp": {
        "type": "cli",
        "command": "parakeet-cli -m models/gguf/tdt-0.6b-v3-q8_0.gguf --files {wav}",
        "capabilities": {"partials": False, "service": False, "offline": True},
        "notes": "parakeet.cpp: prebuilt binaries on GitHub releases; adjust the model path.",
    },
    # ------------------------------------------------- apps with a batch CLI
    # Handy ships a hidden, headless batch mode on its main binary. Verified
    # against Handy v0.9.8 on macOS: one JSON object per call on stdout.
    "handy": {
        "type": "json-cli",
        "command": ["{handy_bin}", "-f", "{wav}", "--model", "{model}", "--json", "--repeat", "{repeat}"],
        "model": "parakeet-tdt-0.6b-v3",
        "json_text_key": "text",
        "json_load_key": "load_ms",
        "json_infer_key": "transcribe_ms",
        "json_wall_key": None,
        "repeat": 3,
        "capabilities": {"partials": False, "service": False, "offline": True, "vocab": False},
        "notes": (
            "Batch mode reloads the model for every file, so 'first phrase' is the honest "
            "number; inside the app the model stays loaded and you get the warm one."
        ),
        "path_hint": "/Applications/Handy.app/Contents/MacOS/Handy",
    },
    # ------------------------------------------------------- custom command
    "custom": {
        "type": "custom",
        "command": "echo 'replace me: my-transcriber {wav}'",
        "capabilities": {"partials": False, "service": False, "offline": True},
        "notes": "Unverified by the project: your own command, your own claim.",
    },
}


def resolve(name: str) -> dict | None:
    return PRESETS.get(name)


def uses_placeholder(spec: dict, placeholder: str) -> bool:
    cmd = spec.get("command")
    if isinstance(cmd, list):
        return any(placeholder in str(x) for x in cmd)
    return isinstance(cmd, str) and placeholder in cmd

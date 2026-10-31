"""Adapters: one thin class per *way of reaching a dictation engine*.

Every adapter answers the same question — "given a 16 kHz mono WAV, give me the
text a user would get, and tell me how long a user would wait" — so the report
can compare a launched app, a CLI, and a raw HTTP endpoint on one table.

Four adapters cover essentially every local dictation product:

``HttpAdapter``
    An OpenAI-compatible endpoint: ``POST /v1/audio/transcriptions`` with a
    multipart ``file``.  This is the de facto standard for local servers
    (whisper.cpp ``--host``, whisper-server, faster-whisper-server,
    NeMo-Speech's ``serve``, LM Studio, Ollama-style wrappers, most others).
    Also handles the ``{"text": ...}`` shape that WhisperKit's server returns.

``CliAdapter``
    A program that prints the transcript on stdout, e.g. ``whisper-cli -nt``,
    ``whisperkit-cli transcribe``, ``moonshine``, ``hns``, ``parakeet.cpp``.
    ``{wav}`` in the command is replaced with the clip path.

``JsonCliAdapter``
    A CLI that prints a JSON object per call and has a "warm" repeat switch,
    like Handy's ``handy -f clip.wav --model X --json --repeat 3``.  This is
    needed to separate *process cost* (model load every time) from *inference
    cost*, which is the difference a user feels as "instant" vs "a beat".

``RawCommandAdapter``
    Last resort for anything scriptable: an arbitrary shell command whose
    stdout is the transcript.  Lets a user adapt an app that ships no CLI.

Capabilities (streaming partials, live capture, vocabulary hints, ...) are not
inferred from a flag: each preset declares what it *verified*, because a wrong
"supports streaming" claim is how benchmarks get discredited.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import AdapterError

#: Capability keys, with the plain-language label used in the report.
CAPABILITIES = {
    "partials": "shows words while you speak",
    "service": "stays resident (no model reload per phrase)",
    "vocab": "custom vocabulary / word boosting",
    "formats": "accepts common audio formats",
    "faster_than_realtime": "keeps up on long recordings",
    "offline": "works with no network",
}


@dataclass
class Result:
    """One transcription attempt."""

    clip: str
    text: str = ""
    ok: bool = True
    error: str = ""
    #: End-to-end wall time the user would experience for this clip.
    wall_s: float = 0.0
    #: Model load time for process-per-clip engines (0 when resident).
    load_s: float = 0.0
    #: Pure inference time when the engine reports it (Handy best_ms, etc.).
    infer_s: float = 0.0
    cold: bool = True


@dataclass
class Adapter:
    name: str
    kind: str
    capabilities: dict[str, bool] = field(default_factory=dict)
    notes: str = ""

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def transcribe(self, wav: Path, cold: bool) -> Result:
        raise NotImplementedError

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# HTTP / OpenAI-compatible
# --------------------------------------------------------------------------- #


class HttpAdapter(Adapter):
    def __init__(self, name: str, url: str, *, model: str | None = None,
                 field_name: str = "json", timeout: float = 120.0,
                 capabilities: dict[str, bool] | None = None, notes: str = ""):
        super().__init__(name, "http", capabilities or {}, notes)
        self.url = url
        self.model = model
        self.field_name = field_name
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        base = self.url.split("/v1/")[0]
        for probe in (f"{base}/health", f"{base}/ready", self.url.rsplit("/audio/", 1)[0] + "/models"):
            try:
                req = urllib.request.Request(probe, method="GET")
                with urllib.request.urlopen(req, timeout=3):
                    return True, ""
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    return True, ""  # a 4xx still means something is listening
            except Exception:
                continue
        try:  # final check: can we at least connect to the host:port?
            from urllib.parse import urlparse

            host = urlparse(self.url)
            import socket

            with socket.create_connection((host.hostname or "127.0.0.1",
                                           host.port or 80), timeout=2):
                return True, ""
        except Exception:
            return False, f"nothing listening at {self.url}"

    def transcribe(self, wav: Path, cold: bool) -> Result:
        boundary = f"----dictbench{uuid.uuid4().hex}"
        body = bytearray()
        if self.model:
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{self.model}\r\n".encode()
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{wav.name}\"\r\nContent-Type: audio/wav\r\n\r\n"
        ).encode()
        body += wav.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            self.url, data=bytes(body), method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except Exception as exc:
            return Result(wav.stem, ok=False, error=str(exc), cold=cold)
        wall = time.perf_counter() - t0
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return Result(wav.stem, text=raw.decode("utf-8", "replace").strip(),
                          wall_s=wall, cold=cold)
        if isinstance(payload, str):
            text = payload
        else:
            text = (
                payload.get("text")
                or payload.get("transcript")
                or payload.get("result", {}).get("text", "")
                if isinstance(payload.get("result"), dict)
                else payload.get("text", "")
            ) or ""
        return Result(wav.stem, text=str(text).strip(), wall_s=wall, cold=cold)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _expand(cmd: str | list[str], wav: Path, model: str | None) -> list[str]:
    parts = shlex_split(cmd)
    out = []
    for p in parts:
        p = p.replace("{wav}", str(wav))
        if model:
            p = p.replace("{model}", model)
        out.append(p)
    return out


def shlex_split(cmd: str | list[str]) -> list[str]:
    import shlex

    if isinstance(cmd, list):
        return [str(x) for x in cmd]
    return shlex.split(cmd)


def _clean_stdout(raw: str, strip_lines: bool = True, json_key: str | None = None) -> str:
    if json_key:
        try:
            return str(json.loads(raw).get(json_key, "")).strip()
        except Exception:
            pass
    lines = [ln for ln in raw.splitlines() if ln.strip() and not ln.startswith("[")]
    text = "\n".join(lines) if strip_lines else raw
    return text.strip()


class CliAdapter(Adapter):
    def __init__(self, name: str, command: str | list[str], *, capabilities=None,
                 notes: str = "", model: str | None = None,
                 require: list[str] | None = None, json_key: str | None = None,
                 path_hint: str | None = None):
        super().__init__(name, "cli", capabilities or {}, notes)
        self.command = command
        self.model = model
        self.require = require or []
        self.json_key = json_key
        self.path_hint = path_hint

    def _resolve(self) -> list[str] | None:
        argv = _expand(self.command, Path("{wav}"), self.model)
        binary = argv[0]
        if os.path.sep in binary:
            return argv if Path(binary).is_file() else None
        found = shutil.which(binary)
        if found:
            argv[0] = found
            return argv
        if self.path_hint:
            hint = Path(os.path.expanduser(self.path_hint))
            if hint.is_file():
                argv[0] = str(hint)
                return argv
        return None

    def available(self) -> tuple[bool, str]:
        if self._resolve() is None:
            return False, f"`{shlex_split(self.command)[0]}` not found on PATH"
        return True, ""

    def transcribe(self, wav: Path, cold: bool) -> Result:
        argv = self._resolve()
        if argv is None:
            return Result(wav.stem, ok=False, error="not installed", cold=cold)
        argv = _expand(argv, wav, self.model)
        t0 = time.perf_counter()
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return Result(wav.stem, ok=False, error="timeout (300 s)", cold=cold)
        wall = time.perf_counter() - t0
        if p.returncode != 0:
            tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
            return Result(wav.stem, ok=False, error=" / ".join(tail) or f"exit {p.returncode}",
                          wall_s=wall, cold=cold)
        return Result(wav.stem, text=_clean_stdout(p.stdout, json_key=self.json_key),
                      wall_s=wall, cold=cold)


class JsonCliAdapter(Adapter):
    """A CLI that emits one JSON object per call (e.g. Handy's hidden batch mode).

    ``repeat`` re-runs inference inside one process, which is how we separate
    warm inference time from per-process model load.
    """

    def __init__(self, name: str, command: str | list[str], *, json_text_key: str,
                 json_wall_key: str | None = None, json_load_key: str | None = None,
                 json_infer_key: str | None = None, repeat: int = 3,
                 capabilities=None, notes: str = "", model: str | None = None,
                 path_hint: str | None = None):
        super().__init__(name, "json-cli", capabilities or {}, notes)
        self.command = command
        self.json_text_key = json_text_key
        self.json_wall_key = json_wall_key
        self.json_load_key = json_load_key
        self.json_infer_key = json_infer_key
        self.repeat = repeat
        self.model = model
        self.path_hint = path_hint

    def _argv(self) -> list[str] | None:
        argv = _expand(self.command, Path("{wav}"), self.model)
        argv = [a.replace("{repeat}", str(self.repeat)) for a in argv]
        binary = argv[0]
        if os.path.sep in binary:
            return argv if Path(binary).is_file() else None
        found = shutil.which(binary)
        if found:
            argv[0] = found
            return argv
        if self.path_hint and Path(os.path.expanduser(self.path_hint)).is_file():
            argv[0] = os.path.expanduser(self.path_hint)
            return argv
        return None

    def available(self) -> tuple[bool, str]:
        if self._argv() is None:
            return False, f"`{shlex_split(self.command)[0]}` not found on PATH"
        return True, ""

    def transcribe(self, wav: Path, cold: bool) -> Result:
        argv = self._argv()
        if argv is None:
            return Result(wav.stem, ok=False, error="not installed", cold=cold)
        argv = [a.replace("{wav}", str(wav)) for a in argv]
        t0 = time.perf_counter()
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return Result(wav.stem, ok=False, error="timeout (600 s)", cold=cold)
        proc_wall = time.perf_counter() - t0
        if p.returncode != 0:
            tail = (p.stderr or "").strip().splitlines()[-3:]
            return Result(wav.stem, ok=False, error=" / ".join(tail) or f"exit {p.returncode}",
                          wall_s=proc_wall, cold=cold)
        try:
            payload: Any = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            return Result(wav.stem, ok=False, error="could not parse JSON output", cold=cold)
        text = str(payload.get(self.json_text_key, "")).strip()
        load_s = float(payload.get(self.json_load_key, 0) or 0) / 1000.0 if self.json_load_key else 0.0
        infer_s = 0.0
        if self.json_infer_key:
            v = payload.get(self.json_infer_key)
            if isinstance(v, list) and v:
                infer_s = float(min(x for x in v if x is not None) or 0) / 1000.0
            elif isinstance(v, (int, float)):
                infer_s = float(v) / 1000.0
        wall = float(payload.get(self.json_wall_key, 0) or 0) / 1000.0 if self.json_wall_key else proc_wall
        return Result(wav.stem, text=text, wall_s=wall or proc_wall, load_s=load_s,
                      infer_s=infer_s, cold=cold)


class RawCommandAdapter(CliAdapter):
    """Any shell command whose stdout is the transcript.

    The command runs through ``sh -c`` and gets ``{wav}`` (and ``{model}``)
    substituted.  Marked as "custom" in the report so nobody assumes the
    numbers were verified by us.
    """

    def __init__(self, name: str, command: str, *, model: str | None = None,
                 notes: str = "", capabilities=None):
        super().__init__(name, ["sh", "-c", command], capabilities=capabilities or {},
                         notes=notes, model=model)
        self.kind = "custom"


# --------------------------------------------------------------------------- #
# Availability helpers
# --------------------------------------------------------------------------- #


def make_engine(spec: dict) -> Adapter:
    """Build an adapter from one engine entry in a benchmark config."""
    kind = spec.get("type", "http")
    name = spec.get("name") or kind
    caps = spec.get("capabilities") or {}
    notes = spec.get("notes", "")
    if kind == "http":
        if not spec.get("url"):
            raise AdapterError(f"{name!r} is type http but has no `url`")
        return HttpAdapter(name, spec["url"], model=spec.get("model"),
                           field_name=spec.get("field", "json"),
                           timeout=float(spec.get("timeout", 120)),
                           capabilities=caps, notes=notes)
    if kind == "cli":
        if not spec.get("command"):
            raise AdapterError(f"{name!r} is type cli but has no `command`")
        return CliAdapter(name, spec["command"], model=spec.get("model"),
                          require=spec.get("require"), json_key=spec.get("json_key"),
                          path_hint=spec.get("path"), capabilities=caps, notes=notes)
    if kind == "json-cli":
        if not spec.get("command"):
            raise AdapterError(f"{name!r} is type json-cli but has no `command`")
        return JsonCliAdapter(
            name, spec["command"],
            json_text_key=spec.get("json_text_key", "text"),
            json_wall_key=spec.get("json_wall_key"),
            json_load_key=spec.get("json_load_key", "load_ms"),
            json_infer_key=spec.get("json_infer_key"),
            repeat=int(spec.get("repeat", 3)),
            model=spec.get("model"), path_hint=spec.get("path"),
            capabilities=caps, notes=notes,
        )
    if kind == "custom":
        if not spec.get("command"):
            raise AdapterError(f"{name!r} is type custom but has no `command`")
        return RawCommandAdapter(name, spec["command"], model=spec.get("model"),
                                 notes=notes, capabilities=caps)
    raise AdapterError(f"unknown engine type {kind!r} for {name!r}")

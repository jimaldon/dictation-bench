"""The measurement loop for one engine.

What a user feels when dictating is not "inference time".  It is:

``cold``   release the key with the model not loaded → text appears.
           Includes process start, model load, and (on a Mac) Metal/CoreML
           shader or ANE model compilation.  This is what a freshly launched
           app gives you for the first phrase.
``warm``   release the key with a resident engine → text appears.
           This is what every phrase after the first costs.

Measuring only warm numbers is how benchmarks end up claiming "instant" for an
app that takes two seconds on first use.  Both are recorded.
"""

from __future__ import annotations

import platform
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .adapters import Adapter, Result
from .corpus import Corpus


@dataclass
class EngineRun:
    name: str
    kind: str
    capabilities: dict[str, bool]
    notes: str
    ok: bool = True
    error: str = ""
    results: dict[str, Result] = field(default_factory=dict)
    retries: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "capabilities": self.capabilities,
            "notes": self.notes,
            "ok": self.ok,
            "error": self.error,
            "retries": self.retries,
            "results": {
                k: {"text": v.text, "ok": v.ok, "error": v.error,
                    "wall_s": v.wall_s, "load_s": v.load_s,
                    "infer_s": v.infer_s, "cold": v.cold}
                for k, v in self.results.items()
            },
        }


def machine_info() -> dict[str, Any]:
    info = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "",
        "python": platform.python_version(),
        "hostname": platform.node(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        import subprocess

        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True)
            info["cpu"] = out.stdout.strip()
            mem = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True)
            if mem.stdout.strip().isdigit():
                info["ram_gb"] = round(int(mem.stdout.strip()) / 1e9, 1)
        elif platform.system() == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    return info


def run_engine(
    adapter: Adapter,
    corpus: Corpus,
    *,
    warmup: bool = True,
    max_clips: int = 0,
    quiet: bool = False,
) -> EngineRun:
    """Transcribe every clip, recording cold and warm timing.

    The first clip (by design a short ``main`` one) is used to pay the
    one-time cost: the first attempt is the cold measurement, then a short
    pause and one more attempt on the same clip gives the warm baseline.  The
    warm baseline is subtracted from later clips when the engine is a
    process-per-clip CLI (see ``report.add_plausibility_warnings``).
    """
    clips = corpus.clips[: max_clips] if max_clips else corpus.clips
    run = EngineRun(adapter.name, adapter.kind, dict(adapter.capabilities), adapter.notes)

    ok, why = adapter.available()
    if not ok:
        run.ok = False
        run.error = why
        if not quiet:
            print(f"  ✗ {adapter.name}: {why}")
        return run

    # Choose the shortest main clip to pay cold-start on.
    ordered = sorted(clips, key=lambda c: (c.group != "main", c.duration_s))
    cold_clip = ordered[0]
    warm_clip = ordered[1] if len(ordered) > 1 else ordered[0]

    if not quiet:
        print(f"  → {adapter.name} ({adapter.kind})")

    # Cold: one attempt, immediately, no prior traffic.
    cold_result = adapter.transcribe(cold_clip.wav, cold=True)

    # Retry once on failure: some engines need a first-run model download or
    # shader build, which is a real cost but not a transcription failure.
    if not cold_result.ok:
        run.retries += 1
        if not quiet:
            print(f"    (first call failed: {cold_result.error[:90]}; retrying once)")
        time.sleep(0.5)
        cold_result = adapter.transcribe(cold_clip.wav, cold=True)
    if not cold_result.ok:
        run.ok = False
        run.error = cold_result.error
        if not quiet:
            print(f"    ✗ {cold_result.error[:120]}")
        return run

    # Warm baseline on a *different* clip, after the engine has been touched once.
    if warmup:
        time.sleep(0.7)
        warm_probe = adapter.transcribe(warm_clip.wav, cold=False)
        if warm_probe.ok and warm_probe.wall_s > 0:
            run.capabilities = dict(run.capabilities)
            run.capabilities["_warm_probe_s"] = warm_probe.wall_s  # type: ignore[assignment]
            run.capabilities["_cold_probe_s"] = cold_result.wall_s  # type: ignore[assignment]

    for clip in clips:
        if clip.name == cold_clip.name:
            res = cold_result
        else:
            res = adapter.transcribe(clip.wav, cold=False)
        if not res.ok:
            run.retries += 0
        run.results[clip.name] = res
        if not quiet:
            mark = "✓" if res.ok else "✗"
            text = res.text[:56] if res.ok else res.error[:56]
            print(f"    {mark} {clip.name:5s} {res.wall_s * 1000:7.0f} ms  {text}")
    return run


# --------------------------------------------------------------------------- #
# Latency statistics used by the report
# --------------------------------------------------------------------------- #


def percentiles(values: list[float], ps: tuple[float, ...] = (50, 90, 95)) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    out = {}
    for p in ps:
        if len(ordered) == 1:
            out[f"p{int(p)}"] = ordered[0]
            continue
        k = (len(ordered) - 1) * p / 100.0
        lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
        out[f"p{int(p)}"] = ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)
    return out


def latency_summary(run: EngineRun, corpus: Corpus) -> dict[str, float]:
    """Cold: first clip. Warm: everything else. Plus per-second-of-audio cost."""
    by_name = {c.name: c for c in corpus.clips}
    cold = None
    warm: list[tuple[float, float]] = []
    for name, res in run.results.items():
        clip = by_name.get(name)
        if clip is None or not res.ok:
            continue
        if res.cold:
            cold = res.wall_s
        elif res.wall_s > 0:
            warm.append((res.wall_s, clip.duration_s))
    warm_only = [w for w, _d in warm]
    stats = {
        "cold_s": cold if cold is not None else float("nan"),
        "warm_median_s": statistics.median(warm_only) if warm_only else float("nan"),
    }
    p = percentiles(warm_only)
    stats.update({f"warm_{k}": v for k, v in p.items()})
    # Marginal cost per second of audio, from the longest warm clip.
    if warm:
        wall, dur = max(warm, key=lambda t: t[1])
        stats["ms_per_audio_s"] = 1000.0 * wall / dur if dur else float("nan")
    return stats


def as_seconds_since(ts: float) -> float:
    return time.perf_counter() - ts


__all__ = ["EngineRun", "run_engine", "latency_summary", "percentiles", "machine_info", "asdict"]

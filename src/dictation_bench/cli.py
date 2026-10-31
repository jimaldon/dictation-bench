"""CLI entry point: ``python -m dictation_bench ...``.

Commands mirror a user's journey:

``doctor``   what is installed and reachable on this machine, and what to run next
``engines``  list presets and the compatible apps found on this machine
``bench``    measure, then write a decision table
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .adapters import make_engine
from .corpus import (
    MACOS_VOICES,
    from_macos_say,
    from_single_recording,
    from_text_file,
    load,
)
from .errors import BenchError
from .evaluate import evaluate
from .presets import PRESETS, resolve
from .report import render_markdown
from .runner import machine_info, run_engine

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent.parent


def bundled_corpus() -> Path:
    """The reference corpus: shipped in the wheel, or read from a source checkout."""
    in_package = PKG_DIR / "data" / "reference"
    if (in_package / "manifest.tsv").is_file():
        return in_package
    return REPO_ROOT / "testdata" / "reference"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2))


def _app_paths() -> dict[str, str]:
    """Common install locations for GUI dictation apps that hide a CLI."""
    import shutil

    found: dict[str, str] = {}
    for name in ("Handy", "Hex", "MacParakeet", "FluidVoice", "OpenWhispr", "Whisper"):
        p = Path(f"/Applications/{name}.app/Contents/MacOS/{name}")
        if p.is_file():
            found[name] = str(p)
    for exe in ("handy", "hex", "whisper-cli", "whisperkit-cli", "hns", "moonshine",
                "nemo-speech", "parakeet-cli"):
        if (w := shutil.which(exe)):
            found[exe] = w
    return found


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def cmd_engines(args: argparse.Namespace) -> int:
    if args.json:
        _print_json({"presets": list(PRESETS), "on_this_machine": _app_paths()})
        return 0
    print("Candidate software (presets):\n")
    for name, spec in PRESETS.items():
        caps = ", ".join(k for k, v in (spec.get("capabilities") or {}).items() if v)
        print(f"  {name:24s} {spec['type']:9s} {caps}")
    print("\nFound on this machine:")
    apps = _app_paths()
    if not apps:
        print("  (nothing recognised — add one with bench.toml, see docs/adding-an-engine.md)")
    for name, path in apps.items():
        print(f"  {name:24s} {path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    info = machine_info()
    print(f"dictation-bench {__version__}")
    print(f"  machine : {info.get('cpu') or info['machine']}")
    print(f"  system  : {info['platform']}")
    print(f"  python  : {info['python']}\n")

    # Corpus.
    corpus_path = Path(args.corpus) if args.corpus else bundled_corpus()
    try:
        corpus = load(corpus_path)
        print(f"✓ corpus: {len(corpus)} clips, {sum(c.duration_s for c in corpus.clips):.1f} s "
              f"({corpus_path})")
    except BenchError as exc:
        print(f"✗ corpus: {exc}")

    # Optional pieces.
    for mod, why in (("whisper_normalizer", "whisper-style scorer (optional)"),
                     ("psutil", "peak memory in reports (optional)")):
        try:
            __import__(mod)
            print(f"✓ {why}")
        except Exception:
            print(f"· {why}: not installed (pip install '{mod.replace('_', '-')}')")

    print("\nEngines from bench.toml:")
    cfg = load_config(Path(args.config) if args.config else Path("bench.toml"))
    specs = cfg.get("engines", []) if cfg else []
    if not specs:
        print("  none configured. `dictation-bench init` writes a starter bench.toml.")
    for spec in specs:
        try:
            ad = make_engine(spec)
        except BenchError as exc:
            print(f"  ✗ {spec.get('name', '?')}: {exc}")
            continue
        ok, why = ad.available()
        detail = "" if ok else f" — {why}"
        if ok and ad.kind in ("json-cli", "cli", "custom"):
            detail = " — note: any CLI works; the report flags unverified numbers"
        print(f"  {'✓' if ok else '✗'} {ad.name} ({ad.kind}){detail}")
    print("\nNext: `dictation-bench engines` to list presets, then `dictation-bench bench --preset NAME`.")
    return 0


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import tomllib  # py3.11+
    except ModuleNotFoundError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            raise BenchError(
                "Python 3.11+ is needed to read bench.toml, or `pip install tomli`."
            ) from None
    with path.open("rb") as f:
        return tomllib.load(f)


def _spec_from_preset(name: str) -> dict:
    spec = resolve(name)
    if spec is None:
        raise BenchError(
            f"unknown preset {name!r}. Known: {', '.join(sorted(PRESETS))}.\n"
            f"Or define it yourself in bench.toml (see docs/adding-an-engine.md)."
        )
    spec = dict(spec)
    spec["name"] = name
    if spec.get("type") in ("json-cli", "custom") and "command" in spec:
        cmd = spec["command"]
        # Resolve Handy's binary or fail with the real reason.
        hint = spec.get("path_hint")
        if hint and Path(hint).is_file() and isinstance(cmd, list):
            spec["command"] = [a.replace("{handy_bin}", hint) for a in cmd]
    return spec


def cmd_bench(args: argparse.Namespace) -> int:
    # 1. engines: bench.toml, or presets named on the command line.
    cfg = load_config(Path(args.config) if args.config else Path("bench.toml"))
    specs: list[dict] = []
    if args.preset:
        specs.extend(_spec_from_preset(n) for n in args.preset)
    if args.engine:
        specs.extend(dict(s, name=s.get("name", "inline")) for s in _json_specs(args.engine))
    if not specs:
        specs = list(cfg.get("engines", []))
    if not specs:
        raise BenchError(
            "No engines to measure. Either name presets (`bench --preset whisperkit-server "
            "--preset nemo-speech-server`) or write bench.toml (`dictation-bench init`)."
        )

    # 2. corpus
    corpus = load(Path(args.corpus) if args.corpus else bundled_corpus())
    if args.groups:
        keep = set(args.groups.split(","))
        corpus.clips = [c for c in corpus.clips if c.group in keep]
    if args.max_clips:
        corpus.clips = corpus.clips[: args.max_clips]

    # 3. run
    print(f"Benchmarking {len(specs)} engine(s) on {len(corpus)} clips "
          f"({sum(c.duration_s for c in corpus.clips):.1f} s)\n")
    runs = []
    for spec in specs:
        try:
            adapter = make_engine(spec)
        except BenchError as exc:
            # A misconfigured engine is a setup error, not a measurement result:
            # say so loudly instead of quietly comparing a shorter list.
            raise BenchError(f"engine {spec.get('name')!r} could not be built: {exc}") from None
        try:
            runs.append(run_engine(adapter, corpus, warmup=not args.no_warmup))
        finally:
            adapter.close()

    if not runs:
        raise BenchError("no engine could be measured")
    if args.preset or cfg.get("engines"):
        # Inline --engine entries are added *alongside* presets; make sure every
        # requested engine appears in the table.
        measured = {r.name for r in runs}
        for spec in specs:
            if spec.get("name") not in measured:
                print(f"  ! {spec.get('name')}: not measured (see above)", file=sys.stderr)

    evs = [evaluate(r, corpus) for r in runs]

    # 4. report
    out_dir = Path(args.out) if args.out else Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(evs, corpus)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    raw = {
        "machine": machine_info(),
        "corpus": str(corpus.root),
        "engines": [e.as_dict() for e in runs],
    }
    (out_dir / "results.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    _write_csv(evs, out_dir / "table.csv")

    if not args.quiet:
        print("\n" + "=" * 72)
        print(md)
    print(f"\nWrote {out_dir}/report.md, {out_dir}/table.csv, {out_dir}/results.json")
    if args.open:
        import subprocess

        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open",
                        str(out_dir / "report.md")])
    return 0


def _json_specs(raw: str) -> list[dict]:
    obj = json.loads(raw)
    return obj if isinstance(obj, list) else [obj]


def _write_csv(evs, path: Path) -> None:
    header = ["engine", "everyday_wer_pct", "numbers_wer_pct", "all_wer_pct",
              "cold_s", "warm_median_s", "resident", "streaming_partials"]
    rows = [",".join(header)]
    for e in evs:
        if not e.ok:
            rows.append(",".join([e.name, "", "", "", "", "", "", ""]))
            continue
        from .evaluate import headline

        h = headline(e)
        rows.append(",".join([
            e.name,
            f"{h['wer_pct']:.2f}",
            f"{e.group_wer('numeric')['wer_pct']:.2f}",
            f"{e.overall()['wer_pct']:.2f}",
            f"{e.latency.get('cold_s', float('nan')):.3f}",
            f"{e.latency.get('warm_median_s', float('nan')):.3f}",
            "yes" if e.caps.get("service") else "no",
            "yes" if e.caps.get("partials") else "no",
        ]))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def cmd_corpus(args: argparse.Namespace) -> int:
    out = Path(args.out or "corpus")
    if args.from_macos_say:
        corpus = from_macos_say(out, voice=args.voice, rate=args.rate,
                                only=set(args.only.split(",")) if args.only else None,
                                pollute=args.pollute)
    elif args.from_text_file:
        corpus = from_text_file(Path(args.from_text_file), out, voice=args.voice,
                                rate=args.rate)
    elif args.from_clip:
        if not args.ref:
            raise BenchError("--from-clip needs --ref with the text that was said")
        corpus = from_single_recording(Path(args.from_clip), args.ref, out)
    else:
        raise BenchError("choose one: --from-macos-say, --from-text-file, --from-clip")
    print(f"\n✓ {len(corpus)} clips -> {out} (manifest: {out / 'manifest.tsv'})")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.out or "bench.toml")
    if path.exists() and not args.force:
        raise BenchError(f"{path} exists; pass --force to overwrite")
    path.write_text(STARTER_TOML, encoding="utf-8")
    print(f"Wrote {path}. Edit the engine entries, then run `dictation-bench doctor`.")
    return 0


STARTER_TOML = '''# dictation-bench config. One [[engines]] entry per piece of software you
# want to compare. Docs: docs/adding-an-engine.md
#
# type = "http"      an OpenAI-compatible transcription endpoint
#        "cli"       a command that prints text on stdout
#        "json-cli"  a command that prints a JSON object per call
#        "custom"    any shell command whose stdout is the transcript
#
# capabilities are a claim about the software, not measured by this tool:
#   partials  shows words while you speak
#   service   stays resident between phrases
#   vocab     custom vocabulary / word boosting
#   offline   needs no network

[[engines]]
name = "whisper.cpp server"
type = "http"
url = "http://127.0.0.1:8080/v1/audio/transcriptions"
capabilities = { service = true, offline = true }

[[engines]]
name = "Handy (batch CLI)"
type = "json-cli"
command = ["/Applications/Handy.app/Contents/MacOS/Handy", "-f", "{wav}", "--model", "{model}", "--json", "--repeat", "{repeat}"]
model = "parakeet-tdt-0.6b-v3"
json_load_key = "load_ms"
json_infer_key = "transcribe_ms"
repeat = 3
capabilities = { offline = true }
'''


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dictation-bench",
        description="Benchmark local dictation / speech-to-text software on THIS machine "
                    "and get a table you can decide with.",
    )
    p.add_argument("--version", action="version", version=f"dictation-bench {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("engines", help="list presets and software found on this machine")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_engines)

    sp = sub.add_parser("doctor", help="check corpus, optional deps and configured engines")
    sp.add_argument("--corpus")
    sp.add_argument("--config")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("bench", help="measure configured engines and write the decision table")
    sp.add_argument("--preset", action="append", help="a preset name from `engines`")
    sp.add_argument("--engine-json", dest="engine", help='inline JSON engine spec, e.g. \'{"name":"x","type":"http","url":"..."}\'')
    sp.add_argument("--corpus")
    sp.add_argument("--groups", help="comma-separated groups to keep, e.g. main,numeric")
    sp.add_argument("--max-clips", type=int, default=0)
    sp.add_argument("--out")
    sp.add_argument("--config")
    sp.add_argument("--no-warmup", action="store_true", help="skip the warm probe (saves a few seconds)")
    sp.add_argument("--open", action="store_true", help="open the report afterwards")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser("corpus", help="build a test corpus (from macOS voices, a text file or your mic)")
    sp.add_argument("--out")
    sp.add_argument("--from-macos-say", action="store_true")
    sp.add_argument("--from-text-file")
    sp.add_argument("--from-clip", help="a WAV/any-audio recording of your own voice")
    sp.add_argument("--ref", help="the text spoken in --from-clip")
    sp.add_argument("--voice", default="Samantha", choices=MACOS_VOICES + ["custom"])
    sp.add_argument("--rate", type=int, default=170)
    sp.add_argument("--only", help="comma-separated groups: main,numeric,stress,long")
    sp.add_argument("--pollute", action="store_true",
                    help="also render clips with a second voice talking over you")
    sp.set_defaults(func=cmd_corpus)

    sp = sub.add_parser("init", help="write a starter bench.toml")
    sp.add_argument("--out")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

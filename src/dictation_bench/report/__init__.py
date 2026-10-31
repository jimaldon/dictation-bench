"""Render results as a decision table plus explicit pros, cons and caveats.

The output is the product.  It answers, in this order:

1. **Can I trust these numbers on this machine?**  (plausibility checks)
2. **Which engine is most accurate here?**  (everyday dictation WER, with the
   "is the gap bigger than one word?" sanity check)
3. **Which is fastest where I actually feel it?**  (cold vs warm)
4. **What plumbing does it give me?**  (capabilities)
5. **So what should I pick, given what I care about?**
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from ..evaluate import EngineEval, headline
from ..runner import machine_info

CAPABILITY_LABELS = {
    "partials": "Words while you speak",
    "service": "Resident (no reload per phrase)",
    "vocab": "Custom vocabulary",
    "formats": "Common audio formats",
    "faster_than_realtime": "Keeps up on long files",
    "offline": "Offline (no network)",
}


# --------------------------------------------------------------------------- #
# Plausibility checks
# --------------------------------------------------------------------------- #


def sanity_checks(evs: list[EngineEval]) -> list[str]:
    """Reasons to distrust the table, stated before the reader trusts it."""
    warnings: list[str] = []
    live = [e for e in evs if e.ok]
    if not live:
        lines = ["No engine produced results — nothing to compare."]
        for e in evs:
            lines.append(f"- **{e.name}** could not be measured: {(e.error or 'unknown error')[:200]}")
        lines.append("Run `dictation-bench doctor` to see which engines are reachable.")
        return lines
    for e in evs:
        if not e.ok:
            warnings.append(f"**{e.name}** was not measured: {e.error[:140]}")
    for e in live:
        if e.failures:
            warnings.append(
                f"**{e.name}** failed on {len(e.failures)} clip(s); they are "
                f"scored as complete misses: " + "; ".join(e.failures[:3])
            )
    # Inference faster than process start is almost always an internal timing
    # counter (used as the "warm" number) rather than end-to-end latency.
    slow_cli = [e for e in live
                if e.kind == "cli" and (e.latency.get("cold_s") or 0) <
                min((e.latency.get("warm_median_s") or 0), 1e9)]
    for e in live:
        if e.caps.get("warm_is_inference_only"):
            warnings.append(
                f"**{e.name}**: 'After that' is the engine's own inference timer, not wall "
                f"time, and it excludes the model load each invocation pays. 'First phrase' "
                f"is real wall time. Do not read the two columns as the same quantity."
            )
    for e in slow_cli:
        warnings.append(
            f"**{e.name}** reports an internal inference time faster than its own "
            f"process start. The warm column uses that internal number; the cold "
            f"column uses real wall time. Neither is the full ‘release key → text’ wait."
        )
    return warnings


# --------------------------------------------------------------------------- #
# Table
# --------------------------------------------------------------------------- #


@dataclass
class Column:
    key: str
    title: str
    width: int


COLUMNS = [
    Column("name", "Engine", 22),
    Column("everyday", "Everyday WER", 12),
    Column("numbers", "Numbers", 8),
    Column("cold", "First phrase", 12),
    Column("warm", "After that", 11),
    Column("resident", "Resident?", 9),
]


def _fmt_pct(v: float) -> str:
    return "—" if v != v else f"{v:.1f}%"


def _fmt_ms(s: float, *, use_ms: bool = True) -> str:
    if s != s or s <= 0:
        return "—"
    if use_ms and s < 10:
        return f"{s * 1000:.0f} ms"
    return f"{s:.1f} s"


def _cell(ev: EngineEval, key: str) -> str:
    if not ev.ok:
        return "—"
    if key == "name":
        return ev.name[: COLUMNS[0].width - 1]
    if key == "everyday":
        h = headline(ev)
        return _fmt_pct(h["wer_pct"])
    if key == "numbers":
        return _fmt_pct(ev.group_wer("numeric")["wer_pct"])
    if key == "cold":
        return _fmt_ms(ev.latency.get("cold_s", float("nan")))
    if key == "warm":
        return _fmt_ms(ev.latency.get("warm_median_s", float("nan")))
    if key == "resident":
        return "yes" if ev.caps.get("service") else "no"
    return ""


def render_table(evs: list[EngineEval]) -> str:
    header = "| " + " | ".join(c.title for c in COLUMNS) + " |"
    sep = "|" + "|".join(":" + "-" * max(c.width - 2, 3) + ":" for c in COLUMNS) + "|"
    rows = [header, sep]
    for ev in evs:
        rows.append("| " + " | ".join(_cell(ev, c.key) for c in COLUMNS) + " |")
    return "\n".join(rows)


def accuracy_detail(evs: list[EngineEval]) -> str:
    """Per-group WER, plus the raw error counts that show what a gap means."""
    live = [e for e in evs if e.ok]
    if not live:
        return ""
    groups: list[str] = []
    for e in live:
        for s in e.clips():
            if s.group not in groups:
                groups.append(s.group)

    def label(g: str) -> str:
        return {
            "main": "Everyday prose",
            "jargon": "Technical terms",
            "numeric": "Numbers",
            "stress": "Acronyms",
            "long": "Long utterance",
            "polluted": "Second speaker talking",
        }.get(g, g)

    lines = [
        "| " + " | ".join(["Group"] + [e.name[:18] for e in live]) + " |",
        "|" + "|".join([":---"] + [":--:" for _ in live]) + "|",
    ]
    for g in groups:
        cells = []
        for e in live:
            agg = e.group_wer(g)
            cells.append(_fmt_pct(agg["wer_pct"]))
        lines.append("| " + " | ".join([label(g)] + cells) + " |")

    # Headline with error counts and intervals.
    lines.append("")
    lines.append("**Everyday dictation, with the raw error counts:**")
    lines.append("")
    lines.append("| Engine | Word errors | Reference words | WER (95% range) |")
    lines.append("|:---|---:|---:|:--:|")
    for e in live:
        h = headline(e)
        lines.append(
            f"| {e.name} | {h['edits']} | {h['ref_words']} | "
            f"{h['wer_pct']:.1f}% ({h['ci_low']:.1f}–{h['ci_high']:.1f}%) |"
        )
    return "\n".join(lines)


def gap_note(evs: list[EngineEval]) -> str:
    """Say plainly when the accuracy gap is one word, and which one."""
    live = sorted([e for e in evs if e.ok], key=lambda e: headline(e)["wer_pct"])
    if len(live) < 2:
        return ""
    best, second = live[0], live[1]
    hb, hs = headline(best), headline(second)
    gap_edits = hs["edits"] - hb["edits"]
    if gap_edits <= 0:
        return ""
    # Where did the gap come from?
    differing = []
    for sb, ss in zip(best.clips(), second.clips(), strict=False):
        if sb.clip == ss.clip and sb.edits != ss.edits:
            differing.append((sb.clip, sb.group, sb.edits, ss.edits))
    differing.sort(key=lambda t: -(abs(t[3] - t[2])))
    where = ", ".join(f"`{c}` ({a}→{b} errors)" for c, _g, a, b in differing[:4])
    if gap_edits <= 2:
        judgement = (
            f"**This is one-word territory.** {best.name} is ahead of {second.name} by "
            f"{gap_edits} word error(s) out of {hb['ref_words']}. On a corpus this size "
            f"that is not a reliable accuracy difference — treat them as tied and "
            f"choose on speed, plumbing or what you already use."
        )
    else:
        judgement = (
            f"{best.name} is ahead of {second.name} by {gap_edits} word errors out of "
            f"{hb['ref_words']}."
        )
    detail = f" The difference comes from: {where}." if where else ""
    return judgement + detail


def normalizer_note(evs: list[EngineEval]) -> str:
    """The artefact: naive scoring punishes some engines for how they format."""
    rows = []
    for e in evs:
        if not e.ok:
            continue
        basic = e.overall("basic")["wer_pct"]
        whisper = e.overall("whisper")["wer_pct"]
        rec = e.overall("reconciling")["wer_pct"]
        rows.append((e.name, basic, whisper, rec))
    if not rows:
        return ""
    spread = max(b - w for _n, b, w, _r in rows)
    lines = [
        "| Engine | Naive scorer | Whisper-style scorer | Number-aware scorer |",
        "|:--|--:|--:|--:|",
    ]
    for name, b, w, r in rows:
        lines.append(f"| {name} | {b:.1f}% | {w:.1f}% | {r:.1f}% |")
    text = "\n".join(lines)
    if spread >= 1.0:
        text += (
            f"\n\nScoring choice moves these numbers by up to **{spread:.1f} percentage "
            f"points**. Engines that write *\"2026\"* where another writes *\"twenty twenty "
            f"six\"* look worse or better purely because of the scorer. This is why many "
            f"published comparisons disagree with each other, and why this table uses the "
            f"number-aware scorer."
        )
    return text


# --------------------------------------------------------------------------- #
# Pros / cons per engine
# --------------------------------------------------------------------------- #


def pros_cons(ev: EngineEval, all_evs: list[EngineEval]) -> tuple[list[str], list[str]]:
    live = [e for e in all_evs if e.ok]
    pros: list[str] = []
    cons: list[str] = []
    if not ev.ok:
        return [], [f"Not measured: {ev.error[:120]}"]

    ranked = sorted(live, key=lambda e: headline(e)["wer_pct"])
    h = headline(ev)
    if len(ranked) == 1:
        pros.append(f"Everyday dictation accuracy: {h['wer_pct']:.1f}% WER "
                    f"({h['edits']} word errors in {h['ref_words']})")
    elif ev.name == ranked[0].name:
        pros.append(f"Most accurate everyday dictation on this machine ({h['wer_pct']:.1f}% WER)")
    elif ev.name == ranked[-1].name:
        cons.append(f"Least accurate everyday dictation here ({h['wer_pct']:.1f}% WER)")
    else:
        pros.append(f"Accurate enough for everyday use ({h['wer_pct']:.1f}% WER)")

    warm = ev.latency.get("warm_median_s", float("nan"))
    cold = ev.latency.get("cold_s", float("nan"))
    warm_rank = sorted([e for e in live], key=lambda e: e.latency.get("warm_median_s", 9e9))
    if warm == warm and len(warm_rank) == 1:
        pros.append(f"Time per phrase once running: {_fmt_ms(warm)}")
    elif warm == warm and warm_rank and ev.name == warm_rank[0].name:
        pros.append(f"Fastest after the first phrase ({_fmt_ms(warm)})")
    ratio = (cold / warm) if (cold == cold and warm == warm and warm > 0) else 1.0
    if cold == cold and ratio >= 4 and cold > 1.0:
        # A large first-call ratio means real one-time setup (model load,
        # shader or model compilation), not a steady per-call cost.
        if ev.caps.get("service"):
            cons.append(
                f"Slow first phrase ({_fmt_ms(cold)} vs {_fmt_ms(warm)}): one-time inference "
                f"setup on the first call; every later phrase is fast"
            )
        else:
            cons.append(
                f"Slow first phrase ({_fmt_ms(cold)}): the model is loaded per invocation, "
                f"so every relaunch pays this once"
            )
    elif cold == cold and cold > warm + 0.5:
        cons.append(f"Slower first phrase ({_fmt_ms(cold)}) than the rest ({_fmt_ms(warm)})")

    if not ev.caps.get("service"):
        cons.append("Not resident: pays model-load cost for every invocation")
    if ev.caps.get("streaming_encoder") and not ev.caps.get("partials"):
        cons.append(
            "A streaming encoder exists upstream, but this benchmark drove it through the "
            "batch endpoint, so no live-partial latency was measured"
        )
    for key, label in CAPABILITY_LABELS.items():
        if ev.caps.get(key):
            pros.append(label)
    for missing in ("partials", "vocab"):
        if key_known(ev, missing) and not ev.caps.get(missing):
            cons.append(f"No {CAPABILITY_LABELS[missing].lower()}")
    nums = ev.group_wer("numeric")["wer_pct"]
    main = ev.group_wer("main")["wer_pct"]
    if nums == nums and main == main and nums > main + 3:
        cons.append(f"Misreads numbers ({nums:.1f}% on the numbers group)")
    elif nums == nums and main == main and main > nums + 1:
        pros.append(f"Writes numbers correctly here ({nums:.1f}% on the numbers group, "
                    f"vs {main:.1f}% on prose)")
    return pros[:6], cons[:6]


def key_known(ev: EngineEval, key: str) -> bool:
    return key in ev.caps


# --------------------------------------------------------------------------- #
# Recommendation
# --------------------------------------------------------------------------- #


def recommendations(evs: list[EngineEval]) -> str:
    live = [e for e in evs if e.ok]
    if not live:
        return "Nothing was measured, so there is nothing to recommend."

    def h(e: EngineEval) -> float:
        return headline(e)["wer_pct"]

    def warm(e: EngineEval) -> float:
        return e.latency.get("warm_median_s", 9e9)

    def cold(e: EngineEval) -> float:
        return e.latency.get("cold_s", 9e9)

    if len(live) == 1:
        e = live[0]
        tail = ""
        if not e.caps.get("partials"):
            tail = (" Nothing measured here shows words while you speak; these are all "
                    "push-to-talk style (text appears when you stop).")
        return (f"Only **{e.name}** was measured, so there is nothing to compare it "
                f"against. Its numbers: {h(e):.1f}% WER on everyday dictation, "
                f"{_fmt_ms(warm(e))} per phrase once running, {_fmt_ms(cold(e))} for the "
                f"first phrase. Add a second engine to `bench.toml` to get a real choice."
                + tail)

    best_acc = min(live, key=h)
    fastest = min(live, key=warm)
    best_cold = min(live, key=cold)
    tied = [e for e in live if h(e) - h(best_acc) < 0.5]

    out: list[str] = []
    if len(tied) > 1 and fastest in tied:
        out.append(
            f"- **You want it to just work, every phrase:** **{fastest.name}** — tied on "
            f"accuracy ({h(fastest):.1f}%) and fastest once running ({_fmt_ms(warm(fastest))})."
        )
    else:
        out.append(
            f"- **Accuracy matters most:** **{best_acc.name}** ({h(best_acc):.1f}% WER)."
        )
        if h(fastest) - h(best_acc) >= 0.5 and fastest.name != best_acc.name:
            out.append(
                f"- **What decides it:** {best_acc.name} wins on accuracy; {fastest.name} is "
                f"{_fmt_ms(warm(fastest))} vs {_fmt_ms(warm(best_acc))} per phrase. Judge on the "
                f"accuracy gap ({h(best_acc):.1f}% vs {h(fastest):.1f}%) first."
            )
    if fastest.name != best_acc.name and h(fastest) - h(best_acc) >= 0.5:
        out.append(
            f"- **You would rather never wait:** **{fastest.name}** is the quickest "
            f"once running ({_fmt_ms(warm(fastest))}) at {h(fastest):.1f}% WER; the "
            f"{h(fastest) - h(best_acc):.1f}-point gap is visible on this corpus, so "
            f"pick it only if speed matters more than that."
        )
    if best_cold.name != fastest.name:
        out.append(
            f"- **You launch it once and dictate all day:** **{best_cold.name}** — its first "
            f"phrase after launch is the quickest ({_fmt_ms(cold(best_cold))})."
        )
    streaming = [e for e in live if e.caps.get("partials")]
    if streaming:
        out.append(
            "- **You want to watch words appear as you speak:** "
            + ", ".join(f"**{e.name}**" for e in streaming)
            + "."
        )
    else:
        out.append(
            "- **Nothing here shows words while you speak.** If that is what you are used to, "
            "these are all push-to-talk style: you get the text when you stop."
        )
    vocab = [e for e in live if e.caps.get("vocab")]
    if vocab:
        out.append(
            "- **You dictate names, jargon or product words:** prefer "
            + ", ".join(f"**{e.name}**" for e in vocab)
            + " and fill in its custom vocabulary; that fixes more real errors than a "
            "model swap."
        )
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Full document
# --------------------------------------------------------------------------- #


def corpus_note(corpus) -> str:
    groups: dict[str, int] = {}
    for c in corpus.clips:
        groups[c.group] = groups.get(c.group, 0) + 1
    total_s = sum(c.duration_s for c in corpus.clips)
    desc = ", ".join(f"{n} {g}" for g, n in groups.items())
    return f"{len(corpus)} clips ({total_s:.1f} s of audio): {desc}."


def render_markdown(evs: list[EngineEval], corpus, *, title: str | None = None) -> str:
    info = machine_info()
    when = _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines: list[str] = []
    lines.append(f"# {title or 'Local dictation: which engine for this machine?'}")
    lines.append("")
    lines.append(f"Measured {when} on **{info.get('cpu') or info['machine']}**, "
                 f"{info.get('ram_gb', '?')} GB RAM, {info['platform'].split(' ')[0]}.")
    lines.append("")
    lines.append(f"Corpus: {corpus_note(corpus)}")
    lines.append("")

    warns = sanity_checks(evs)
    if warns:
        lines.append("## Before you trust this")
        lines.append("")
        for w in warns:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## The table")
    lines.append("")
    lines.append(render_table(evs))
    lines.append("")
    lines.append("_First phrase = you pressed the key with the model not loaded yet "
                 "(what a freshly launched app costs you). After that = every following "
                 "phrase. (—) means the number could not be measured._")
    lines.append("")
    lines.append("| Engine | Runs as | Shows words while speaking | Custom vocabulary |")
    lines.append("|:--|:--|:-:|:-:|")
    kind_label = {"http": "resident server", "cli": "command per phrase",
                  "json-cli": "app / command per phrase", "custom": "custom command"}
    for ev in evs:
        if not ev.ok:
            continue
        runs = "resident server" if ev.caps.get("service") else kind_label.get(ev.kind, ev.kind)
        lines.append(
            f"| {ev.name} | {runs} | {'yes' if ev.caps.get('partials') else 'no'} | "
            f"{'yes' if ev.caps.get('vocab') else 'no'} |"
        )
    lines.append("")

    lines.append("## Accuracy in detail")
    lines.append("")
    detail = accuracy_detail(evs)
    if detail:
        lines.append(detail)
        lines.append("")
    gn = gap_note(evs)
    if gn:
        lines.append(gn)
        lines.append("")

    lines.append("## Why published WER numbers disagree")
    lines.append("")
    nn = normalizer_note(evs)
    lines.append(nn or "Not enough data.")
    lines.append("")

    lines.append("## Pros and cons")
    lines.append("")
    for ev in evs:
        pros, cons = pros_cons(ev, evs)
        lines.append(f"### {ev.name}")
        lines.append("")
        for p in pros:
            lines.append(f"- ✅ {p}")
        for c in cons:
            lines.append(f"- ⚠️ {c}")
        if ev.notes:
            lines.append(f"- ℹ️ {ev.notes}")
        if not pros and not cons:
            lines.append("- No data.")
        lines.append("")

    lines.append("## What I would pick")
    lines.append("")
    lines.append(recommendations(evs))
    lines.append("")
    lines.append("## What this does not tell you")
    lines.append("")
    lines.append("- **Your voice and your microphone are not the test.** Default synthetic")
    lines.append("  speakers are cleaner than a real room; real accuracy gaps tend to be larger.")
    lines.append('  Use `dictation-bench corpus --from-clip recording.wav --ref "what you said"`.')
    lines.append("- **Latency here is engine time, not the full felt wait.** Launching an app,")
    lines.append("  audio capture, the paste keystroke and clipboard handling add tens to")
    lines.append("  hundreds of milliseconds that no engine-level benchmark can see.")
    lines.append("- **One run, one machine.** Re-run it if you care; that is the point.")
    return "\n".join(lines) + "\n"

"""Render a coverage report: terminal table, Markdown (PR comment), JSON, SVG badge, test stubs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from flagcov.analyze import FlagState, Report, _pct

TICK, CROSS, DASH = "tested", "NOT TESTED", "-"


def write_all(report: Report, out: str | Path) -> dict[str, Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "json": out / "report.json",
        "markdown": out / "report.md",
        "badge": out / "badge.svg",
        "stubs": out / "test_flagcov_stubs.py",
    }
    files["json"].write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    files["markdown"].write_text(markdown(report), encoding="utf-8")
    files["badge"].write_text(badge(report), encoding="utf-8")
    files["stubs"].write_text(stubs(report), encoding="utf-8")
    return files


def headline(report: Report) -> str:
    return (
        f"Flag coverage: {report.state_coverage:.0f}% of flag states tested | "
        f"{len(report.fully_tested)}/{len(report.live_flags)} live flags fully tested"
    )


# --------------------------------------------------------------------------- terminal


def terminal(report: Report, show_covered: bool = True) -> str:
    rows = []
    for f in report.flags:
        for s in f.states:
            if not show_covered and s.covered:
                continue
            status = TICK if s.covered else ("optional" if s.kind == "kill_switch" else CROSS)
            note = ""
            if s.kind == "segment" and s.targeting_verified is False and s.covered:
                note = " (value tested, targeting rule never matched)"
            if f.stale:
                if s.kind == "kill_switch":
                    continue
                status = "STALE (no code reads it)"
            elif not f.evaluated and s.kind == "default":
                status = "NEVER READ BY TESTS"
            rows.append((f.flag, s.label, status + note, s.where, str(s.hits)))
    head = ("flag", "state", "status", "who gets it", "hits")
    widths = [max(len(r[i]) for r in [head, *rows]) for i in range(5)]
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    out = [line(head), line(tuple("-" * w for w in widths))]
    out += [line(r) for r in rows]
    out.append("")
    out.append(headline(report))
    worst = report.worst_flag
    if worst and worst.untested_traffic > 0:
        out.append(f"Riskiest flag: {worst.flag} ({_pct(worst.untested_traffic)} of its production traffic hits untested code)")
    if report.unknown_flags:
        out.append("Read in code but missing from Flagsmith: " + ", ".join(report.unknown_flags))
    if report.unreferenced_flags:
        out.append("In Flagsmith but never read in the scanned code: " + ", ".join(report.unreferenced_flags))
    return "\n".join(out)


# --------------------------------------------------------------------------- markdown


def markdown(report: Report, changed_flags: set[str] | None = None) -> str:
    lines = [
        "## 🚩 FlagCov: feature flag coverage",
        "",
        f"**{report.state_coverage:.0f}%** of flag states tested · **{len(report.fully_tested)}/{len(report.live_flags)}** live flags fully tested"
        + (f" · environment `{report.environment}`" if report.environment else ""),
        "",
    ]
    worst = report.worst_flag
    if worst and worst.untested_traffic > 0:
        lines += [f"Riskiest flag: `{worst.flag}`: **{_pct(worst.untested_traffic)}** of its production traffic runs code no test has executed.", ""]
    if changed_flags is not None:
        if changed_flags:
            lines += ["Flags touched by this change: " + ", ".join(f"`{k}`" for k in sorted(changed_flags)), ""]
        else:
            lines += ["This change doesn't touch any flag, so all flags are shown.", ""]
            changed_flags = None
    risky = [
        (f, s)
        for f in report.flags
        for s in f.states
        if not s.covered and s.required and (changed_flags is None or f.flag in changed_flags)
    ]
    risky.sort(key=lambda fs: -(fs[1].weight or 0))
    if risky:
        lines += ["| | Flag | State | Who gets it in production |", "|---|---|---|---|"]
        for f, s in risky:
            mark = "🔴" if (s.weight or 0) >= 25 or not f.evaluated else "🟠"
            lines.append(f"| {mark} | `{f.flag}` | `{s.label}` | {s.where}{' · never read by any test' if not f.evaluated else ''} |")
        lines.append("")
    else:
        lines += ["✅ Every flag state production can serve was exercised by the tests.", ""]

    kill = [s for s in report.states if s.kind == "kill_switch" and not s.covered and not s.stale]
    if kill:
        names = ", ".join(f"`{s.flag}`" for s in kill)
        lines += [f"⚠️ **Kill switch never tested:** {names}. If you turn these off during an incident, that code path has never run in tests.", ""]
    unverified = [s for s in report.states if s.kind == "segment" and s.covered and s.targeting_verified is False]
    if unverified:
        lines += ["ℹ️ Segment values tested, but no test used traits that match the segment rule: "
                  + ", ".join(f'`{s.flag}` → "{s.segment}"' for s in unverified), ""]
    if report.unknown_flags:
        lines += ["❓ **Read in code but missing from Flagsmith** (typo, or not created yet): "
                  + ", ".join(f"`{k}` ({v[0]})" for k, v in report.unknown_flags.items()), ""]
    if report.unreferenced_flags:
        lines += ["🧹 In Flagsmith but never read in the scanned code (stale?): "
                  + ", ".join(f"`{k}`" for k in report.unreferenced_flags), ""]
    if risky:
        lines += [
            "<details><summary>Copy-paste tests for the untested states</summary>",
            "",
            "```python",
            stubs(report, only_flags=changed_flags).strip(),
            "```",
            "</details>",
            "",
        ]
    lines.append("<sub>Generated by FlagCov from the live Flagsmith environment document.</sub>")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- badge


def badge(report: Report) -> str:
    tested = report.state_coverage
    color = "#2ea44f" if tested >= 90 else "#dfb317" if tested >= 70 else "#e05d44"
    label, value = "flag coverage", f"{tested:.0f}%"
    lw, vw = 6 * len(label) + 12, 7 * len(value) + 12
    w = lw + vw
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{label}: {value}">'
        f"<title>{label}: {value}</title>"
        f'<rect width="{lw}" height="20" fill="#555"/><rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
        f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">'
        f'<text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" y="14">{value}</text></g></svg>'
    )


# --------------------------------------------------------------------------- stubs


def _ident(text: str) -> str:
    return re.sub(r"\W+", "_", text).strip("_").lower() or "flag"


def _literal(state: FlagState) -> str:
    if state.kind == "kill_switch" or not state.enabled:
        return "OFF"
    if state.value is None:
        return "True"
    return repr(state.value)


def stubs(report: Report, only_flags: set[str] | None = None) -> str:
    """Parametrised pytest stubs that force every untested state through ``flag_override``."""
    blocks = []
    for f in report.flags:
        if f.stale or (only_flags is not None and f.flag not in only_flags):
            continue
        missing = [s for s in f.states if not s.covered and s.kind in ("default", "variant", "kill_switch")]
        segments = [s for s in f.states if s.kind == "segment" and (not s.covered or s.targeting_verified is False)]
        if not missing and not segments:
            continue
        if missing:
            values = ", ".join(_literal(s) for s in missing)
            blocks.append(
                f"@pytest.mark.parametrize(\"state\", [{values}])\n"
                f"def test_{_ident(f.flag)}_untested_states(flag_override, state):\n"
                f"    flag_override({f.flag!r}, state)\n"
                f"    # TODO: call the code that reads {f.flag!r} and assert on the behaviour.\n"
            )
        for s in segments:
            blocks.append(
                f"def test_{_ident(f.flag)}_segment_{_ident(s.segment or 'segment')}():\n"
                f"    # Production serves {_literal(s)} to segment {s.segment!r} ({s.rule}).\n"
                f"    # Evaluate with traits that satisfy the rule, so the targeting itself is tested:\n"
                f"    # ctx = EvaluationContext(targeting_key=\"test-user\", attributes={{...}})\n"
                f"    # assert client.get_string_value({f.flag!r}, ..., ctx) == {_literal(s)}\n"
                f"    pytest.skip(\"TODO: write this test\")\n"
            )
    if not blocks:
        return "# FlagCov: no untested flag states. Nothing to generate.\n"
    header = "# Generated by FlagCov. Each test forces one untested flag state.\nimport pytest\n\nfrom flagcov import OFF\n\n\n"
    return header + "\n\n".join(blocks)

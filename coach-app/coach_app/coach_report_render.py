"""Plain Markdown rendering of a CoachingReportV1 (for the local CLI and for reviewers)."""
from __future__ import annotations

from typing import Any

VERDICT = {"sound": "Consistent with the decision-time read", "defensible_if": "Defensible under an assumption",
           "risky": "A known risk was present", "questionable": "The decision-time read argued against it",
           "debatable": "Debatable", "unclear": "Not clearly supported or ruled out", "not_assessed": "Not assessed"}


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def render_markdown(report: dict[str, Any], *, player_label: str = "you") -> str:
    out = [f"# Coaching report ({report['schema']}, experimental)", "",
           f"Player: {player_label} ({report.get('focus_player_team')} team). "
           f"Situations analysed: {report['coverage']['situations_analysed']} "
           f"({', '.join(f'{k} {v}' for k, v in sorted(report['coverage']['by_class'].items()))}).",
           "", "> Rule-based analysis, not expert-validated. Times are replay seconds. Stage A uses only what was known at "
           "the decision moment; the 'What you did' part is retrospective and never changes Stage A.", ""]
    for f in report["findings"]:
        sit = f["situation"]
        out += [f"## {f['finding_id']} - {_mmss(f['t0'])} - {sit['label']}", "",
                f"*Why this moment:* {', '.join(sit['selection'].get('why_selected', []))}. {sit['why_it_matters']}", ""]
        if f["kind"] == "observation_only" or f.get("status") != "ok":
            out += [f"**Observation only.** {f['interpretation']['text']}", ""]
            out += [f"- {c['reading'][0].upper() + c['reading'][1:]}" for c in f.get("decision_context", []) if c.get("reading")]
            out.append("")
            continue
        out += ["**What the situation was (at decision time)**", ""]
        for c in f["decision_context"]:
            if c["reading"]:
                tag = "" if c["status"] in ("holds", "fails") else f" *({c['status'].replace('_', ' ')})*"
                out.append(f"- {c['reading'][0].upper() + c['reading'][1:]}{tag}")
        out += ["", f"**Interpretation ({f['kind'].replace('_', ' ')}).** {f['interpretation']['text']}", "",
                "**Options**", "", "| Option | At t0 | Gains / preserves | Sacrifices / risks |", "|---|---|---|---|"]
        for a in f["alternatives"]:
            g = "; ".join(x["text"] + ("" if x["status"] == "applies" else " (possible)") for x in a["gains"] + a["preserves"])
            r = "; ".join(x["text"] + ("" if x["status"] == "applies" else " (possible)") for x in a["sacrifices"] + a["risks"])
            out.append(f"| {a['label']} | {a['status']} | {g or '-'} | {r or '-'} |")
        dec = f["assumptions"]["decisive"]
        unobs = f["assumptions"]["unobservable"]
        if dec or unobs:
            out += ["", "**Assumptions the replay cannot settle**", ""]
            out += [f"- {d.get('question', d['text'])} ({d['current'].replace('_', ' ')}; resolve with {d['how_to_resolve']})" for d in dec]
            if unobs:
                out.append("- Not observable at all: " + ", ".join(u["condition"].replace("_", " ") for u in unobs))
        if f["takeaway"]["text"]:
            out += ["", f"**Takeaway ({f['takeaway']['kind']}).** {f['takeaway']['text']}"]
        rb = f.get("retrospective")
        if rb:
            o = rb["outcome"]
            seq = ", ".join(f"{x['by']} +{x['t_after_s']} s" for x in o["touch_sequence"]) or "no touches"
            goal = f"; goal by {o['goal']['scored_by']} +{o['goal']['t_after_s']} s" if o["goal"] else ""
            out += ["", f"**What you did (retrospective):** {VERDICT[rb['assessment']['verdict']]}. {rb['assessment']['text']}",
                    f"Next {o['window_s']:g} s: {seq}{goal}. *{rb['outcome_independence']}*"]
        out += ["", f"<sub>Evidence: {len(f['claims'])} decision-time claims ({'valid' if f['validation']['claims_structurally_valid'] else 'INVALID'}); "
                f"numbers traced to {', '.join(sorted({r for v in f['numbers'].values() for r in v['refs']}))}.</sub>", ""]
    pat = report.get("patterns")
    if pat:
        out += ["## Match patterns (observed actions vs decision-time read; outcomes not used)", ""]
        for cls, c in sorted(pat["by_class"].items()):
            out.append(f"- {cls.replace('_', ' ')}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
        for t in pat["tendencies"]:
            out.append(f"- **Tendency:** {t['text']} (at {', '.join(_mmss(x) for x in t['t0s'])})")
    out += ["", "## Limits", ""] + [f"- {x}" for x in report["limits"]]
    return "\n".join(out) + "\n"

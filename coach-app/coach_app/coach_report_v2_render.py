"""Markdown rendering of CoachingReportV2 (local CLI and reviewers)."""
from __future__ import annotations

from typing import Any

from .coach_report_render import render_markdown

V2_VERDICT = {"consistent_with_rule_read": "Matched the decision-time rule read",
              "defensible_if": "Defensible under an assumption",
              "against_rule_read_unconfirmed": "Went against the rule read (unconfirmed: review, not a mistake)",
              "unclear": "Not clearly supported or ruled out", "not_assessed": "Not assessed"}


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _pct(x):
    return "-" if x is None else f"{round(100 * x)}%"


def render_markdown_v2(rep: dict[str, Any], *, player_label: str = "you") -> str:
    hp = rep["habit_profile"]
    out = [f"# Coaching report V2 ({rep['schema']}, experimental)", "",
           f"Player: {player_label}. Matches: {hp['replays']}. Nothing here is expert-validated; read the evidence-status "
           "table at the end before acting on anything.", "",
           "## 1. Habits (rates across the match, compared with a reference cohort of unknown rank)", "",
           "| Habit | Your rate | Instances | Reference percentile | Reliability | Examples |", "|---|---|---|---|---|---|"]
    for h in hp["habits"]:
        pct = "-" if h["reference_percentile"] is None else f"{h['reference_percentile']}" + (
            f" ({h['standout']})" if h["standout"] else "")
        ex = ", ".join(_mmss(t) for t in h["examples"]) or "-"
        note = "" if h["enough_data"] else " (too few)"
        out.append(f"| {h['description']} | {_pct(h['rate'])}{note} | {h['n']} | {pct} | {h['status']} | {ex} |")
    out += ["", f"*{hp['reference']['note']}*", ""]
    for m in rep["matches"]:
        tag = f"match {m['match_index'] + 1}" if len(rep["matches"]) > 1 else "this match"
        out += [f"## 2. Turning points in {tag} (retrospective selection)", "",
                "Largest changes in your team's expected control over 2 s, both directions. 'Your movement' is how much "
                "of that change your own movement accounts for in the model (leave-one-player-out), not blame.", ""]
        if not m["turning_points"]:
            out.append("- None found.")
        for tp in m["turning_points"]:
            touches = ", ".join(f"{x['by']} {_mmss(x['t'])}" for x in tp["touches"]) or "no touches"
            out.append(f"- **{_mmss(tp['t_start'])}-{_mmss(tp['t_end'])}: control {tp['direction']}**; your movement "
                       f"{tp['your_movement']} it (share {round(100 * tp['your_share_of_attributed_change'])}% of the attributed "
                       f"change). Touches: {touches}.")
            link = tp.get("decision_time_reading")
            if link:
                out.append(f"  - Decision-time read at {_mmss(link['t0'])} ({link['class'].replace('_', ' ')}): {link['interpretation']}")
                ctx = link.get("commitment_context")
                if ctx:
                    out.append(f"  - Context: teammate recovery debt {ctx['teammate_recovery_debt_s']} s, yours "
                               f"{ctx['your_recovery_debt_s']} s; your team reached {_pct(ctx['own_goal_zone_control'])} of the "
                               f"area around your goal first. {ctx['note']}")
        out += ["", f"## 3. Decision moments in {tag} (decision-time reads)", ""]
        for f in m["decision_findings"]:
            b = f["retrospective"]["assessment"]
            f2 = {**f, "retrospective": {**f["retrospective"], "assessment": {**b, "text": b.get("text_v2", b["text"]),
                                                                             "verdict": b["verdict"]}}}
            md = render_markdown({"schema": "CoachingFindingV1", "focus_player_team": m["team"], "findings": [f2],
                                  "patterns": None, "coverage": {"situations_analysed": 1, "by_class": {}}, "limits": []},
                                 player_label=player_label)
            body = md.split("\n## ", 1)[1].rsplit("\n## Limits", 1)[0] if "\n## " in md else md
            out += ["### " + body.replace("**What you did (retrospective):**",
                                          f"**What you did (retrospective, {V2_VERDICT.get(b.get('verdict_v2'), '')}):**"), ""]
            if f.get("ledger_adjustments"):
                out += [f"<sub>Round 13 adjustment: {a['condition']} {a['from']} -> {a['to']}: {a['why']}</sub>"
                        for a in f["ledger_adjustments"]] + [""]
            if f.get("commitment_context"):
                c = f["commitment_context"]
                out += [f"Context: teammate recovery debt {c['teammate_recovery_debt_s']} s; your team reached "
                        f"{_pct(c['own_goal_zone_control'])} of the area around your goal first.", ""]
    out += ["## Evidence status", "", "| Component | Status | Detail |", "|---|---|---|"]
    out += [f"| {e['component']} | {e['status']} | {e['detail']} |" for e in rep["evidence_status"]]
    out += ["", "## Limits", ""] + [f"- {x}" for x in rep["limits"]]
    return "\n".join(out) + "\n"

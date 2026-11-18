"""Write the Round 12 example documents.

  docs/round12/EXAMPLES_SYNTHETIC.md  every synthetic scenario (labelled SYNTHETIC) through coach_moment
  docs/round12/EXAMPLES_REAL.md       selected findings from public cached replays (anonymised: match hash,
                                      no names or IDs), chosen to cover classes and verdicts, not quality

Usage (from coach-app/): python scripts/round12_examples.py CACHE_DIR
"""
from __future__ import annotations

import glob
import hashlib
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.coach_report import build_coaching_report, coach_moment  # noqa: E402
from coach_app.coach_report_render import render_markdown  # noqa: E402
from coach_app.synthetic_scenarios import T0, materialise, scenarios  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "round12"


def _wrap(findings, team="blue"):
    return {"schema": "CoachingReportV1", "focus_player_team": team, "findings": findings, "patterns": None,
            "coverage": {"situations_analysed": len(findings), "by_class": {}},
            "limits": ["Rule-based tactical reasoning; not validated by expert raters."]}


def synthetic() -> str:
    out = ["# Round 12 coaching examples - SYNTHETIC scenarios", "",
           "**Every example on this page is synthetic**: a hand-built replay run through the real pipeline "
           "(`coach_report.coach_moment`). They show how the reasoning handles difficult cases; they are not real "
           "gameplay and not evidence of tactical accuracy. Where a scenario has several futures, Stage A is identical "
           "across them (tested); only the retrospective part changes.", ""]
    for sc in scenarios():
        futs = list(sc["futures"]) or [None]
        out += [f"# Scenario: {sc['name']} (SYNTHETIC)", "", sc["description"], ""]
        for k, fut in enumerate(futs):
            f = coach_moment(materialise(sc, fut), "b1", T0, finding_id=f"{sc['name']}" + (f" / future: {fut}" if fut else ""))
            if f.get("status") == "no_supported_situation":
                out += [f"**Result: abstained.** {f['reason']}", ""]
                break
            md = render_markdown(_wrap([f]), player_label="synthetic focus player")
            body = md.split("\n## ", 1)[1].rsplit("\n## Limits", 1)[0] if "\n## " in md else md
            if k == 0:
                out += ["## " + body, ""]
            else:
                rb = f["retrospective"]
                out += [f"**Alternative future `{fut}`** (Stage A unchanged): {rb['assessment']['text']} "
                        f"Outcome: {rb['outcome']['goal'] or 'no goal within 5 s'}.", ""]
    return "\n".join(out)


def real(cache: Path) -> str:
    out = ["# Round 12 coaching examples - real public replays (anonymised)", "",
           "Public 2v2 replays of **unknown rank** from the cached cohort. Matches are identified by a hash; player "
           "names and IDs are omitted. Examples were chosen to cover situation classes and retrospective verdicts, "
           "**not** because they read best, and nothing here has been reviewed by an expert. Read them as what the "
           "system would tell a player, with its limits shown.", ""]
    picked, seen = [], set()
    for f in sorted(glob.glob(str(cache / "*.pkl")))[:8]:
        d = pickle.loads(Path(f).read_bytes())
        mh = "match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]
        for pi in (0, 2):
            rep = build_coaching_report(d, d["players"][pi]["id"], max_findings=6)
            for x in rep["findings"]:
                key = (x["situation"]["class"], x.get("retrospective", {}).get("assessment", {}).get("verdict"))
                if x["status"] == "ok" and key not in seen and len(picked) < 10:
                    seen.add(key)
                    x["finding_id"] = f"{mh} / player {pi} / {x['finding_id']}"
                    picked.append((x, rep["focus_player_team"]))
    for x, team in picked:
        md = render_markdown(_wrap([x], team), player_label="focus player")
        out += ["## " + md.split("\n## ", 1)[1].rsplit("\n## Limits", 1)[0], ""]
    return "\n".join(out)


if __name__ == "__main__":
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "EXAMPLES_SYNTHETIC.md").write_text(synthetic())
    if len(sys.argv) > 1:
        (DOCS / "EXAMPLES_REAL.md").write_text(real(Path(sys.argv[1])))
    print("written")

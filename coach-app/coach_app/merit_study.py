"""Blind two-stage expert tactical-merit study (Round 11, Phase C).

Separate from PR #16's commitment-TIMING study: this one asks whether each action was acceptable.

Stage A (blind, before anything is revealed)
  The expert sees a clip that ENDS at the decision time t0 (no later footage), with a marked focus car.
  For every action family they rate: good / acceptable / poor / cannot_judge, give an overall
  confidence, may name an action outside the menu, and say what missing information would change
  their view. They never see the system's output, the player's actual action or the outcome.
Lock
  Stage A responses are canonicalised and hashed. Stage B cannot be built without the matching lock.
Stage B (reveal)
  The expert sees the full clip (actual action + outcome) and rates the actual decision again, says
  whether the outcome looked consistent / lucky / unlucky, and whether their view changed.

Scoring compares one or more systems with expert *consensus* per (case, action):
  consensus = acceptable or poor only when >= 2 raters judged it and none disagreed in direction;
  otherwise contested (raters disagree) or insufficient (< 2 judgments). Contested items are never
  counted as system errors; they are reported separately.
Metrics: false-blame rate (system says poor, experts say acceptable), missed-problem rate, positive
recognition, coverage / accuracy-when-judging, Cohen's kappa vs consensus, abstention quality
(do system abstentions fall on items experts also find hard?), inter-rater Krippendorff alpha, per
stratum figures with case-bootstrap intervals, and a hindsight check from Stage B.

Nothing here creates expert labels. Synthetic ratings exist only in tests.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from typing import Any, Callable

STUDY_SCHEMA = "TacticalMeritStudyV0"
ACTIONS = ("immediate_challenge", "controlled_fifty_fifty", "controlled_touch", "clear_or_pass_to_space",
           "shadow_delay", "goal_side_hold", "fake_challenge", "yield_to_teammate", "rotate_through_small_pads")
RATINGS = ("good", "acceptable", "poor", "cannot_judge")
CONFIDENCE = ("low", "medium", "high")
OUTCOME_VIEW = ("consistent", "lucky", "unlucky", "unclear")
STRATA = ("withheld", "risky_aggression", "covered_aggression", "intelligent_restraint", "possession",
          "recovery", "off_ball_defense", "strong_positive", "other")
CHOICE_TO_ACTION = {"challenge": "immediate_challenge", "shadow": "shadow_delay", "retreat": "goal_side_hold",
                    "boost": "rotate_through_small_pads"}
STAGE_A_LEAD_RANGE = (3.0, 5.0)
STAGE_B_AFTER_S = 3.0


class StudyError(ValueError):
    """A study file breaks the protocol."""


# ---------- system outputs -> per-action labels ----------

def rationale_labels(r: dict) -> dict[str, str]:
    """ActionRationaleV0 -> acceptable / poor / abstain per action."""
    if r.get("judgment") != "available":
        return {a: "abstain" for a in ACTIONS}
    m = {"supported": "acceptable", "conditional": "acceptable", "refuted": "poor", "contested": "abstain"}
    return {a: m[r["actions"][a]["status"]] for a in ACTIONS}


def rationale_evidence_only_labels(r: dict) -> dict[str, str]:
    """Stricter reading: only evidence-established support counts; premise-based support abstains."""
    if r.get("judgment") != "available":
        return {a: "abstain" for a in ACTIONS}
    m = {"supported": "acceptable", "conditional": "abstain", "refuted": "poor", "contested": "abstain"}
    return {a: m[r["actions"][a]["status"]] for a in ACTIONS}


def decision_state_v1_labels(r: dict) -> dict[str, str]:
    if r.get("status") == "abstain":
        return {a: "abstain" for a in ACTIONS}
    m = {"robustly_defensible": "acceptable", "defensible_gamble": "acceptable", "defensible_tradeoff": "acceptable",
         "questionable": "poor", "undetermined": "abstain", "not_available": "abstain"}
    got = {a["action"]: m[a["stance"]] for a in r.get("actions", [])}
    return {a: got.get(a, "abstain") for a in ACTIONS}


def tactical_options_v0_labels(r: dict) -> dict[str, str]:
    if r.get("status") == "abstain":
        return {a: "abstain" for a in ACTIONS}
    m = {"defensible": "acceptable", "defensible_with_conditions": "acceptable", "questionable": "poor",
         "not_available": "abstain", "not_assessable": "abstain"}
    got = {o["action"]: m[o["strategic_stance"]] for o in r.get("options", [])}
    return {a: got.get(a, "abstain") for a in ACTIONS}


# ---------- stratification (pre-registered; uses the retrospective choice for SAMPLING only) ----------

def assign_stratum(rationale: dict, observed_choice: str | None) -> str:
    cond = {k: v["status"] for k, v in rationale.get("conditions", {}).items()}
    action = CHOICE_TO_ACTION.get(observed_choice or "")
    if rationale.get("judgment") != "available":
        return "withheld"
    if observed_choice == "challenge" and cond.get("teammate_covers") in ("fails", "within_error"):
        return "risky_aggression"
    if observed_choice == "challenge" and cond.get("teammate_covers") == "holds":
        return "covered_aggression"
    if observed_choice in ("shadow", "retreat") and (cond.get("carrier_first") == "holds" or cond.get("teammate_covers") == "fails"):
        return "intelligent_restraint"
    if cond.get("focus_first") == "holds":
        return "possession"
    if cond.get("focus_grounded") == "fails" or cond.get("boost_for_recovery") == "fails":
        return "recovery"
    if cond.get("teammate_first") in ("holds", "within_error"):
        return "off_ball_defense"
    if action and rationale["actions"].get(action, {}).get("status") == "supported":
        return "strong_positive"
    return "other"


# ---------- preparation ----------

def _blind_id(seed: str, case_id: str) -> str:
    return "rv-" + hashlib.sha256(f"{seed}|{case_id}".encode()).hexdigest()[:10]


def prepare_study(cases: list[dict], *, seed: str, per_stratum: int = 6, overlap_raters: int = 2) -> dict:
    """``cases``: [{case_id, replay_group, team, source_t0_s, systems{name: labels}, rationale_summary,
    stratum, retrospective{observed_action, outcome}}]. Returns public Stage A packets + a sealed private map."""
    rng = random.Random(seed)
    by = defaultdict(list)
    for c in sorted(cases, key=lambda c: c["case_id"]):
        by[c["stratum"]].append(c)
    chosen = []
    for st in STRATA:
        pool = by.get(st, [])
        rng.shuffle(pool)
        groups_used: Counter = Counter()
        for c in pool:                       # spread across matches
            if len([x for x in chosen if x["stratum"] == st]) >= per_stratum:
                break
            if groups_used[c["replay_group"]] >= max(1, per_stratum // 2):
                continue
            groups_used[c["replay_group"]] += 1
            chosen.append(c)
    rng.shuffle(chosen)
    packets, private = [], {}
    for c in chosen:
        rid = _blind_id(seed, c["case_id"])
        lead = round(rng.uniform(*STAGE_A_LEAD_RANGE), 3)
        packets.append({"review_id": rid, "clip_file": f"{rid}-A.mp4", "clip_start_s": round(c["source_t0_s"] - lead, 3),
                        "clip_end_s": c["source_t0_s"], "decision_at": "the final frame of the clip",
                        "focus_hint": f"Follow the marked {c['team']} car", "actions": list(ACTIONS),
                        "replay_group": c["replay_group"]})
        private[rid] = {"case_id": c["case_id"], "stratum": c["stratum"], "systems": c["systems"],
                        "rationale_summary": c.get("rationale_summary"), "retrospective": c["retrospective"],
                        "source_t0_s": c["source_t0_s"], "replay_group": c["replay_group"]}
    for p in packets:                        # the replay group is for the exporter only, not shown to raters
        private[p["review_id"]]["clip_a"] = {k: p[k] for k in ("clip_file", "clip_start_s", "clip_end_s")}
    return {"schema": STUDY_SCHEMA, "seed": seed, "raters_per_case": overlap_raters,
            "stage_a_packets": [{k: v for k, v in p.items() if k != "replay_group"} for p in packets],
            "exporter_rows": packets, "private_map": private,
            "strata_counts": dict(Counter(private[p["review_id"]]["stratum"] for p in packets))}


# ---------- Stage A ----------

def validate_stage_a(responses: list[dict], packets: list[dict]) -> None:
    ids = {p["review_id"] for p in packets}
    seen = set()
    for r in responses:
        key = (r.get("review_id"), r.get("rater_id"))
        if r.get("review_id") not in ids:
            raise StudyError(f"Unknown review_id {r.get('review_id')}.")
        if not r.get("rater_id"):
            raise StudyError("rater_id required.")
        if key in seen:
            raise StudyError(f"Duplicate response {key}.")
        seen.add(key)
        ratings = r.get("ratings", {})
        if set(ratings) != set(ACTIONS) or any(v not in RATINGS for v in ratings.values()):
            raise StudyError(f"{key}: every action needs one of {RATINGS}.")
        if r.get("confidence") not in CONFIDENCE:
            raise StudyError(f"{key}: confidence must be one of {CONFIDENCE}.")
        pref = r.get("preferred", [])
        if any(a not in ACTIONS or ratings[a] not in ("good", "acceptable") for a in pref):
            raise StudyError(f"{key}: preferred actions must be rated good or acceptable.")
        forbidden = {"actual_action", "outcome", "system", "goal"} & set(r)
        if forbidden:
            raise StudyError(f"{key}: Stage A responses may not contain {sorted(forbidden)}.")


def canonical(responses: list[dict]) -> bytes:
    return json.dumps(sorted(responses, key=lambda r: (r["review_id"], r["rater_id"])), sort_keys=True,
                      separators=(",", ":")).encode()


def lock_stage_a(responses: list[dict], packets: list[dict]) -> dict:
    validate_stage_a(responses, packets)
    return {"schema": STUDY_SCHEMA + "/lock", "sha256": hashlib.sha256(canonical(responses)).hexdigest(),
            "responses": len(responses), "review_ids": sorted({r["review_id"] for r in responses})}


# ---------- Stage B ----------

def build_stage_b(study: dict, responses: list[dict], lock: dict) -> list[dict]:
    if hashlib.sha256(canonical(responses)).hexdigest() != lock.get("sha256"):
        raise StudyError("Stage A responses do not match the lock; Stage B cannot be revealed.")
    rated = {r["review_id"] for r in responses}
    out = []
    for rid, priv in sorted(study["private_map"].items()):
        if rid not in rated:
            continue
        retro = priv["retrospective"]
        out.append({"review_id": rid, "clip_file": f"{rid}-B.mp4", "clip_start_s": priv["clip_a"]["clip_start_s"],
                    "clip_end_s": round(priv["source_t0_s"] + STAGE_B_AFTER_S, 3),
                    "actual_action": CHOICE_TO_ACTION.get(retro.get("observed_action"), "other"),
                    "actual_action_label_source": "retrospective classifier (choices.py); may be wrong",
                    "outcome": retro.get("outcome")})
    return out


def validate_stage_b(responses: list[dict], packets: list[dict]) -> None:
    ids = {p["review_id"] for p in packets}
    for r in responses:
        if r.get("review_id") not in ids or not r.get("rater_id"):
            raise StudyError("Stage B response needs a revealed review_id and a rater_id.")
        if r.get("actual_action_rating") not in RATINGS or r.get("outcome_view") not in OUTCOME_VIEW:
            raise StudyError("Stage B needs actual_action_rating and outcome_view.")
        if not isinstance(r.get("view_changed"), bool):
            raise StudyError("Stage B needs view_changed true/false.")


# ---------- scoring ----------

def _dir(r: str) -> int | None:
    return {"good": 1, "acceptable": 1, "poor": 0}.get(r)


def consensus(stage_a: list[dict]) -> dict[tuple[str, str], dict]:
    by = defaultdict(list)
    for r in stage_a:
        for a, v in r["ratings"].items():
            by[(r["review_id"], a)].append(v)
    out = {}
    for key, vals in by.items():
        dirs = [_dir(v) for v in vals if _dir(v) is not None]
        if len(dirs) < 2:
            label = "insufficient"
        elif len(set(dirs)) > 1:
            label = "contested"
        else:
            label = "acceptable" if dirs[0] == 1 else "poor"
        out[key] = {"label": label, "good": all(v == "good" for v in vals if _dir(v) == 1) and label == "acceptable",
                    "ratings": vals}
    return out


def krippendorff_alpha_nominal(stage_a: list[dict]) -> float | None:
    """Nominal alpha over {acceptable, poor}; cannot_judge is missing data."""
    units = defaultdict(list)
    for r in stage_a:
        for a, v in r["ratings"].items():
            d = _dir(v)
            if d is not None:
                units[(r["review_id"], a)].append(d)
    pairs = [vals for vals in units.values() if len(vals) >= 2]
    n = sum(len(v) for v in pairs)
    if n < 2:
        return None
    coinc = Counter()
    for vals in pairs:
        m = len(vals)
        for i, x in enumerate(vals):
            for j, y in enumerate(vals):
                if i != j:
                    coinc[(x, y)] += 1 / (m - 1)
    marg = Counter()
    for (x, _y), w in coinc.items():
        marg[x] += w
    do = sum(w for (x, y), w in coinc.items() if x != y) / n
    de = sum(marg[x] * marg[y] for x in marg for y in marg if x != y) / (n * (n - 1))
    return None if de == 0 else round(1 - do / de, 3)


def _kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def _rate(num: int, den: int) -> dict:
    return {"num": num, "den": den, "rate": round(num / den, 3) if den else None}


def _metrics(items: list[dict]) -> dict:
    judged_acc = [i for i in items if i["consensus"] == "acceptable"]
    judged_poor = [i for i in items if i["consensus"] == "poor"]
    good = [i for i in items if i["good"]]
    decided = [i for i in items if i["consensus"] in ("acceptable", "poor")]
    sys_judged = [i for i in decided if i["system"] != "abstain"]
    hard = [i for i in items if i["consensus"] in ("contested", "insufficient")]
    abstained = [i for i in items if i["system"] == "abstain"]
    return {
        "false_blame": _rate(sum(i["system"] == "poor" for i in judged_acc), sum(i["system"] != "abstain" for i in judged_acc)),
        "missed_problem": _rate(sum(i["system"] == "acceptable" for i in judged_poor), sum(i["system"] != "abstain" for i in judged_poor)),
        "positive_recognition": _rate(sum(i["system"] == "acceptable" for i in good), len(good)),
        "coverage": _rate(len(sys_judged), len(decided)),
        "accuracy_when_judging": _rate(sum(i["system"] == i["consensus"] for i in sys_judged), len(sys_judged)),
        "kappa_vs_consensus": _kappa([(i["system"], i["consensus"]) for i in sys_judged]),
        "abstention_on_expert_hard_items": _rate(sum(i["system"] == "abstain" for i in hard), len(hard)),
        "expert_hard_share_among_abstentions": _rate(sum(i["consensus"] in ("contested", "insufficient") for i in abstained),
                                                     len(abstained)),
    }


def _bootstrap(items: list[dict], key: str, reps: int = 500, seed: int = 0) -> list[float] | None:
    cases = sorted({i["review_id"] for i in items})
    if len(cases) < 3:
        return None
    rng = random.Random(seed)
    by = defaultdict(list)
    for i in items:
        by[i["review_id"]].append(i)
    vals = []
    for _ in range(reps):
        sample = [i for c in rng.choices(cases, k=len(cases)) for i in by[c]]
        r = _metrics(sample)[key]["rate"]
        if r is not None:
            vals.append(r)
    if not vals:
        return None
    vals.sort()
    return [round(vals[int(0.025 * (len(vals) - 1))], 3), round(vals[int(0.975 * (len(vals) - 1))], 3)]


def score(study: dict, stage_a: list[dict], stage_b: list[dict] | None = None,
          systems: tuple[str, ...] | None = None) -> dict:
    validate_stage_a(stage_a, study["stage_a_packets"])
    cons = consensus(stage_a)
    priv = study["private_map"]
    names = systems or tuple(sorted({n for p in priv.values() for n in p["systems"]}))
    report: dict[str, Any] = {
        "schema": STUDY_SCHEMA + "/score", "cases_rated": len({r["review_id"] for r in stage_a}),
        "raters": sorted({r["rater_id"] for r in stage_a}),
        "inter_rater_alpha_nominal": krippendorff_alpha_nominal(stage_a),
        "expert_consensus_counts": dict(Counter(v["label"] for v in cons.values())),
        "cannot_judge_share": _rate(sum(v == "cannot_judge" for r in stage_a for v in r["ratings"].values()),
                                    sum(len(r["ratings"]) for r in stage_a)),
        "systems": {},
        "caveat": "Expert consensus is the reference, not ground truth; contested items are reported, never scored as errors.",
    }
    for name in names:
        items = []
        for (rid, a), c in cons.items():
            sysl = priv[rid]["systems"].get(name, {}).get(a, "abstain")
            actual = CHOICE_TO_ACTION.get(priv[rid]["retrospective"].get("observed_action"))
            items.append({"review_id": rid, "action": a, "system": sysl, "consensus": c["label"], "good": c["good"],
                          "stratum": priv[rid]["stratum"], "actual": a == actual})
        overall = _metrics(items)
        overall["false_blame"]["ci95"] = _bootstrap(items, "false_blame")
        overall["missed_problem"]["ci95"] = _bootstrap(items, "missed_problem")
        report["systems"][name] = {
            "overall": overall,
            "actual_choice_only": _metrics([i for i in items if i["actual"]]),
            "by_stratum": {st: _metrics([i for i in items if i["stratum"] == st])
                           for st in sorted({i["stratum"] for i in items})},
        }
    if stage_b:
        report["hindsight"] = hindsight_check(study, stage_a, stage_b)
    return report


def hindsight_check(study: dict, stage_a: list[dict], stage_b: list[dict]) -> dict:
    """Did ratings of the actual action move with the outcome after the reveal?"""
    a_by = {(r["review_id"], r["rater_id"]): r for r in stage_a}
    moved, toward_outcome, n = 0, 0, 0
    views = Counter()
    for r in stage_b:
        a = a_by.get((r["review_id"], r["rater_id"]))
        if not a:
            continue
        actual = CHOICE_TO_ACTION.get(study["private_map"][r["review_id"]]["retrospective"].get("observed_action"))
        before = _dir(a["ratings"].get(actual, "cannot_judge")) if actual else None
        after = _dir(r["actual_action_rating"])
        views[r["outcome_view"]] += 1
        if before is None or after is None:
            continue
        n += 1
        if before != after:
            moved += 1
            good_outcome = (study["private_map"][r["review_id"]]["retrospective"].get("outcome") or {}).get("opponents_regained") is False
            toward_outcome += (after == 1) == good_outcome
    return {"comparable": n, "rating_changed": _rate(moved, n), "changed_in_outcome_direction": _rate(toward_outcome, moved),
            "outcome_views": dict(views),
            "note": "Changes that follow the outcome suggest hindsight bias; Stage A ratings remain the reference."}


SYSTEM_ADAPTERS: dict[str, Callable[[dict], dict[str, str]]] = {
    "action_rationale_v0": rationale_labels,
    "action_rationale_v0_evidence_only": rationale_evidence_only_labels,
    "decision_state_v1": decision_state_v1_labels,
    "tactical_options_v0": tactical_options_v0_labels,
}


def summarise_rationale(r: dict) -> dict:
    return {"judgment": r.get("judgment"), "supported": r.get("supported"), "conditional": r.get("conditional"),
            "contested": r.get("contested"), "refuted": r.get("refuted"),
            "decisive": [d["condition"] for d in r.get("decisive_information", [])]}


def _nan_safe(x: Any) -> Any:
    return None if isinstance(x, float) and math.isnan(x) else x

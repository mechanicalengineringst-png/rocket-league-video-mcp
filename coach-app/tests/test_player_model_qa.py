"""Player model and natural-question answering (Round 5, checkpoint 4). Synthetic fixtures only."""
from __future__ import annotations

from coach_app.coaching_qa import answer_natural, route_question, validate_answer, build_packet
from coach_app.player_model import Observation, build_profile, practice_priority, shrunk_rate
from coach_app.tactical_analysis import Alternative, Finding, Statement


def obs(pid, match, verdict, choice="challenge", contest=False, cover=False, situation="defender_decision"):
    return Observation(pid, match, situation, verdict, choice, {"contest_in_time": contest, "teammate_can_cover": cover})


def population():
    """Three other players: mostly sound. 'me' over 4 matches: 10 late uncovered challenges flagged."""
    out = []
    for pid in ("p2", "p3", "p4"):
        for m in range(4):
            out += [obs(pid, f"m{m}", "reinforce", "shadow"), obs(pid, f"m{m}", "reinforce", "challenge", True, True),
                    obs(pid, f"m{m}", "tradeoff", "shadow", True, True)]
    for m in range(4):
        out += [obs("me", f"m{m}", "risk_hypothesis"), obs("me", f"m{m}", "risk_hypothesis"),
                obs("me", f"m{m}", "reinforce", "challenge", True, True)]
    return out


def test_small_samples_are_insufficient_however_extreme():
    r = shrunk_rate("x", 3, 3, 1, 0.2)
    assert r.status == "insufficient" and r.mean < 1.0


def test_repeated_flags_across_matches_become_a_pattern_with_evidence():
    prof = build_profile("me", population())
    dc = prof["decision_consistency"]["defender_decision"]
    assert dc["status"] == "above_pool" and dc["k"] == 8 and dc["n"] == 12 and dc["matches"] == 4
    pri = practice_priority(prof)
    assert pri and pri[0]["situation"] == "defender_decision" and "8 of 12" in pri[0]["evidence"]
    assert any("improve" in n for n in prof["notes"])


def test_preference_is_reported_separately_from_quality():
    prof = build_profile("me", population())
    pref = prof["preferences"]["challenges_as_first_defender"]
    assert pref["k"] == 12 and pref["n"] == 12          # always challenges: a tendency, not a verdict
    assert "Chooses" in pref["label"]


def test_other_players_have_no_pattern():
    prof = build_profile("p2", population())
    assert prof["patterns"] == [] and practice_priority(prof) == []


def test_execution_is_kept_apart_from_decisions():
    ex = {"me": [("m0", 9, 20), ("m1", 8, 20), ("m2", 9, 20)], "p2": [("m0", 1, 30), ("m1", 1, 30), ("m2", 2, 30)]}
    prof = build_profile("me", population(), ex)
    assert prof["execution"]["whiff_rate"]["status"] == "above_pool"
    assert {p["kind"] for p in prof["patterns"]} == {"decision", "execution"}


# ---------- natural questions ----------

def finding(verdict="reinforce", headline="Held back when a challenge would have been late or uncovered"):
    return Finding("d1", 10.0, "defender_decision", headline, verdict,
                   [Statement("derived", "Earliest feasible touch at t0: the ball carrier 0.40 s, this defender 1.30 s.", ["focus"]),
                    Statement("derived", "The teammate could be goal-side in 2.73 s.", ["mate"])],
                   [Alternative("challenge now", "implausible", "Arrival order or timing does not support a contest.")],
                   [], ["Whether the challenge would be won."], "shadow",
                   factors={"contest_in_time": False, "teammate_can_cover": False})


def test_router_maps_the_six_product_questions():
    assert route_question("Why was that challenge bad?") == ("why_flagged", True)
    assert route_question("What could I have done differently?")[0] == "alternative_feasibility"
    assert route_question("Was my teammate actually covered?")[0] == "teammate_actions"
    assert route_question("Would a higher-ranked player necessarily choose differently?")[0] == "higher_rank_comparison"
    assert route_question("Is this a recurring problem for me?")[0] == "recurring_patterns"
    assert route_question("What should I practice first?")[0] == "practice_priority"
    assert route_question("What's the weather?") == (None, False)


def test_false_premise_is_corrected_with_a_citation():
    out = answer_natural("Why was that challenge bad?", finding())
    assert out["premise_correction"]["text"].startswith("The engine did not judge this as bad")
    assert out["premise_correction"]["cites"]


def test_no_premise_correction_when_the_engine_did_flag_it():
    out = answer_natural("Why was that challenge bad?", finding("risk_hypothesis", "Late challenge with no cover behind"))
    assert "premise_correction" not in out


def test_higher_rank_question_admits_there_is_no_reference_data():
    out = answer_natural("Would a higher-ranked player necessarily choose differently?", finding())
    texts = " ".join(s["text"] for s in out["answer"]["sentences"])
    assert "not established" in texts and "Different successful styles" in texts


def test_practice_question_without_a_pattern_says_so():
    prof = build_profile("p2", population())
    out = answer_natural("What should I practice first?", finding(), profile=prof)
    assert "No pattern is established yet" in out["answer"]["sentences"][0]["text"]


def test_practice_and_recurring_answers_pass_the_validator():
    prof = build_profile("me", population())
    for q in ("What should I practice first?", "Is this a recurring problem for me?"):
        out = answer_natural(q, finding("risk_hypothesis"), profile=prof)
        p = build_packet(finding("risk_hypothesis"), out["routed_to"], q, profile=prof)
        assert validate_answer(out["answer"], p) == []


def test_invented_opinion_from_a_model_is_rejected():
    bad = {"sentences": [{"text": "A GC player would definitely have challenged here.", "cites": ["E1"]}]}
    out = answer_natural("Would a higher-ranked player necessarily choose differently?", finding(), model_answer=bad)
    assert out["answer"]["answerer"] == "deterministic"
    problems = " ".join(out["rejected_model_answer"]["problems"])
    assert "comparison with other players" in problems and "certainty" in problems

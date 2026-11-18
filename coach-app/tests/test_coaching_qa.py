"""Evidence-bound Q&A contract (Round 4, Phase 3). Synthetic fixtures only.

The "model answers" below are hand-written stand-ins for what a language model
might return. No model is called anywhere in these tests.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from coach_app.coaching_qa import QUESTION_TYPES, answer, build_packet, recurring_patterns, validate_answer, what_would_change
from coach_app.main import app
from coach_app.tactical_analysis import assess_challenge, assess_shot, read_state
from tests.test_tactical_analysis import EXAMPLE_A, ball, car, snapshot

EXAMPLE_B_CARS = {"b1": car(-2600, 4300, vy=1500, boost=12), "b2": car(-800, 1200, boost=40),
                  "o1": car(-2900, 4900, boost=50), "o2": car(500, 3800, boost=70)}


def example_b():
    return assess_challenge(read_state(snapshot(EXAMPLE_B_CARS, ball(-2800, 4900, z=900)), 10.0, "b1"), "b-b1")


def example_a():
    return assess_shot(read_state(snapshot(**EXAMPLE_A), 10.0, "b1"), "a-b1", "no_shot")


def first(packet, kind):
    return next(i for i in packet.items if i.kind == kind)


# ---------- the deterministic answer always satisfies its own contract ----------

def test_deterministic_answers_pass_validation_for_every_question_type():
    for f in (example_a(), example_b()):
        for q in QUESTION_TYPES:
            p = build_packet(f, q, history=[f])
            a = answer(f, q)["answer"]
            assert validate_answer(a, p) == [], (f.case_id, q)
            assert a["answerer"] == "deterministic"


def test_packets_only_carry_items_relevant_to_the_question():
    f = example_b()
    mate = build_packet(f, "teammate_actions")
    assert mate.items and all("teammate" in i.tags or "teammate" in i.text.lower() for i in mate.items)
    alts = build_packet(f, "alternative_feasibility")
    assert any(i.kind == "alternative" and "shadow" in i.text for i in alts.items)
    assert all(i.kind != "retrospective" for i in alts.items)


# ---------- invented facts are rejected ----------

def test_model_answer_with_invented_number_is_rejected_and_replaced():
    f = example_b()
    p = build_packet(f, "why_flagged")
    fact = first(p, "fact")
    bad = {"sentences": [{"text": "The ball was 7777 uu from goal and the challenger had 99 boost.", "cites": [fact.id]}]}
    out = answer(f, "why_flagged", model_answer=bad)
    assert out["answer"]["answerer"] == "deterministic"
    assert any("numbers not in its cited evidence" in x for x in out["rejected_model_answer"]["problems"])


def test_uncited_or_unknown_citations_are_rejected():
    p = build_packet(example_b(), "why_flagged")
    assert validate_answer({"sentences": [{"text": "Your teammate was isolated.", "cites": []}]}, p)
    assert validate_answer({"sentences": [{"text": "Your teammate was isolated.", "cites": ["E999"]}]}, p)


def test_intent_blame_and_probability_language_is_rejected():
    p = build_packet(example_b(), "why_flagged")
    i = first(p, "interpretation").id
    for text in ("You wanted to win the ball back.", "This was a mistake.",
                 "The challenge had a 30% chance of working.", "The scoring probability was low."):
        assert validate_answer({"sentences": [{"text": text, "cites": [i]}]}, p), text


def test_later_events_must_be_worded_as_later():
    f = example_a()
    p = build_packet(f, "why_flagged")
    r = first(p, "retrospective").id
    assert validate_answer({"sentences": [{"text": "No shot was taken.", "cites": [r]}]}, p)
    assert validate_answer({"sentences": [{"text": "Afterwards, no shot was taken.", "cites": [r]}]}, p) == []


def test_not_established_items_cannot_be_asserted():
    f = example_a()
    p = build_packet(f, "why_flagged")
    i = first(p, "derived").id
    bad = {"sentences": [{"text": "Whether the player saw the lane: they did.", "cites": [i]}]}
    assert any("not established" in x for x in validate_answer(bad, p))


def test_a_faithful_model_answer_is_accepted():
    f = example_b()
    p = build_packet(f, "why_flagged")
    interp = [i for i in p.items if i.kind == "interpretation"]
    good = {"sentences": [{"text": "The ball was in the opponent's corner, so a contact tends to go to the wall.",
                           "cites": [interp[0].id]},
                          {"text": "If the challenge is lost, your teammate may have to defend two attackers.",
                           "cites": [interp[1].id]}]}
    out = answer(f, "why_flagged", model_answer=good)
    assert out["answer"]["answerer"] == "model" and out["answer"]["validated"] is True


# ---------- what would change, and patterns ----------

def test_what_would_change_flips_factors_through_the_real_rule():
    lines = what_would_change(example_b())
    assert any("costly recovery" in l and "tradeoff" in l for l in lines)
    unknown_boost = dict(EXAMPLE_B_CARS, b1=car(-2600, 4300, boost=None))
    f = assess_challenge(read_state(snapshot(unknown_boost, ball(-2800, 4900, z=900)), 10.0, "b1"), "u")
    assert any("is unknown; if it were True, the verdict would be risk_hypothesis" in l for l in what_would_change(f))


def test_patterns_need_three_occurrences_and_report_denominators():
    one = recurring_patterns([example_b()])
    assert any("not a pattern" in l for l in one)
    three = recurring_patterns([example_b(), example_b(), example_b(), example_a()])
    assert any("risk_hypothesis in 3 of 3" in l for l in three)
    assert any("'costly recovery' was present in 3 of 3" in l for l in three)


# ---------- endpoint ----------

def test_coach_question_endpoint_answers_from_the_packet():
    from tests.test_causal_integrity import challenge_payload
    client = TestClient(app)
    payload = challenge_payload()
    cases = client.post("/api/decision-cases", json={"replay": payload, "analyze": True, "player_id": "b1"}).json()["cases"]
    cid = next(c["decision_case_id"] for c in cases if c["situation_type"] == "first_man_challenge")
    r = client.post("/api/coach-question", json={"replay": payload, "player_id": "b1", "case_id": cid,
                                                  "question_type": "what_would_change"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"]["answerer"] == "deterministic" and body["packet"]["case_id"] == cid
    missing = client.post("/api/coach-question", json={"replay": payload, "player_id": "b1", "case_id": "nope",
                                                        "question_type": "why_flagged"})
    assert missing.status_code == 404
    wrong = client.post("/api/coach-question", json={"replay": payload, "player_id": "b1", "case_id": cid,
                                                      "question_type": "make_something_up"})
    assert wrong.status_code == 422

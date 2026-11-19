# CoachingReviewV1: the one coaching contract for the viewer side panel

Audience: Antigravity (viewer) and ChatGPT (integration/tests). Owner: Claude (coaching backend).
Status: experimental, **not expert-validated**. Branch `feature/round15-coaching-quality-recovery-20261119`.

This replaces, for the default review, the stack of coaching panels below the viewer:
- the CoachReviewBundleV0 evidence lessons;
- the client "review moments" heuristics;
- the V1/V2 experimental reports;
- earlier-cause hypotheses.

It is a projection of the existing pipeline (situation discovery → Round 12 ledger with Round 13 adjustments →
validated Stage A finding → movement label → outcome). It adds no new model and no new tactical rules.

## Call

```
POST /api/coach/review            Content-Type: application/json
{ "replay": <decoded payload from POST /api/replays>, "player_id": "<selected player id>", "max_moments": 5 }
```

| Request | Behaviour |
|---|---|
| default (whole match) | at most 5 moments, chronological; mean 23 s, max 48 s per player on the 15-replay cohort (call once per player after upload, show a progress state; cache the result) |
| `"t0": <seconds>` (single moment) | `mode: "single_moment"`; returns `status: "ok"` with one moment, or `status: "abstain"` with `abstention_reason` |
| unknown player / not 2v2 | HTTP 422 |

Discovery: `GET /api/coach/capabilities` → `coaching_review: "CoachingReviewV1"`, `coaching_review_endpoint: "/api/coach/review"`.

## Response (stable fields; anything else is optional detail)

```jsonc
{
  "schema": "CoachingReviewV1", "experimental": true, "expert_validated": false,
  "moments": [{
    "id": "M2",
    "category": "good_decision | possible_mistake | tradeoff | possible_missed_opportunity",
    "category_label": "Possible mistake (unconfirmed)",          // show verbatim
    "t0": 51.5949,                                              // exact recorded frame time (replay clock)
    "clip": { "start": 47.595, "decision": 51.5949, "end": 54.595 },  // inside live play: never before the
                                                                // last kickoff, never past the next goal
    "headline": "0:51.6 Loose ball in transition",              // <= 90 chars
    "situation": "You had 66 boost; ...",                       // decision-time facts with numbers, <= 260 chars
    "your_choice": { "label": "Challenge now", "basis": "movement_label ..." },
    "assessment": "You chose to ..., but the read argued against it (...). Rule-based and unconfirmed.",  // <= 300
    "options": [ { "label": "...", "status_at_t0": "supported|conditional|contested|refuted",
                   "chosen": true, "for": "...|null", "against": "...|null" } ],   // 1-3, each line <= 170
    "uncertainty": [ "Unknown: ...", "Not observable in replay data: ...", "No expert has validated ..." ],
    "evidence": [ { "condition": "...", "status": "...", "reading": "...", "refs": ["E.focus.boost"] } ],  // drawer only
    "numbers": { "boost": { "value": 66, "refs": ["E.focus.boost"] } },                                   // drawer only
    "outcome_after": { "shown_separately": true, "used_in_assessment": false,
                       "touch_sequence": [ { "by": "focus|teammate|opponent", "t_after_s": 0.6 } ],
                       "goal_within_5s": null }
  }],
  "coverage": { "situations_analysed": 17, "abstained": 11, "eligible_by_category": {...}, "abstention_reason": "..." },
  "not_included": [ "habit claims ...", "turning-point attributions and earlier-cause hypotheses ...", "probabilities ..." ]
}
```

## Display rules (what the side panel must do; layout is Antigravity's call)

1. **The replay stays visible.** The panel lists the moments (`headline` + `category_label`) beside the viewer, not below it.
2. **Selecting a moment** seeks to `clip.start`, plays to `clip.decision`, and pauses. Show `situation`, `your_choice.label`, `assessment` and `options`.
3. **The outcome is a separate, user-initiated reveal.** "What happened next" plays `clip.decision → clip.end` and shows `outcome_after`. Never colour or re-rank the assessment by the outcome.
4. **Show `uncertainty` in full;** it is at most three short lines. Put `evidence` and `numbers` in a collapsed drawer.
5. **Never present `possible_mistake` or `possible_missed_opportunity` as "Mistake".** Show `category_label` verbatim.
6. **Zero moments is a valid answer.** Show `coverage.abstention_reason` instead of filler.

## Basis of every field (what is measured, estimated, heuristic)

| Field | Basis |
|---|---|
| `t0`, `clip`, `outcome_after` | **Replay measurement**: decoded frames and touch/goal events |
| `situation` numbers | **Replay measurement** (boost, positions) plus **kinematic estimate** (arrival and cover times: model estimates with a 0.30–0.55 s error band) |
| `category`, `assessment`, option `status_at_t0`, `for`/`against` | **Rule heuristic** (Round 12 condition ledger with Round 13 adjustments). Not statistical, not model-generated, not expert-validated |
| `your_choice` | **Movement label** from the next 2.5 s (83% agreement with an independent classifier in Round 13; not intent) |
| anything statistical or LLM | **None.** The review never calls a model and contains no probabilities |

## Guarantees enforced by tests (`tests/test_round15_review.py`)

**Clips and wording:**
- At most 5 moments; `t0` is a recorded frame time; the clip lies in live play.
- Each moment has at least 2 replay-specific numbers, all traced to evidence. No two moments share an assessment template.
- No habit, causal or probability wording.

**Integrity:**
- Changing everything after the observation window (ball path, a fake goal) leaves `category`, `situation`, `assessment`, `options` and `uncertainty` unchanged.
- A missing car means no moment or an explicit abstention.

**Fairness:**
- Good restraint is not criticised even when a goal follows.
- An uncovered challenge is not praised even when it works.
- Covered aggression is recognised; holding back there is at most a *possible missed opportunity*.
- An ambiguous 50/50 is not a mistake.
- **A mistake requires a risk present at t0** (no cover, a live threat, a double commit, no room to delay). The absence of a modelled reason is not enough.
- Aerial/wall play abstains.

**Size:**
- Payload under 30 KB; each card's visible text at most 1,200 characters.

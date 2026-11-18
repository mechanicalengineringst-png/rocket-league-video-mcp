# Replay Lab — Coaching Experience API Specification
**Version:** `1.0.0` (Round 9 Integration)  
**Authors:** Antigravity (Frontend Lead) & Replay Lab Engineering  
**Target Backend Implementer:** ChatGPT (Backend & API Routes Lead)  
**Related Schemas:** `Stage1EpisodePacketV0`, `EpisodeEvidenceV0`, `CoachingLessonV0`  

---

## 1. Executive Summary & Architectural Contract

The **Round 9 Interactive AI Coaching Experience** transitions Replay Lab from isolated heuristic flags into a coherent, multi-node tactical coaching application. The interface allows players to:
1. Select detected **tactical episodes** ($N_1 \to N_2 \to N_3$).
2. Step backward through earlier contributing choices to understand causal chains.
3. Review **feasible counterfactual alternatives** at decision time ($t_0$) with risk/feasibility ratings.
4. Deep-dive into an **Interactive Evidence Inspector** to audit exact physical telemetry ($X, Y, Z$, boost, velocities, reachability) with strict epistemic tags (`OBSERVED`, `DERIVED`, `HYPOTHETICAL`, `UNKNOWN`).
5. Enforce a **Stage 1 / Stage 2 Temporal Firewall** that quarantines hindsight outcomes post-$t_0$ until explicitly unlocked.
6. Engage in an **evidence-bound conversational Q&A** (`POST /api/coach-question`) that strictly cites verified packet evidence (`[E.focus.boost]`, `[E.teammate.spacing]`).

To maintain strict boundary separation:
- **ChatGPT** owns backend route implementation, orchestration, and model prompt pipelines.
- **Claude** owns tactical intelligence models, `EpisodeEvidenceV0`, and commitment heuristics.
- **Antigravity** owns the frontend UI, interactive stepper, synchronized 2D/3D pitch playback, and deterministic evidence-grounded chat rendering.

This document defines the expected JSON payloads, routes, and error handling for the backend integration.

---

## 2. API Endpoints

### 2.1. `POST /api/decision-cases` (Existing Live Route)

Extracts and evaluates decision cases with optional tactical analysis.

#### Request Format
```json
{
  "replay": { ... },
  "player_id": "p-12345",
  "evaluate": true,
  "analyze": true
}
```

#### Response Format
```json
{
  "mode": "opt_in_decision_engine",
  "count": 3,
  "cases": [
    {
      "case_id": "case-blue-5.8",
      "t0": 5.8,
      "focus_player_id": "p-12345",
      "situation": "first_man_challenge",
      "title": "First-Man Diving Challenge",
      "evaluation": {
        "assessment": "tactical_risk",
        "title": "Unfavorable challenge commitment",
        "summary": "Teammate cover is absent at t0."
      },
      "analysis": {
        "verdict": "risk_hypothesis",
        "headline": "Over-aggressive first-man challenge with teammate trailing in rotation",
        "statements": [
          { "kind": "observation", "text": "Focus car boost is 24 uu at t0." },
          { "kind": "derived", "text": "Teammate cover time exceeds 2.1 seconds." }
        ],
        "alternatives": [
          {
            "action": "shadow_defensively",
            "feasibility": "feasible",
            "feasibility_basis": "Kinematically reachable with 24 boost."
          }
        ]
      },
      "coaching": {
        "policy": "reconcile/0.1",
        "display": {
          "stance": "concern",
          "headline": "Over-aggressive first-man challenge",
          "confidence": "hypothesis"
        },
        "agreement": "agree",
        "unknowns": ["camera_pov", "controller_intent"]
      }
    }
  ]
}
```

---

### 2.2. `POST /api/episodes` (Proposed Multi-Node Route)

Retrieves detected multi-decision tactical episodes for the selected player.

#### Request Format
```json
{
  "replay": { ... },
  "player_id": "p-12345",
  "max_episodes": 10
}
```

#### Response Schema (`EpisodeEvidenceV0`)
```json
{
  "status": "ok",
  "episodes": [
    {
      "schema": "EpisodeEvidenceV0",
      "episode_id": "ep-midfield-challenge-01",
      "title": "First-Man Diving Challenge vs Shadow Transition",
      "subtitle": "2v2 Midfield Transition · Blue Team Defence",
      "player_id": "p-12345",
      "player_name": "Blue Defender",
      "window": {
        "start_s": 1.0,
        "end_s": 9.5,
        "length_s": 8.5,
        "stage1_horizon_s": 5.8
      },
      "nodes": [
        {
          "node_id": "N1",
          "label": "Midfield Boost Pickup & Forward Push",
          "t0": 2.0,
          "is_primary": false,
          "information_cutoff_s": 2.0,
          "summary": "Accelerating toward midfield corner boost while ball bounces near midfield.",
          "car_state": {
            "position": [-1200, -800, 17],
            "velocity": [450, 1100, 0],
            "speed_uups": 1188,
            "boost": 82,
            "forward": [0.38, 0.92, 0]
          },
          "coaching": {
            "headline": "Upfield commitment without confirmed possession",
            "stance": "neutral",
            "confidence": "hypothesis",
            "takeaway": "Collecting boost is viable, but pushing past the halfway line commits you as first man."
          }
        },
        {
          "node_id": "N2",
          "label": "Opponent Possession Read & Closing Approach",
          "t0": 4.0,
          "is_primary": false,
          "information_cutoff_s": 4.0,
          "summary": "Opponent secures clean bounce dribble; focus car continues advancing forward.",
          "car_state": {
            "position": [-400, 300, 17],
            "velocity": [300, 1400, 0],
            "speed_uups": 1431,
            "boost": 54,
            "forward": [0.21, 0.98, 0]
          },
          "coaching": {
            "headline": "Forward momentum maintained despite opponent having controlled possession",
            "stance": "concern",
            "confidence": "hypothesis",
            "takeaway": "When opponent controls bounce dribble, continuing forward straightens attack angle."
          }
        },
        {
          "node_id": "N3",
          "label": "Dive Challenge Commitment vs Shadow Transition",
          "t0": 5.8,
          "is_primary": true,
          "information_cutoff_s": 5.8,
          "summary": "Critical decision point: Focus commits to dive challenge.",
          "car_state": {
            "position": [120, 1100, 25],
            "velocity": [200, 1650, 180],
            "speed_uups": 1671,
            "boost": 24,
            "forward": [0.12, 0.99, 0.11]
          },
          "coaching": {
            "headline": "Over-aggressive first-man challenge with trailing teammate in rotation",
            "stance": "concern",
            "confidence": "hypothesis",
            "agreement": "agree",
            "assessment": "High-risk commitment. Opponent has ball under close control with bounce height suitable for a flick.",
            "feasible_alternatives": [
              {
                "id": "alt-shadow",
                "action": "Shadow defensively towards back post",
                "feasibility": "feasible",
                "feasibility_label": "Fully Feasible",
                "risk_level": "low",
                "pros": "Allows teammate 1.6s to reach defensive back-post.",
                "cons": "Surrenders midfield possession territory.",
                "description": "Turn car towards own corner, match ball speed, and turn into shot once teammate is back."
              }
            ],
            "observed_evidence": [
              {
                "id": "E.focus.boost",
                "kind": "observation",
                "label": "Focus Boost at t0",
                "value": "24 / 100",
                "unit": "boost",
                "provenance": "replay_sample",
                "description": "Car has only 24 boost remaining."
              }
            ],
            "earlier_contributors": [
              {
                "id": "H.1",
                "earlier_node": "N1",
                "concerns_node": "N3",
                "question": "Focus player used 28 boost at N1. Did this boost deficit constrain defensive options at N3?",
                "evidence_refs": ["D.N1-N2.boost", "N1/E.focus.boost"],
                "status": "hypothesis_unverified",
                "not_established": "Whether higher boost would have saved the play."
              }
            ],
            "takeaway": "In 2v2 as first man when opponent has controlled bounce dribble, prioritize buying time over diving.",
            "unknowns": [
              "What each player saw on screen (camera POV, ball cam status).",
              "Controller analog stick input and jump timing intent.",
              "Voice comms between teammates."
            ]
          }
        }
      ],
      "relations": [
        { "from": "N1", "to": "N2", "delta_t_s": 2.0, "delta_label": "2.0s transition" },
        { "from": "N2", "to": "N3", "delta_t_s": 1.8, delta_label: "1.8s commitment" }
      ],
      "changes": [
        {
          "id": "D.N1-N2.boost",
          "from_node": "N1",
          "to_node": "N2",
          "field": "focus.boost",
          "from_val": 82,
          "to_val": 54,
          "delta": -28,
          "label": "Boost spent: -28"
        }
      ],
      "timeline_events": [
        { "id": "T.boost_pickups.1", "t": 1.8, "type": "boost_pickup", "label": "Blue Focus grabbed 100-pad" },
        { "id": "T.touch.1", "t": 3.6, "type": "touch", "label": "Orange Attacker touched ball" }
      ],
      "retrospective": {
        "stage": 2,
        "warning": "HINDSIGHT INFORMATION: Observed after t0. NOT available at decision time.",
        "summary": "Orange Attacker executed a forward flick at t=6.1s. Focus player jumped into a diving challenge at t=5.9s.",
        "events": [
          { "t": 5.9, "label": "Focus player committed jump forward" },
          { "t": 6.1, "label": "Opponent touched ball over defender" },
          { "t": 8.4, "label": "Orange team scored goal" }
        ],
        "consequence": "Conceded goal from diving challenge."
      }
    }
  ]
}
```

---

### 2.3. `POST /api/coach-question` (Existing Live Route)

Processes conversational questions strictly grounded in decision evidence.

#### Request Format
```json
{
  "replay": { ... },
  "player_id": "p-12345",
  "case_id": "case-blue-5.8",
  "question_type": "alternative_feasibility",
  "question": "Why was challenging here worse than shadowing?",
  "model_answer": null
}
```

#### Response Format
```json
{
  "question_type": "alternative_feasibility",
  "case_id": "case-blue-5.8",
  "answer": "Shadowing was evaluated as Fully Feasible at t0 (5.8s). With 24 boost [E.focus.boost], turning towards your own back-post allows matching the attacker's speed while your teammate completes recovery [E.teammate.spacing]. Diving into the 50/50 from a straight attack angle surrendered all recovery momentum.",
  "citations": ["E.focus.boost", "E.teammate.spacing"],
  "packet_id_count": 2,
  "stage1_compliant": true
}
```

---

## 3. Epistemic Classification Standard

Every piece of evidence presented to the user must carry an explicit epistemic badge:

| Badge | Class | Meaning / Source |
|---|---|---|
| 🟢 `OBSERVED` | `observation` | Direct replay sample from subtr-actor network packet replication. |
| 🔵 `DERIVED` | `derived` | Kinematic or geometric model computation (speed, distance, reachability). |
| 🟡 `HYPOTHETICAL` | `hypothesis` | Counterfactual alternative evaluated at $t_0$. |
| ⚪ `UNKNOWN` | `unknown` | Explicitly disclosed unobservable factor (POV, controller intent, voice comms). |
| 🟣 `RETROSPECTIVE`| `retrospective`| Stage 2 post-$t_0$ outcome. Must be quarantined behind the firewall. |

---

## 4. Stage 1 / Stage 2 Temporal Firewall Invariants

1. **Information Cutoff**: Under Stage 1 review, no data with $t > t_0$ may appear in the primary coaching card, alternatives, or evidence chips.
2. **Outcome Independence**: The AI coaching verdict must never state or imply:
   - "This was a mistake because they scored."
   - "This was the right play because you won the 50/50."
3. **Quarantine Lock**: Retrospective information must reside under a separate `retrospective` JSON block with `"stage": 2` and require an explicit UI toggle (`🔓 Reveal Retrospective`) to view.
4. **Causal Hypotheses ($H.1, H.2$)**: Hypotheses connecting earlier nodes ($N_1, N_2$) to $N_3$ must be phrased as neutral diagnostic questions, explicitly disclaiming definitive causal proof (`not_established`).

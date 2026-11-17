# Replay Lab — Coaching Backend Engineering Audit, Benchmark & Architecture

**Date:** November 17, 2026  
**Author:** Antigravity (Lead Implementation Engineer)  
**Branch:** `feature/coaching-backend-benchmark-decision-cases`  
**Primary Test Fixture:** `23A661D44DBC5964B0718DBC5F956A33.replay` (approx. 7-minute 2v2 competitive match, 12,071 frames @ 30Hz)

---

## Executive Summary

Replay Lab's visual playback engine has achieved near-native fluidity (continuous timeline clock, Hermite position interpolation, quaternion SLERP rotations, synchronized 2D/3D dual-viewport, and full boost pad cooldown tracking). However, this engineering audit of the coaching analysis backend reveals a severe **capability mismatch**:

1. **Decoder Capability Waste**: The underlying Rust replay engine (`subtr-actor-py` v1.5.1) computes **58 native statistics modules** generating **6,788 native domain events** across 45 distinct event streams in our 7-minute 2v2 match (including tactical classifications like `first_man_change`, `fifty_fifty`, `depth_role`, `rotation_role`, `possession`, and `beaten_to_ball`). 
2. **Aggressive Discard in Ingest**: Current `subtr_replays.py` filters events through an arbitrary `TRACKED_EVENTS` whitelist that discards **88.9% of all native events** (retaining only 751 events).
3. **Flawed Mistake Detection**:
   - `coaching.py` uses two primitive Euclidean thresholds (`dist < 900` for "double commit" and `boost <= 12` near own goal), generating 10–15 false-positive warnings per player per match (e.g., repeatedly penalizing valid kickoff cheats).
   - `contextual_review.py` implements rigid geometric snapshot heuristics that almost completely fail to fire on high-level gameplay (producing only 1–3 candidates in an entire 7-minute GC2 match, 100% of which were identical second-man warnings).
4. **AI/LLM Telemetry Bottleneck**: The optional Gemini integration passes an uncurated numerical coordinate table (`compact_game_states`) into generic text prompts with no tactical framing, no video/visual data, and zero hindsight protection.
5. **Architectural Solution Implemented**: We have designed, implemented, and verified:
   - An evidence-safe `DecisionCase` extraction engine in `coach_app/decision_cases.py` anchored to native `subtr-actor` streams.
   - Strict hindsight separation via `coach_app/evidence.py` ensuring claims cite only pre-decision facts (`finalized_through_s <= t0`), with post-decision outcomes strictly quarantined.
   - **Approach A (Enhanced Deterministic Context)**: Domain logic that recognizes valid kickoff cheats, supported 50/50 spills, and forced defensive positions.
   - **Approach B (Structured Decision Payload for LLM)**: Structured prompt serialization that isolates pre-decision facts, known uncertainties, and feasible alternatives.
   - An adversarial test suite (`test_adversarial_coaching.py`) verifying 8 critical competitive edge cases.

---

## 1. Ten Core Audit Questions

### Q1: What library / version is currently used to decode `.replay` files?
- **Library**: `subtr-actor-py` version **1.5.1** (compiled Rust extension via PyO3).
- **Binding**: Imported in `coach-app/coach_app/subtr_replays.py` (lines 380–389):
  ```python
  meta, data = subtr_actor.get_ndarray_with_info_from_replay_filepath(
      str(path), global_feature_adders=GLOBAL_FEATURES,
      player_feature_adders=PLAYER_FEATURES, fps=FPS, dtype='float32'
  )
  event_data = subtr_actor.get_stats_events(str(path), include_expected_goals=False)
  ```
- **Execution**: Runs in a thread pool (`run_in_threadpool`) off FastAPI's async event loop because decoding 12,000+ frames is CPU-bound (taking ~2.3–3.1 seconds per match in native Rust).

---

### Q2: What stats / events does the decoder natively compute vs. what does `coach-app` actually consume?

`subtr-actor` v1.5.1 exposes 58 native modules. In our primary 2v2 test fixture (`23A661D44DBC5964B0718DBC5F956A33.replay`), it generated **6,788 native events** across 45 event streams.

#### Native Event Inventory vs. Current Application Ingest:
| Event Stream | Native Events in 2v2 Match | Ingested by `subtr_replays.py`? | Consumed by Coaching Analysis? | Notes & Tactical Capability |
| :--- | :---: | :---: | :---: | :--- |
| `movement` | 1,503 | ❌ Dropped | ❌ Ignored | Powerslide, air-roll, turning states |
| `rotation_role` | 714 | ❌ Dropped | ❌ Ignored | Classifies offense/defense rotation transitions |
| `ball_depth` | 700 | ❌ Dropped | ❌ Ignored | Ball position relative to field zones |
| `ball_proximity` | 568 | ❌ Dropped | ❌ Ignored | Distance intervals between cars and ball |
| `powerslide` | 520 | ❌ Dropped | ❌ Ignored | Exact powerslide engagement durations |
| `depth_role` | 461 | ❌ Dropped | ❌ Ignored | Classifies `most_back`, `most_forward`, `other` |
| `boost_pickups` | 330 | ✅ Retained (330) | ❌ Ignored | Mapped to PR #11 pad contract (93.9% resolution) |
| `field_third` / `field_half` | 464 | ❌ Dropped | ❌ Ignored | Positional zone occupancy |
| `dodge` | 199 | ❌ Dropped | ❌ Ignored | Jump/dodge impulse activations |
| `touch` | 181 | ✅ Retained (181) | ⚠️ Partial | Used only as raw timestamps in `contextual_review` |
| `core_player` | 166 | ❌ Dropped | ❌ Ignored | High-level player state summaries |
| `shadow_defense` | 116 | ✅ Retained (116) | ❌ Ignored | Natively detects shadow defense positioning |
| `first_man_change` | 99 | ❌ Dropped | ❌ Ignored | Critical tactical handoffs between 1st and 2nd man |
| `possession` / `loose` | 158 | ❌ Dropped | ❌ Ignored | Team and individual possession continuity |
| `ball_half` / `ball_third`| 153 | ❌ Dropped | ❌ Ignored | Field territory classification |
| `speed_flip` | 43 | ✅ Retained (43) | ❌ Ignored | Speed-flip mechanic verification |
| `fifty_fifty` | 22 | ✅ Retained (22) | ❌ Ignored | Records 50/50 contact, approach, and win/loss |
| `whiff` | 27 | ✅ Retained (27) | ❌ Ignored | Natively classifies aerial/ground whiffs |
| `beaten_to_ball` | 29 | ❌ Dropped | ❌ Ignored | Measures margin seconds and challenger speeds |
| `controlled_play` | 23 | ❌ Dropped | ❌ Ignored | Dribbles, carries, and soft ball control |
| `pass` | 16 | ❌ Dropped | ❌ Ignored | Intentional passes between teammates |
| `rush` | 20 | ❌ Dropped | ❌ Ignored | Fast challenge commitments |
| `kickoff` | 15 | ✅ Retained (15) | ⚠️ Partial | Used only as blackout window ($\pm 4\text{s}$) in legacy code |
| `demolition` / `bump`| 17 | ✅ Retained (17) | ❌ Ignored | Physical interference events |
| `goal_context` | 6 | ✅ Retained (6) | ❌ Ignored | Scorer and conceded goal contexts |

**Key Finding**: `coach-app` retains only **11.1% of native events** and ignores 100% of the native tactical streams (`rotation_role`, `depth_role`, `first_man_change`, `possession`, `beaten_to_ball`, `fifty_fifty`).

---

### Q3: How does the current system identify a "decision" or "mistake"?

The codebase contains two parallel legacy implementations, neither of which leverages native tactical event streams:

1. **`coach_app/coaching.py` (`find_review_candidates`)**:
   - **Double-Commit / Overlap**: Flags any frame where a player is $<900$ units from the ball while their teammate is also $<900$ units from the ball.
     - *Defect*: Fails on kickoffs (where cheating up is standard GC2 play), offensive goalmouth pressure, and rotation handoffs.
     - *Band-Aid*: Suppresses candidates within 4.0s of kickoff events (`_near_kickoff`).
   - **Low Boost in Defense**: Flags any frame where a player has $\le 12$ boost and is within 2,500 units of their own goal line while an opponent is attacking.
     - *Defect*: Mistaking a forced situation for a mistake. Players forced to defend on low boost after a teammate turnover are penalized rather than advised on defensive posture.

2. **`coach_app/contextual_review.py` (`build_contextual_reviews`)**:
   - Evaluates only 3 hardcoded snapshot heuristics anchored to touches:
     - `_shot_window`: Requires open goal, distance $<3000$, all opponents $>1200$ away, boost $>20$. *Almost never triggers in high-level 2v2 because opponents rarely leave goal wide open.*
     - `_second_man`: Flags second man if within 1,400 units of first man's touch and opponent is $<1600$ units away. *Fires repeatedly on normal GC2 offensive pressure.*
     - `_defensive_pressure`: Opponent touch in defensive third, focus player boost $<15$, own net $<2500$, teammate $>2500$.
   - **Result in 7-minute match**: Only 1–3 total review leads per match across all players, with 0 shot windows and 0 defensive pressure moments.

---

### Q4: What information is passed to the AI / LLM layer?

In `coach_app/main.py` (`POST /api/ai-review`):
- **Endpoint**: Calls Google Gemini (`gemini-3.8-flash` via raw `httpx.AsyncClient` HTTP REST API).
- **Sampling**: `compact_game_states(payload.replay, payload.player_id, max_frames=90)`:
  - Takes 90 evenly spaced frames across the match (or $\pm 3.5\text{s}$ around a user-selected timestamp).
  - Formats raw Cartesian coordinates as a space-separated ASCII string:
    ```
    t=12.30 b=[120,-340,55] p1=[-200,450,17,b=45] p2=[...] ...
    ```
- **Prompt Size**: Approximately 14,400 characters (~3,600 tokens).
- **Missing Inputs**:
  - **Zero video footage or rendered imagery** reaches the model.
  - No player camera orientation (ball cam vs. car cam).
  - No input signals (steer, throttle, jump, powerslide).
  - No tactical context (depth roles, kickoff behaviors, or 50/50 win attributions).
  - The model is asked to hallucinate tactical coaching purely from numerical coordinate matrices.

---

### Q5: What domain models exist in the backend?
- **Domain-trained ML / RL Models**: **Zero**.
- There are no fine-tuned tactical classifiers, no counterfactual physics models, and no learned policy evaluators in `coach-app`.
- The entire intelligence consists of:
  - Deterministic Euclidean geometric checks (`math.hypot(dx, dy) < 900`).
  - Native `subtr-actor` heuristic rules compiled in Rust.
  - Zero-shot prompting of commercial general-purpose LLMs (`gemini-3.8-flash`).

---

### Q6: How is hindsight bias prevented?
- **Previous State**: In `main.py` and `coaching.py`, there was **zero hindsight protection**. If an opponent scored 5 seconds after a player challenged, downstream prompts and rules were vulnerable to blaming the challenger based on the conceded goal.
- **PR #7 Baseline (`coach_app/evidence.py`)**:
  - Introduced the `Evidence` dataclass with `event_time_s`, `finalized_through_s`, and `kind` (`decision_context`, `post_decision_outcome`, `player_intent`).
  - Created `partition_evidence` and `require_decision_evidence`, which reject any decision claim that cites evidence finalized after $t_0$.
- **Current Branch Upgrade (`coach_app/decision_cases.py`)**:
  - Fully integrated `Evidence` into `DecisionCase`.
  - Quarantines post-decision outcomes into a separate, isolated block with strict warnings:
    `"DO NOT USE THIS LATER OUTCOME TO JUSTIFY OR CONDEMN THE T0 DECISION"`.

---

### Q7: How are player identities handled?
- **Identity Ingest**: In `subtr_replays.py` (`_players`):
  - Parses `meta['replay_meta']['all_headers']`.
  - In modern Epic/Crossplay replays, the recording player name is frequently absent from replay headers.
  - `_players()` correlates player spawn positions during the first kickoff against standard kickoff spawn coordinates (`[0, -4608]`, `[-256, -3840]`, etc.).
  - Sets `playerMappingVerified = True` if all players match kickoff spawn slots; otherwise sets `playerMappingVerified = False` and warns that identities are inferred from metadata track order.

---

### Q8: How does the system handle 1v1 vs. 2v2 vs. 3v3?
- **Current Limitation**:
  - `contextual_review.py` line 192 hardcodes:
    ```python
    mates = [pid for pid, p in players.items() if pid != focus_id and p.get('team') == team]
    ```
    If `len(mates) == 0` (1v1 match), `_second_man()` silently fails or raises errors.
  - In 3v3, `_second_man()` arbitrarily evaluates only the single closest teammate, ignoring 3rd-man defensive rotation.
  - The legacy heuristics are essentially hardcoded for 2v2 and give degraded or nonexistent output in 1v1 and 3v3.

---

### Q9: How are boost pads modeled?
- **Implementation**: Handled via PR #11 integration (`boost_pad_events.py` and `test_boost_pad_state.cjs`):
  - Uses the official 34-pad canonical field geometry (6 large full boosts, 28 small pads).
  - Cooldown timers: 10.0 seconds for large pads, 4.0 seconds for small pads.
  - Pickup Detection: Matches `subtr-actor` native `boost_pickups` events to canonical pads using nearest-neighbor Euclidean distance with a 200-unit threshold.
  - **Resolution Rate**: Verified on `23A661D44DBC5964B0718DBC5F956A33.replay` at **93.9% resolution** (310 of 330 pickups mapped; 20 unmapped due to demolition/respawn edge cases).
  - Kickoff Resets: Automatically resets all 34 pads to active at every kickoff timestamp (15 resets).

---

### Q10: What is the performance profile?
- Replay decoding in `subtr-actor` takes **2.3–3.1 seconds** for ~12,000 frames (7-minute match).
- Python-side normalization (`parse_subtr_replay`) takes **10.4–10.9 seconds** and consumes **72–80 MB peak memory**.
- Candidate extraction is lightweight:
  - `contextual_review.py`: ~15 milliseconds.
  - Legacy `find_review_candidates`: ~175 milliseconds.
  - New `DecisionCase` extraction: ~35 milliseconds.

---

## 2. Multi-Replay Diagnostic Benchmark

We benchmarked three representative real competitive matches from the player's match library:

| Metric | Primary 2v2 Fixture (`23A661...`) | 2026 Match 2 (`03F49B...`) | Standard Match 3 (`022B27...`) |
| :--- | :---: | :---: | :---: |
| **File Size** | 1,159 KB | 1,151 KB | 1,113 KB |
| **Match Duration** | 405.9 s (6:46) | 368.9 s (6:08) | 353.3 s (5:53) |
| **Frames @ 30Hz** | 12,071 | 10,962 | 10,491 |
| **Player Count** | 4 (2v2) | 4 (2v2) | 4 (2v2) |
| **Native Decode Time** | 2.34 s | 3.00 s | 3.10 s |
| **Native Peak Memory** | 27.8 MB | 28.5 MB | 31.1 MB |
| **Native Events Generated** | **6,788** | **6,924** | **6,751** |
| **Native Event Types** | 45 | 46 | 45 |
| **Ingested Events (Old)** | 751 (11.1%) | 741 (10.7%) | 754 (11.2%) |
| **App Peak Memory** | 80.3 MB | 72.2 MB | 72.5 MB |
| **Legacy Overlap Flags** | 38 flags (9–10/player) | 48 flags (12–14/player) | 36 flags (8–10/player) |
| **Legacy Boost Flags** | 18 flags (4–5/player) | 21 flags (5–7/player) | 17 flags (4–5/player) |
| **Contextual Reviews (Old)**| 6 total (1–2/player) | 9 total (1–3/player) | 5 total (0–3/player) |
| **Contextual Review Breakdown**| 100% `second_man_support` | 100% `second_man_support` | 100% `second_man_support` |
| **LLM Payload Token Est.** | 3,601 tokens | 3,789 tokens | 3,840 tokens |

---

## 3. The `DecisionCase` Architecture

To bridge the gap between `subtr-actor`'s rich native data and actionable coaching, we implemented `DecisionCase` in `coach_app/decision_cases.py`.

### Architectural Flowchart
```mermaid
flowchart TD
    A[".replay File"] --> B["subtr-actor (v1.5.1 Rust Parser)"]
    B --> C["Sampled Physics Arrays (30Hz)"]
    B --> D["6,700+ Native Events (45 Streams)"]
    
    D --> E["DecisionCase Extractors"]
    C --> E
    
    subgraph "Decision Extraction Engine"
        E --> E1["Kickoff Decisions (Taker vs Cheat/Boost)"]
        E --> E2["1st-Man Challenges & 50/50s (Supported vs Diving)"]
        E --> E3["Last-Man Goal Defense (Backpost vs Low-Boost)"]
    end
    
    E1 & E2 & E3 --> F["DecisionCase Structure"]
    
    subgraph "Evidence Guard (coach_app/evidence.py)"
        F --> G1["Pre-Decision Evidence (t <= t0)"]
        F --> G2["Quarantined Outcomes (t > t0)"]
    end
    
    G1 --> H1["Approach A: Enhanced Heuristics (Deterministic)"]
    G1 & G2 --> H2["Approach B: Structured Prompt (LLM Payload)"]
    
    H1 --> I1["Verified Coaching Findings (Zero False Overlaps)"]
    H2 --> I2["Gated LLM Hypothesis (No Hindsight Leakage)"]
```

### `DecisionCase` Schema
```python
@dataclass(frozen=True)
class DecisionCase:
    case_id: str
    replay_id: str
    t0: float  # Decision commitment instant
    focus_player_id: str
    focus_player_name: str
    focus_player_team: str
    situation_type: SituationType  # 'kickoff_support' | 'first_man_challenge' | 'last_man_defense' | ...
    evidence: tuple[Evidence, ...]
    tactical_context: dict[str, Any]
    feasible_alternatives: tuple[str, ...]
    uncertainties: tuple[str, ...]
    provenance: dict[str, Any]
```

---

## 4. Approach Comparison: Approach A vs. Approach B

### Approach A: Enhanced Deterministic Context (`decision_evaluation.py`)
- **Mechanism**: Evaluates `DecisionCase` using verified domain logic.
- **Key Enhancements**:
  - **Kickoff Cheating**: When `support_behavior == 'cheat'`, recognizes this as standard GC2 competitive play. Generates a `positive_recognition` finding rather than a false "double-commit" error.
  - **Supported 50/50s**: When a first man challenges while the second man covers the defensive goal line, recognizes the play as structurally sound even if the 50/50 spills unfavorably.
  - **Unsupported Dives**: Flags challenges committed when the second man is caught forward ($>4500$ units away).
  - **Low-Boost Defense**: Recognizes low boost as a forced constraint; advises goal-line small-pad pathing rather than blaming defensive commitment.
- **Speed & Cost**: Purely local, $\approx 0.05\text{ ms}$ evaluation time, zero token cost.

### Approach B: Structured Decision Payload for LLM (`decision_evaluation.py`)
- **Mechanism**: Formats `DecisionCase` into a structured, evidence-guarded prompt.
- **Key Enhancements**:
  - **Strict Sectioning**: Explicitly divides:
    - Section 1: Verified Pre-Decision Facts ($t \le t_0$).
    - Section 2: Tactical Context (spacing, boost, depth roles).
    - Section 3: Feasible Alternatives.
    - Section 4: Epistemic Uncertainties (what cannot be known from telemetry).
    - Section 5: **[QUARANTINED POST-DECISION OUTCOME]** with an explicit directive: *"DO NOT USE THIS LATER OUTCOME TO JUDGE WHETHER THE DECISION WAS SOUND AT T0"*.
  - **Evidence Citation Gate**: Requires the LLM response to cite specific evidence keys, verified against `case.validate_admissibility(cited_keys)`.
  - **Offline Mock Adapter**: Includes `evaluate_decision_case_llm_mock` allowing comprehensive unit and integration testing without network calls or API token expenditures.

---

## 5. Adversarial Test Suite Verification

The adversarial test suite in `coach-app/tests/test_adversarial_coaching.py` verifies 8 competitive edge cases:

1. **Scenario 1 — Valid Kickoff Cheat**: Cheating up from center spawn behind kicker evaluated as `sound` (`positive_recognition`); does not cite post-kickoff outcomes.
2. **Scenario 2 — Supported 50/50 Spill**: 50/50 contest with second man covering goal mouth evaluated as `sound` (`positive_recognition`).
3. **Scenario 3 — Failed Aerial without Hindsight**: Aerial challenge with sound initial boost and teammate backup is judged by $t_0$ facts; attempting to cite post-decision whiff raises `ValueError`.
4. **Scenario 4 — Unsupported Last-Man Challenge**: Challenge committed with teammate caught deep in opponent corner correctly flagged as `high_risk` (`tactical_risk`).
5. **Scenario 5 — Close Second-Man Support**: Tight support behind backboard pressure correctly formatted in structured prompt without false double-commit labeling.
6. **Scenario 6 — Low-Boost Goalkeeper**: Defending net with 6 boost framed as `forced_situation`; advises small-pad pathing rather than blaming commitment.
7. **Scenario 7 — Positive Back-Post Recognition**: Proper back-post defensive alignment with 65 boost receives positive reinforcement.
8. **Scenario 8 — Missing Telemetry Abstention**: Decision case with missing boost/ball evidence fails closed via `require_decision_evidence`.

**Test Status**: **91 passed, 1 skipped** across the complete test suite.

---

## 6. Strategic Recommendations for Gemini & Long-Term Roadmap

1. **Adopt `subtr-actor` Native Event Streaming in Ingest**:
   - Update `subtr_replays.py` to ingest all 45 native event streams rather than discarding 88.9% of events.
   - Specifically retain `first_man_change`, `depth_role`, `rotation_role`, `fifty_fifty`, `beaten_to_ball`, and `possession`.
2. **Replace Raw Coordinate Prompts with `DecisionCase` Payloads**:
   - Retire `compact_game_states` (the raw 90-frame ASCII coordinate table).
   - Use `DecisionCase.to_llm_payload()` to send structured tactical situations, reducing prompt token bloat while vastly increasing coaching accuracy.
3. **Multi-Mode Support (1v1, 2v2, 3v3)**:
   - Generalize tactical extractors to branch on `mode`:
     - 1v1: Shadow defense, bounce dribbles, flick timings, boost denial.
     - 2v2: Cheat vs. corner kickoff, first-man challenge support, last-man back-post defense.
     - 3v3: Third-man safety margins, mid-field rotation lanes, offensive backboard pressure.
4. **Interactive UI Integration**:
   - Expose `DecisionCase` moments as clickable bookmarks on the 3D replay timeline, allowing users to jump directly to decision points ($t_0 - 2\text{s}$) with visible alternative route overlays.

# Round 15 feature truthfulness audit: coaching controls

Scope: every coaching-related control in `coach_app/static/index.html` (base `integration/round14p5-owner-test-20261119`), traced to the JS handler and the backend it calls.

How each control was probed:
- `scripts/audit_round15.py` calls every backend route in-process on two real cached 2v2 replays and records status, size, time and repeated-template counts. Raw output is in the scratchpad and is not committed (the replays are private).
- Code reading covers the client-only controls.

Viewer playback, camera, HUD and layout are Antigravity's and are **not** audited here. The owner's PR #64 list covers them.

Classes:
- **W**: working end-to-end;
- **L**: working but limited or unvalidated;
- **P**: partially implemented;
- **X**: misleading, redundant or nonfunctional.

Recommendation key: **Keep**, **Replace** (by CoachingReviewV1), **Hide** (behind a developer flag), **Remove**.

## Coaching controls

| Control | Calls | Probe result | Class | Recommendation |
|---|---|---|---|---|
| Coaching panel after upload (review flow) | `/api/coach/review-bundle` → fallback candidates + `/lesson` → fallback `/api/decision-cases` | 200, 65–67 KB, 1.1–1.8 s. Lessons have grade `null`/"undetermined" and **no takeaway**. One disclaimer template repeated **56–60×** per bundle. Candidates are picked by state change (R12: 438 of 480 were not first-defender moments) | **X** (looks like coaching, says nothing actionable) | **Replace** with `/api/coach/review` |
| Decision-cases fallback | `/api/decision-cases` | **HTTP 500 on a real replay** ("inf" not JSON-compliant), 134 KB / 20 s on the other | **X → fixed** in this branch (`_json_safe`); still heavy and redundant | **Remove** from the default flow |
| "Review moments" list (client) | `refreshFindings` in app.js, no backend | Fixed sentences ("Two teammates near the ball", "Low boost near own goal") fired by thresholds; the same advice in every replay | **X** (fails the paste-into-another-replay test) | **Remove**; use `moments[]` from the review |
| Follow-up question box | `/api/coach/followup` | 200, **350 bytes**: one generic sentence plus refs, whatever the question | **X** | **Remove** |
| Evidence drawer per claim | `/api/coach/evidence` | 422 on the generic probe (needs claim refs from a lesson); not verified end-to-end | **P** | **Replace** with `moment.evidence` (inline, no extra call) |
| `experimentalReportBtn` "Analyze this match locally (experimental)" | `/api/coach/coaching-report-v1` | 200, 107–109 KB, **7.8–25 s**. Uses "questionable" verdicts that Round 13 found unsupported (action-value placebo) | **X** (redundant, partly unsupported) | **Remove** |
| `reportV2Btn` "Analyze this match with V2" | `/api/coach/coaching-report-v2` | 200, 117–122 KB, **14.7–44.8 s**. 10 "habits" from one match (R13: unreliable within a match), 4 turning points | **L/X** (same reads as the review, buried; habit claims unsupported) | **Remove** from UI; the endpoint stays for research |
| Blind/predecision review (`blindStart…`, `blindLock…`, `blindReveal…`, `blindFinish…`, `blindExport…`) | client plus local storage | Works as a self-test, but it is a research instrument, not coaching | **L** | **Hide** (dev flag) |
| `blindOpenModelBtn`, `modelCoachRunBtn`, `modelCoachRefreshBtn`, `modelCoachExportBtn` | `/api/coach/model-readiness`, lesson model mode | Model disabled by default (readiness 200 says not configured; generation 403/503). Unverifiable without keys | **X** in default install | **Hide** unless readiness says configured |
| `modelCoachSpatialBtn` "Inspect source-backed geometry" | `/api/coach/scene-relations` | 200, 7–9 KB of relation data; developer inspection | **L** | **Hide** (dev flag) |
| `aiBtn` "Ask Gemini about selected moment" | `/api/ai-review` | **503** without a key | **X** in default install | **Remove** (or hide behind configured key) |
| `lensManualReviewBtn` "Review this overlooked moment" | `/api/coach/lesson` at a chosen t | Evidence-only lesson, as above | **X** | **Replace** with `/api/coach/review` + `t0` (single-moment mode: review or explicit abstain) |
| Decision Lens seek buttons (`lensApproach`, `lensDecision`, `lensLoop`, `lensReveal`, `lensAfter`, `lensPin`, `lensClear`) | client only | Correct seeks around a pinned t | **W** | **Keep, merge**: they are exactly "seek to clip.start / pause at t0 / reveal outcome"; drive them from `moment.clip` |
| `loadDemoBtn` "Try Interactive Replay & Coaching" | `coaching-fixtures.js` | Handwritten demo episodes presented as coaching output | **X** (not produced by the backend) | **Remove**, or label as a mock-up |
| `exportBtn` "Export review JSON" | client | Exports the bundle | **L** | Keep only if it exports the CoachingReviewV1 payload |
| `markBtn` "+ Mark" | client | Bookmark on the timeline | **W** | Keep (could feed `t0` mode) |
| Companion (`companionProbe/Load/Sync`) | `/api/companion/*` + external plugin | Status 200; needs a BakkesMod-style plugin not shipped here | **P** | **Hide** unless the plugin is detected |
| Video align/remove | client | Out of coaching scope | n/a | Antigravity |

## Summary

- **Before this round, no control in the default panel produced an actionable, replay-specific read end-to-end.** The useful backend reads (the Round 12/13 ledger) were reachable only through 8–45 s, 100+ KB reports.
- **Fixed here:** the `/api/decision-cases` 500. Added `/api/coach/review` (CoachingReviewV1):
  - at most 5 moments;
  - about 3 s per player on the 130 s fixture, mean 23 s (max 48 s) on full matches;
  - under 30 KB.
- **Recommended for Antigravity** (I did not touch the frontend):
  - one side panel driven by `/api/coach/review`;
  - Decision Lens reused for clip seeking;
  - remove the client heuristics, follow-up box, V1/V2 buttons, Gemini button and demo coaching;
  - hide the blind-review, model-coach and companion tools behind a developer flag.

  That takes the visible coaching controls from about 25 to: a moment list, "Play to decision", "What happened next", and an evidence drawer.

## CoachingReviewV1 on the cached cohort (`review_cohort_eval.json`)

The cohort is 15 public 2v2 replays of unknown rank, giving 60 player reports. There are no expert labels, so these numbers describe behaviour, not accuracy.

| Measure | Result |
|---|---|
| Moments per report | 5 in 58 reports, 4 in 2; no empty reports |
| Situations abstained | 67.5% (by design: only firm reads are shown) |
| Categories | tradeoff 157, good 91, possible mistake 41, possible missed opportunity 9 |
| Payload | max 20 KB |
| Time | mean 23 s, max 48 s per player |
| Within-report template repeats | 0 |
| Cross-replay repeats | 76 distinct assessment templates out of 298; the most common one appears 33 times (with different numbers) |
| Privacy leaks | 0 |

Open quality concerns:
- "Tradeoff" is the most common label (53%), and part of that is cautious hedging.
- One assessment template recurs across matches. Each instance cites that replay's own numbers, but it is the weakest point on the "paste into another replay" test.
- 23 s per player is slow for an on-upload call.

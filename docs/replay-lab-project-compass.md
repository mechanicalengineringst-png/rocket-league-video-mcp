# Replay Lab — Project Compass (read first)

**Status snapshot: 17 November 2026.** **Source of truth for product direction and active work.** Keep this file short and updated after material decisions, tests, and PR changes. It is **not** a transcript archive; exact GitHub code/CI is the authority for implementation claims.

**Detailed historical record:** [Google Drive master handoff](https://docs.google.com/document/d/12OuLwWCDxprVzGSnQVWJ6vvIQ_SujJAOqNn3_FBF-Q0/edit). The older [AI team onboarding](AI_TEAM_ONBOARDING.md) is historical and no longer current. **All new ChatGPT/Claude/Antigravity sessions must read this compass, then check current PR heads, before proposing work.**

**Round 6 multi-agent strategic meeting (Gemini + Claude + Antigravity + ChatGPT):** [Read the synthesized findings, corrected overclaims, and proposed 12-case/native-API evidence gates](REPLAY_LAB_ROUND6_CROSS_AGENT_STRATEGY_REVIEW.md). This memo is PRELIMINARY, not permission to modify the game, train models, upload replays or merge code. Antigravity's docs-only native architecture report is linked there.

**Round 6 independent research (ChatGPT, research-only):** [Initial architecture/evidence report](REPLAY_LAB_ROUND6_INDEPENDENT_RESEARCH.md) and [Deep-dive addendum: replicar v2, human observability, existing viewer options, high-rank data and models](REPLAY_LAB_ROUND6_DEEP_DIVE_ADDENDUM.md). Findings requiring other-agent review: selected-moment Gemini prompt presently samples the whole match rather than its named decision window; a published curated 2v2 replay dataset reports 49,658 matches (actual file quality and rights unverified); existing possession/xG/goal-hazard code might help with grounded tactical features; run small expert-blinded side-by-side tests BEFORE investing in local LLM training. **No architecture chosen or code implemented by this report.**

## 1. Mission: build an exceptional coach, not a replay viewer

Player uploads a **native Rocket League \`.replay\` file**, selects who is being coached, and receives a **few insightful, evidence-grounded, high-skill lessons** about decisions they would not necessarily notice themselves. Show both **excellent** and **questionable** decisions, explain strategic tradeoffs and *feasible alternatives*, allow follow-up questions, and identify meaningful trends across matches.

**Quality bar:** eventually useful to experienced GC/SSL players; not claimed today. Reject simplistic rules ("two teammates near each other = mistake", "lost a 50/50 = bad", "always cover first"). Multiple aggressive or defensive playstyles can be valid. A good decision can fail and a poor decision can succeed. Distinguish observed facts, prediction, hypothetical alternatives, actual post-decision outcome, intent, and uncertain claims.

**Owner's example of required depth (illustration, NOT a measured replay finding):** when challenging an opponent controlling their own backboard, consider their available outplay, teammate's possible 1v2 exposure, boost and recovery cost, whether even a won 50/50 gives valuable possession, opponent's second-man position, and whether shadowing/rotating before contesting would preserve better pressure. Don't just flag a "50/50".

## 2. Visual interfaces serve the coach

- **2D:** clean, small tactical overview with ball, players, nose orientation, optional boost pads and contextual coach alternatives. No permanent paths, ball-height dashed ring, TOUCH callouts, big selected-player halo, pad pickup counts, duplicate clock or debug disclaimer. Selected player marked subtly; individual player boost readable and **unknown != zero**.
- **3D:** actual replay-like view of height, mechanics, touches and cameras. The old geometric renderer was rejected; prioritize usable elevated chase camera and authentic playback.
- **Desktop today:** evaluate **optional official Rocket League Stats API companion** to control the *real native game replay* where installed, while the local coach and 2D map stay in our app. It is not a direct browser renderer; don't assume native game video can be embedded.
- **Standalone/mobile later:** our independent HD 3D renderer remains **mandatory** for phone/offline viewing when the game cannot run. Launching Rocket League is **never required** to use the coach. Native and standalone modes are alternative visual backends, not competing products.

## 3. Coaching design: proposed target, NOT yet deployed

\`.replay\` -> reliable typed telemetry with source times and unknowns -> meaningful decision candidates and t0 commitment -> kinematic/physics feasibility and several tactical choices -> evidence packet and context -> **Gemini API as tool-using reasoning/tutoring layer** (or alternative measured model) -> claim verification / expert calibration -> concise lesson and replay seek -> eventual cross-match profile.

The coach should explore the full strategic situation: possession, challenge timing, first/second man, support, rotations, likely ball destinations, boost economy, pressure, recovery, risks and alternatives. Every model claim must cite source evidence or be visibly marked hypothetical; never use frames after t0 as information known at the decision. Retrospective labels and outcomes are separate. The user must be able to challenge the conclusion.

**Current reality:** today's \`/api/ai-review\` sends a small selection of numeric telemetry to Gemini and requests at most one cautious hypothesis. It is **not** this expert coaching architecture. Claude's evidence-bound Q&A is mostly deterministic and not a live tool-using Gemini tutor. We have **not** trained or validated a full local tactical model. Earlier small-data ML/retrieval experiments did not justify one. Do not confuse separate \`src/\` Cloudflare/YouTube Gemini MCP with the \`coach-app/\` replay coach.

## 4. Current engineering branches — all separate, draft, unmerged

| Work | GitHub | Verified capability and caveat |
| --- | --- | --- |
| Advanced tactical coach | [PR #22](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/22), stacked on [#21](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/21) | Decoder case analysis, new reachability (touch-bound violations 27.6% -> 5.7% within same 15 replays), shadow/challenge candidates, tactical interpretations and provisional player patterns. **No expert validation.** Unknown/finite boost, missing telemetry, temporal Q&A safety still need fixes; benchmark tuning lacks independent held-out replay set. |
| Evaluating coaching | [PR #16](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/16) | Blind timing study and **separate** expert tactical-merit review, match-clustered paired comparisons, packet freshness and fake-video checks. **No real expert ratings yet.** Timing labels cannot validate tactical wisdom. |
| Viewer improvements | [PR #23](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/23) | Camera/visual/sync changes; its claimed clip exporter is a **single dummy WebM frame**, not gameplay footage. "200x full replay loader" claim does not follow from first-player-only precomputed binary test. |
| User-driven decluttering | [PR #24](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/24), stacked on #23 | HD-first split/map, fewer overlays, player boost bars, experimental higher chase camera. **Needs Windows visual testing and HD rebuild**; advanced coach not integrated. |
| Native Rocket League link | [PR #20](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/20) | **Previously investigated and partly implemented** official Stats API command/protocol repair. This is **NOT a new discovery**. Must verify game-side commands, local configuration, seek/POV/pause/speed, actual round-trip behavior and time alignment on user's PC. Unverified until that test passes. |

Repo: https://github.com/mechanicalengineringst-png/rocket-league-video-mcp . The separate \`src/\` Cloudflare MCP is **not** the local replay coach. Do not treat GitHub green CI, research documents, or synthetic tests as proof of product-quality visual fidelity or GC/SSL coaching.

## 5. What we do next (priority order)

**P0 — One complete coaching vertical slice:** On one genuine 2v2 replay, integrate advanced backend + a genuinely capable Gemini reasoning/tool workflow + actual usable 3D/native playback + small 2D. Produce **1–3 falsifiable, high-value coaching cases**, including a hard backboard/challenge-type decision; present evidence, alternative, uncertainty and a follow-up explanation. Owner must judge whether it teaches something new. Avoid auto-generated dozens of shallow flags.

**P0 in parallel — Native game control proof:** On the user's Windows game installation (only with user permission and manual opt-in setup), test official Stats API from replay loading through seeking, player POV, pause/speed and measured time sync. Existing PR #20 and official API docs are the starting point, **not something to rediscover**. Fall back to standalone HD, never require game launch.

**P1 — Trust calibration:** Fix reachability/Q&A data-contract gaps; obtain actual video clips, not placeholder WebMs; do separate commitment **timing** and blind tactical **merit** reviews with experienced players, tune on training matches and evaluate on **different complete replays**. Track false criticism of sound decisions, unsupported claims, usefulness and abstentions.

**P2 — Accessibility:** Keep improving independent replay fidelity for eventual mobile, local-first replay library, long-term habits and optional cloud reasoning. Do not let mobile or cosmetic work block the coaching prototype.

## 6. Anti-amnesia / agent operating rules

1. **Before every work round:** read this file, verify live GitHub branches/PRs/tests, and read the latest relevant decision notes. Do not call a previously discussed approach a new discovery.
2. **After significant work:** update this document's current state, PR/commit references, explicit known defects, new decisions and next handoff. Keep the detailed evidence in PRs and longer Google Drive archive.
3. **Human decisions are binding:** user priorities and rejected UI elements trump preserving AI-generated features. Do not silently reintroduce them. Explicitly flag if goals appear contradictory or a tradeoff needs the owner's choice.
4. **Distinguish statuses:** proposed / implemented / CI-tested / browser-observed / real-game-verified / expert-validated. Passing CI doesn't move a feature through all statuses.
5. **Security:** this repository is public. Store **summaries, decisions, URLs and non-sensitive evidence**, NOT conversation dumps containing personal information, raw replay identities, secrets, API keys, tokens or local file paths. GitHub is the **operational handoff**; Google Drive is the deep historical record.
6. **Branch safety:** no unreviewed merges into \`main\`; agents work on independent branches/PRs. If this compass changes, make the change visible in a docs PR and call it out to the other models.

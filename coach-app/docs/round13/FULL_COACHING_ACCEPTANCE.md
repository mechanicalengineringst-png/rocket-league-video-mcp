# Round 13 full-coaching acceptance workstream

This workstream makes one deterministic local test exercise ALL relevant coaching
backend contracts on the SAME replay. It is NOT proof of high-rank tactical merit,
real Windows browser rendering, or a configured external AI model.

## Included

- scripts/round13_full_acceptance.py: privacy-safe, complete local FastAPI
  TestClient traversal (capabilities, model readiness, review shortlist,
  exact source candidate to lesson parity, local evidence, pre-decision scene
  geometry, user-pinned-style manual episode, and experimental situation report).
  It reports successful, blocked and legitimately empty results separately.
- round13-test-windows.cmd: drag-and-drop command for a real 2v2 replay.
- tests/test_round13_full_acceptance.py: synthetic-only smoke, no-spend check,
  identity guard, manually sampled recorded window and 1v1 refusal.

No raw replay contents, player IDs, filenames, secrets or model-generated text
are printed or saved. The script never sends native Rocket League commands.

## Windows sequence after integrating the current branches

1. From the repository root, git fetch origin and switch to the final
   integrated Round 13 branch (NOT main or an unfinished draft agent branch).
2. Run coach-app\setup-high-fidelity.cmd AFTER switching branches, then
   run coach-app\start-windows.cmd.
3. Load a real ranked 2v2 replay in the browser, confirm the player identity.
4. Optional command-line verification:
     coach-app\round13-test-windows.cmd "C:\path\match.replay" 1
   The final 1 is the confirmed, decoded 1-based roster slot. It can be 1-4.
   If mapping is unverified and no slot is provided, the test abstains.
5. Inspect the sanitized statuses/counts. "api_structural_pass" means the
   connected LOCAL API contracts worked for this replay. It never means
   high-rank advice quality or browser visual accuracy has been proved.
6. In the browser verify HD+Map/HD/2D, real replay seek, camera ON/OFF,
   Decision Lens, manual missed moments, situation report Stage A/B,
   blind human-first review, model readiness, geometry, and feedback export.

## Optional real model

A real AI provider is NOT bundled. To test one, explicitly enable a local or
approved remote OpenAI-compatible chat completion server, set the server
variables REPLAY_LAB_ENABLE_COACH_MODEL=1, REPLAY_LAB_COACH_MODEL_URL,
REPLAY_LAB_COACH_MODEL_NAME, and (for remote HTTPS) the API key PRIVATE in
your environment. Use the in-app single-call consent checkbox. The advanced
CLI also has an explicit --model switch, which makes at most one request if
configured. The default Windows wrapper NEVER calls a model.

A stub provider only verifies transport; it cannot validate intelligent
coaching. Source-checked model advice remains a hypothesis. Source-backed
deterministic coaching and situation reports work without a model.

## Integration gates still outstanding

- Combine this PR with Antigravity PR #53 and Claude's in-progress Round 13
  tactical branch on a new integration branch (do not merge directly to main).
- All GitHub workflows must pass on the exact combined commit SHA.
- Antigravity must demonstrate actual browser interactions and visible WebGL
  pixels with a real replay; synthetic tests alone are inadequate.
- Owner must test several interesting real ranked moments and one missed
  moment, distinguish bad decision from bad outcome, and flag false criticism.
- Actual AI-powered coaching requires an explicitly approved working model
  and a nonzero accepted, useful source-cited proposal (not merely readiness).
- Native game commands remain an independently gated Windows acceptance.

The purpose is to expose missing links rather than pretend all features are
ready when the current branch or machine has unresolved prerequisites.

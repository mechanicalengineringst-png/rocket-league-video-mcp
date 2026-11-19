# Round 12 integration acceptance — one actual Replay Lab build

This file is the handoff for draft PR #52, **not** a claim of full
real-world acceptance and **not** a merge to \`main\`.

## Source ancestry and preservation

The current test branch is
\`integration/round12-complete-hd-tactical-20261118\`, based on
ChatGPT's PR #50, which contains PRs #43→#44→#46→#47→#48→#49→#50
plus the compatible #41 source-backed model transport.
It additionally ports:

- Antigravity's PR #51 exact current HD source and tests:
  authentic GLB car assets + awaited replacement, level/elevated chase
  camera, soft supersonic ribbon shader, indexed camera events,
  iframe replay File/Blob correction and restored HD controls.
  Historical screenshot binaries are not copied into this branch.
- Claude's PR #45 experimental situation-aware tactical engine and
  prerequisite Round 11 contracts (31 files): seven situation
  classes, source-cited alternatives, separate Stage A and
  retrospective, replay/heuristic evaluation studies and offline CLI.
  This import **does not replace** ChatGPT's newer \`coach_api.py\`,
  \`coach_model.py\`, \`static/app.js\`, \`index.html\`,
  \`coaching-experience.js\` or blind evaluation guards.
- New integration API and user interface:
  \`POST /api/coach/coaching-report-v1\`, explicit capabilities flags,
  and a collapsed **Experimental situation-aware 2v2 report** panel.
  It runs only when clicked, locally and deterministically. Up to six
  findings, stage-A interpretations, reasonable alternatives, decisive
  unknowns, synchronized HD+2D seeks and postdecision outcome **inside
  a separate initially closed disclosure**. Source validation failures
  are withheld and reported as counts. The experimental panel is also
  hidden/blocked during blind human-first Stage A. No model provider
  is contacted by this route. A real external model is separately
  explicit opt-in, NOT implicitly enabled by the report.

### Research-quality boundaries

Claude's public unknown-rank sample and synthetic scenario tests
**do not constitute expert agreement**. Its 1.0s cover window
affects conclusions; opponent approach may be fake/bait, reachability
is a lower bound not intent, observed action is inferred from
movement, and all aerial/wall plays are observation only. A player
should inspect *the situation and option ledger first*, then
question any \`questionable\` action labels. Outcomes do not prove
decision quality.

Antigravity's reported asset screenshots and browser test improve
confidence but cannot establish that **this merged build** looks
correct on the user's Windows machine. Follow-cam must be verified
on known recorded ON/OFF and non-recorded camera conditions.
Native Rocket League Stats API command transport is an independent
feature from the standalone HD viewer, and must never be represented
as a video feed or confirmed game action merely because a TCP port
is listening.

## Windows owner-test steps

1. Clone or switch to the **draft integration branch**, not \`main\`.
   From a Windows Command Prompt at the project root:
   \`git fetch origin\` then
   \`git switch integration/round12-complete-hd-tactical-20261118\`
   (or \`git switch -c integration/round12-complete-hd-tactical-20261118
   --track origin/integration/round12-complete-hd-tactical-20261118\`
   if it is not yet local).
2. From project root run \`coach-app\setup-high-fidelity.cmd\` once
   to build the latest bundled renderer, **after** checking out the
   integration branch; otherwise an older built \`hd-player\` remains.
   Then run \`coach-app\start-windows.cmd\`. Open the exact local URL
   printed by the launcher (normally \`http://127.0.0.1:8000\`).
3. Upload one real local **2v2** \`.replay\` using the app, confirm
   which player is being coached (do not guess the recording player).
   Verify the title, 2v2 identity, actual replay source and 2D clock.
4. Start in **HD + Map**, then check HD 3D and Tactical 2D separately.
   Compare real vehicle meshes/wheels and paint (no blue placeholder),
   floor/wall/arena materials, camera horizon from kickoff to walls
   and aerials, correct player POV, Ball Cam ON/OFF event timing
   where actually recorded, boost gauge, thin readable tire trails,
   and forward/backward seeks. Capture *local* screenshots or notes
   at the exact replay-relative t0 for any regression; do not post
   private files, local paths or player IDs in the public repo.
5. Click a source-backed automatic shortlist moment: verify
   selected player, synchronised HD/map seek, source citations,
   Decision Lens predecision positioning and explicit recorded
   outcome reveal. **No demo fixture** may be silently substituted
   for a real replay.
6. Find a meaningful situation the detector missed. Manually pin it,
   click **Review this overlooked moment (local)** and inspect
   its genuine source-backed lesson. Compare observed positional
   relationships using the free local scene inspector. The
   manually selected moment is **not** automatically a proven error.
7. Open **Experimental situation-aware 2v2 report**, manually
   click **Analyze this match locally (experimental)**. This may take
   several seconds; there is no AI provider charge. Review up to
   six findings covering first defense, possession, first man
   offense, second man, loose ball and recovery. For each, inspect
   the **Stage A ledger and alternative conditions before** opening
   **What you did & recorded outcome**. Flag unfair criticisms
   or falsely certain recovery/interception estimates.
8. To minimize anchoring, separately use **Blind Decision Review**
   on a real primary episode. It limits the shared parent clock
   to t0, masks existing coaching and AI results and collects
   **your action, teammate coverage and confidence before** you
   unlock postdecision viewing. It cannot erase your prior
   knowledge of the match or conceal another open game window.
   Save and export \`ReplayLabBlindReviewReportV0\` locally.
9. **Optional AI model**: do not enable just to make the app work.
   The model panel remains separate, with readiness diagnostics
   and explicit consent **per request**. Real model quality, costs,
   security and evidence citation must be inspected separately.
10. **Optional native game**: this is a separate Windows test
    only after the owner explicitly enables native commands and
    configures the installed Rocket League Stats API. A successful
    port probe is NOT a successful LoadReplay. Enter the exact
    *game-local* replay identifier, send LoadReplay with opt-in,
    visually confirm it is the same match, then check seek/POV/
    pause/speed against the companion's actual supported commands.
    Avoid native game controls while collecting blind Stage A.

## Acceptance matrix

| Area | Automated pass is meaningful for | Actual owner acceptance still required |
|---|---|---|
| 2D/coaching integration | source-linked contracts and per-player state | correct identity, no demo leak, useful candidate selection |
| HD authentic 3D | camera, shader and asset-load code paths | realistic wheels/car, stable ball camera, terrain and visuals |
| HD+2D synchronization | parent clock and bridge guards | matched timestamps at kickoff, goal, wall and backward seeks |
| Claude V1 | deterministic source/claim checks, known scenario regressions | genuine tactical fairness at rank, abstention and false positives |
| Experimental report UI | manual initiation, withheld bad claims, closed Stage B | readable alternatives and fair situational explanations |
| Blind review | time cutoff and masked panels | independent human review, prior exposure self-report |
| Model proposal | sanitized packet + user consent gate | approved actual provider call, cost/quality, no unsupported claims |
| Native Rocket League game | loopback command gating and status semantics | physical game actually loaded/seeked the correct replay |

## Release gate and rollback

DO NOT label this ready for normal use until:
- exact **integrated** GitHub CI is green;
- at least one real 2v2 replay is loaded into the full Windows application
  with full HD+2D split and no blue placeholder;
- trial reports and Stage A/B masks work without hindsight leakage;
- native controls are represented honestly (untested until in-game);
- serious false-criticism examples and the relevant replay-relative
  timestamps are documented, not silently hidden by test-pass counts.

Keep the draft integration PR until the owner signs off. Make small,
source-linked fixes on this branch and preserve the exact tested SHA.
Use the canonical project compass in docs-only PR #25 to reconstruct
cross-session decisions if the chat context is lost.

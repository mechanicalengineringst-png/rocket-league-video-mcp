# Round 12E — Blind-ish human-first two-stage replay review

## Why this is substantial product work

We are trying to learn whether the coaching AI is genuinely helpful at
experienced 2v2 play, not merely structurally valid. Existing testing
buttons let users react to recommendations **after** seeing them, which
risks anchoring and after-the-fact justification. Gemini's independent
Round 12E work is building adversarial paired hypothetical tactical
scenarios; this product feature provides a way to evaluate real replay
moments without that suggestion-induced bias.

A two-stage **Blind Decision Review** panel is available below the
Decision Lens, initially collapsed so ordinary replay watching stays
uncluttered. A full independent review takes two distinct stages.

### Stage A — Record an independent action before the outcome

1. Load a real (not synthetic demo) 2v2 replay and confirm the coached
   player. Select a **primary** source-backed episode; this can be an
   automatically discovered candidate or a manual overlooked moment
   from PR #48.
2. Open **Blind Decision Review**. Self-report previous exposure as
   unseen / seen / unsure. This matters; neither technology nor user
   intent can guarantee that someone has never seen this match.
3. Click **Start predecision review**. The parent playhead/HD+2D sync
   is capped at the selected \`primary_t0\`. The normal automated coach,
   AI model panel, native-companion panel, optional video, and
   Decision Lens's +2s/loop controls are temporarily hidden.
   If playback reaches t0 it stops; external native windows and footage
   independently playing outside this app cannot be controlled.
4. Review the setup, choose an intended action (challenge/50/50,
   fake/pressure, shadow/delay, control, abort/rotate, or insufficient
   information), assess teammate coverage (covered / exposed /
   unclear), and select a confidence from 1 to 5. Optionally add why,
   including alternative assumptions that could change your decision.
5. Click **Lock my predecision judgment**. The selected action,
   coverage, confidence and rationale are frozen and cannot be edited
   after revealing future events.

A half-finished predecision attempt is not exported. Switching context
destroys the unlocked attempt rather than creating a false independent
data point; it can then be restarted.

### Stage B — Separate outcome, execution and advice

Only after Stage A is locked can the user explicitly:
- **Reveal actual recorded follow-through** in the existing Decision
  Lens, synchronized with the HD/2D parent clock. This is observed
  replay motion, not a proposed counterfactual.
- **Open optional AI coaching**. No model call is made by blind review.
  Actual model generation still requires the existing explicit one-call
  consent and server-side model enablement from PR #47.

Then the user independently rates:
- **Decision merit:** defensible / tradeoff / questionable /
  cannot tell. An unsuccessful result does not make a decision bad.
- **Execution:** clean / mechanical error / opponent adaptation /
  insufficient evidence.
- **AI feedback:** useful / false criticism / missing context /
  too generic / uncertain / not tested. You cannot label AI as
  wrong or helpful if no model proposal was actually generated.
- Optional postdecision notes.

The completed review is held in the **current browser session only**.
A button exports local \`ReplayLabBlindReviewReportV0\` JSON, with
match_index, t0_s, manual-vs-auto provenance, prior-exposure
self-report, the LOCKED predecision record, postdecision ratings, and
a bounded model result summary if generated. No raw frames, filenames,
player IDs, full provider prompts, API keys, network uploads,
background writes, localStorage or databases.

The report presents counts such as locked judgments, completed reviews,
self-reported unseen cases, manually chosen moments, and flagged false
criticism. These counts are **tester observations, not verified model
accuracy or GC/SSL expert agreement**. Data is lost on browser refresh
unless the user exports. User-entered notes may contain private
information; review exported files before sharing.

## Technical guardrails

- \`coach_app/static/blind-review.js\`: independent browser-only trial
  state machine, one trial per unique match/episode/player per session,
  unlocked vs. locked phase separation, explicit user-triggered reveal,
  anonymous in-memory export.
- \`coach_app/static/app.js\`: shared playback guard applied in
  \`chooseTime\`, \`playTick\`, and the normal Decision Lens loop/reveal
  controls; uses the parent synchronized HD/2D clock. The selected
  input episode's t0 remains the cutoff. The owner can still navigate
  backward through recorded setup.
- \`coach_app/static/model-coaching.js\`: masks both existing cached
  results and new generation while Stage A is open, irrespective of
  provider status. This is a viewer UI guard, not a secret-management
  or remote provider authentication feature.
- \`index.html\` / \`style.css\`: collapsed mode, clear distinction of
  Stage A vs B, private feedback, free export, honest limitations.
- \`.github/workflows/replay-viewer.yml\`: executes
  \`high-fidelity/test/blind-review.test.mjs\` on all updates alongside
  previous Decision Lens, model UI, geometry and manual-review tests.

## Known limitations

The source-backed episode may have been *selected* by an event-driven
detector that consulted later play, or a user who has already watched
the entire match. Our tool cannot establish an independent blind
condition from that selection. It only controls **when this UI reveals**
the outcome and AI advice. Native replay game controls/second monitor,
human memory, external recordings, browser devtools and future-state
knowledge are not blocked. Real validation should stratify by
self-reported unseen/seen/unsure, and ideally have an expert who has
not watched the match select neutral moments before outcome playback.

A reviewer’s judgments are useful labels but not necessarily correct.
Need independent expert verification for GC/SSL-grade coaching. The
application does not automatically align AI's action-specific proposals
with a human's preferred action, since today's \`CoachDraftV0\` may not
encode a unique selected action; those must remain separately reviewed
rather than overcounted as agreement.

## Independent technical verification

New Node VM tests cover:
- confirmed source-backed 2v2 primary-episode gating and no demo;
- no automatic Stage A model requests, playback cutoff and masked panels;
- independent decision, teammate and confidence capture;
- immutable Stage A post-lock despite later changed form controls;
- no automatic outcome/AI disclosure and explicit reveal only;
- decision quality versus execution grade separation;
- false criticism cannot be recorded without an actual AI result;
- player/match switch invalidation with retriable unfinished review;
- anonymous two-match local reports with no identifying fields;
- integration contracts: parent playTick/chooseTime and model cache
  are gated in source.
- Model UI Node tests additionally assert cached advice stays hidden
  and generation is disabled until Stage A is locked.

Python UI contract tests preserve the new wiring, and full existing
coach suite must continue passing. These are synthetic fixtures and
structural checks; real HD/natives tests and tactical quality remain
separate owner acceptance steps.

## Cross-agent coordination

**Branch lineage:** Antigravity #43 → native safeguards #44 →
Decision Lens #46 → opt-in model #47 → manual missed moments #48 →
grounded scene relations #49 → **this PR #50**.

- **Gemini** builds hypothetical paired adversarial tactical cases
  and reviewer scoring specifications; distinguish imaginary test
  conditions from observed game telemetry.
- **Claude** continues its independently experimental
  \`CoachingReportV1\` tactical pipeline #45. Do not merge uncalibrated
  verdicts into this blind evaluation as ground truth.
- **Antigravity** owns HD vehicle/scene/camera/effects and native
  Stats API integration. Its updated HD render needs to respect the
  existing parent playback cutoff; do not overwrite these new
  \`app.js\` and \`model-coaching.js\` guards with older ancestor versions.
  Native game windows are explicitly outside the blind masking contract.
- **ChatGPT** owns trial state machine, mask/playback guard, export and
  integration constraints.

All code and test status should be preserved in draft GitHub PRs and
the canonical project compass in PR #25. No merge to \`main\`
without owner approval. Do not suggest these tests alone prove that
the coach makes elite-level tactical recommendations.

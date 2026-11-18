# Round 12B — Real opt-in model coaching in Replay Lab

**Owner objective:** gain actual coaching suggestions from a real configured
AI model during ranked replay testing, without turning Replay Lab into a
chat-first product. The user will test the coaching quality separately.

## Why this feature exists

The Round 9–12 frontend supported deterministic source-backed review cards
and optional evidence navigation, while the local backend already had
\`POST /api/coach/lesson\` with \`mode:"model"\`. But the normal integrated
browser UI did not provide an explicit way to use that contract.

**A second bug blocked the obvious integration:** Antigravity's fast
\`CoachReviewBundleV0\` path passed its **bundle-level request** (max
candidates / preview count), not the individual candidate's audited
\`decision_times\`, \`episode_start_s\`, and \`primary_t0\`, as
\`backendRequest\` on each rendered episode. That payload is invalid for
both \`/api/coach/lesson\` and \`/api/coach/evidence\`.

This branch fixes the mapping using the **exact original candidate fields**
and refuses inconsistent previews; it never silently reconstructs a
different timeline from UI guesses.

## What changed in the actual product

There is now an **AI coaching proposals** section immediately following
the regular coaching deck, collapsed until opened.

1. Load a real native 2v2 \`.replay\` and confirm who is being coached.
2. Select a **source-backed primary coaching decision** (not an earlier
   context-only snapshot). No fixture suggestions on actual matches.
3. Open AI coaching, click **Check model configuration**. This is a
   read-only/no-cost local preflight that reports disabled, incomplete,
   invalid, or **configured but provider/quality unverified**.
4. Check the explicit checkbox authorizing **one** model request based on
   sanitized predecision evidence. The checkbox resets after each call;
   selecting another replay or player resets the model panel.
5. Click **Generate AI coaching for this decision**. The browser requests
   \`POST /api/coach/lesson\` on its **local server**, with the exact audited
   episode timestamps and \`mode:"model"\`, always
   \`experimental_tactical_v1:false\`. The server creates a sanitized
   \`Stage1EpisodePacketV0\` and sends **only the verified packet and
   uncalibrated tactical menu** to the owner-configured provider.
   **No raw replay file, original filename, credentials, or retrospective
   outcome is sent to the external provider.** The *local server* does
   receive the decoded replay from the local browser.
6. The backend's \`CoachLessonV0\` evidence gate either rejects model
   statements or returns accepted, source-cited **hypotheses**, clearly
   marked as **not expert-validated for tactical meaning**. The frontend
   displays **only** \`author:"model_proposal"\` claims with validated
   review status, not deterministic baseline facts disguised as generated
   insights. Accepted/rejected counts are shown honestly.
7. Click individual source citations to request
   \`POST /api/coach/evidence\` **locally**, with
   \`mode:"deterministic"\`. The display does not make another model call.
8. Rate the advice **Useful & accurate / Incorrect / Missing context**
   and optionally type what the model missed. Export model feedback as
   local JSON, or include it with the existing full Replay Lab tester
   report. Nothing is auto-uploaded or persisted to the provider.

There are **no automatic model retries**. A 403/422/502/503 response shows
an honest non-sensitive failure message, never a fake answer.

## Integration with existing engineering branches

- **Frontend base:** draft PR #46, which includes Antigravity #43 →
  native safeguards #44 → ChatGPT Decision Lens #46.
- **Model backend:** exact \`coach_api.py\` and \`coach_model.py\` from
  ChatGPT's CI-green PR #41 were brought into this branch, including
  strict JSON or single JSON-fence parsing, optional JSON object mode,
  read-only \`/api/coach/model-readiness\`, and capability status.
- **Local testing:** PR #41's Windows replay acceptance runner,
  example setup guide, and real-loopback HTTP model contract tests
  are included so this branch can serve as a coherent testing build.
- **Claude #45:** experimental \`CoachingReportV1\` remains a separate
  opt-in tactical pipeline. This frontend does not consume its unreviewed
  output or forward its speculative grades to the language model. Once
  Claude's evaluation is complete, integrate a versioned adapter.
- **HD PR #42:** camera switch index and actual tire-ribbon shader
  correction remain separate for Antigravity's targeted integration.
- **Antigravity next branch:** owns
  \`coach-app/high-fidelity/src/**\`, the HD bridge and native
  companion visual integration. Do not replace this branch's new
  \`model-coaching.js\`, exact bundled episode mapping or feedback export.

The project compass is maintained on docs-only PR #25, not yet \`main\`.
Neither this nor other agent PRs have been merged into \`main\`.

## Configure a real provider on your Windows PC

A real model is **not bundled or assumed installed**. Use the owner-approved
local or remote **OpenAI-compatible /chat/completions** endpoint. Example for
a model server already installed and running on your own loopback port:

\`\`\`cmd
cd coach-app
set "REPLAY_LAB_ENABLE_COACH_MODEL=1"
set "REPLAY_LAB_COACH_MODEL_URL=http://127.0.0.1:11434/v1/chat/completions"
set "REPLAY_LAB_COACH_MODEL_NAME=YOUR_INSTALLED_MODEL_NAME"
set "REPLAY_LAB_COACH_MODEL_JSON_MODE=1"
start-windows.cmd
\`\`\`

This is **only an example**; a specific provider, model installation and
correct endpoint must be verified on your PC. An API-compatible response
is necessary; the model must follow the \`CoachDraftV0\` strict JSON
contract or no model lesson can be accepted. Not all local models can do so.

For a remote HTTPS-compatible provider, set its explicit endpoint, model
name and \`REPLAY_LAB_COACH_MODEL_API_KEY\` locally. The server requires
an API key for HTTPS. Do not commit it, paste it into the UI or put it in a
URL. Remote calls may incur usage fees and transmit **sanitized evidence**
to the configured provider. Only enable when the user authorizes this.

**Every call is doubly opt-in:** server setting equals \`1\`, AND a
single browser user click with the consent checkbox. Viewing/moving between
scenes and deterministic lesson generation remains free/no-spend.

## Proof and testing limits

Code-backed:
- \`high-fidelity/test/model-coaching-ui.test.mjs\` exercises the actual
  browser script in a clean VM with simulated DOM. Tests include
  audited request generation, explicit consent, one outbound call,
  accepted/rejected model claims, stale player switching, malformed
  reply rejection, model feedback export and exact review bundle payload.
- The existing \`test_round12_model_acceptance.py\` uses an actual
  local HTTP server (mock model **transport**, not AI) through FastAPI.
  It verifies sanitized Stage1 payloads, strict JSON responses, evidence
  gate acceptance and no-spend default.
- \`test_ui_contract.py\` ensures the real UI controls and JS integration
  hooks exist.
- Source files and test workflow are executed in GitHub CI at each PR
  head, with no real external model calls.

**Still required for owner's comprehensive testing:**
- A real local or remote configured model must respond successfully to a
  real replay packet, with nonzero accepted source-cited claims.
- Inspect the actual model advice and judge its tactical merit, missing
  context, false criticism and usefulness. Accepted citations alone do
  **not** prove strategy.
- Verify exact HD visuals, 2D/HD time sync and native Rocket League client
  separately; these are independent acceptance dimensions.
- Prefer a few high-value moments from 3–5 real ranked 2v2 matches over
  many unsupported generated suggestions.

## Security and privacy

The local app has no authentication. Do not expose it on public network
interfaces, reverse proxies or internet tunnels. API key stays in local
server environment, never inside frontend scripts. Client output uses
\`textContent\` for all model-supplied text, not HTML interpolation. Source
inspection remains local. No model inputs or outputs are logged to the
browser console. A slow response is discarded if the replay/player/moment
changes; cancellation cannot guarantee a remote provider did not already
process or bill the request.

User feedback is held in browser memory until the user explicitly exports
it. The local export may contain personal replay observations, so keep it
private unless the user chooses to share it.

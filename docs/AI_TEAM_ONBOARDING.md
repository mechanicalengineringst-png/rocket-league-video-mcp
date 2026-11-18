> **OUTDATED HISTORICAL HANDOFF (15 November 2026).** This file describes the PR #4-era prototype and is retained for provenance. For current user-approved goals, previous native Rocket League Stats API research, all Round 5 branch statuses and what to do next, **READ FIRST:** [Replay Lab — Project Compass](replay-lab-project-compass.md). Do not infer current code or decisions from the dated sections below.

# Rocket League AI Coach — Multi-model project handoff

**Status:** active prototype, 15 November 2026  
**Canonical repository:** https://github.com/mechanicalengineringst-png/rocket-league-video-mcp  
**Native replay app draft PR:** https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/4  
**Public-facing production MCP URL:** https://rocket-league-video-mcp.mechanicalenginering-s-t.workers.dev/mcp

This is an onboarding brief for **ChatGPT/GPT-6, Claude, and Gemini**. It is deliberately public and contains **no credentials or private replay data**. The project owner wants all three models to inspect the actual code and independently challenge design and gameplay conclusions. Do not claim to have reviewed any source you have not opened.

## 1. Product goal

Build a useful **high-skill Rocket League replay coaching app** rather than a generic video summarizer. A player uploads a native Rocket League '.replay' file, chooses their player, and receives a chronological, evidence-grounded review of decisions such as:

- Challenge versus delay; second-man overcommit; teammate coverage; recovering into defensive responsibility.
- Rotation and boost-pad routes, spatial pressure, possession, and spacing.
- A **top-down field** at each moment showing *observed car/ball/teammate/opponent locations*, the player's **recorded movement path**, and an **illustrative alternative path** recommended by the coach.
- Timestamp, what was observed, why it matters, alternatives, model confidence, and the assumptions that would change the recommendation.
- Patterns across many matches; prioritized training goals; support for 2v2 first.

The target is an experienced competitive player, not a beginner. Do not substitute stock back-post advice for position-specific evidence. Favor a **few substantial, verifiable decisions** over a long list of superficial criticisms.

**Crucial limitation:** A replay shows what actually happened, not what would definitely have happened on an alternate route. Proposed routes are coaching hypotheses, never proven counterfactual outcomes. Replay data also may be incomplete or require interpolation.

## 2. Already built / verified

### Working YouTube-analysis connector

The Cloudflare Worker is deployed and successfully connected to ChatGPT as a custom Model Context Protocol (MCP) tool. Its tool is 'watch_video', which passes a **public YouTube URL** and an analysis prompt to the **Gemini 3.8 Flash API**. The worker supports static video intervals/frame sampling and agentic video analysis; it returns text and usage. MCP calls are authenticated by **GitHub OAuth**, with authorization restricted to the GitHub owner account 'mechanicalengineringst-png' (enforced by numeric GitHub user ID).

Relevant source: 'src/oauth-worker.ts', 'src/github-oauth.ts', 'src/services/gemini.ts', 'src/tools/watch-video.ts'. Some upstream template README language may predate the deployed GitHub OAuth customization; source code is authoritative.

Three calls successfully examined an ApparentlyJack 2v2 coaching video from YouTube: a short sample, a targeted visual clip, and a broader agentic pass. One initial attempt failed temporarily. The reports found potentially useful time-coded decisions, but a human coach narrated the errors, so **independent expert-level coaching is NOT demonstrated**.

The Gemini API project was 'Default Gemini Project', with free-tier Gemini 3.8 Flash limits observed around **5 requests/minute, 250K input tokens/minute, and 20 requests/day** at the time of testing. These quotas are associated with the user's Google project and can change.

### Experimental native replay application (draft)

GitHub PR #4, branch 'feature/replay-coach-local-mvp-20261115', introduces a standalone local-first Python/FastAPI application under 'coach-app/'. Features in the draft:

- Native '.replay' upload, size guard, and temporary-file parsing based on RLGym Tools / carball.
- Sampled game states and player, ball and boost information; interactive 2D pitch and scrubber.
- Selected-player movement trails, provisional review candidates, adjustable dashed alternative routes, optional Gemini positional critique, report export.
- Initial **8 synthetic-fixture tests** and JavaScript syntax checks; GitHub checks passed.

**Important:** Native replay parsing has **not yet been validated end-to-end on a real current replay**, and the application is **not deployed as a public website**. The draft must remain subject to verification. The scripted flags are exploratory, not validated coaching conclusions. Do not present the dashed route as algorithmically optimal.

### Useful existing open-source technologies

- RLGym Tools replay conversion: https://rlgym.org/RLGym%20Tools/introduction/
- Boxcars replay parser (Rust): https://github.com/nickbabcock/boxcars
- Browser WASM replay parser example: https://github.com/nickbabcock/rl-web

Choose parsers and data representations only after comparing compatibility with current replays, validation, hosting cost, security, and access to game-state fields. Parsing is distinct from interpreting decision quality.

## 3. Desired workflow

1. Player uploads a replay privately and selects their car.
2. Validate file and parse game-state events; verify player IDs, timestamps, goal clock, boost and coordinates.
3. Show a pitch/time scrubber with actual replay state. No LLM call is required for ordinary viewing.
4. Generate **candidate** decision moments with transparent triggers (e.g. challenge while last-back, unsafe teammate spacing, boost detour, premature rotation). Triggers alone are not proof of mistakes.
5. Send only relevant time-window game-state slices (and optional consenting video clips) to independent model reviewers.
6. Each model returns a **structured critique**: time window, verifiable observations, decision, alternative route/action, reasoning, competing explanations, confidence, evidence/source.
7. Compare disagreements. Never treat agreement among models as proof. Human reviews important clips.
8. Annotate a 2D field: observed route as a solid trail; proposed route as a dashed, clearly labeled suggestion; pad and teammate positions; reason for the change.
9. Track validated recurring patterns across matches. Let player mark suggestions accurate / incorrect / context missing.

A recommended JSON review schema could include: replay_id, focal_player_id, t_start, t_end, observation, recommendation, evidence_frames, evidence_fields, alternative_actions, uncertainty, confidence, and reviewer_model.

## 4. Collaboration roles

- **ChatGPT / GPT-6:** Primary conversation with the owner, system design, implementation coordination, synthesis and decision tracking. Calls existing MCP tools when available.
- **Gemini:** Visual/YouTube interpretation and a second tactical review of structured replay windows, with explicit distinction between audible coaching commentary and independently inferred decisions.
- **Claude:** Independent architecture/code review and independent tactical critique, especially attacking weak reasoning, unstated assumptions and false-positive coaching.
- **Human player:** Final judge of whether situational claims match the replay, especially at advanced ranks.

Avoid delegating every task to every model. Use specialist reviewers only when their added value exceeds their time/cost.

## 5. What it means to integrate the three models

**Now, using existing subscriptions:** The three chat apps can study the same repository; Claude and Gemini can also connect to the same *remote MCP* server with their own GitHub OAuth login. This provides **shared tools**, but **not shared chat memory**, automatic model-to-model communication, or a pooled subscription.

**Later, with consent:** Add a separate authenticated project-review service backed by Cloudflare D1/R2/KV/Queues, with MCP tools such as 'project_get_brief', 'review_submit', 'review_list', and 'replay_get_window'. Each chat model could explicitly publish structured critiques to the common review store; the user can compare them. Write actions require access checks and provenance.

**Fully automatic three-model consensus:** A Cloudflare coordinator could call OpenAI, Anthropic and Google **APIs**, consolidate distinct results and log spend. Consumer subscriptions (ChatGPT plan, Claude Pro, Google AI Pro) should **not be assumed to cover external API use**. Add this only if worthwhile, with cost caps and an explicit decision to enable paid access. Claude Pro alone does not include unlimited Claude API calls. The current Cloudflare Worker already uses a separately quota-limited Gemini API key.

## 6. Read-only onboarding and connector setup

### Claude Pro

1. Create a Claude Project named **Rocket League AI Coach**. Add the repository to Project Knowledge using the GitHub integration. Include this file from 'main' and app files from the PR #4 branch if GitHub project selection supports it; otherwise paste the PR link and attach required files explicitly.
2. In Claude: [Customize > Connectors](https://claude.ai/customize/connectors) > '+ Add' > 'Add custom connector'. Enter the MCP URL above.
3. Follow OAuth authentication and choose GitHub owner account 'mechanicalengineringst-png'. The server rejects any other GitHub account.
4. Enable the connector in the project conversation. Test 'watch_video' **only if the owner wants to spend Gemini API quota**.

### Gemini web app

1. Sign in with an eligible **personal** Google Account (not a school-managed account); Google requires age 18+, US location, English, and **Keep Activity enabled** for personal custom MCP apps.
2. To import repository code: in Gemini web chat, 'Add file > More Uploads > Import code', paste the repository URL or the PR #4 **branch URL**, and import. Imported repositories are snapshots, not live sync.
3. To connect shared MCP: [Gemini Connected Apps](https://gemini.google.com/apps) > 'Add a custom app' > use the same MCP URL; follow GitHub OAuth with the authorized GitHub account. The server advertises dynamic client registration; compatibility should be tested, not assumed.
4. Gemini Developer Mode at https://gemini.google.com/devmode can show tool schemas, authentication behavior and tool-call latency.
5. Test 'watch_video' only when approved; calls consume the existing Gemini API quota **in addition to** the Gemini chat subscription's own usage.

Official references: Claude [custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) and [GitHub integration](https://support.claude.com/en/articles/10167454-use-the-github-integration); Gemini [custom apps](https://support.google.com/gemini/answer/17209137), [GitHub import](https://support.google.com/gemini/answer/16176929), and [AI Studio/API plan separation](https://aistudio.google.com/docs/google-ai-plans).

**Security:** Never paste GitHub OAuth codes, API secrets, GitHub private tokens or raw identity-bearing replay files in shared prompts. The repository is public. Do not weaken server authorization to make third-party clients connect.

## 7. Immediate next milestones

1. **Independent review:** Claude and Gemini examine the GitHub source and this handoff, and independently identify the top 3 technical risks and top 3 improvements.
2. **Native replay validation:** Obtain one real current 2v2 '.replay', confirm parser output / clock / car IDs / boost / field geometry against playback, and repair any mismatch.
3. **Reliable visual explainer:** Make annotated moment cards and actual-vs-recommended paths with a confidence label and evidence references. Never invent opponent trajectories.
4. **Coaching evaluation:** Blind-test on uncommentated matches; compare conclusions to advanced-player review; measure false positives and usefulness instead of counting comments.
5. **Shared multi-model review store:** Design and secure review_submissions via the MCP server; keep subscriptions useful without forcing automatic paid API orchestration.
6. **Private hosted app:** After file/parser validation, choose low-cost storage and asynchronous job processing, add authentication and privacy controls, test latency/quota, then deploy.

## 8. Request to a new model joining the project

Please analyze the repository and PR #4, using this brief as the project goals. Clearly distinguish verified features from experimental ones. Be constructively skeptical: explain the biggest practical obstacles to accurate, high-level 2v2 coaching, where missing data can cause false confidence, and how to improve the app without turning it into an expensive engineering project.

**Do not change production auth, deploy a public service, spend paid API quota, or rewrite working code without first presenting your evidence and a scoped plan.** Your first response should be:

- A concise current-state summary with source paths.
- The top 3 technical or product risks.
- The smallest concrete next development milestone that will substantially improve trustworthiness.
- One or two ideas the other models might overlook.

We are designing a useful project with measurable validation, **not** trying to prove that three models always make a better answer than one.

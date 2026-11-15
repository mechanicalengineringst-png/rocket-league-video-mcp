# ChatGPT video MCP: deployment and verification

This code prepares an OAuth-protected public YouTube video-analysis tool for
ChatGPT. **A build/test pass does not prove the live OAuth login works.**
Do not connect ChatGPT until the deployed login and MCP handshake have been tested.

## Resources

- Repo: `mechanicalengineringst-png/rocket-league-video-mcp`
- Worker: `rocket-league-video-mcp`
- Endpoint: `https://rocket-league-video-mcp.mechanicalenginering-s-t.workers.dev/mcp`
- GitHub authorization callback:
  `https://rocket-league-video-mcp.mechanicalenginering-s-t.workers.dev/callback`
- Allowed GitHub identity: `mechanicalengineringst-png`, user ID 357125258
- Cloudflare KV namespace: `rocket-league-video-oauth` (ID bound in `wrangler.chatgpt.jsonc`)

## Safe first Git deployment

1. The GitHub branch needs passing GitHub Actions checks and then can be
   merged into `main`. The Cloudflare Git integration deploys from that branch.
2. In Cloudflare Workers & Pages -> Create application -> Connect GitHub, use
   this repo and set Worker name `rocket-league-video-mcp`.
3. Build command: `bun install --frozen-lockfile`. Deploy command:
   `npx wrangler deploy --config wrangler.chatgpt.jsonc`.
   **Do not** use the default `npx wrangler deploy` command, which selects
   `wrangler.jsonc` (development-only and wrong Worker name).
4. The initial Worker may be created without secrets; the login and MCP
   application deliberately return `503` until credentials are configured.
   Unauthenticated callers never reach Gemini. This is a deliberate
   fail-closed first-deployment arrangement, not a working installation.
5. In Cloudflare Workers & Pages -> Worker -> Settings -> Variables and
   Secrets, add each as a **Secret** (not plaintext variable):
   `GEMINI_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.
   Never put values in GitHub source, GitHub Actions logs, or ChatGPT chat.
6. Publish the changed Worker settings if prompted. Never share a screenshot
   that exposes the secret values.

## Required live verification after secrets

- The Worker must answer OAuth discovery and require authorization at `/mcp`
  rather than permitting an unauthenticated MCP request.
- `/authorize` must show consent before GitHub login and return successfully
  only for GitHub account ID 357125258.
- Reject the wrong GitHub account without issuing access to Gemini.
- Confirm ChatGPT's OAuth redirect and token handshake actually work.
- Test one **short, public** YouTube video via `watch_video`; inspect results
  and Google/Cloudflare usage before attempting lengthy gameplay.

The main video-processing service is inherited from the upstream project and
has not been modified. Long tasks may exceed Workers Free CPU/time limits or
Gemini free quotas. The connection is **not live** until these tests pass.

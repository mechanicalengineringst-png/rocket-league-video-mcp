# ChatGPT video MCP integration (work in progress)

This branch is **not deployment-ready** until dependencies and the OAuth flow
have been tested. Do not deploy the original `wrangler.jsonc` (it is configured
for loopback development without authentication).

## Target

- ChatGPT MCP endpoint: `https://rocket-league-video-mcp.mechanicalenginering-s-t.workers.dev/mcp`
- Worker name: `rocket-league-video-mcp`
- GitHub login allowed: `mechanicalengineringst-png` (numeric ID 357125258)
- GitHub callback: `https://rocket-league-video-mcp.mechanicalenginering-s-t.workers.dev/callback`
- Video tool: existing `watch_video`, forwarded from an OAuth-protected Worker

## Changes in this branch

- `src/github-oauth.ts`: consent, GitHub sign-in, and owner-only check
- `src/oauth-worker.ts`: Cloudflare OAuth gateway around the existing MCP implementation
- `wrangler.chatgpt.jsonc`: production configuration template (with a placeholder KV namespace)
- `package.json`: dependency on Cloudflare's OAuth provider

No Gemini or GitHub secrets belong in GitHub files. No OAuth app credentials
are committed to this repository.

## Before deploying

1. Create a Cloudflare Workers KV namespace called `rocket-league-video-oauth`.
   Copy its namespace **ID**, not an API token, into the
   `REPLACE_WITH_CLOUDFLARE_KV_NAMESPACE_ID` placeholder in
   `wrangler.chatgpt.jsonc`.
2. Synchronize `bun.lock` with the `package.json` change (`bun install`).
3. Run dependency install, TypeScript checks, and a real OAuth integration
   test. Confirm `401`/OAuth discovery without credentials and `403` for
   unauthorized users.
4. Store these values as Cloudflare Worker secrets (never GitHub source code):
   `GEMINI_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.
5. Deploy from Cloudflare with
   `npx wrangler deploy --config wrangler.chatgpt.jsonc`.
   The initial deployment may require setting the secrets at the same time.
   Do not use `npx wrangler deploy` without the specified configuration.
6. Use the live `/mcp` URL in ChatGPT's **Add custom MCP server** form, with
   OAuth selected. Verify a real private sign-in and a short public YouTube
   test before considering the integration complete.

The existing Gemini service may exceed Cloudflare Workers Free limits on
long-running calls. Test short clips first and watch usage. Gemini may also
have separate usage or billing limits.

This is a single-user setup. Changing the account or Worker hostname
requires updating both the OAuth account check and resource URL.

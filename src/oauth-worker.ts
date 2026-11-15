/**
 * ChatGPT-facing production entry point.
 *
 * The Cloudflare OAuthProvider validates every /mcp request before it reaches
 * the original video MCP application. We deliberately use AUTH_MODE=none only
 * on the *inner*, unreachable-by-itself application to avoid a second auth
 * gate after OAuthProvider has already checked the token.
 */
import OAuthProvider from '@cloudflare/workers-oauth-provider';
import { githubAuth } from './github-oauth';
import { createApp } from './platform/app';
import { parseConfig } from './platform/config';

type VideoEnv = Env & {
  OAUTH_KV: KVNamespace;
  GEMINI_API_KEY: string;
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  MCP_PUBLIC_URL: string;
};

const apiHandler = {
  async fetch(request: Request, env: VideoEnv, ctx: ExecutionContext) {
    // OAuthProvider verifies the token; the tool gate additionally enforces
    // the exact owner identity and the mcp:read scope before any Gemini calls.
    const caller = ctx as ExecutionContext & {
      auth?: { scope?: string[] };
      props?: { githubUserId?: string };
    };
    if (caller.props?.githubUserId !== '357125258' || !caller.auth?.scope?.includes('mcp:read')) {
      return new Response('Forbidden', { status: 403 });
    }
    const config = parseConfig({ ...env, AUTH_MODE: 'none' });
    const app = createApp(config, {
      runtime: { waitUntil: (promise) => ctx.waitUntil(promise) },
    });
    return app.fetch(request);
  },
} satisfies ExportedHandler<VideoEnv>;

export default new OAuthProvider<VideoEnv>({
  apiRoute: '/mcp',
  apiHandler,
  defaultHandler: githubAuth,
  authorizeEndpoint: '/authorize',
  tokenEndpoint: '/oauth/token',
  clientRegistrationEndpoint: '/register',
  scopesSupported: ['mcp:read'],
  requiredScopes: ['mcp:read'],
  clientIdMetadataDocumentEnabled: true,
  resourceMetadata: {
    resource: 'https://rocket-league-video-mcp.mechanicalenginering-s-t.workers.dev/mcp',
    authorization_servers: ['https://rocket-league-video-mcp.mechanicalenginering-s-t.workers.dev'],
  },
});

import { AuthorizationError, type OAuthHelpers } from '@cloudflare/workers-oauth-provider';
import { Hono } from 'hono';
import { html } from 'hono/html';

type OAuthBindings = Env & {
  OAUTH_PROVIDER: OAuthHelpers;
  OAUTH_KV: KVNamespace;
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  GEMINI_API_KEY: string;
};

const ALLOWED_GITHUB_USER_ID = 357125258; // mechanicalengineringst-png
const githubAuth = new Hono<{ Bindings: OAuthBindings }>();

// Log only the step and exception class, never OAuth codes, browser state,
// access tokens, request URLs, cookie values, or raw exception messages.
async function callbackStep<T>(stage: string, operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    const type = error instanceof Error ? error.name : 'UnknownError';
    console.error('[video-mcp oauth] callback failure', { stage, type });
    throw error;
  }
}

// This Worker can be created before secrets exist, but never authorize or
// spend Gemini quota until all three credentials are configured.
githubAuth.use('*', async (c, next) => {
  if (!c.env.GITHUB_CLIENT_ID || !c.env.GITHUB_CLIENT_SECRET || !c.env.GEMINI_API_KEY) {
    return c.text('Service is not configured yet.', 503);
  }
  await next();
});

// Consent precedes GitHub login. Cloudflare binds the consent handle and OAuth
// state to the browser; another MCP client cannot reuse prior approval silently.
githubAuth.get('/authorize', async (c) => {
  const oauth = c.env.OAUTH_PROVIDER;
  const request = await oauth.parseAuthRequest(c.req.raw);
  const details = await oauth.describeConsent(request);
  const consent = await oauth.beginConsent(request);

  const page = html`<!doctype html>
    <html lang="en">
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Authorize Rocket League Video MCP</title>
        <style>
          body { font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 1rem; line-height: 1.55; }
          form { display: flex; gap: .75rem; margin-top: 1.5rem; }
          button { padding: .65rem 1rem; cursor: pointer; }
        </style>
      </head>
      <body>
        <h1>Allow ${details.clientName} to use the private video analyzer?</h1>
        <p>Requested permission: <strong>mcp:read</strong> (watch public YouTube videos using your Gemini API quota).</p>
        <p>After authorization, access returns to <strong>${details.redirectHost}</strong>.</p>
        <p>Only the repository owner's GitHub account is permitted to sign in.</p>
        <form method="post">
          <input type="hidden" name="handle" value="${consent.handle}">
          <button type="submit" name="decision" value="approve">Continue to GitHub</button>
          <button type="submit" name="decision" value="deny">Deny</button>
        </form>
      </body>
    </html>`;
  consent.headers.set('Content-Type', 'text/html; charset=utf-8');
  consent.headers.set('Cache-Control', 'no-store');
  return new Response(await page, { headers: consent.headers });
});

githubAuth.post('/authorize', async (c) => {
  const oauth = c.env.OAUTH_PROVIDER;
  const form = await c.req.raw.formData();
  const handle = String(form.get('handle') ?? '');

  if (form.get('decision') !== 'approve') {
    const denied = await oauth.denyConsent(c.req.raw, handle);
    return new Response(null, { status: 302, headers: denied.headers });
  }
  const approved = await oauth.approveConsent(c.req.raw, handle);
  const verifier = crypto.randomUUID() + crypto.randomUUID();
  const { state, headers } = await oauth.beginUpstream(approved.request, {
    data: { verifier },
    headers: approved.headers,
  });

  const challenge = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  const challenge64 = btoa(String.fromCharCode(...new Uint8Array(challenge)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  const redirect = new URL('https://github.com/login/oauth/authorize');
  redirect.searchParams.set('client_id', c.env.GITHUB_CLIENT_ID);
  redirect.searchParams.set('redirect_uri', new URL('/callback', c.req.url).href);
  redirect.searchParams.set('scope', 'read:user');
  redirect.searchParams.set('state', state);
  redirect.searchParams.set('code_challenge', challenge64);
  redirect.searchParams.set('code_challenge_method', 'S256');
  headers.set('Location', redirect.href);
  return new Response(null, { status: 302, headers });
});

githubAuth.get('/callback', async (c) => {
  const oauth = c.env.OAUTH_PROVIDER;
  const {
    request: original,
    data,
    headers,
  } = await callbackStep('restore-upstream-state', () =>
    oauth.finishUpstream<{ verifier: string }>(c.req.raw),
  );
  const code = new URL(c.req.url).searchParams.get('code');
  if (!code) return c.text('GitHub did not return an authorization code.', 400);

  const exchange = await callbackStep('github-token-exchange', () =>
    fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: c.env.GITHUB_CLIENT_ID,
        client_secret: c.env.GITHUB_CLIENT_SECRET,
        code,
        code_verifier: data.verifier,
        redirect_uri: new URL('/callback', c.req.url).href,
      }),
      redirect: 'error',
    }),
  );
  if (!exchange.ok) {
    console.error('[video-mcp oauth] github token endpoint non-success', {
      status: exchange.status,
    });
    return c.text('GitHub authorization could not be completed.', 502);
  }
  const token = (await callbackStep('parse-github-token', () => exchange.json())) as {
    access_token?: string;
    error?: string;
  };
  if (!token.access_token) {
    console.error('[video-mcp oauth] github token response missing access_token', {
      error: token.error === 'bad_verification_code' ? 'bad_verification_code' : 'unspecified',
    });
    return c.text('GitHub did not issue an access token.', 502);
  }

  const whoami = await callbackStep('github-user-request', () =>
    fetch('https://api.github.com/user', {
      headers: {
        Authorization: `Bearer ${token.access_token}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'rocket-league-video-mcp',
      },
      redirect: 'error',
    }),
  );
  if (!whoami.ok) {
    console.error('[video-mcp oauth] github user endpoint non-success', { status: whoami.status });
    return c.text('Could not verify the GitHub account.', 502);
  }
  const identity = (await callbackStep('parse-github-user', () => whoami.json())) as {
    id?: number;
    login?: string;
  };

  // Fail closed: a GitHub login alone does not grant access to Gemini quota.
  if (identity.id !== ALLOWED_GITHUB_USER_ID || identity.login !== 'mechanicalengineringst-png') {
    return c.text('This GitHub account is not permitted to use the private video analyzer.', 403);
  }

  const { redirectTo } = await callbackStep('complete-chatgpt-authorization', () =>
    oauth.completeAuthorization({
      request: original,
      userId: String(identity.id),
      metadata: { label: identity.login },
      scope: original.scope,
      props: { githubUserId: String(identity.id), login: identity.login },
    }),
  );
  headers.set('Location', redirectTo);
  return new Response(null, { status: 302, headers });
});

githubAuth.onError((error, c) => {
  if (error instanceof AuthorizationError) {
    if (error.redirectTo) return c.redirect(error.redirectTo, 302);
    return c.text(error.description, 400);
  }
  // Do not reflect stack traces, access tokens or credentials to clients.
  return c.text('Authorization failed.', 500);
});

export { githubAuth };

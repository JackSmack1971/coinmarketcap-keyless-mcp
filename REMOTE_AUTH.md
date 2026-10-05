# Remote MCP OAuth hardening

Status: approved by the repository owner for the private ChatGPT plugin deployment requested on 2026-10-05.

This record supersedes the earlier local-only assumption for Streamable HTTP **only when the remote OAuth configuration below is present**. It does not change the CoinMarketCap upstream boundary: upstream access remains keyless, fixed-host, GET-only, allowlisted, and read-only.

## Security objective

An internet-facing `/mcp` endpoint must not be anonymously usable to consume the deployment's keyless CoinMarketCap rate limit. Local stdio and loopback Streamable HTTP remain available without remote OAuth.

## Remote authorization contract

Internet-facing Streamable HTTP uses OAuth 2.1 authorization-code flow with PKCE `S256` and MCP protected-resource metadata.

- The MCP protected resource is `<CMC_MCP_PUBLIC_URL>/mcp`.
- The only granted scope is `cmc:read`.
- Authorization codes are short-lived and HMAC-signed.
- Access tokens are audience-bound to the exact protected resource.
- Refresh tokens are rotated on use.
- Authorization-code and refresh-token replay is rejected within a running process.
- Client identifiers must use ChatGPT callback-specific Client ID Metadata Document form: `https://chatgpt.com/oauth/<callback_id>/client.json`.
- Redirect URIs are derived from and fixed to the matching ChatGPT callback: `https://chatgpt.com/connector/oauth/<callback_id>`.
- `CMC_MCP_ALLOWED_CLIENT_ID`, when set after initial connection, pins the deployment to one exact ChatGPT connector client ID.
- No bearer token, authorization code, refresh token, or signing key may be logged.

The OAuth authorization endpoint is intentionally approval-less because the MCP tools expose only public, read-only market data. Authorization here protects the remote transport/rate-limit budget rather than private end-user data. The PKCE flow and ChatGPT-only redirect binding prevent a non-ChatGPT caller from receiving a usable authorization code.

## Required deployment configuration

Remote non-loopback HTTP fails closed unless both variables are present:

- `CMC_MCP_PUBLIC_URL`: public HTTPS origin only, for example `https://coinmarketcap-keyless-mcp.onrender.com`.
- `CMC_MCP_OAUTH_SIGNING_KEY`: server-side secret of at least 32 bytes. Store only in the deployment secret/environment manager; never commit it or place it in plugin files.

Optional hardening after the first successful ChatGPT connection:

- `CMC_MCP_ALLOWED_CLIENT_ID`: exact callback-specific ChatGPT client ID observed during the initial OAuth authorization. Once set, every other client ID is rejected.

## Runtime behavior

- `stdio`: unchanged; no OAuth.
- loopback `streamable-http`: always remains local and unauthenticated; remote OAuth environment variables are ignored on loopback binds.
- non-loopback `streamable-http`: refuses startup without OAuth configuration.
- authenticated non-loopback HTTP: exposes `/mcp`, RFC 9728 protected-resource metadata, OAuth authorization-server metadata, `/authorize`, and `/token`.

## Non-goals

This change does **not** introduce CoinMarketCap API keys, authenticated CoinMarketCap fallback, arbitrary upstream headers, write tools, trading, wallets, signing, custody, or a generic proxy.

## Verification requirements

Before deploying remotely, verify at minimum:

1. configuration fails closed when only part of the OAuth environment is present;
2. non-loopback Streamable HTTP refuses startup without OAuth;
3. OAuth metadata advertises authorization-code + refresh-token grants, PKCE `S256`, and public-client token authentication;
4. wrong client IDs, redirect URIs, resources, scopes, and PKCE verifiers fail;
5. authorization code replay fails;
6. refresh token replay fails after rotation;
7. a valid access token is accepted by the MCP bearer verifier and is bound to the exact `/mcp` resource;
8. existing stdio and loopback transport tests remain green.

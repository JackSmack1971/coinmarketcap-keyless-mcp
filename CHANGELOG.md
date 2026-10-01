# Changelog

## Unreleased

- Bounded the response cache to 64 entries, evicting expired entries first and then the least recently used.
- `symbols` and `convert` items now reject commas and whitespace and are capped at 64 characters, so comma-joined strings can no longer bypass list-size and uniqueness bounds.
- `verify_live` now exits non-zero when any route is not classified `SUPPORTED`.

## 1.0.1

- Added CI and static quality gates, with stronger mutation and negative-path coverage.
- Hardened streaming response-size enforcement, compressed-response and deep-JSON handling, and security boundaries.
- Improved cleanup reliability and qualified isolated wheel and source distribution installs.
- Completed fresh, credential-free live qualification of all 13 released routes.

## 1.0.0

- Released 13 keyless CoinMarketCap MCP tools over stdio and Streamable HTTP transports.
- Added bounded retry, cache, and concurrency behavior.
- Added live keyless capability verification; all 13 released routes are verified supported.
- Preserved a credential-free, read-only design.

# Changelog

## Unreleased

- Cross-field validation failures (selectors, duplicate values, timestamps, map argument combinations) now reach MCP clients as `INVALID_ARGUMENT: <reason>`. MCP SDK 2.2 previously reported them as a generic, unclassified tool crash.
- Only HTTP 2xx responses can succeed. Redirects (3xx) with a success-shaped body are `UPSTREAM_HTTP_ERROR`, never success, and are never cached.
- `NaN`, `Infinity`, `-Infinity` and numbers that overflow a finite float (such as `1e400`) are rejected as `UPSTREAM_CONTRACT_MISMATCH` instead of being returned and cached.
- Compressed responses must end with a complete stream: a gzip body missing its CRC/length trailer, or a deflate body cut short, is `UPSTREAM_CONTRACT_MISMATCH` even when the decoded prefix is valid JSON.
- `verify_live` checks endpoint-specific minimum fields and types taken from CoinMarketCap's published response schemas, instead of accepting any non-empty object or list. Live capability must be requalified with the stricter checks.

## 1.0.2

- CI runs mutmut and fails if the mutation score (killed + timeout) drops below 92%. Reviewing the surviving mutants added `tests/unit/test_client_contract.py` and widened mutmut's test selection; the score went from 61.6% to 93.0%, and the 70 remaining survivors are all equivalent (see `verification/mutation-survivors.md`). Removed the unused `_cache_enabled` attribute and an unreachable empty-selector check.
- Dev dependencies: bumped `pytest` to `>=9.0.3,<10` (fixes PYSEC-2026-1845) and `pytest-asyncio` to `>=1.3,<2`, which pytest 9 requires.
- Non-retryable 4xx errors now include the provider's error message when the body carries one (read up to 4 KiB and sanitized).
- A `Retry-After` longer than the backoff cap now stops retrying immediately with the final classification, instead of retrying early.
- Each upstream attempt has a 30-second wall-clock deadline, so a slow-drip body cannot hold capacity indefinitely.
- Identical concurrent cold requests share one upstream fetch. The cache stores validated response bytes, and payloads over 64 KiB are parsed off the event loop.
- JSON nested deeper than 256 levels is rejected as `UPSTREAM_CONTRACT_MISMATCH` on every Python version (Python 3.14's parser accepts deeper nesting than 3.11's).
- `deflate` responses without a zlib header, and multi-member `gzip` responses, now decode correctly.
- Shutdown cleanup gives up after 10 seconds instead of waiting forever.
- Binding Streamable HTTP to a non-loopback host logs a warning.
- `mcp` is pinned to `>=2.2,<2.3` because the server relies on private SDK internals; `uvicorn` now has an upper bound.
- The sdist now includes `LICENSE`.
- Licensed under MIT (`LICENSE`, `license` metadata in `pyproject.toml`).
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

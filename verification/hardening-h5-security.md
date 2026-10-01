# H5 security and failure-mode evidence

## Run identity

- Recorded: 2026-10-01 04:29 UTC
- Environment: Windows 11 x86_64, PowerShell, CPython 3.14.3, uv 0.12.7
- Branch: `hardening/v1.0.1`; worktree was clean before H5 edits
- Fixtures: HTTPX mock transports, bounded subprocesses, and loopback transport tests; no live CoinMarketCap calls
- Dependencies and `uv.lock`: unchanged

## Findings and changes

- Exact membership in `ROUTES.values()` plus HTTPX's fixed `BASE_URL` rejects hostile route strings before transport. Absolute and scheme-relative URLs, alternate schemes, userinfo/ports, dot and encoded-dot segments, duplicate separators, query/fragment suffixes, backslashes, and a Unicode lookalike were exercised. A valid request remains HTTPS to `pro-api.coinmarketcap.com`, port-default, at `/public-api` plus one allowlisted route. This is structural enforcement, not a denylist.
- Runtime and client code read no environment variables. The production client has no caller header argument, and params only serialize into the query. Adversarial `Authorization`, `X-CMC_PRO_API_KEY`, `Cookie`, `Host`, and URL-like params did not alter headers, method, host, port, or route. Plausible CMC credential/base-URL environment variables did not affect construction. HTTP bind defaults to `127.0.0.1`; a non-loopback bind requires an explicit `--host`. Transport choices and port range are constrained by argparse; invalid invocation exits 2 with usage on stderr and no traceback. No auth was added to local HTTP.
- `httpx.aiter_bytes()` could allocate an expanded decoded chunk before the existing byte accumulator enforced 2 MiB. The client now advertises only gzip/deflate and incrementally decodes those encodings with zlib's `max_length`, stopping at at most 2 MiB + 1 decoded bytes (the extra byte is the rejection sentinel). It retains at most that same amount; crossing the limit yields `UPSTREAM_CONTRACT_MISMATCH`, closes the stream, and never caches. Identity responses are streamed under the same accumulator bound. The deterministic gzip fixture was smaller than 2 MiB compressed and expanded beyond 2 MiB; rejection occurred before JSON parsing and the next valid response succeeded and cached normally. Declared `Content-Length` remains an early rejection when larger than 2 MiB.
- A malformed gzip stream could otherwise escape as a low-level decompression error. The client now classifies zlib decode failures as `UPSTREAM_CONTRACT_MISMATCH`; a streamed malformed-gzip adversarial case verifies the stable classification.
- Malformed text, truncated JSON, scalars, arrays, null/wrong-type/missing status fields, invalid error-code types, missing data, and duplicate object keys remain `UPSTREAM_CONTRACT_MISMATCH`. Duplicate keys now fail closed rather than using Python's last-key-wins parser behavior. Deep JSON that parses but exceeds Python's safe recursive copy depth is converted to the same contract mismatch instead of escaping as `RecursionError`; it is not cached and a later valid response can succeed.
- Provider application error text is limited to 256 characters and control characters are replaced/collapsed to one line. `UPSTREAM_APPLICATION_ERROR` remains visible. INFO logs do not include provider bodies; runtime cache logs include only fixed route identities. Source inspection and stdio subprocess tests cover startup, discovery, tool failure, cleanup, and stdout protocol integrity; arbitrary cleanup diagnostics are on stderr.
- Retry probes cover three-attempt exhaustion for repeated 429, huge/negative/non-finite/invalid `Retry-After`, alternating 429/503/504, and retryable-then-malformed success. Delays remain capped at 2 seconds by production defaults and occur outside the semaphore. Existing tests cover HTTP-date parsing, 502/503/504 recovery, cancellation during delay, and permit release. Failures and cancellation are not cached.
- Repeated cancellation during owned client cleanup is now shielded until cleanup completes; cleanup failure during MCP server construction also closes the client. Event-controlled tests cover repeated cancellation, and existing HTTP tests verify shutdown releases the loopback port. `CancelledError` propagates after cleanup.
- MCP errors contain stable classifications and bounded sanitized provider detail. They do not include response bodies, stack traces, filesystem paths, environment values, or internal test configuration.

## Verification

- `uv run pytest tests/security/test_h5.py -q --disable-warnings` — 43 passed.
- `uv sync` — passed; 55 resolved, 53 checked; lock unchanged.
- `uv run ruff check src tests` — passed.
- `uv run pytest tests/unit -q --disable-warnings` — 118 passed.
- `uv run pytest tests/contract -q --disable-warnings` — 9 passed.
- `uv run pytest tests/mcp -q --disable-warnings` — 32 passed.
- `uv run pytest -q --disable-warnings` — 202 passed.
- `uv build --out-dir "$env:TEMP\\cmc-h5-artifacts"` — wheel and sdist built from the H5 worktree.
- `uv run python scripts/qualify_packaging.py --artifacts "$env:TEMP\\cmc-h5-artifacts"` — passed: wheel and sdist on Python 3.11/3.14, plus installed wheel Streamable HTTP smoke.
- `uv build` — wheel and sdist built.
- `uv lock --check` — passed.
- `git diff --check` — run at final review.

Pytest emitted existing pytest-asyncio event-loop-policy deprecation warnings; no failures. No dependency vulnerability or need for a dependency update was identified. No public tool, schema, route, output, error-code meaning, cache TTL, concurrency default, CLI option, or transport name changed.

## Remaining limitations

H5 is a bounded local adversarial audit, not a third-party penetration test or live provider qualification. HTTP-date handling and delay cancellation rely on existing H3/client tests in addition to the H5 table-driven cases. Only advertised gzip/deflate encodings are decoded by the bounded path; other content encodings fail closed as contract mismatch. The effective decoded body is capped, while the transport may already have delivered one bounded raw input chunk to the decoder. No H6 or live route verification was performed.

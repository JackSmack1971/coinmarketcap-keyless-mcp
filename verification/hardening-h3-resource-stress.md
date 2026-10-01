# H3 resource stress evidence

Recorded 2026-10-01 UTC on Windows, PowerShell, CPython 3.14.3;
repository-local uv environment. Branch: `hardening/v1.0.1`;
pre-edit baseline: `37f523b`. Worktree and index were clean before editing.
All upstream fixtures are local HTTPX transports. No live provider verification,
mutation campaign, dependency change, commit, push, or H4 work was performed.

## Defect and fix

The existing `AsyncClient.get()` buffered the entire body before the 2 MiB
check. It now uses an async streaming context while holding the per-attempt
semaphore, rejects a declared length greater than the maximum, and accumulates
at most 2 MiB + 1 decoded bytes. On crossing the boundary it raises the existing
`UPSTREAM_CONTRACT_MISMATCH`, closes the stream, and releases capacity. Partial
JSON is never parsed. Valid complete responses retain envelope validation and
deep-copy/cache behavior. Error HTTP statuses are classified without consuming
their bodies; retry delays occur after both stream closure and semaphore release.
The API used follows [HTTPX async streaming documentation](https://www.python-httpx.org/async/).

No cache, semaphore, or transport production defect was found in these checks.
Only `client.py` changed in production. The 13 names, schemas, routes, stable
error codes, GET-only fixed keyless destination, TTLs, default concurrency 2,
2 MiB default limit, and transport invocation surface remain unchanged.

## Deterministic cases

- Nine boundary combinations: 2,097,151, 2,097,152, and 2,097,153 bytes with
  absent, misleading-small, or accurate Content-Length. The first two sizes
  pass with valid JSON; the last fails. Accurate oversized declaration reads
  zero body bytes.
- Four 8 MiB streams: absent length, misleading length, chunked header, and
  oversized declared length. Undeclared/misleading/chunked streams stop at the
  first crossing chunk (at most 2 MiB + 4 KiB delivered by the test transport);
  the declared oversized body is never iterated. All streams close. The client
  accumulator retains at most limit + 1 bytes, including the rejection sentinel.
- Malformed streamed JSON below the limit remains contract mismatch.
- Ten contention cases: 24 simultaneous identical, different-key, disabled-cache,
  expired-cache, or application-error misses at capacities 2 and 3. All callers
  reach semaphore acquisition before release. Peak active upstream attempts
  equal the configured bound, capacity fully returns, and no deadlock occurs.
- Successful completion is cacheable; 48 subsequent concurrent hits require no
  network attempts. Disabled cache requires all 48 attempts. Both fresh-return
  and cached-return nested mutation isolation are asserted. Errors under
  contention are never cached.
- Fake time advances to exact 30-second expiry. No stale generation is returned;
  duplicate refreshes stay bounded and final cached results remain valid. A
  separate 24-reader barrier/lock test proves exact expiry and deletion, plus
  deep-copy isolation of the object supplied to cache storage.
- Four failure paths during active body consumption: cancellation, read timeout,
  network error, and provider application error. Each also cancels a confirmed
  semaphore waiter. Responses close, cancellation propagates, capacity returns,
  and a later identical request reaches upstream successfully.
- Four retry/backoff cases: repeated 429/503 with exhaustion or cancellation
  during an event-controlled delay. Another key completes using capacity 1 while
  the first sleeps. Retry exhaustion remains RATE_LIMITED/UPSTREAM_5XX at three
  attempts. Errors are not cached. A separate 503-then-success case proves no
  cache population during retry delay and caching only after final success.
- Repeated client close after success (with cached data) and after failure closes
  the owned transport once. Uncached calls after close raise HTTPX's RuntimeError
  before network access; existing cache-only reads after close remain possible.
- Client close concurrent with an active request and explicit request cancellation
  completes, closes the response/transport, releases capacity, and stores no
  partial result.
- Added subprocess stdio idle EOF test proves exit code 0, empty stdout, and
  client cleanup on stderr. Existing stdio tests retain tool-completion and handled
  error shutdown coverage.
- Two added HTTP shutdown cases cover idle sessions and completion of an
  event-controlled active tool call before shutdown. Runtime cancellation closes
  the owned client and releases the listening port. Existing HTTP and parity
  tests continue to pass. Local readiness/port checks reuse bounded polling because
  sockets have no shared in-process readiness event; concurrency assertions use
  events/barriers, not elapsed-time thresholds.

Duplicate identical misses are deliberately retained: v1 does not promise
single-flight. All 24 callers may fetch, but only N network attempts proceed
simultaneously, successful completed values remain isolated and cacheable, and
final state is valid. No optimization or public lifecycle API was added.

## H2 deferred survivor audit

The H2 report aggregates 40 deferred cache key/TTL/cache-state survivors without
individual mutant IDs or diffs. Historical counts and classifications are left
unchanged. H3 supplies behavioral evidence for those deferred categories:

| Deferred behavior | H3 evidence / conceptual disposition |
| --- | --- |
| Cache identity / effective query | Existing deterministic route/query/list serialization tests plus different-key contention; now exercised within H3 |
| TTL policy / expiry comparison / stale-entry removal | Existing route TTL assertions and fake-clock tests, exact-boundary concurrent refresh and lock-contended expiry; now exercised within H3 |
| Cache get/set state / copying | Concurrent misses/hits, direct source mutation after set, nested return mutation isolation, final valid cached state; now exercised within H3 |
| Disabled cache / errors | Concurrent disabled/error cases plus existing error non-caching tests; now exercised within H3 |
| Constructor cache bounds among H2's aggregate constructor group | Existing invalid TTL/route/configuration tests retained; concurrency default/configured bounds now stressed |

These categories are no longer deferred behavioral coverage. This is not a
claim that all 40 historical mutants were killed: the retained H2 report cannot
identify each exact edit, and no mutation rerun was performed. Cache/retry target
logic is unchanged; the production edit replaces buffering, covered directly by
stream-consumption assertions and existing size/error/retry regression tests.

## Verification

- Initial focused client/resource run: 91 passed.
- Focused resource + stdio + HTTP run: 43 passed, then 44 passed after the direct
  cache storage/expiry test. The focused cases also run in both the module suites
  and full regression, providing repeated qualification.
- `uv sync`: passed, 55 packages resolved, 53 checked; lock unchanged.
- `uv run ruff check src tests`: passed.
- `uv run pytest tests/unit -q --disable-warnings`: 118 passed.
- `uv run pytest tests/contract -q --disable-warnings`: 9 passed.
- `uv run pytest tests/mcp -q --disable-warnings`: 32 passed.
- `uv run pytest -q --disable-warnings`: 159 passed.
- `uv build`: wheel and sdist built at existing version 1.0.0.
- `uv lock --check`: passed.
- `git diff --check`: passed.

Pytest reports Python 3.14 event-loop-policy deprecation warnings from the
installed pytest-asyncio dependency. No failures or test weakening occurred.

## Limits and disposition

This proves bounded deterministic local cases, not throughput, live provider
capacity, cross-platform soak behavior, or H4 installed-package qualification.
HTTPX/transport decoding may deliver a chunk larger than the remaining allowance;
the client stops at that first chunk and bounds its own retained accumulation,
but cannot undo bytes already delivered or decoder allocation for that chunk.
Compressed-bomb/deep-JSON abuse qualification remains H5 scope. Shutdown retains
HTTPX ownership semantics: callers cancel/await their active request tasks;
`aclose()` does not add a task registry or promise to drain arbitrary callers.
Repeated cancellation interrupting cleanup itself is not qualified here.

Disposition: `H3_RESOURCE_STRESS_QUALIFIED` / `H3_ACCEPTED` for this offline H3
slice. No release-readiness or live-support claim is made. At evidence capture,`r`nchanges were unstaged and uncommitted; H4 had not begun.

# `coinmarketcap-keyless-mcp` — Post-release hardening plan

**Plan status:** REVIEWED — READY FOR H1 IMPLEMENTATION
**Baseline:** `v1.0.0` (`main` / `origin/main` at `2862e92`)
**Working branch:** `hardening/v1.0.1`
**Purpose:** improve engineering quality, reliability, test strength, packaging confidence, and failure-mode resilience without changing the released 13-tool MCP contract.

This document is an implementation map for the post-release hardening cycle. It authorizes planning and sequencing, not implementation by itself. Each phase must remain within the public-contract boundary below and must satisfy its own exit gate before the next phase begins. H1–H6 are the only planned slices; H1 must not begin until separately requested.

## 1. Hardening invariants

The following remain release-blocking invariants throughout H1–H6:

- The public MCP surface remains exactly the 13 tools defined by `PLAN.md` Section 8.
- No DEX tools, generic request/path proxy, new route, new public parameter, or new derived functionality is added.
- The production upstream base remains exactly `https://pro-api.coinmarketcap.com/public-api`.
- Upstream requests are GET-only and route selection is an explicit allowlist.
- User input cannot control scheme, host, port, arbitrary path, method, or headers.
- No API key, bearer token, cookie, wallet, signing, credential environment variable, authenticated fallback, or equivalent auth path is read, accepted, stored, logged, or emitted.
- A successful HTTP status is insufficient without a valid CMC envelope and successful normalized `status.error_code`.
- Exhausted HTTP 429 is `RATE_LIMITED`, never proof of unsupported capability.
- Validation, retry, cache, concurrency, response size, and transport behavior remain bounded.
- Provider market values and the stable output envelope are preserved.
- stdio stdout is reserved for MCP protocol traffic; diagnostics belong on stderr/configured logging.
- Hardening must not make cache behavior a correctness dependency.

### Explicit scope boundary

This cycle may fix defects, strengthen tests, add developer/release tooling, and clarify operational evidence. It may not change tool names, descriptions, schemas, route mappings, output shapes, stable error classifications, transport-visible expectations, or configuration categories except where a backward-compatible defect fix is necessary and separately reviewed. Any proposed public functionality, new MCP tool, route, or contract change stops this cycle and requires a separate plan and version decision.

## 2. Release-blocking and advisory checks

Release-blocking checks are: exact 13-tool discovery and schema parity; authentication/host/method/route invariants; envelope and error classification; local validation; stdio protocol integrity; non-live regression; packaging/install qualification; transport qualification; security review; and current live classification for all 13 released routes. A failure in any of these prevents a release claim.

Advisory checks include additional lint rules, non-required type warnings, benchmark observations, mutation survivors that are demonstrably unreachable without changing the public contract, and platform-specific transport checks outside the declared support matrix. Advisory results must still be recorded and must not be silently converted into passes.

## 3. Failure classification and evidence rules

Use the existing taxonomy and preserve distinctions:

| Failure | Classification / handling |
| --- | --- |
| Local schema, unknown argument, or cross-field violation | `INVALID_ARGUMENT`; no upstream request |
| Exhausted HTTP 429 | `RATE_LIMITED`; route capability remains unresolved/support-preserving |
| Timeout, network failure, or retryable 5xx after bounded retry | existing transient upstream classification |
| Malformed JSON, malformed envelope, or invalid provider success shape | `UPSTREAM_CONTRACT_MISMATCH` |
| Valid envelope with provider application error | `UPSTREAM_APPLICATION_ERROR` |
| Positive documented/live evidence that a route is unavailable | `UNSUPPORTED_ROUTE`; never inferred from arbitrary exceptions, 429, or one transient result |
| Protocol, packaging, security, or invariant violation | release-blocking hardening failure |

Every release-blocking result must be reproducible from a command, fixture, test report, mutation report, package artifact, or transport transcript that retains only the minimum safe data. Evidence must identify the commit/branch, command, environment or matrix entry, timestamp where relevant, result, and failure classification. Live evidence must identify the exact keyless base URL, route/tool, no-credential mode, and route-level classification without retaining full market payloads.

## 4. Phase H1 — CI and static quality gates

### Objective

Establish a minimal, reproducible CI qualification layer that catches regressions before packaging or release without adding tools merely because they are fashionable.

### Exact scope

- Add `.github/workflows/ci.yml` with exactly three blocking jobs: Ubuntu + Python 3.11, Ubuntu + Python 3.14, and Windows + Python 3.14. The declared minimum and current newest supported minor catch lower-bound and forward-compatibility regressions; one Windows job covers subprocess/port behavior without a full OS/version Cartesian product. MCP SDK v2 metadata supports Python 3.11–3.14; each job must prove dependency resolution and tests pass.
- Every job runs `uv sync --locked --all-groups`, `uv run pytest`, `uv run ruff check src tests`, `uv build`, and `uv lock --check`. These checks do not call CoinMarketCap; package-index access for dependencies is expected. Live verification is never invoked in CI.
- Run in-process MCP and stdio subprocess tests in all jobs. Run Streamable HTTP localhost tests on Ubuntu 3.11 and Windows 3.14; omit only the redundant Ubuntu 3.14 run. Tests must bind loopback and use bounded readiness/cleanup.
- Adopt Ruff as a release-blocking lint and import-order gate only. Configure only `E4`, `E7`, `E9`, `F`, and `I`; add Ruff to the dev group and lock. Exact command: `uv run ruff check src tests`. Do not adopt formatting or run `ruff format`; resolve baseline violations narrowly, without mass reformatting.
- Do not add a type checker in v1.0.1. Annotations are selective and there is no defined, high-value checker scope; a partial checker would create an unclear gate. Reassess separately when a typing boundary is defined.
- Build wheel and sdist in CI. Clean-install isolation and installed behavior qualification belong to H4.

### Non-goals

- No product behavior change, schema change, dependency upgrade for its own sake, or live network calls in ordinary CI.
- No formatter, type checker, coverage threshold, or extra Python/OS matrix entries.
- No CI job that requires credentials or treats rate limiting as a test failure.

### Candidate files

- `.github/workflows/ci.yml` (new, if justified)
- `pyproject.toml`, `uv.lock`, `README.md`
- `src/coinmarketcap_keyless_mcp/`, `tests/`
- `PLAN.md`, `HARDENING_PLAN.md`

### Tests and checks

- `uv sync --locked --all-groups`
- `uv run pytest`
- `uv run ruff check src tests`
- `uv build`
- `uv lock --check`

### Acceptance criteria

- The blocking CI matrix is exactly Ubuntu/Python 3.11, Ubuntu/Python 3.14, and Windows/Python 3.14; each job resolves the lock and passes required checks.
- Offline tests are isolated from live verification and pass on every blocking matrix entry.
- Ruff lint and import-order checks have a clean baseline; violations are fixed narrowly, never ignored wholesale.
- No type check is part of the v1.0.1 gate.
- CI does not expose credentials, run arbitrary upstream requests, contaminate stdio, or weaken tests.

### Exit gate

`H1_CI_QUALIFIED`: the blocking matrix, offline suite, package build validation, and selected static checks pass, with advisory findings recorded and no unresolved release-blocking issue.

### Commit checkpoint

Create one reviewable `hardening H1: establish CI and static quality gates` commit only after the gate passes. Do not mix mutation, stress, or packaging implementation into it. H1 is a distinct logical commit.

### PR review checkpoint

Yes. CI permissions, trust boundaries, dependency installation, action pinning, cache behavior, and release-blocking semantics require PR review.

## 5. Phase H2 — Mutation and negative-path testing

### Objective

Measure whether tests detect mutations of the security, routing, validation, envelope, error, and protocol invariants that protect the v1 release.

### Exact scope

Target mutation campaigns at:

- fixed upstream host/base path;
- GET-only request construction;
- allowlisted one-route-per-tool mapping;
- no authentication headers or credential reads;
- absence of generic proxy behavior;
- 429 classification as `RATE_LIMITED`;
- envelope and normalized error-code validation;
- schema, unknown-argument, selector, and cross-field validation;
- MCP error propagation and stable classifications;
- stdio framing and stdout protocol integrity.

Use `mutmut>=3.6,<4` as an opt-in developer tool, not a per-commit or CI gate. This line supports current Python versions and exposes explicit mutation timeout settings. Target only `client.py`, `contracts.py`, `models.py`, and `server.py`; runtime entrypoints and transport process behavior remain covered by deterministic tests rather than mutation runs. Exclude `verify_live.py`, generated files, third-party code, tests, and live probe data. Use `source_paths`/`only_mutate` in `[tool.mutmut]`, one target and relevant test selection at a time. Set `timeout_constant=1.0`, `timeout_multiplier=5.0`, and hard-stop each target campaign at 10 minutes. Mutmut timeout survivors are recorded as timed out, never killed.

### Non-goals

- No requirement for a 100% mutation score.
- No mutation-driven public API expansion, test weakening, or broad refactoring.
- No live provider dependency in mutation runs.

### Candidate files

- `src/coinmarketcap_keyless_mcp/client.py`
- `src/coinmarketcap_keyless_mcp/contracts.py`
- `src/coinmarketcap_keyless_mcp/models.py`
- `src/coinmarketcap_keyless_mcp/server.py`
- `src/coinmarketcap_keyless_mcp/runtime.py`
- `tests/unit/`, `tests/contract/`, `tests/mcp/`
- `pyproject.toml`, `README.md`

### Tests and checks

- Add `mutmut>=3.6,<4` to the dev dependency group and resolve/lock it. Verify this selected release line installs on Python 3.11 and 3.14 before H2. Configure each bounded campaign's `source_paths`, `only_mutate`, and `pytest_add_cli_args_test_selection` in `[tool.mutmut]`; use `uv run mutmut run` then `uv run mutmut results` (configuration changes between partitions invalidate results). Set timeout constants to 1 and 5 respectively: per-mutant timeout is `(baseline test duration + 1 second) * 5`; externally stop each target at 10 minutes. Record tool version, commit, command, target, configuration, elapsed time, killed/survived/timed-out counts, and each survivor classification in a concise checked-in report. Do not retain generated cache data.
- Explicit negative tests for altered hosts, paths, methods, headers, route mappings, status success, envelope shapes, error-code normalization, unknown arguments, and stdout writes.
- Existing subprocess stdio tests assert parseable protocol output and clean shutdown; do not duplicate them.
- Run `uv run pytest` once before and once after the full campaign, not per mutant or partition.

### Acceptance criteria

- Every mutation of a release-critical invariant is killed, or has a documented survivor classification.
- Survivors are classified as: equivalent; unreachable under the public contract; defensive code outside the release boundary; test/tool limitation; or genuine coverage gap.
- Any genuine gap in a release-blocking invariant is fixed with a focused test before exit.
- Stop when all mutants are classified, at 10 minutes per target, or when remaining setup cost exceeds release-critical signal; record the stop condition. No network is used. H2 is one coherent commit after evidence and focused coverage fixes.

### Exit gate

`H2_NEGATIVE_PATHS_QUALIFIED`: all release-critical survivors are explained, no genuine release-blocking gap remains, and the full offline suite passes.

### Commit checkpoint

Create `hardening H2: strengthen invariant and negative-path coverage` after the gate, preserving the mutation report as review evidence without committing transient tool output unless repository policy requires it.

### PR review checkpoint

Yes. Independent review is appropriate for survivor classification, especially where a proposed test could accidentally encode a changed public contract.

## 6. Phase H3 — Cache, concurrency, and resource stress

### Objective

Prove deterministic behavior under contention, cancellation, resource pressure, and shutdown without relying on fragile timing sleeps.

### Exact scope

Test and harden existing cache, semaphore, HTTP-client ownership, response-size, and transport shutdown behavior. Cover concurrent cache access, duplicate simultaneous misses, TTL expiration, cached-object mutation isolation, semaphore bounds, cancellation, exceptions while capacity is held, clean HTTP-client shutdown, transport shutdown races, and oversized responses.

Use barriers, events, task groups, fake clocks, controlled transports, and bounded local servers where possible. Use sleeps only as a last-resort bounded polling mechanism with an explicit reason. Keep correctness, stress, and security-abuse tests distinct: correctness asserts exact deterministic semantics; stress uses bounded repetitions/concurrency and asserts no leaks or invariant violations, not throughput; security abuse is covered in H5.

### Non-goals

- No unbounded cache, concurrency increase, distributed coordination, performance feature, or public configuration expansion.
- No requirement to prove provider rate capacity or conduct live load testing.
- No change that makes caching necessary for correctness.

### Candidate files

- `src/coinmarketcap_keyless_mcp/client.py`
- `src/coinmarketcap_keyless_mcp/runtime.py`
- `src/coinmarketcap_keyless_mcp/server.py`
- `tests/unit/test_client.py`
- `tests/mcp/test_stdio.py`, `tests/mcp/test_streamable_http.py`, `tests/mcp/test_transport_parity.py`
- `pyproject.toml` only if test configuration requires it

### Tests and checks

- Deterministic async tests for the cache lock and duplicate-miss behavior.
- Fake-clock TTL tests at exact expiry boundaries.
- Deep-copy/mutation-isolation tests for returned and stored objects.
- Instrumented semaphore tests proving maximum in-flight upstream calls and release on success, error, cancellation, and timeout.
- Client `aclose`/context-manager tests, including repeated close and shutdown during an active request.
- Transport startup, cancellation, port release, and shutdown-race tests.
- Preserve the existing 2 MiB (`2 * 1024 * 1024`) response limit; code defines this bound and no evidence justifies changing the value. Current implementation checks size only after `httpx.get` has buffered the full body, so H3 must change the internal read to bounded streaming: reject a declared length above the limit, and read at most limit + 1 bytes when length is absent or inaccurate before classifying oversize as the existing `UPSTREAM_CONTRACT_MISMATCH`. This is an internal resource fix and must not change the MCP output/error contract. Correctness tests cover exactly-at-limit acceptance and one-byte-over rejection for declared and actual streamed bytes. Stress tests use fixed concurrency and bounded payloads with no timing or throughput threshold. H5 abuse tests cover malformed/deep JSON and oversized bodies. No test allocates an unbounded payload.

### Acceptance criteria

- No duplicate upstream call occurs for simultaneous identical misses unless the documented behavior explicitly permits it and evidence explains why.
- TTL, cache disabled, mutation isolation, and error non-caching behavior remain deterministic.
- Semaphore capacity is never leaked, including cancellation and exceptions.
- Shutdown completes without hanging tasks, leaked ports, or unclosed HTTP clients.
- Oversized responses fail with a stable bounded classification and do not cause unbounded memory use in the tested path.
- The suite is repeatable without timing-sensitive flakes.

### Exit gate

`H3_RESOURCE_STRESS_QUALIFIED`: focused resource/concurrency tests pass repeatedly, full offline regression passes, and no leak, race, or bound violation remains unexplained.

### Commit checkpoint

Create one `hardening H3: qualify cache concurrency and shutdown resilience` commit after the gate.

### PR review checkpoint

Yes. Async ownership, cancellation safety, and resource bounds deserve focused concurrency-aware review.

## 7. Phase H4 — Packaging and install qualification

### Objective

Demonstrate that the published artifacts install and run independently of the source checkout.

### Exact scope

- Build both wheel and sdist with the supported toolchain.
- Inspect package metadata, included files, entry points, dependency declarations, and version.
- Install artifacts into temporary `uv` virtual environments outside the checkout. Build with `uv build --out-dir <temp-artifacts>`. For each wheel and sdist, create separate Python 3.11 and 3.14 venvs using `uv venv --seed --python <version> <venv>`, then install the artifact with `uv pip install --python <venv-python> <artifact>`. Run from an empty temporary cwd with `PYTHONPATH` unset; never install from the source path.
- Execute the installed console script, stdio MCP discovery, and one representative mocked tool call.
- Run Streamable HTTP smoke qualification once for the built wheel on Ubuntu/Python 3.11; this is the only installed HTTP artifact check needed because H1 exercises the source transport on Ubuntu and Windows.
- Detect source-tree imports, repository-relative files, undeclared runtime dependencies, and accidental test/verification payload inclusion.

### Non-goals

- No version bump or release tag in H4.
- No publishing, pushing, or external package-index upload.
- No new runtime feature or packaging escape hatch that changes the public contract.

### Candidate files

- `pyproject.toml`, `uv.lock`, `README.md`
- `src/coinmarketcap_keyless_mcp/`
- `tests/mcp/test_stdio.py`, `tests/mcp/test_streamable_http.py`
- New packaging/qualification tests or scripts only if they remain offline and bounded

### Tests and checks

- `uv build --out-dir <temp-artifacts>` for wheel and sdist.
- Metadata and file-list inspection using the built artifacts.
- For both artifacts on Python 3.11 and 3.14: `uv venv --seed --python <version> <venv>`; `uv pip install --python <venv-python> <artifact>`; then from an empty temp cwd run `<venv-python> -m coinmarketcap_keyless_mcp --help` and a stdio `mcp.Client` discovery/call harness.
- The harness supplies a fixture `ClientFactory` through `run_server`, asserts exact tool names from the 13 `TOOL_CONTRACTS`, makes one mocked tool call, and checks protocol-only stdout and clean shutdown. Clear `PYTHONPATH` and assert the imported package resolves under that venv's site-packages. The harness has no source checkout or provider network access.
- On Ubuntu/Python 3.11, perform one installed-wheel Streamable HTTP discovery/call smoke test using a fixture client. Record the selected artifact, interpreter, platform, and result.
- Runtime import audit against declared dependencies.

### Acceptance criteria

- Wheel and sdist build reproducibly enough for the repository’s declared process and contain the intended package only.
- Metadata declares all runtime dependencies and the console entry point.
- Clean installs work without source-tree assumptions.
- Installed stdio exposes exactly the 13 tools, emits no diagnostic stdout, and shuts down cleanly.
- Any Streamable HTTP limitation is explicit, tested, and not mistaken for package failure.

### Exit gate

`H4_PACKAGE_QUALIFIED`: wheel, sdist, clean installation, installed console script, and required transport smoke checks pass with artifact evidence retained.

### Commit checkpoint

Create `hardening H4: qualify build and clean installation artifacts` after the gate.

### PR review checkpoint

Yes. Package contents, dependency declarations, entry points, and clean-environment claims should receive review before release.

## 8. Phase H5 — Security and failure-mode audit

### Objective

Exercise adversarial inputs and operational failures at the boundaries without broadening the public API.

### Exact scope

Cover host/path injection, encoded path tricks, arbitrary-header attempts, environment-variable misuse, malformed JSON, deeply nested or oversized responses, retry exhaustion, malicious provider strings in logs, stdout contamination, unsafe HTTP bind behavior, and unexpected cancellation/shutdown states.

Verify structural rejection at request construction and schema boundaries. Verify logs are bounded and safe without attempting to sanitize an expanded arbitrary user payload surface.

### Non-goals

- No public arbitrary URL, route, method, header, credential, or bind configuration beyond the existing contract.
- No claim of a complete third-party security certification or penetration test.
- No telemetry, secret handling, or production configuration expansion.

### Candidate files

- `src/coinmarketcap_keyless_mcp/client.py`
- `src/coinmarketcap_keyless_mcp/models.py`
- `src/coinmarketcap_keyless_mcp/runtime.py`
- `src/coinmarketcap_keyless_mcp/server.py`
- `tests/unit/`, `tests/contract/`, `tests/mcp/`
- `README.md`, `pyproject.toml`

### Tests and checks

- Property-like and table-driven malicious route/query/header/environment cases.
- JSON depth/size and provider-string logging fixtures, asserting no full payload or control-sequence contamination at INFO.
- Retry exhaustion and `Retry-After` boundary cases.
- Stdio subprocess framing checks with malformed input and injected diagnostic attempts.
- Bind-host validation and local-only/default safety checks for Streamable HTTP.
- Cancellation and shutdown fault injection at each async ownership boundary.
- Manual diff review for auth paths, permissive test hooks, debug output, and unsafe dependency/tool changes.

### Acceptance criteria

- All adversarial cases fail closed with the expected stable classification.
- No input controls upstream host, path, method, or headers.
- No CMC credential environment variable is read or emitted.
- Malformed/oversized input cannot cause unbounded processing in the tested boundary.
- Logs and stdout remain protocol-safe and bounded.
- Cancellation and shutdown do not leave capacity, tasks, clients, or ports leaked.
- No unresolved release-blocking security finding remains.

### Exit gate

`H5_SECURITY_AUDIT_PASSED`: adversarial suite, diff/security review, and required offline regression pass; findings are either fixed or explicitly accepted as advisory by the release decision owner.

### Commit checkpoint

Create `hardening H5: close security and failure-mode gaps` only after all release-blocking findings are resolved.

### PR review checkpoint

Yes, and preferably with a reviewer independent of the implementation of the affected boundary.

## 9. Phase H6 — Release qualification

### Objective

Produce evidence for a backward-compatible hardening release and stop if the work has drifted into a public feature release.

### Exact scope

- Run the full non-live regression and all blocking static, mutation, resource, packaging, security, and transport checks from H1–H5.
- Run packaging qualification on the final candidate commit.
- Run stdio and Streamable HTTP qualification as required by `PLAN.md` and the support matrix.
- Run the canonical `uv run python -m coinmarketcap_keyless_mcp.verify_live` 13-route capability verification serially, credential-free, minimally sized, and classification-aware, once on the H6 candidate. H1–H5 remain offline. Rerun earlier only if a hardening change directly alters upstream request construction, route/query mapping, envelope validation, or error classification; record the triggering diff and route scope. Test-only, CI, and packaging changes do not trigger provider calls.
- Review the final diff for scope, secrets, generated junk, test weakening, stdout contamination, and public-contract drift.
- Obtain PR review and make the version decision.

### Non-goals

- No new MCP tools, routes, schemas, or functionality.
- No live verification interpreted as a substitute for offline, package, transport, or security gates.
- No tag, push, publish, or release side effect in this planning phase.

### Candidate files

- All files changed by H1–H5
- `PLAN.md`, `HARDENING_PLAN.md`, `README.md`, `CHANGELOG.md`, `pyproject.toml` only if the approved release process requires documentation/version updates
- `verification/` only for minimal approved live evidence, never full payload retention

### Tests and checks

- Full non-live regression: `uv run pytest`.
- Focused qualification commands documented by H1–H5.
- Wheel/sdist and clean-install checks.
- Installed stdio and Streamable HTTP smoke checks.
- Live 13-route verification using the canonical opt-in command from `PLAN.md`, with each result classified as supported, unsupported by positive evidence, rate-limited, transient, or contract mismatch.
- Final `git diff --check`, secret/auth scan, public-surface comparison, and PR review.

### Acceptance criteria

- All mandatory non-live, package, transport, security, and scope gates pass.
- Every released route has current route-level live evidence; `RATE_LIMITED`, `TRANSIENT_ERROR`, and `CONTRACT_MISMATCH` remain distinct and are not silently treated as unsupported.
- The final public surface remains exactly 13 tools with no DEX or generic proxy.
- The final diff contains only intentional hardening changes and approved documentation/version updates.
- If all changes are backward-compatible bug fixes and hardening only, the target version is `v1.0.1`.
- If any public functionality or MCP tool is added, stop this release and require a separate plan/version decision; do not label it `v1.0.1`.

### Exit gate

`HARDENING_RELEASE_QUALIFIED` for a candidate release, or `HARDENING_RELEASE_BLOCKED` with the exact failed gate and evidence recorded. This plan alone never declares a release published.

### Commit checkpoint

Keep H6 release-preparation edits with H6 qualification in one final reviewable commit if authorized and needed. H1–H5 phase commits remain separate logical checkpoints within the same PR. Tagging, pushing, publishing, and release creation require separate explicit authorization under `VERSION_CONTROL.md`.

### PR review checkpoint

Yes, mandatory. Review must cover the complete diff, contract preservation, security invariants, evidence, and version decision.

## 10. Version control and PR structure

H1 CI/static tooling, H2 mutation evidence/coverage, H3 resource tests/fixes, H4 packaging qualification, and H5 security fixes/tests are separate commits after their gates. Each is a coherent phase slice; do not create micro-commits per test or report edit. H6 is release qualification and documentation/version preparation; use one final release-preparation commit only if required by the approved release workflow. This plan alone authorizes no Git side effects; `VERSION_CONTROL.md` and explicit authorization govern staging, commits, branches, PRs, tags, pushes, and releases.

Use one PR for the complete v1.0.1 cycle. H1 is not independently useful to release and shares contract-preservation and qualification review with H2–H5; separate PRs would fragment evidence and duplicate release review. Request focused reviewers per phase within that PR. No public MCP contract change is in scope; any such change stops this cycle and requires a separate plan/version decision.

## 11. Remaining release-time decisions

Only execution findings remain open: whether a concrete defect needs a backward-compatible fix, final route-level live classifications at H6, and whether the final diff remains hardening-only and qualifies for `v1.0.1`. Public functionality or contract changes are out of scope and block this release cycle.

## 12. Plan completion status

This document has been reviewed and is ready for H1 when separately authorized. No hardening implementation is authorized or included by this plan review.

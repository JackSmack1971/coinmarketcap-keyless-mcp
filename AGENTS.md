# AGENTS.md

## Purpose

This repository implements `coinmarketcap-keyless-mcp`, a bounded, read-only, credential-free Model Context Protocol server for selected CoinMarketCap Keyless Public API routes.

This file is the persistent execution map for Codex. Keep detailed product and Git doctrine in their dedicated files rather than duplicating them here.

For product scope, route contracts, tool schemas, error semantics, phases, acceptance criteria, and release gates, use `PLAN.md`.

## Instruction precedence

Follow instructions in this order:

1. The active user request.
2. This `AGENTS.md` for repository execution rules.
3. `PLAN.md` for product scope, contracts, phases, acceptance criteria, and release gates.
4. `VERSION_CONTROL.md` for Git/worktree/staging/commit/integration/push/tag/release doctrine.
5. Applicable tests and repository configuration.
6. Current official upstream documentation when external behavior must be verified.
7. Existing repository conventions.

If instructions conflict, do not silently reconcile a material product, compatibility, security, or public-contract conflict. Preserve the narrower safe behavior and report the conflict.

## Read contextually

Do not automatically read the entire repository or all of `PLAN.md` for every change.

Consult `PLAN.md` when changing product scope, MCP tools/schemas/routes/outputs/errors, retries, caching, transports, live capability, security/configuration, phases, or release gates.

Consult `VERSION_CONTROL.md` whenever Git/worktree state or a version-control side effect is relevant.

For OpenAI, Codex, or MCP SDK behavior, verify current official documentation when the answer may have changed.

Use the relevant `PLAN.md` sections for the task at hand:

- product boundaries and non-goals: Sections 1-3
- technology and HTTP/MCP constraints: Sections 4-6
- route/tool contracts: Sections 7-9
- errors, retry, cache, live classification: Sections 10-14
- test requirements: Section 15
- security/configuration: Sections 16-17
- implementation phases: Section 18
- release gates and commands: Sections 20-21
- Codex execution rules: Section 23
- definition of done: Section 24

For any change to a public MCP tool, route, schema, output contract, error classification, release gate, or security invariant, consult the corresponding normative `PLAN.md` section before editing.

## Scope discipline

Implement only the active user-requested slice or active PLAN phase.

Do not opportunistically:

- add tools or routes outside the approved v1 surface;
- add DEX support;
- add authenticated CoinMarketCap support;
- add API-key, bearer-token, cookie, wallet, signing, or credential abstractions;
- add arbitrary hosts, methods, headers, routes, or a generic URL/path/query proxy;
- add investment advice, portfolio logic, or derived market indicators;
- widen schemas because an undocumented provider parameter appears to work;
- refactor unrelated code;
- introduce speculative abstractions for future phases.

The v1 public surface is exactly the released subset authorized by `PLAN.md`. Any public-contract expansion requires an explicit plan change or user instruction.

## Repository invariants

Treat the following as release-blocking invariants:

- CoinMarketCap access is keyless only.
- The production upstream base URL is fixed to `https://pro-api.coinmarketcap.com/public-api`.
- Upstream access is GET-only.
- Every MCP tool maps to exactly one allowlisted route.
- User input cannot control scheme, host, port, arbitrary path, arbitrary method, or arbitrary headers.
- No `X-CMC_PRO_API_KEY` or equivalent credential may be read, accepted, stored, or emitted.
- There is no authenticated fallback.
- A 2xx HTTP response is not success unless the expected CMC envelope is valid and normalized `status.error_code` indicates success.
- HTTP 429 is `RATE_LIMITED`, never proof that a route is unsupported.
- Arbitrary diagnostics must never contaminate stdout while stdio MCP is active.
- Pagination, list sizes, retries, concurrency, response use, and sleeps remain bounded.
- Provider market values are preserved rather than silently transformed.

If an implementation approach threatens one of these invariants, change the approach rather than weakening the invariant.

## Public contract changes

Treat these as public-contract changes:

- tool names;
- tool descriptions that alter behavioral expectations;
- JSON schemas;
- route mappings;
- validation rules;
- provider field renaming or transformation;
- output envelope shape;
- error classifications;
- transport-visible behavior.

Do not make a breaking public-contract change merely to accommodate provider drift.

When upstream documentation or behavior changes:

1. verify the current upstream contract;
2. update or add contract fixtures/tests;
3. update `PLAN.md` or a superseding approved design record if the public contract must change;
4. rerun affected live capability verification before claiming support.

## Development workflow

Before editing a non-trivial change:

- inspect `git status` and the relevant diff;
- inspect the files, tests, and configuration directly related to the request;
- preserve pre-existing user changes;
- identify the smallest coherent implementation that satisfies the request.

Do not revert, overwrite, reformat, or clean up unrelated work.

Prefer existing repository patterns over new abstractions.

Do not edit generated, vendored, lock, environment, or tool-generated files unless the active task requires it.

Do not install global dependencies. Use the repository's documented `uv`/project tooling.

## Implementation quality

Write straightforward Python with explicit boundaries.

Prefer:

- typed interfaces where they improve public or internal contracts;
- small single-purpose modules and functions;
- deterministic validation and serialization;
- dependency injection only where it materially improves testing or boundary enforcement;
- explicit allowlists over denylist/string-filter approaches;
- structured internal errors over generic exception swallowing;
- async resource ownership that is clear and closed cleanly.

Avoid:

- unnecessary framework layers;
- premature plugin systems;
- generic request builders exposed to MCP clients;
- hidden fallback behavior;
- broad exception catches that erase error classification;
- duplicated route/schema definitions that can drift independently;
- tests that depend on live network access unless explicitly marked live.

## MCP and stdio requirements

For MCP-facing work:

- use the current official MCP Python SDK v2 behavior required by `PLAN.md`;
- preserve the same intended tool surface across in-process, stdio, and Streamable HTTP;
- keep stdout reserved for the stdio protocol;
- send diagnostics through stderr or configured logging;
- reject unknown tool arguments;
- enforce cross-field validation locally before upstream network access;
- keep discoverable schemas semantically equivalent to the normative PLAN contract.

If the installed SDK API differs from the PLAN's documented assumptions, verify the current official SDK before changing architecture. Do not guess API names or silently fall back to obsolete SDK patterns.

## HTTP client requirements

The production client must structurally enforce:

- fixed keyless base URL;
- GET only;
- allowlisted routes only;
- no auth headers;
- finite connect/read/write/pool timeouts;
- conservative bounded concurrency;
- bounded retry attempts;
- `Retry-After` handling when valid and bounded;
- exponential backoff with jitter otherwise for approved transient cases;
- no retry of deterministic non-429 4xx by default;
- response-envelope validation before success.

Test-only dependency injection may replace the transport or upstream destination internally. Do not expose that as a production runtime escape hatch.

## Error semantics

Preserve the stable error taxonomy defined in `PLAN.md`.

In particular:

- validation failure -> `INVALID_ARGUMENT`;
- exhausted 429 -> `RATE_LIMITED`;
- network/timeout/retryable 5xx -> transient upstream classifications;
- malformed or structurally unexpected successful responses -> `UPSTREAM_CONTRACT_MISMATCH`;
- provider application errors -> `UPSTREAM_APPLICATION_ERROR`;
- unsupported capability requires positive evidence;
- never map an arbitrary exception directly to `UNSUPPORTED_ROUTE`.

Do not use error reclassification to make tests pass.

## Tests and verification

The local non-live tests are expected to use mocks, fixtures, local subprocesses, or disposable local servers and have no production write access. Run affected tests, fix failures caused by the requested change, and rerun them without requesting approval for each local iteration.

Use focused verification first. Expand verification in proportion to the change.

Typical progression:

1. directly affected unit/contract test;
2. affected test module or endpoint family;
3. MCP/transport test when public or transport behavior changed;
4. broader non-live suite when the change can affect shared behavior.

Do not run live CoinMarketCap verification unless:

- the active task requires live capability evidence;
- the active PLAN phase requires it; or
- the user explicitly asks for it.

Live verification must remain opt-in, credential-free, serial by default, minimally sized, and classification-aware. Do not treat `RATE_LIMITED` or `TRANSIENT_ERROR` as unsupported capability.

Never weaken, skip, delete, rewrite, or broaden tolerances in a test merely to obtain a pass.

Do not claim a command, test, release gate, route, or capability passed unless it actually ran and passed under the required conditions.

## Phase discipline

When implementing a PLAN phase:

- complete only that phase unless the user explicitly requests more;
- satisfy its acceptance criteria before treating it as complete;
- run the phase-appropriate focused checks;
- run applicable broader checks required by the PLAN;
- record concrete blockers instead of guessing through them.

Do not begin later-phase functionality just because it is convenient while editing an earlier phase.

Caching is not a correctness dependency and must not obscure uncached correctness.

## Live capability evidence

Capability claims require evidence, not inference from documentation alone.

For live verification:

- call the exact `/public-api` route;
- use no credentials;
- use minimal deterministic parameters;
- classify each result according to `PLAN.md`;
- preserve `RATE_LIMITED`, `TRANSIENT_ERROR`, and `CONTRACT_MISMATCH` as distinct states;
- minimize retained payload data;
- record the base URL, timestamp, route/tool identity, classification, and enough evidence to audit the result.

Do not remove a route from the claimed surface solely because of one 429, timeout, or transient 5xx.

## Security and privacy

Security boundaries are structural requirements.

Do not:

- introduce secrets;
- read CMC API-key environment variables;
- log entire upstream market payloads at INFO;
- expose arbitrary headers or URLs;
- create production configuration that weakens host/route/method restrictions;
- add telemetry that transmits data externally without explicit authorization;
- persist unnecessary provider responses in verification artifacts.

Before completion, inspect the diff for credential leaks, debug output, permissive test hooks, and stdout contamination risks.

## Dependencies

Use the smallest dependency set that meets the PLAN.

Before adding or changing a dependency:

- confirm it is needed for the active slice;
- prefer the repository's existing dependency choices;
- use a current stable compatible release;
- bound versions according to repository policy;
- do not pin speculative or unreleased versions.

A dependency change is not a reason to modify unrelated lock or environment state unless the repository workflow requires it.

## Git and external side effects

`VERSION_CONTROL.md` is normative for Git behavior. Without explicit authorization, edit, test, and review only; do not stage, commit, branch, merge, tag, push, open PRs, or release. Never discard user changes or use destructive Git operations as a shortcut.

## Completion standard

Continue until the active requested slice is actually complete or a concrete blocker prevents further progress.

Before finishing:

- inspect the final diff;
- verify no unrelated edits were introduced;
- verify no tests were weakened;
- verify no credential/auth path was introduced;
- verify public contracts remain within PLAN scope;
- run the required checks that are feasible in the current environment.

A mocked test pass does not establish live route support.

A live route response does not waive unit, contract, MCP, or transport requirements.

## Final handoff

Report only:

1. what changed or was determined;
2. files changed;
3. verification commands actually run and their outcomes;
4. blockers, unresolved decisions, or unverified behavior.

When Git state is material, also report the relevant repository state required by `VERSION_CONTROL.md`. Do not claim release readiness, live support, clean repository state, commit state, or acceptance gates beyond verified evidence.

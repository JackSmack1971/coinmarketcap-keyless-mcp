# v1.1 Expansion Plan — `coinmarketcap-keyless-mcp`

**Status:** E0 accepted; E1 accepted after retrospective review and F1 remediation; E2-A contract approved with implementation not started; v1.1.0 live release gate pending
**Audience:** Repository maintainers and implementation agents
**Plan date:** 2026-10-01
**Historical baseline:** [`PLAN.md`](PLAN.md) defines the frozen v1 contract and remains unchanged.

## Preserved v1.0.1 surface

v1.1 preserves the 13-tool v1.0.2 release surface and its existing contracts:

1. `cmc_crypto_map`
2. `cmc_crypto_info`
3. `cmc_quotes_latest`
4. `cmc_listings_latest`
5. `cmc_global_metrics_latest`
6. `cmc_fear_greed_latest`
7. `cmc_fear_greed_historical`
8. `cmc_altcoin_season_latest`
9. `cmc_altcoin_season_historical`
10. `cmc_cmc100_latest`
11. `cmc_cmc100_historical`
12. `cmc_cmc20_latest`
13. `cmc_cmc20_historical`

Their schemas, route mappings, output and error contracts remain those in `PLAN.md`; this expansion gate does not rename, remove, or redefine them.

## 1. Purpose and precedence

This document defines the planning and evidence gate for a possible v1.1 expansion. It does not itself approve any added route. Until `E0_CAPABILITY_INVENTORY_ACCEPTED`, the released v1 surface remains the only implementation scope.

For v1.0.x, `PLAN.md` remains contract-frozen. For v1.1, this document explicitly authorizes consideration only of additions individually marked `APPROVED` at E0. The v1.1 additions preserve all existing invariants: keyless access only, fixed base URL `https://pro-api.coinmarketcap.com/public-api`, GET only, one allowlisted route per tool, bounded behavior, no credentials or authenticated fallback, and no generic proxy. No POST or other non-GET implementation path is authorized. No trading, wallet, signing, custody, or transaction functionality is in scope.

The v1 plan remains authoritative for existing v1 tool schemas, errors, transports, security requirements, and verification practices. Where v1.1 expands those boundaries, this document is controlling only for the specific approved additions and their separate release gate. No unrelated v1 contract is reopened.

## 2. Candidate ceiling and documentation discrepancy

The maximum catalog under consideration is **35 tools**:

- 13 frozen v1 tools;
- 5 Standard additions;
- 17 DEX additions.

This is a candidate ceiling, not an unconditional tool-count or support claim. The dedicated Keyless reference and guide enumerate 18 Standard plus 17 DEX routes (35 total); the Keyless landing page advertises 36 endpoints. The extra landing-page route is unidentified in the current 35-route inventory. Track it as `UNIDENTIFIED_DOCUMENTATION_DISCREPANCY`; it is outside this plan's candidate set and cannot change scope without an explicit plan amendment.

The current candidate inventory below is based on the Keyless reference's 18 Standard + 17 DEX enumeration, with the 13 v1 routes already frozen in `PLAN.md` removed. E0 must verify every candidate against the current official documentation. Documentation visibility or keyless wording alone is not proof of a GET contract or live support.

### 2.1 Five Standard additions

| Candidate | Route | E0 note |
|---|---|---|
| `cmc_simple_price` | `/v2/simple/price` | E0 confirmed the detailed Keyless reference route and GET contract; the landing-page `/v1` mention is stale/inconsistent. |
| `cmc_crypto_categories` | `/v1/cryptocurrency/categories` | Confirm exact keyless route and GET contract. |
| `cmc_crypto_category` | `/v1/cryptocurrency/category` | Confirm exact keyless route and GET contract. |
| `cmc_price_conversion` | `/v2/tools/price-conversion` | Confirm exact keyless route and GET contract. |
| `cmc_exchange_map` | `/v1/exchange/map` | Confirm exact keyless route and GET contract. |

### 2.2 Seventeen DEX additions

| Candidate | Route | E0 note |
|---|---|---|
| `cmc_dex_spot_pairs_latest` | `/v4/dex/spot-pairs/latest` | Verify keyless GET contract and bounded query semantics. |
| `cmc_dex_pair_quotes_latest` | `/v4/dex/pairs/quotes/latest` | Verify keyless GET contract and bounded query semantics. |
| `cmc_dex_token` | `/v1/dex/token` | Verify keyless GET contract and identity semantics. |
| `cmc_dex_token_price` | `/v1/dex/token/price` | Verify keyless GET contract and identity semantics. |
| `cmc_dex_token_liquidity` | `/v1/dex/token-liquidity/query` | Verify keyless GET contract and bounded query semantics. |
| `cmc_dex_token_pools` | `/v1/dex/token/pools` | Verify keyless GET contract and bounded query semantics. |
| `cmc_dex_search` | `/v1/dex/search` | Verify keyless GET contract and bounded query semantics. |
| `cmc_dex_security_detail` | `/v1/dex/security/detail` | Verify keyless GET contract and identity semantics. |
| `cmc_dex_transactions` | `/v1/dex/tokens/transactions` | Verify keyless GET contract and pagination bounds. |
| `cmc_dex_liquidity_change_list` | `/v1/dex/liquidity-change/list` | Verify keyless GET contract and pagination bounds. |
| `cmc_dex_platform_list` | `/v1/dex/platform/list` | Verify keyless GET contract. |
| `cmc_dex_platform_detail` | `/v1/dex/platform/detail` | Verify keyless GET contract and identity semantics. |
| `cmc_dex_kline_candles` | `/v1/k-line/candles` | Verify keyless GET contract, interval, and bounds. |
| `cmc_dex_kline_points` | `/v1/k-line/points` | Verify keyless GET contract, interval, and bounds. |
| `cmc_dex_holders_list` | `/v1/dex/holders/list` | Gated: admit only if an unambiguous keyless GET contract is established. |
| `cmc_dex_holders_count` | `/v1/dex/holders/count` | Normal GET candidate; verify required query and keyless contract. |
| `cmc_dex_holders_detail` | `/v1/dex/holders/detail` | Gated: admit only if an unambiguous keyless GET contract is established. |

Holder list and detail documentation currently exposes POST request-body contracts alongside keyless availability wording. That does not authorize POST. Unless E0 finds authoritative evidence establishing the exact route as keyless GET, classify the candidate `METHOD_CONTRACT_UNRESOLVED` or `EXCLUDED_NON_GET` and exclude it. Holder count is documented as GET and remains an ordinary candidate subject to E0 evidence.

## 3. E0 — Capability inventory and scope freeze

E0 is a mandatory planning phase. It must finish before any v1.1 implementation, public schemas, route allowlists, or implementation-phase work begins.

### 3.1 Required candidate dispositions

E0 must classify all 22 additions, one by one, using exactly one disposition per candidate:

- `APPROVED` — the exact route has an authoritative keyless GET contract, bounded tool semantics are defined, and no unresolved contract issue prevents inclusion;
- `METHOD_CONTRACT_UNRESOLVED` — current authoritative evidence does not settle whether keyless access uses GET;
- `EXCLUDED_NON_GET` — the established contract requires a method other than GET;
- `EXCLUDED_OTHER` — a documented, evidence-backed reason other than method prevents inclusion.

Only `APPROVED` candidates proceed. A `RATE_LIMITED`, timeout, transient 5xx, or other inconclusive live result is not evidence for `EXCLUDED_OTHER` or unsupported capability. Preserve live classifications using the taxonomy in the frozen v1 plan.

For each candidate, record at minimum:

1. candidate name, exact route, method, and Standard/DEX family;
2. official documentation URL, retrieval timestamp, and relevant contract evidence (including required inputs and whether parameters are query or body fields);
3. keyless availability evidence and whether credentials/headers are explicitly unnecessary;
4. disposition and concise rationale;
5. live capability classification, timestamp, HTTP status where available, and minimal auditable evidence, without retaining unnecessary provider payloads;
6. bounded input, pagination/response, and identity constraints needed for an eventual tool contract;
7. unresolved questions and the reason they do or do not block approval.

For holders list/detail, explicitly record whether the keyless GET contract is established; POST examples or generic “available with no API key” text alone do not establish it. For holder count, record its GET query contract. Record the landing-page count conflict separately as `UNIDENTIFIED_DOCUMENTATION_DISCREPANCY`; do not invent or add a 36th candidate.

### 3.2 Required E0 artifacts

E0 must deliver both artifacts before acceptance:

- `verification/v1.1-route-recon.md` — route-by-route documentation and capability evidence, all 22 dispositions, discrepancy record, and rationale for each decision;
- `V1_1_CAPABILITY_INVENTORY.md` — concise frozen inventory of the 13 existing v1 routes plus each E0-approved addition, with exact tool identity, route, method, family, and disposition reference. Include excluded candidates for audit, clearly marked as excluded.

Minimize retained data. Route evidence should be enough to audit the decision but should not copy complete market responses or sensitive user-provided identifiers.

### 3.3 E0 acceptance and frozen count

E0 is accepted only when:

- all 22 candidates have exactly one evidence-backed disposition;
- all `APPROVED` entries have established keyless GET contracts and bounded proposed semantics;
- holders list/detail are excluded unless that GET requirement is met;
- the unidentified 36th landing-page entry is recorded without expanding scope;
- both required artifacts are complete and cross-consistent;
- the final release-contract count is frozen as **N = 13 + the number of `APPROVED` additions**.

Record the literal acceptance token `E0_CAPABILITY_INVENTORY_ACCEPTED`, the frozen N, and the inventory artifact revision/date in the E0 record. Until this token is recorded, there is no v1.1 implementation authorization. Later scope changes require an explicit amendment and renewed inventory acceptance.

## 4. Post-E0 implementation and release boundary

After E0 acceptance, implementation may cover only the frozen 13 v1 tools and the additions marked `APPROVED` in the accepted inventory. It must preserve all v1 security, HTTP, MCP, error, boundedness, and transport requirements. Every MCP tool maps to exactly one explicitly allowlisted GET route. No generic route builder or user-controlled host/path/method/header is permitted.

The v1.0.x release contract remains unchanged. v1.1 public-contract details for each approved addition must be specified and reviewed before that route is implemented, including schemas, validation, output treatment, errors, bounds, and tests. If implementation research contradicts E0 evidence, stop that route and amend/reaccept the inventory before proceeding.

The v1.1 live release gate is exactly:

> **`N/N RELEASE-CONTRACT ROUTES SUPPORTED`**

Here N is the frozen total from E0, including the 13 v1 routes and all approved additions. Each of those N routes must have current `SUPPORTED` live evidence under the frozen v1 capability criteria. Excluded and unresolved candidates are outside N and must not be represented as supported. 429, transient errors, and contract mismatches remain distinct classifications and do not count as `SUPPORTED`.

## 4.1 E1 Standard implementation and retrospective contract assessment

E0 was accepted as `E0-CLOSE-2026-10-01-r1`, freezing N = 32. Later conversational authorization covered implementation of the five approved Standard additions. E1 implementation preceded the contract-review step required by §4, so the missing pre-implementation review remains a recorded sequencing deviation rather than being rewritten as if it occurred.

The independent retrospective review initially returned **REVISE** for one confirmed defect: `cmc_price_conversion` described conversion to “one or more target currencies” while its approved schema and implementation permit exactly one target via `convert` or `convert_id`. The implementation owner corrected only that description and its pinned test. Independent re-review reproduced the intended one-target behavior, confirmed no accompanying schema/route/validation/output/error drift, and preserved the earlier REVISE chronology.

The required non-live gates passed on 2026-10-02: focused E1 tests, Ruff check/format, full pytest, `uv lock --check`, `git diff --check`, and the mutation gate at **93.5%** against the **92%** minimum (`killed=987`, `survived=69`, `timeout=3`) in WSL. Packaged wheel/sdist qualification and live CoinMarketCap verification were not part of this acceptance and remain separate limitations/release work.

**E1 status: `E1_ACCEPTED`.** This is retrospective acceptance of the five Standard additions only; it does not erase the sequencing deviation, accept the v1.1.0 release, or satisfy the 32/32 live release gate. See `verification/v1.1-e1-standard.md`.

## 4.2 E2-A DEX identity foundation contract review

E2-A is limited to D11 `cmc_dex_platform_list` (`GET /v1/dex/platform/list`) and D4 `cmc_dex_token_price` (`GET /v1/dex/token/price`). Its public contract was reviewed before implementation and is recorded in `verification/v1.1-e2a-contract-review.md`.

The review used minimal credential-free live evidence on 2026-10-02 to resolve platform identity semantics. `/v1/dex/platform/list` returned 244 platform records; Ethereum appeared as `id=1`, `n="Ethereum"`, `pltA="ETH"`. `/v1/dex/token/price` succeeded for both `platform=Ethereum` and `platform=ethereum` using Ethereum USDC and returned `pid=1`. `platform=ETH` was rate-limited and `platform=1` returned HTTP 500, so those forms were treated as inconclusive rather than accepted or rejected.

The approved contract preserves provider envelopes unchanged, keeps the fixed keyless base and GET-only one-tool/one-route invariants, uses a strict empty schema for platform-list, and requires bounded case-preserving `platform` and `address` inputs for token-price with exact provider serialization. D5 remains deferred; D15 and D17 remain excluded.

**E2-A contract status: `E2A_CONTRACT_APPROVED` — `IMPLEMENTATION NOT STARTED`.** This token authorizes implementation of D11+D4 only. It does not accept E2-A implementation, authorize E2-B, or satisfy any part of the 32/32 live release gate.

## 5. Planning hierarchy and change control

1. Active user request and explicit approved amendments.
2. `AGENTS.md` execution and repository invariants.
3. `V1_1_PLAN.md` for the E0 gate and v1.1-authorized scope.
4. `PLAN.md` for the historical, frozen v1 contract and unchanged behavior.
5. `VERSION_CONTROL.md` for Git operations.
6. Current official CoinMarketCap and MCP documentation where needed.

The amendments A1–A8 referenced by the planning brief were not present as repository files when this plan was prepared. Therefore this document records the supplied requirements as interpreted in the brief and the explicit assumptions below; it does not claim a clause-by-clause audit of unavailable amendment text. If A1–A8 are added later, reconcile them against this plan before accepting E0 or beginning implementation.

## 6. Assumptions and unresolved evidence

- The dedicated Keyless reference's 18 Standard + 17 DEX listing is the source for the 35 candidate identities, pending route-by-route E0 verification.
- The landing page's extra advertised endpoint is unidentified and out of scope until an explicit amendment names and approves it.
- Holders list/detail are not assumed GET merely because the documentation labels them keyless; the established POST request-body contract makes GET eligibility unresolved pending direct authoritative evidence.
- No candidate is claimed live-supported by this planning document. E0 must record real route-level evidence and preserve inconclusive outcomes accurately.

## 7. Reference starting points

These are discovery sources for E0, not substitutes for route-specific evidence:

- Keyless Public API reference: <https://coinmarketcap.com/api/documentation/pro-api-reference/keyless-public-api>
- Keyless landing page: <https://coinmarketcap.com/api/keyless/>
- Holder endpoint reference: <https://coinmarketcap.com/api/documentation/pro-api-reference/holder>

The landing-page count, route methods, keyless eligibility, parameters, and live behavior are time-sensitive. E0 must record the versions and retrieval timestamps it actually reviewed rather than treating this planning baseline as current proof.

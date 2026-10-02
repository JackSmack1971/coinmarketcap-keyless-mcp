# v1.1.0 Capability Inventory — E0

**Review date:** 2026-10-01
**Production base:** `https://pro-api.coinmarketcap.com/public-api`
**Credential mode:** `NONE`
**Evidence:** [Route-by-route reconnaissance](verification/v1.1-route-recon.md)

## Frozen existing tools

The existing 13 tools remain frozen per `V1_1_PLAN.md` and `PLAN.md`:

| Candidate | Path | Method | Classification | Disposition | Proposed tool |
|---|---|---|---|---|---|
| Existing | `/v1/cryptocurrency/map` | GET | Existing v1 evidence | Frozen | `cmc_crypto_map` |
| Existing | `/v2/cryptocurrency/info` | GET | Existing v1 evidence | Frozen | `cmc_crypto_info` |
| Existing | `/v3/cryptocurrency/quotes/latest` | GET | Existing v1 evidence | Frozen | `cmc_quotes_latest` |
| Existing | `/v3/cryptocurrency/listings/latest` | GET | Existing v1 evidence | Frozen | `cmc_listings_latest` |
| Existing | `/v1/global-metrics/quotes/latest` | GET | Existing v1 evidence | Frozen | `cmc_global_metrics_latest` |
| Existing | `/v3/fear-and-greed/latest` | GET | Existing v1 evidence | Frozen | `cmc_fear_greed_latest` |
| Existing | `/v3/fear-and-greed/historical` | GET | Existing v1 evidence | Frozen | `cmc_fear_greed_historical` |
| Existing | `/v1/altcoin-season-index/latest` | GET | Existing v1 evidence | Frozen | `cmc_altcoin_season_latest` |
| Existing | `/v1/altcoin-season-index/historical` | GET | Existing v1 evidence | Frozen | `cmc_altcoin_season_historical` |
| Existing | `/v3/index/cmc100-latest` | GET | Existing v1 evidence | Frozen | `cmc_cmc100_latest` |
| Existing | `/v3/index/cmc100-historical` | GET | Existing v1 evidence | Frozen | `cmc_cmc100_historical` |
| Existing | `/v3/index/cmc20-latest` | GET | Existing v1 evidence | Frozen | `cmc_cmc20_latest` |
| Existing | `/v3/index/cmc20-historical` | GET | Existing v1 evidence | Frozen | `cmc_cmc20_historical` |

## Candidate disposition table

| Candidate | Path | Method | Classification | Disposition | Proposed tool |
|---|---|---|---|---|---|
| S1 | `/v2/simple/price` | GET | `SUPPORTED` | `APPROVED` | `cmc_simple_price` |
| S2 | `/v1/cryptocurrency/categories` | GET | `SUPPORTED` | `APPROVED` | `cmc_crypto_categories` |
| S3 | `/v1/cryptocurrency/category` | GET | `SUPPORTED` | `APPROVED` | `cmc_crypto_category` |
| S4 | `/v2/tools/price-conversion` | GET | `SUPPORTED` | `APPROVED` | `cmc_price_conversion` |
| S5 | `/v1/exchange/map` | GET | `SUPPORTED` | `APPROVED` | `cmc_exchange_map` |
| D1 | `/v4/dex/spot-pairs/latest` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_spot_pairs_latest` |
| D2 | `/v4/dex/pairs/quotes/latest` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_pair_quotes_latest` |
| D3 | `/v1/dex/token` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_token` |
| D4 | `/v1/dex/token/price` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_token_price` |
| D5 | `/v1/dex/token-liquidity/query` | GET | `CONTRACT_MISMATCH` | `DEFERRED` | `cmc_dex_token_liquidity` |
| D6 | `/v1/dex/token/pools` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_token_pools` |
| D7 | `/v1/dex/search` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_search` |
| D8 | `/v1/dex/security/detail` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_security_detail` |
| D9 | `/v1/dex/tokens/transactions` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_transactions` |
| D10 | `/v1/dex/liquidity-change/list` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_liquidity_change_list` |
| D11 | `/v1/dex/platform/list` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_platform_list` |
| D12 | `/v1/dex/platform/detail` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_platform_detail` |
| D13 | `/v1/k-line/candles` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_kline_candles` |
| D14 | `/v1/k-line/points` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_kline_points` |
| D15 | `/v1/dex/holders/list` | POST documented; GET tested | `METHOD_CONTRACT_UNRESOLVED` | `EXCLUDED_NON_GET` | `cmc_dex_holders_list` |
| D16 | `/v1/dex/holders/count` | GET | `SUPPORTED` | `APPROVED` | `cmc_dex_holders_count` |
| D17 | `/v1/dex/holders/detail` | POST documented; GET tested | `METHOD_CONTRACT_UNRESOLVED` | `EXCLUDED_NON_GET` | `cmc_dex_holders_detail` |

## Counts and scope freeze

- Existing frozen tools: **13**
- Approved Standard additions: **5**
- Approved DEX additions: **14**
- Excluded candidates: **2**
- Unresolved candidates: **0**
- Deferred candidates: **1**
- Frozen v1.1.0 tool count: **32**

Landing-page reconciliation: landing page advertises 19 Standard + 17 DEX = 36, while the detailed Keyless reference enumerates 18 Standard + 17 DEX = 35. Its additional `/v1/cryptocurrency/listings/latest` path is outside these 22 additions; the frozen v1 surface already exposes canonical Listings via `cmc_listings_latest` at `/v3/cryptocurrency/listings/latest`, so no duplicate candidate is added. Simple Price is approved at the official Keyless `/v2/simple/price` path; the landing-page v1 mention is stale/inconsistent with the endpoint-specific and detailed Keyless references.

No non-GET candidate is approved. Approved routes each have an authoritative Keyless GET claim and a successful credential-free GET with provider success. No production runtime, schema, route, test, CI, cache, retry, or version files were changed.

**E0 status: `E0_CAPABILITY_INVENTORY_ACCEPTED`** — inventory revision `E0-CLOSE-2026-10-01-r1`; frozen count **N = 32** (13 existing + 19 approved additions). D5 Token Liquidity is deliberately deferred from v1.1.0 because provider HTTP 400 “Parameter error” conflicts with the documented query fields after bounded attempts. The landing-page listing path is not a duplicate addition. No route inclusion awaits rate-limit recovery.

**E1 governance reconciliation:** later conversational authorization covered the five approved Standard additions. E1 implementation preceded the required contract-review step, so the sequencing deviation remains recorded. Independent retrospective review found one description/schema mismatch in `cmc_price_conversion`; the description was corrected to exactly one target currency, re-reviewed, and the required non-live checks plus the mutation gate passed. E1 is now `E1_ACCEPTED`; see [`verification/v1.1-e1-standard.md`](verification/v1.1-e1-standard.md) and §4.1 of `V1_1_PLAN.md`. E0 scope is unchanged.

**E2-A reconciliation:** the first DEX contract slice is D11 `cmc_dex_platform_list` plus D4 `cmc_dex_token_price`. Its pre-implementation review is approved as `E2A_CONTRACT_APPROVED` with `IMPLEMENTATION NOT STARTED`; see [`verification/v1.1-e2a-contract-review.md`](verification/v1.1-e2a-contract-review.md) and §4.2 of `V1_1_PLAN.md`. No other DEX slice is authorized by that token.

**E1-R reconciliation (2026-10-02):** the code covered by the historical `E1_ACCEPTED` record is unavailable, so that acceptance is superseded for current-code purposes. S1–S5 are being reconstructed clean-room under `E1R_CONTRACT_APPROVED` — `IMPLEMENTATION NOT STARTED`; see [`verification/v1.1-e1r-contract-review.md`](verification/v1.1-e1r-contract-review.md) and §4.1a of `V1_1_PLAN.md`. E0 scope, N = 32 and all routes (including S1 `/v2/simple/price`) are unchanged. E2-A implementation is blocked until `E1R_ACCEPTED`.

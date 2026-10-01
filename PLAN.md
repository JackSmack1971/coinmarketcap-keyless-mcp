# PLAN.md — `coinmarketcap-keyless-mcp`

**Status:** IMPLEMENTED (v1, package version 1.0.2; see `verification/release-1.0.2.md`)\
**Audience:** repository-maintaining coding agents (Codex CLI, Claude Code) and human maintainers\
**Document date:** 2026-09-30 (header updated 2026-10-01)\
**Implementation state:** Implemented. This document remains the normative contract for tools, schemas, routes, errors and release gates. Section 5 is the original target tree; the actual layout differs (no `config.py`, `cache.py`, `tools/` or `tests/live/`; caching lives in `client.py`, tools in `server.py`).

---

## 1. Objective

Build a small, read-only Model Context Protocol (MCP) server that exposes a deliberately limited set of CoinMarketCap Keyless Public API capabilities for quantitative cryptocurrency research and market-regime analysis.

The server MUST:

- use CoinMarketCap's keyless base URL only: `https://pro-api.coinmarketcap.com/public-api`;
- send only `GET` requests to supported keyless routes;
- require no account, API key, secret, wallet, or authentication header;
- expose explicit, typed MCP tools rather than a generic arbitrary-path proxy;
- be safe for local Codex CLI use over stdio;
- support Streamable HTTP as a secondary transport;
- distinguish provider capability failures from temporary rate limiting or transport failures;
- preserve CoinMarketCap's response data faithfully while enforcing a stable local error model;
- include automated tests and opt-in live capability verification;
- avoid duplicating the DEX surface in the first release.

The primary downstream use case is a professional-style crypto research pipeline in which:

- Massive supplies deeper historical/tick market data;
- Fin Data MCP supplies OKX derivatives, macro, and broader financial data;
- this MCP supplies CoinMarketCap-native market breadth, sentiment, proprietary indices, canonical identifiers, and current aggregate market data.

---

## 2. Non-goals

The first release MUST NOT:

- implement trading, order placement, wallet actions, signing, custody, or transactions;
- accept or store a CoinMarketCap API key;
- fall back to CoinMarketCap's authenticated Pro API;
- expose arbitrary URL/path execution such as `cmc_request(path, params)`;
- expose undocumented parameters merely because they appear to work;
- claim that every route advertised by CoinMarketCap is available without live evidence;
- implement DEX tools;
- implement historical OHLCV not explicitly available in the selected v1 keyless scope;
- provide investment advice or portfolio construction logic;
- transform source values into derived indicators unless the tool contract explicitly says so;
- silently coerce invalid asset identifiers to another asset.

---

## 3. Source-of-truth hierarchy

Implementation decisions MUST use this precedence:

1. This `PLAN.md` for repository scope and acceptance requirements.
2. Repository `AGENTS.md`, if present, for repository execution rules.
3. Current CoinMarketCap Keyless Public API documentation for upstream route behavior.
4. Current official MCP Python SDK v2 documentation for MCP behavior.
5. Live keyless integration evidence for whether a documented route actually responds.
6. Existing repository conventions, once implementation has begun.

Do not widen scope because a route is visible in CoinMarketCap documentation unless this plan is updated.

### 3.1 External documentation baseline

As of 2026-09-30:

- Keyless base URL: `https://pro-api.coinmarketcap.com/public-api`
- Keyless calls require no API key and use `GET`.
- CoinMarketCap's current keyless landing page advertises **36 endpoints: 19 Standard + 17 DEX**.
- CoinMarketCap's current keyless reference/developer guide still enumerates **18 Standard + 17 DEX** in some places.
- The implementation MUST therefore treat the advertised catalog count as informational, not as a tested capability contract.
- The selected v1 routes below are individually documented as keyless and MUST still pass live verification before release.
- CoinMarketCap may return `status.error_code` as either numeric `0` or string-like values; normalize before success evaluation.
- HTTP `429` is a rate-limit condition, not evidence that a route is unsupported.

Reference URLs:

- `https://coinmarketcap.com/api/keyless/`
- `https://coinmarketcap.com/api/documentation/pro-api-reference/keyless-public-api`
- `https://coinmarketcap.com/api/documentation/pro-api-reference/cryptocurrency`
- `https://coinmarketcap.com/api/documentation/pro-api-reference/global-metrics`
- `https://coinmarketcap.com/api/documentation/pro-api-reference/cmc-index`
- `https://github.com/modelcontextprotocol/python-sdk`

---

## 4. Technology decisions

### 4.1 Language and packaging

Use Python.

Target:

- Python `>=3.11`
- `pyproject.toml`-based package
- `uv` as the documented development workflow
- official `mcp` Python SDK v2 stable line
- async HTTP client suitable for connection pooling and explicit timeout control

Do not pin to a speculative future SDK version. Pin a compatible bounded dependency only after implementation inspects the current stable release.

### 4.2 MCP SDK contract

Use the current official MCP Python SDK v2 API.

The implementation MUST use the v2 high-level server API (`MCPServer`, not the removed v1 `FastMCP` API) unless repository evidence at implementation time proves otherwise.

Required transports:

- **stdio** — acceptance-critical for local Codex CLI use;
- **Streamable HTTP** — secondary deployment/runtime transport.

SSE-only deployment is not required.

### 4.3 HTTP behavior

The upstream client MUST:

- have one fixed base URL constant: `https://pro-api.coinmarketcap.com/public-api`;
- permit only an allowlisted route set defined in code;
- issue `GET` only;
- set `Accept: application/json`;
- never send `X-CMC_PRO_API_KEY`;
- never read a CMC API key environment variable;
- use finite connect/read/write/pool timeouts;
- use bounded retries only for retryable failures;
- honor `Retry-After` when present;
- otherwise use exponential backoff with jitter for HTTP 429 and selected transient 5xx failures;
- never retry validation errors or deterministic 4xx responses other than 429;
- validate the response envelope before returning success.

### 4.4 Concurrency

No numeric upstream rate limit is assumed by this plan.

Until live evidence supports something more aggressive:

- default upstream request concurrency MUST be conservative;
- a single process SHOULD default to at most 2 concurrent upstream requests;
- live verification MUST run serially by default;
- tests MUST NOT infer unsupported capability from 429 responses.

---

## 5. Repository target shape

The implementation should converge on this structure unless existing repository conventions require a smaller equivalent:

```text
coinmarketcap-keyless-mcp/
├── AGENTS.md
├── PLAN.md
├── README.md
├── LICENSE
├── pyproject.toml
├── src/
│   └── coinmarketcap_keyless_mcp/
│       ├── __init__.py
│       ├── server.py
│       ├── client.py
│       ├── config.py
│       ├── errors.py
│       ├── models.py
│       ├── cache.py
│       └── tools/
│           ├── __init__.py
│           ├── cryptocurrency.py
│           ├── market.py
│           ├── sentiment.py
│           └── indices.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── mcp/
│   └── live/
└── verification/
    ├── README.md
    └── .gitkeep
```

Do not create empty architecture layers simply to match this tree. Prefer the smallest coherent structure that preserves the boundaries defined in this plan.

---

## 6. Core invariants

These are release-blocking invariants.

### INV-001 — Keyless-only

No execution path may add `X-CMC_PRO_API_KEY`, bearer auth, cookies, or another provider credential.

### INV-002 — Fixed upstream host

User/tool input MUST NOT control scheme, host, port, or arbitrary path.

### INV-003 — Read-only

Every upstream call MUST use `GET`.

### INV-004 — Allowlisted routes

Every MCP tool MUST map to exactly one allowlisted CoinMarketCap keyless route.

### INV-005 — No generic proxy tool

There MUST NOT be an MCP tool that accepts an arbitrary route, URL, query dictionary, or HTTP method.

### INV-006 — Stable identifier preference

Tool descriptions MUST tell agents that CMC numeric IDs are preferred over ticker symbols where practical because symbols can be ambiguous.

### INV-007 — 429 classification

An exhausted HTTP 429 retry sequence MUST classify as `RATE_LIMITED`, never `UNSUPPORTED`.

### INV-008 — No silent fallback

If the keyless route fails, do not retry against the authenticated Pro path.

### INV-009 — Envelope validation

A 2xx response is not successful unless it contains the expected CoinMarketCap envelope and its normalized `status.error_code` represents success.

### INV-010 — Transport integrity

Nothing may write arbitrary text to stdout while stdio MCP is active. Diagnostics/logging must use stderr or the configured logger.

### INV-011 — Bounded resource use

Tool schemas MUST bound pagination and list sizes more tightly where needed to keep agent calls predictable, even when CoinMarketCap allows larger values.

### INV-012 — Evidence-based capability

A route may be documented as keyless yet still fail temporarily. Release capability claims MUST come from both documentation and live verification evidence.

---

## 7. v1 route contract

Only the following 13 routes are in initial scope.

| MCP tool | CMC keyless route | Method | Purpose |
|---|---|---:|---|
| `cmc_crypto_map` | `/v1/cryptocurrency/map` | GET | Resolve canonical CMC IDs |
| `cmc_crypto_info` | `/v2/cryptocurrency/info` | GET | Static asset metadata |
| `cmc_quotes_latest` | `/v3/cryptocurrency/quotes/latest` | GET | Current quotes for known assets |
| `cmc_listings_latest` | `/v3/cryptocurrency/listings/latest` | GET | Ranked current market list |
| `cmc_global_metrics_latest` | `/v1/global-metrics/quotes/latest` | GET | Aggregate crypto-market metrics |
| `cmc_fear_greed_latest` | `/v3/fear-and-greed/latest` | GET | Current CMC Fear & Greed |
| `cmc_fear_greed_historical` | `/v3/fear-and-greed/historical` | GET | Historical CMC Fear & Greed |
| `cmc_altcoin_season_latest` | `/v1/altcoin-season-index/latest` | GET | Current Altcoin Season Index |
| `cmc_altcoin_season_historical` | `/v1/altcoin-season-index/historical` | GET | Historical Altcoin Season Index |
| `cmc_cmc100_latest` | `/v3/index/cmc100-latest` | GET | Current CMC100 |
| `cmc_cmc100_historical` | `/v3/index/cmc100-historical` | GET | Historical CMC100 |
| `cmc_cmc20_latest` | `/v3/index/cmc20-latest` | GET | Current CMC20 |
| `cmc_cmc20_historical` | `/v3/index/cmc20-historical` | GET | Historical CMC20 |

No DEX route is permitted in v1.

---

## 8. Exact initial MCP tool schemas

The schemas below are normative for v1. Implementation may use Pydantic/types to generate equivalent JSON Schema, but the externally discoverable MCP schema MUST remain semantically equivalent.

General rules:

- unknown input fields are rejected;
- empty arrays are rejected;
- comma-separated upstream values are represented to MCP clients as arrays where practical;
- the server serializes arrays into the provider's comma-separated query format;
- timestamp strings accepted by index tools MUST be passed through only after validating that they are either Unix timestamps or parseable ISO-8601 strings;
- defaults shown here are server defaults, not assumptions about undocumented provider behavior.

### 8.1 `cmc_crypto_map`

**Description:** Resolve CoinMarketCap cryptocurrency IDs and canonical identifiers. Prefer this tool before symbol-based research when an asset's CMC ID is not already known.

**Upstream:** `GET /v1/cryptocurrency/map`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "listing_status": {
      "type": "array",
      "items": {"enum": ["active", "inactive", "untracked"]},
      "minItems": 1,
      "uniqueItems": true,
      "default": ["active"]
    },
    "start": {"type": "integer", "minimum": 1, "default": 1},
    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
    "sort": {"enum": ["id", "cmc_rank"], "default": "id"},
    "symbols": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[^,\\s]+$"},
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true
    }
  }
}
```

Validation rule:

- if `symbols` is supplied, reject simultaneous explicit use of `listing_status`, `start`, `limit`, or `sort` rather than relying on upstream silently ignoring them.

Serialization:

- `listing_status` -> comma-separated `listing_status`
- `symbols` -> comma-separated `symbol`

### 8.2 `cmc_crypto_info`

**Description:** Get CoinMarketCap metadata for known cryptocurrencies. Numeric CMC IDs are preferred because symbols are not globally unique.

**Upstream:** `GET /v2/cryptocurrency/info`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "ids": {
      "type": "array",
      "items": {"type": "integer", "minimum": 1},
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true
    },
    "slugs": {
      "type": "array",
      "items": {"type": "string", "pattern": "^[0-9a-z-]+$"},
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true
    },
    "symbols": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[^,\\s]+$"},
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true
    },
    "skip_invalid": {"type": "boolean", "default": false}
  }
}
```

Cross-field rule:

- exactly one of `ids`, `slugs`, or `symbols` MUST be supplied.

Serialization:

- `ids` -> `id`
- `slugs` -> `slug`
- `symbols` -> `symbol`
- `skip_invalid` -> lowercase `true` / `false`

The initial MCP tool intentionally does not expose contract-address lookup or `aux`; add only through a plan revision.

### 8.3 `cmc_quotes_latest`

**Description:** Get the latest CoinMarketCap market quotes for a known set of cryptocurrencies. Prefer CMC IDs over symbols when identity ambiguity matters.

**Upstream:** `GET /v3/cryptocurrency/quotes/latest`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "ids": {
      "type": "array",
      "items": {"type": "integer", "minimum": 1},
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true
    },
    "slugs": {
      "type": "array",
      "items": {"type": "string", "pattern": "^[0-9a-z-]+$"},
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true
    },
    "symbols": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[^,\\s]+$"},
      "minItems": 1,
      "maxItems": 100,
      "uniqueItems": true
    },
    "convert": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[^,\\s]+$"},
      "minItems": 1,
      "maxItems": 3,
      "uniqueItems": true,
      "default": ["USD"]
    },
    "skip_invalid": {"type": "boolean", "default": false}
  }
}
```

Cross-field rule:

- exactly one of `ids`, `slugs`, or `symbols` MUST be supplied.

Serialization:

- `ids` -> `id`
- `slugs` -> `slug`
- `symbols` -> `symbol`
- `convert` -> comma-separated `convert`
- `skip_invalid` -> lowercase `true` / `false`

### 8.4 `cmc_listings_latest`

**Description:** Get a ranked, paginated list of active cryptocurrencies with current market data. Use this tool for market breadth/ranking; use `cmc_quotes_latest` for a known small asset set.

**Upstream:** `GET /v3/cryptocurrency/listings/latest`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "start": {"type": "integer", "minimum": 1, "default": 1},
    "limit": {"type": "integer", "minimum": 1, "maximum": 250, "default": 100},
    "convert": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[^,\\s]+$"},
      "minItems": 1,
      "maxItems": 3,
      "uniqueItems": true,
      "default": ["USD"]
    },
    "sort": {
      "enum": [
        "market_cap",
        "market_cap_strict",
        "name",
        "symbol",
        "date_added",
        "price",
        "circulating_supply",
        "total_supply",
        "max_supply",
        "num_market_pairs",
        "market_cap_by_total_supply_strict",
        "volume_24h",
        "volume_7d",
        "volume_30d",
        "percent_change_1h",
        "percent_change_24h",
        "percent_change_7d"
      ],
      "default": "market_cap"
    },
    "sort_dir": {"enum": ["asc", "desc"], "default": "desc"}
  }
}
```

Serialization is one-to-one except `convert`, which is comma joined.

The initial MCP tool intentionally omits provider threshold filters, `tag`, `cryptocurrency_type`, `convert_id`, and `aux`.

### 8.5 `cmc_global_metrics_latest`

**Description:** Get CoinMarketCap's latest aggregate crypto-market metrics, including market capitalization, volume, and dominance measures.

**Upstream:** `GET /v1/global-metrics/quotes/latest`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "convert": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[^,\\s]+$"},
      "minItems": 1,
      "maxItems": 3,
      "uniqueItems": true,
      "default": ["USD"]
    }
  }
}
```

Serialization: `convert` -> comma-separated `convert`.

### 8.6 `cmc_fear_greed_latest`

**Description:** Get the latest CoinMarketCap Crypto Fear and Greed Index value and classification.

**Upstream:** `GET /v3/fear-and-greed/latest`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

### 8.7 `cmc_fear_greed_historical`

**Description:** Get historical CoinMarketCap Crypto Fear and Greed values, paginated from the provider's daily series.

**Upstream:** `GET /v3/fear-and-greed/historical`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "start": {"type": "integer", "minimum": 1, "default": 1},
    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50}
  }
}
```

### 8.8 `cmc_altcoin_season_latest`

**Description:** Get the latest CoinMarketCap Altcoin Season Index snapshot.

**Upstream:** `GET /v1/altcoin-season-index/latest`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

### 8.9 `cmc_altcoin_season_historical`

**Description:** Get CoinMarketCap Altcoin Season Index history for one provider-supported timeframe.

**Upstream:** `GET /v1/altcoin-season-index/historical`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "timeframe": {"enum": ["7d", "30d", "90d"], "default": "7d"}
  }
}
```

### 8.10 `cmc_cmc100_latest`

**Description:** Get the latest CoinMarketCap 100 Index value, constituents, and constituent weights.

**Upstream:** `GET /v3/index/cmc100-latest`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

### 8.11 `cmc_cmc100_historical`

**Description:** Get historical CoinMarketCap 100 Index values at a provider-supported interval.

**Upstream:** `GET /v3/index/cmc100-historical`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "time_start": {"type": "string", "minLength": 1},
    "time_end": {"type": "string", "minLength": 1},
    "count": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    "interval": {"enum": ["5m", "15m", "daily"], "default": "daily"}
  }
}
```

Cross-field rules:

- if neither `time_start` nor `time_end` is supplied, use `count` (default 5);
- if one boundary is supplied, allow provider reverse/forward semantics and still cap `count` at 10;
- if both boundaries are supplied, `time_start` MUST be <= `time_end` after parsing;
- maximum 10 returned periods is an intentional v1 server bound even if provider behavior later permits more.

### 8.12 `cmc_cmc20_latest`

**Description:** Get the latest CoinMarketCap 20 Index value, constituents, and constituent weights.

**Upstream:** `GET /v3/index/cmc20-latest`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
```

### 8.13 `cmc_cmc20_historical`

**Description:** Get historical CoinMarketCap 20 Index values at a provider-supported interval.

**Upstream:** `GET /v3/index/cmc20-historical`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "time_start": {"type": "string", "minLength": 1},
    "time_end": {"type": "string", "minLength": 1},
    "count": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    "interval": {"enum": ["5m", "15m", "daily"], "default": "daily"}
  }
}
```

Cross-field behavior is identical to `cmc_cmc100_historical`.

---

## 9. Output contract

### 9.1 Successful calls

Do not invent a large normalization model in v1.

Each tool MUST return structured JSON content that preserves the provider envelope:

```json
{
  "status": {"...": "CoinMarketCap status fields"},
  "data": "CoinMarketCap endpoint-specific payload"
}
```

Permitted normalization:

- normalize `status.error_code` internally for success/error evaluation;
- do not mutate the actual source market values;
- do not rename provider fields;
- do not convert timestamps or percentages into derived values unless the upstream endpoint already returns them that way.

Cache state, retry count, and local timing SHOULD be logged/observable but MUST NOT be injected into `data`.

### 9.2 Empty valid data

An upstream success envelope with empty `data` is not automatically an error. Tool-specific contract tests decide whether empty data is valid.

### 9.3 Application-level upstream errors

If HTTP is successful but normalized `status.error_code != 0`, return/raise a stable local upstream application error rather than exposing it as tool success.

---

## 10. Error taxonomy

Implementation MUST use stable internal error classifications.

| Code | Meaning | Retry? | Capability impact |
|---|---|---:|---|
| `INVALID_ARGUMENT` | MCP/tool validation failure | No | None |
| `UPSTREAM_TIMEOUT` | connect/read/write/pool timeout | Yes, bounded | Transient |
| `UPSTREAM_NETWORK_ERROR` | DNS/socket/connection failure | Yes, bounded | Transient |
| `RATE_LIMITED` | HTTP 429 after bounded retry | Yes later | **Never unsupported** |
| `UPSTREAM_5XX` | selected HTTP 5xx | Yes, bounded | Transient |
| `UPSTREAM_HTTP_ERROR` | deterministic non-429 4xx | No | Investigate |
| `UPSTREAM_APPLICATION_ERROR` | CMC envelope error code nonzero | Depends on code | Investigate |
| `UPSTREAM_CONTRACT_MISMATCH` | missing/malformed expected envelope | No automatic retry after initial attempt | Contract failure |
| `UNSUPPORTED_ROUTE` | route positively shown unavailable by live capability criteria | No | Unsupported |
| `INTERNAL_ERROR` | local unexpected defect | No blind retry | Local defect |

Never map a generic exception directly to `UNSUPPORTED_ROUTE`.

---

## 11. Retry policy

Default policy:

- maximum attempts: 3 total, including initial request;
- retry HTTP 429;
- retry HTTP 502/503/504;
- retry selected network/timeouts;
- do not retry 400/401/403/404 by default;
- honor `Retry-After` exactly when it is parseable and within a configured maximum sleep;
- otherwise use exponential backoff + jitter;
- configure a maximum backoff delay so MCP calls cannot sleep indefinitely.

Unit tests MUST patch sleeping/time to keep retry tests fast and deterministic.

---

## 12. Cache policy

Caching is an optimization, not a correctness dependency.

Implement only after uncached tools pass contract tests.

Suggested initial TTLs:

| Tool group | Local TTL |
|---|---:|
| map / metadata | 300 s |
| latest quotes / listings | 30 s |
| global metrics | 300 s |
| Fear & Greed latest | 900 s |
| Fear & Greed historical | 900 s |
| Altcoin Season latest/history | 900 s |
| CMC100 / CMC20 latest/history | 300 s |

Requirements:

- cache key is route + normalized query params;
- identical parameter arrays MUST normalize deterministically;
- failed/error responses MUST NOT be cached;
- 429 responses MUST NOT be cached;
- cache implementation MUST be process-local in v1;
- no Redis/database dependency;
- tests MUST verify expiry and key normalization.

If cache complexity materially enlarges the first coherent slice, defer caching until Phase 3 without blocking Phase 2 tool correctness.

---

## 13. Live capability model

Live verification MUST classify each selected route as one of:

- `SUPPORTED`
- `RATE_LIMITED`
- `TRANSIENT_ERROR`
- `CONTRACT_MISMATCH`
- `UNSUPPORTED`

### 13.1 Classification rules

`SUPPORTED` requires:

- a request reaches the exact `/public-api` route;
- HTTP response is successful;
- the CMC envelope is valid;
- normalized `status.error_code == 0`;
- endpoint-specific `data` has the minimum expected shape.

`RATE_LIMITED` requires:

- HTTP 429, or provider-equivalent explicit rate-limit response.

`TRANSIENT_ERROR` includes:

- timeout;
- network failure;
- retryable 5xx after retry exhaustion.

`CONTRACT_MISMATCH` includes:

- successful HTTP response but missing/malformed `status` or `data` compared with the expected route contract.

`UNSUPPORTED` requires positive evidence such as:

- deterministic route-not-found/not-available response repeated after a separate run;
- documented removal of keyless support;
- deterministic provider response explicitly saying the route is unavailable to keyless requests.

A single 401/403 SHOULD be classified as investigation-required rather than immediately unsupported because provider policy/routing may have changed.

### 13.2 Evidence record

The live verifier MUST be able to write a machine-readable report containing at least:

```json
{
  "generated_at": "ISO-8601 UTC timestamp",
  "base_url": "https://pro-api.coinmarketcap.com/public-api",
  "server_version": "package version or git SHA",
  "routes": [
    {
      "tool": "cmc_quotes_latest",
      "route": "/v3/cryptocurrency/quotes/latest",
      "classification": "SUPPORTED",
      "http_status": 200,
      "cmc_error_code": 0,
      "attempts": 1,
      "latency_ms": 123,
      "evidence": "minimum-shape checks passed"
    }
  ]
}
```

Do not persist full market payloads in the capability report unless explicitly needed for debugging. Evidence should minimize unnecessary data retention.

---

## 14. Live verification matrix

Live tests are opt-in and MUST be serial by default.

Use small, deterministic requests:

| Tool | Minimal live call |
|---|---|
| `cmc_crypto_map` | `symbols=["BTC"]` |
| `cmc_crypto_info` | `ids=[1]` |
| `cmc_quotes_latest` | `ids=[1,1027]`, `convert=["USD"]` |
| `cmc_listings_latest` | `start=1`, `limit=2`, `convert=["USD"]` |
| `cmc_global_metrics_latest` | `convert=["USD"]` |
| `cmc_fear_greed_latest` | no args |
| `cmc_fear_greed_historical` | `start=1`, `limit=2` |
| `cmc_altcoin_season_latest` | no args |
| `cmc_altcoin_season_historical` | `timeframe="7d"` |
| `cmc_cmc100_latest` | no args |
| `cmc_cmc100_historical` | `count=2`, `interval="daily"` |
| `cmc_cmc20_latest` | no args |
| `cmc_cmc20_historical` | `count=2`, `interval="daily"` |

Expected identity constants used only for tests:

- BTC CMC ID: `1`
- ETH CMC ID: `1027`

Do not hard-code these as the only valid production assets.

---

## 15. Test strategy

### 15.1 Unit tests — mandatory

No network.

Cover at least:

1. fixed base URL construction;
2. no auth header ever emitted;
3. only GET requests permitted;
4. allowlisted route enforcement;
5. array -> comma-separated serialization;
6. exact selector mutual exclusion rules;
7. pagination bounds;
8. conversion-list bounds;
9. CMC100/CMC20 time validation;
10. normalized success for numeric `0` error code;
11. normalized success for string `"0"` error code if observed/allowed by parser;
12. nonzero CMC application error classification;
13. timeout classification;
14. 429 retry then success;
15. 429 exhaustion -> `RATE_LIMITED`;
16. 503 retry behavior;
17. deterministic 400 not retried;
18. malformed JSON classification;
19. missing `status` classification;
20. missing `data` classification;
21. no caching of errors;
22. deterministic cache keys;
23. cache expiry;
24. logger/output does not contaminate stdio protocol path.

### 15.2 Contract tests — mandatory

Use checked-in synthetic or sanitized response fixtures representing each endpoint family.

Test:

- minimum valid envelope;
- representative complete envelope;
- null optional fields;
- empty valid list where applicable;
- malformed provider shape;
- response model drift detection.

Do not assert every CoinMarketCap field forever. Assert the minimum structural contract needed to safely pass provider data through.

### 15.3 MCP tests — mandatory

Use the official SDK client in-process where possible.

Verify:

- tool discovery returns exactly the 13 v1 tools;
- tool names are stable;
- discoverable schemas are semantically equal to Section 8;
- unknown arguments are rejected;
- a representative call per endpoint family reaches the mocked client correctly;
- tool failures are surfaced as errors rather than fake successful payloads.

Endpoint families:

- cryptocurrency identity/info;
- quotes/listings;
- global metrics;
- sentiment/breadth;
- indices.

### 15.4 stdio integration tests — release blocking

Launch the server as a subprocess through the MCP client.

Verify:

- clean startup;
- tool discovery works;
- at least one mocked/safe tool invocation completes;
- stdout contains only MCP protocol traffic;
- process terminates cleanly;
- Windows-compatible subprocess behavior is exercised where CI/environment permits.

### 15.5 Streamable HTTP integration tests — release blocking

Verify:

- server starts on localhost;
- MCP client connects by URL;
- tool discovery works;
- one representative call succeeds using a mocked upstream;
- shutdown is clean.

### 15.6 Live tests — opt-in, release evidence required

Live tests MUST NOT run on every unit-test invocation.

They MUST:

- require an explicit flag/environment opt-in;
- never require credentials;
- run serially;
- use minimal payload sizes;
- produce capability classifications;
- avoid failing the entire suite merely because a route is `RATE_LIMITED` or `TRANSIENT_ERROR`.

Release qualification is separate from raw pytest pass/fail: see Section 20.

---

## 16. Security and privacy requirements

1. No secrets are required or accepted.
2. Do not log entire upstream responses at INFO level.
3. Do not log user-provided arbitrary metadata because there is none in v1 tool schemas.
4. Query values MAY be logged at DEBUG only if they contain no secrets; default logs should stay concise.
5. Prevent host/path injection structurally, not with string filtering after URL construction.
6. Set a bounded maximum response size if the HTTP library/runtime makes this practical.
7. Tool pagination limits intentionally remain below some provider limits.
8. No telemetry leaves the process unless the user explicitly configures ordinary logging/observability in a later plan.

---

## 17. Configuration contract

Keep configuration minimal.

Allowed configuration categories:

- log level;
- request timeout values;
- retry maximum attempts/backoff cap;
- cache enabled/disabled;
- local cache TTL overrides;
- transport selection;
- HTTP bind host/port for Streamable HTTP;
- conservative local max concurrency.

Forbidden configuration:

- CMC API key;
- arbitrary upstream base URL in production mode;
- arbitrary allowed routes;
- arbitrary HTTP headers;
- arbitrary HTTP method.

A test-only mechanism may inject a mock HTTP transport/base URL internally; it MUST NOT become a public runtime escape hatch.

---

## 18. Implementation phases

Each phase is a smallest coherent slice. Do not begin a later phase until the previous exit criteria are met or an explicit blocker is recorded.

### Phase 0 — Repository bootstrap and contract lock

#### Work

- inspect repository status and existing files;
- preserve all pre-existing user changes;
- add/confirm `AGENTS.md` if repository requires one;
- add package metadata and test skeleton;
- encode the 13-route allowlist as data/constants;
- encode exact tool names and descriptions;
- establish lint/type/test commands using existing project conventions;
- document no-key/no-auth invariant.

#### Acceptance criteria

- [ ] repository has one documented development/test command path;
- [ ] no credentials are referenced anywhere;
- [ ] route allowlist contains exactly the 13 v1 routes;
- [ ] no DEX route exists;
- [ ] no generic proxy abstraction is exposed;
- [ ] initial tests can run, even if they are only bootstrap tests.

#### Exit gate

`PHASE_0_ACCEPTED` only after repository bootstrap tests pass.

---

### Phase 1 — Keyless HTTP client and error model

#### Work

Implement the internal HTTP client before MCP tools.

Required behavior:

- fixed host/base path;
- GET-only allowlisted requests;
- query serialization;
- timeout handling;
- retry policy;
- envelope parsing;
- normalized `status.error_code` evaluation;
- stable internal error taxonomy.

#### Acceptance criteria

- [ ] no auth header test passes;
- [ ] host/path injection tests pass;
- [ ] only allowlisted GET requests can be constructed;
- [ ] 429 is classified as `RATE_LIMITED` after bounded retry;
- [ ] 502/503/504 retry tests pass;
- [ ] deterministic 4xx is not blindly retried;
- [ ] envelope errors are not returned as success;
- [ ] numeric/string zero error-code variants are safely handled.

#### Exit gate

All Phase 1 unit tests pass with no live network dependency.

---

### Phase 2 — Initial 13 MCP tools

#### Work

Implement the exact schemas from Section 8 and map each tool to one route.

Recommended implementation order:

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

#### Acceptance criteria

- [ ] discovery exposes exactly 13 tools;
- [ ] schemas match this plan;
- [ ] all cross-field validation rules are enforced locally;
- [ ] every tool calls exactly one allowlisted route;
- [ ] outputs preserve provider `status` + `data` shape;
- [ ] no DEX tool is visible;
- [ ] contract tests cover every endpoint family.

#### Exit gate

Unit + contract + in-process MCP tests pass.

---

### Phase 3 — Cache and resource hardening

#### Work

- process-local TTL cache;
- deterministic cache keys;
- concurrency bound;
- response-size/resource protections where practical;
- logging discipline.

#### Acceptance criteria

- [ ] cache never stores errors/429s;
- [ ] expiry tests pass;
- [ ] parameter-order-independent cache keys pass;
- [ ] concurrency bound is tested;
- [ ] logging does not emit response payloads at INFO;
- [ ] disabling cache yields correct behavior.

#### Exit gate

Phase 3 focused tests and full non-live suite pass.

---

### Phase 4 — Transport qualification

#### Work

- stdio entry point;
- Streamable HTTP entry point;
- Codex CLI configuration example in README;
- local HTTP configuration example.

#### Acceptance criteria

- [ ] stdio subprocess MCP discovery passes;
- [ ] stdio representative tool call passes with mocked upstream;
- [ ] no stdout contamination;
- [ ] Streamable HTTP discovery passes;
- [ ] Streamable HTTP representative call passes;
- [ ] both transports expose identical 13-tool surface.

#### Exit gate

Both transport integration suites pass.

---

### Phase 5 — Live keyless capability verification

#### Work

Run the matrix from Section 14 against the real keyless base URL.

Requirements:

- serial requests;
- no credentials;
- bounded retries;
- record route-level classifications;
- produce machine-readable evidence;
- rerun only ambiguous/transient routes rather than hammering the whole catalog.

#### Acceptance criteria

For release:

- [ ] every one of the 13 routes has a recorded live classification;
- [ ] all 13 are `SUPPORTED`, OR any non-supported route is explicitly removed from the claimed v1 surface before release;
- [ ] no route is removed solely because of `RATE_LIMITED` or `TRANSIENT_ERROR` evidence;
- [ ] evidence records the exact base URL and timestamp;
- [ ] live calls show no authentication header is required.

#### Exit gate

`LIVE_KEYLESS_CORE_VERIFIED` when the released tool surface is fully supported by current evidence.

---

### Phase 6 — Documentation and release readiness

#### Work

README must include:

- project purpose;
- keyless/no-account property;
- explicit 13-tool catalog;
- transport setup;
- Codex CLI stdio example;
- Streamable HTTP example;
- known provider rate-limit behavior without inventing a numeric quota;
- error semantics;
- live-verification command;
- disclaimer that CoinMarketCap can change keyless coverage;
- how to rerun capability verification after provider changes.

#### Acceptance criteria

- [ ] fresh clone install instructions work;
- [ ] README commands are tested as written where environment permits;
- [ ] full non-live test suite passes;
- [ ] transport qualification passes;
- [ ] live evidence gate passes;
- [ ] final diff contains no unrelated changes;
- [ ] package contains no credential configuration.

#### Exit gate

`V1_RELEASE_READY` only when all release gates in Section 20 are satisfied.

---

## 19. Deferred Phase 2 product scope: DEX expansion

DEX functionality is intentionally not part of v1.

A future plan revision may add selected keyless DEX routes such as:

- spot-pair listings;
- pair quotes;
- token detail/price;
- token liquidity;
- token pools;
- search;
- security detail;
- swap list;
- platform list/detail;
- K-line candles/points;
- holder count/list/detail.

Before adding any DEX tool:

1. verify the exact current route and parameters in official docs;
2. establish chain/platform and contract-address identity semantics;
3. define bounded tool schemas;
4. define pagination/output-size limits;
5. create separate live capability evidence;
6. prove no generic on-chain path proxy is introduced.

Do not add DEX opportunistically while implementing v1.

---

## 20. Release gates

All gates are mandatory for the released v1 surface.

### GATE-001 — Scope

- exactly 13 tools;
- no DEX;
- no generic proxy.

### GATE-002 — Authentication

Automated tests prove no API key/header is required or emitted.

### GATE-003 — HTTP correctness

All selected routes use fixed keyless base URL + GET only.

### GATE-004 — Unit/contract tests

All non-live unit and contract tests pass.

### GATE-005 — MCP discovery

In-process discovery returns stable schemas matching Section 8.

### GATE-006 — stdio

Subprocess stdio discovery and representative invocation pass without stdout contamination.

### GATE-007 — Streamable HTTP

HTTP MCP discovery and representative invocation pass.

### GATE-008 — Live capability

Every released route has current `SUPPORTED` evidence.

### GATE-009 — Rate-limit semantics

429 behavior is verified to classify as `RATE_LIMITED`, not unsupported.

### GATE-010 — Diff review

Final implementation diff contains no unrelated edits, secrets, generated junk, or test weakening.

---

## 21. Required verification commands

Exact commands may be adjusted to repository tooling established in Phase 0, but the final README and handoff must report commands that actually ran.

Expected shape:

```bash
uv sync
uv run pytest tests/unit tests/contract tests/mcp
uv run pytest tests/mcp/test_stdio.py
uv run pytest tests/mcp/test_streamable_http.py
uv run pytest
```

Opt-in live verification should have one explicit command, for example:

```bash
uv run python -m coinmarketcap_keyless_mcp.verify_live
```

or an equivalent test marker:

```bash
uv run pytest -m live tests/live
```

Choose one canonical interface during implementation; do not leave two partially maintained mechanisms.

If lint/type checking are adopted, their exact commands become release-required once added.

---

## 22. Acceptance scenarios

### Scenario A — Canonical asset research

Input:

1. resolve BTC/ETH through `cmc_crypto_map`;
2. use returned IDs with `cmc_quotes_latest`;
3. retrieve `cmc_global_metrics_latest`.

Expected:

- no credential setup;
- stable IDs used;
- valid current quote/global data returned;
- no hidden fallback.

### Scenario B — Sentiment overlay

Input:

- `cmc_fear_greed_latest`;
- `cmc_fear_greed_historical(limit=30)`;
- `cmc_altcoin_season_latest`;
- `cmc_altcoin_season_historical(timeframe="30d")`.

Expected:

- source index values returned unchanged;
- no locally invented sentiment score;
- upstream failures use stable error classification.

### Scenario C — Benchmark regime context

Input:

- `cmc_cmc100_latest`;
- `cmc_cmc100_historical(count=5, interval="daily")`;
- `cmc_cmc20_latest`;
- `cmc_cmc20_historical(count=5, interval="daily")`.

Expected:

- latest/historical constituent/index structure preserved;
- bounded result periods;
- response shape validated.

### Scenario D — Rate limit

Simulate or observe 429.

Expected:

- bounded retry occurs;
- `Retry-After` honored when supplied;
- final classification is `RATE_LIMITED` if exhausted;
- route remains capability-unknown/support-preserving rather than becoming unsupported.

### Scenario E — Agent misuse

Attempt:

- arbitrary URL;
- unsupported path;
- API key header;
- DEX route;
- unknown tool argument.

Expected:

- impossible through the public MCP schema or rejected locally before upstream network access.

---

## 23. Codex execution protocol

When implementing this plan, the coding agent MUST:

1. read `AGENTS.md`, this plan, relevant existing tests/configuration, and current git status/diff before editing;
2. preserve all pre-existing user changes;
3. implement only the active phase or explicitly requested slice;
4. prefer existing repository patterns over new abstractions;
5. not install global dependencies;
6. not add DEX/tools outside Section 8;
7. not weaken tests to make implementation pass;
8. run focused tests first, then applicable broader checks;
9. review the final diff for unrelated changes and credential leaks;
10. report commands actually run and their actual outcomes;
11. record blockers rather than guessing through provider/API ambiguity;
12. stop scope expansion when an external documentation discrepancy is discovered and update evidence/plan before changing public contracts.

### 23.1 Decision rule for upstream documentation drift

If CoinMarketCap documentation changes while implementation is underway:

- do not silently change an existing public MCP schema;
- confirm the new provider contract;
- add/update a contract fixture;
- update this plan or a superseding ADR/plan before a breaking schema change;
- rerun live capability verification.

---

## 24. Definition of done

The v1 implementation is done only when:

- the repository exposes exactly the 13 tools in Section 8;
- each tool maps to exactly one documented keyless route;
- there is no credential path or authenticated fallback;
- unit, contract, MCP, stdio, and Streamable HTTP required tests pass;
- every released route has current live `SUPPORTED` evidence;
- 429 behavior is correctly classified;
- documentation accurately describes current behavior and limitations;
- the final diff is reviewed and contains no unrelated changes.

Passing mocked tests alone is insufficient.

A live 429 alone is also insufficient to reject a route.

The controlling completion statement is:

> `coinmarketcap-keyless-mcp` v1 is a bounded, read-only, credential-free MCP adapter whose released tool surface is verified against CoinMarketCap's current `/public-api` keyless routes and whose stdio transport is qualified for Codex CLI use.

---

## 25. Explicit unresolved items

These items are intentionally deferred to implementation evidence rather than guessed now:

1. **Current exact upstream keyless catalog count:** official pages currently disagree between 35 and 36 total routes. This does not block the selected 13-route v1 scope.
2. **Numeric keyless rate limit:** do not invent one. Observe 429/`Retry-After` behavior and document only verified facts.
3. **Exact stable dependency versions:** choose after inspecting current package releases at implementation time.
4. **DEX surface:** requires a separate plan revision after v1 verification.
5. **Authenticated upgrade path:** explicitly out of v1 scope; do not pre-build credential abstractions.


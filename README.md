# coinmarketcap-keyless-mcp

`coinmarketcap-keyless-mcp` is a bounded, read-only Model Context Protocol (MCP) server for selected CoinMarketCap Keyless Public API routes. It requires no CoinMarketCap account, API key, secret, wallet, or authentication header. Upstream access is fixed to `https://pro-api.coinmarketcap.com/public-api` and uses `GET` only.

The v1 surface is deliberately narrow: exactly 13 typed tools, each mapped to one allowlisted route. It does not expose a generic URL/path proxy, authenticated fallback, or DEX tools.

## Tool catalog

| Tool | Route | Purpose |
|---|---|---|
| `cmc_crypto_map` | `/v1/cryptocurrency/map` | Resolve canonical CoinMarketCap IDs and identifiers. |
| `cmc_crypto_info` | `/v2/cryptocurrency/info` | Read static metadata for known assets. |
| `cmc_quotes_latest` | `/v3/cryptocurrency/quotes/latest` | Read current quotes for known assets. |
| `cmc_listings_latest` | `/v3/cryptocurrency/listings/latest` | Read a ranked, paginated current market list. |
| `cmc_global_metrics_latest` | `/v1/global-metrics/quotes/latest` | Read aggregate market capitalization, volume, and dominance metrics. |
| `cmc_fear_greed_latest` | `/v3/fear-and-greed/latest` | Read the current Fear & Greed value and classification. |
| `cmc_fear_greed_historical` | `/v3/fear-and-greed/historical` | Read paginated historical Fear & Greed values. |
| `cmc_altcoin_season_latest` | `/v1/altcoin-season-index/latest` | Read the current Altcoin Season Index snapshot. |
| `cmc_altcoin_season_historical` | `/v1/altcoin-season-index/historical` | Read Altcoin Season Index history for a supported timeframe. |
| `cmc_cmc100_latest` | `/v3/index/cmc100-latest` | Read the current CMC100 value, constituents, and weights. |
| `cmc_cmc100_historical` | `/v3/index/cmc100-historical` | Read bounded CMC100 historical values. |
| `cmc_cmc20_latest` | `/v3/index/cmc20-latest` | Read the current CMC20 value, constituents, and weights. |
| `cmc_cmc20_historical` | `/v3/index/cmc20-historical` | Read bounded CMC20 historical values. |

Numeric CMC IDs are preferred over ticker symbols where practical because symbols can be ambiguous. Tool schemas reject unknown arguments, enforce bounded list/pagination inputs, and validate cross-field constraints locally.

## Requirements and development

Python 3.11 or newer is required. The documented workflow uses [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest -q
```

The package reports the version declared in `pyproject.toml`. Runtime dependencies are `mcp`, `httpx`, and `uvicorn` (for Streamable HTTP); test dependencies are provided by the `dev` dependency group.

## Transports

The canonical local stdio command is:

```bash
uv run coinmarketcap-keyless-mcp
```

It keeps stdout reserved for MCP protocol traffic; diagnostics go to logging/stderr. The same command's help is available with `uv run coinmarketcap-keyless-mcp --help`.

For Codex CLI, use the tested command directly and provide no secret environment variables:

```toml
[mcp_servers.coinmarketcap_keyless]
command = "uv"
args = ["run", "coinmarketcap-keyless-mcp"]
```

The secondary Streamable HTTP transport is intended for local use. It binds to `127.0.0.1:8000` by default and exposes MCP at `/mcp`:

```bash
uv run coinmarketcap-keyless-mcp --transport streamable-http
```

Use `--host` and `--port` to choose the local bind address and port, for example `--host 127.0.0.1 --port 8001`. This is not an internet-facing hosted service: the HTTP transport has no authentication, so anyone who can reach it can spend this machine's keyless CoinMarketCap rate limit. Binding to a non-loopback host such as `0.0.0.0` logs a warning to stderr. Both transports expose the same 13 tools and schemas.

## Behavior and errors

The server preserves the provider's `status` and `data` envelope rather than inventing derived market indicators. Provider text fields (for example project descriptions) are passed through verbatim, so treat them as untrusted input to the model. A successful HTTP 2xx response must also have a valid CMC envelope with normalized `status.error_code == 0`.

Validation failures are `INVALID_ARGUMENT`. Exhausted HTTP 429 retries are `RATE_LIMITED`, never `UNSUPPORTED_ROUTE`. Timeout, network, and retryable 5xx failures retain transient upstream classifications; malformed successful responses are `UPSTREAM_CONTRACT_MISMATCH`; provider application errors are `UPSTREAM_APPLICATION_ERROR`. Unsupported capability is recorded only with positive evidence.

Retries are bounded and apply to 429, 502/503/504, and selected network/timeouts. Valid `Retry-After` values within the backoff cap are honored; a longer `Retry-After` ends retrying immediately with the final classification (for example `RATE_LIMITED`) instead of retrying early; otherwise capped exponential backoff with jitter is used. Each attempt also has a 30-second wall-clock deadline. Deterministic non-429 4xx responses are not retried. Non-retryable 4xx errors include the provider's error message when the body carries one (read up to 4 KiB, sanitized). The client uses a bounded (64-entry) process-local TTL cache for successful responses only, coalesces identical concurrent cold requests into one upstream fetch, with route-specific short TTLs for volatile data and a default maximum of two concurrent upstream requests. Caching is an optimization, not a correctness dependency.

## Live keyless capability verification

Live verification is opt-in and separate from ordinary offline tests:

```bash
uv run python -m coinmarketcap_keyless_mcp.verify_live
```

It serially probes the 13 minimal route calls against the fixed keyless base URL without credentials and writes a timestamped, minimized JSON report under [`verification/`](verification/). To rerun one selected ambiguous or transient route:

```bash
uv run python -m coinmarketcap_keyless_mcp.verify_live --tool cmc_quotes_latest
```

Classifications are:

- `SUPPORTED`: the keyless response passed the route's minimum shape checks;
- `RATE_LIMITED`: the route exhausted HTTP 429 handling;
- `TRANSIENT_ERROR`: a timeout, network, or retryable upstream failure prevented a conclusion;
- `CONTRACT_MISMATCH`: the response envelope or minimum route shape was not valid;
- `UNSUPPORTED`: positive provider evidence indicates the keyless capability is unavailable.

The command exits `0` only when every probed route is `SUPPORTED`, `1` otherwise, and `2` if the run or evidence write fails.

The current release evidence is `verification/live-capability-20261001T151943758586Z.json`, produced by the manual `live-release-qualification.yml` workflow (run `36883326560`) on the exact `1.0.2` release commit `b486dec35b0a6849abaa5f0ade8633b08ebafa4a`; see [`verification/release-1.0.2.md`](verification/release-1.0.2.md). It records all 13 released routes as `SUPPORTED` with HTTP 200 and provider error code 0, the exact fixed base URL, timestamps, no credentials, and server version `1.0.2`; reports intentionally retain no full provider payloads. The status is `LIVE_KEYLESS_CORE_VERIFIED`. The earlier Phase 5 evidence for pre-release `0.1.0` (`verification/live-capability-20261001T015531675887Z.json`, with the selected historical-route rerun in `verification/live-capability-20261001T015419204714Z.json`) is kept for history. CoinMarketCap can change keyless coverage or rate-limit behavior, so rerun the full command or a selected route after provider changes and before a later release qualification. Do not infer unsupported capability from one 429 or transient failure.

## Tests

The required non-live qualification commands are:

```bash
uv sync
uv run pytest tests/unit -q
uv run pytest tests/contract -q
uv run pytest tests/mcp -q
uv run pytest tests/mcp/test_stdio.py -q
uv run pytest tests/mcp/test_streamable_http.py -q
uv run pytest -q
git diff --check
```

Tests use fixtures, mocks, local subprocesses, and a localhost HTTP server; they do not require live CoinMarketCap access.

## Explicit non-goals

This v1 package provides no trading, order placement, wallets, signing, custody, transactions, credentials, API-key configuration, authenticated fallback, DEX surface, generic proxy, investment advice, portfolio construction, or locally derived investment-advice logic. It does not silently transform provider values into locally derived indicators.

The exact contract is encoded in [`src/coinmarketcap_keyless_mcp/contracts.py`](src/coinmarketcap_keyless_mcp/contracts.py), and the product boundary is defined in [`PLAN.md`](PLAN.md).

## License

MIT. See [LICENSE](LICENSE).

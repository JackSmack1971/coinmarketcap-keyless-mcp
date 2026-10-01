# coinmarketcap-keyless-mcp

`coinmarketcap-keyless-mcp` is a bounded, read-only MCP adapter for the selected CoinMarketCap public routes defined in [`PLAN.md`](PLAN.md). Phase 0 locks the v1 route and tool contract; Phase 1 provides the internal fixed-host HTTP client and stable upstream error model; Phase 2 exposes the initial 13 MCP tools. Transports remain later-phase work.

## Development

Install the project and development dependencies with `uv sync`, then run the canonical test command:

```bash
uv sync
uv run pytest
```

The adapter is designed to run without account setup or provider credentials. It will use only the fixed public API base URL and GET routes defined by the contract.

The Phase 1 client retries only bounded transient failures (429 and 502/503/504, plus selected network/timeouts). Exhausted 429 responses are classified as `RATE_LIMITED`; malformed successful envelopes are classified as `UPSTREAM_CONTRACT_MISMATCH`.

## Phase 0 contract

The exact 13-tool surface and route mapping are encoded in [`src/coinmarketcap_keyless_mcp/contracts.py`](src/coinmarketcap_keyless_mcp/contracts.py). DEX routes and arbitrary proxy behavior are intentionally outside this package's public contract.

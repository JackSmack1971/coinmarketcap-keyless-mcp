# H2 Mutation Evidence

**Recorded:** 2026-10-01 UTC
**Branch / baseline:** `hardening/v1.0.1` / H1 commit `20181b847dcfd91594757e634e3a2174ec266230`
**Mutmut:** 3.8.0
**Environment:** WSL2 Ubuntu, CPython 3.14.4, Linux; isolated copy at `/tmp/h2-campaign/repo`. The locked dev group also resolved on CPython 3.11.16 and reported mutmut 3.8.0.
**Scope:** `client.py`, `errors.py`, `models.py`, `contracts.py`, and `server.py`; no live network access.

## Configuration and commands

The opt-in `[tool.mutmut]` configuration in `pyproject.toml` names those five source files, the offline unit/contract/MCP test subset, `timeout_constant = 1.0`, and `timeout_multiplier = 5.0`. It does not add a CI or normal `pytest` requirement.

The selected pytest subset passed independently before mutation: **89 passed** on Windows and **89 passed** on WSL/Linux. Each target process was externally capped at 600 seconds. The final partition commands were:

```bash
timeout --signal=INT --kill-after=10s 600s .venv/bin/mutmut run --max-children 2 "coinmarketcap_keyless_mcp.client*"
timeout --signal=INT --kill-after=10s 600s .venv/bin/mutmut run --max-children 2 "coinmarketcap_keyless_mcp.errors*"
timeout --signal=INT --kill-after=10s 600s .venv/bin/mutmut run --max-children 2 "coinmarketcap_keyless_mcp.models*" "coinmarketcap_keyless_mcp.contracts*"
timeout --signal=INT --kill-after=10s 600s .venv/bin/mutmut run --max-children 2 "coinmarketcap_keyless_mcp.server*"
.venv/bin/mutmut results --all true
```

All partitions completed well below the cap. Observed elapsed times were 34.8s (`client`), 4.6s (`errors`), 8.0s (`models` / `contracts`), and 23.9s (`server`). The total result set contained **574 generated and run mutants**: 389 killed and 185 survived. There were 0 timeouts, suspicious results, or tool errors.

| Campaign | Generated / run | Killed | Survived | Timeout / suspicious / error |
| --- | ---: | ---: | ---: | ---: |
| A — HTTP boundary and errors (`client.py`, `errors.py`) | 437 | 282 | 155 | 0 / 0 / 0 |
| B — validation contracts (`models.py`, `contracts.py`) | 60 | 40 | 20 | 0 / 0 / 0 |
| C — MCP adapter (`server.py`) | 77 | 67 | 10 | 0 / 0 / 0 |
| **Total** | **574** | **389** | **185** | **0 / 0 / 0** |

Campaign B's 60 mutants were all in `models.py`; mutmut generated none for `contracts.py`, which contains route/tool data declarations rather than mutatable function bodies. Exact route identity remains covered by the offline tool/route tests. This is a mutmut tooling limitation, not evidence that `contracts.py` was mutation-qualified.

## Survivor classification

Every one of the final 185 survivors is classified below; none is an unexplained release-critical survivor.

| Classification | Count | Survivor groups and rationale |
| --- | ---: | --- |
| `OUT_OF_SCOPE` | 176 | 40 cache key/TTL/cache-state mutations deferred to H3; 39 `get` mutations affecting diagnostic text/metadata rather than its tested error code; 20 constructor/cache/diagnostic/HTTP-header/default-timeout mutations; 45 envelope error wording or diagnostic metadata mutations; 18 selector/timestamp validation wording or argument-label mutations; 5 internal `CmcClientError` message/metadata mutations; and 9 server identity/version or validation-message mutations outside the released 13-tool surface. |
| `EQUIVALENT_OR_SEMANTICALLY_IRRELEVANT` | 9 | 3 timezone-adjustment mutations that do not change a parsed, GMT-qualified HTTP date; 2 case changes to the case-insensitive `Retry-After` header lookup; 1 extra retry-loop range element made unreachable by the explicit attempt guards; 1 `by_alias=False` schema serialization change with no aliased fields; and 2 `Z` replacement mutations where the supported Python ISO parser already accepts the UTC suffix. |
| `TEST_GAP` | 0 remaining | Gaps found during review were repaired with the focused tests listed below, then the final campaigns were rerun. |
| `TOOLING_LIMITATION` | 0 survivors | `contracts.py` produced no mutants; see Campaign B note above. |
| `REQUIRES_PRODUCT_DECISION` | 0 | No survivor requires changing the public contract. |

## Coverage strengthened

Focused negative-path tests were added or extended for:

- exact route allowlisting against traversal, encoded, absolute-URL, query-suffixed, and trailing-slash inputs;
- error-code integer, float, whitespace-padded string, and boolean handling; missing `error_code` versus missing `data`;
- HTTP 500 classification without retry and distinct timeout/network classifications;
- exact response-size acceptance, `Retry-After` zero/cap/date handling, capped exponential jitter for HTTP and network retries, and constructor retry/backoff/time bounds;
- continued query serialization after an omitted `None` value;
- host-timezone-independent UTC assignment for naive ISO timestamps, equal-instant index bounds, slug-to-query mapping, and the default server client factory.

## Final verification

- `uv sync` — passed.
- `uv run ruff check src tests` — passed.
- `uv run pytest tests/unit -q` — 81 passed.
- `uv run pytest tests/contract -q` — 9 passed.
- `uv run pytest tests/mcp -q` — 29 passed.
- `uv run pytest -q` — 119 passed.
- `uv build` — wheel and source distribution built.
- `uv lock --check` — passed.
- `git diff --check` — passed.

No production implementation changed. Existing stdio subprocess tests were retained without duplication. The normal H1 workflow was not changed and does not invoke mutmut.

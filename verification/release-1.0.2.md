# 1.0.2 release qualification evidence

## Candidate

- Base: `main` at `a3c363c` (merge of PR #12). Since `v1.0.1` it includes PRs #10, #11 and #12.
- Candidate changes: the version bump to `1.0.2` in `pyproject.toml` and `uv.lock`, the `CHANGELOG.md` section, and this file. Runtime code is unchanged from `a3c363c`.
- Release commit qualified live: `b486dec35b0a6849abaa5f0ade8633b08ebafa4a` (merge of PR #13).

## Offline qualification

Environment: Linux x86_64, CPython 3.11.15, uv (local).

| Command | Result |
|---|---:|
| `uv sync --locked --all-groups` | passed |
| `uv run ruff check src tests scripts` | passed |
| `uv run ruff format --check src tests scripts` | passed |
| `uv run pytest -q tests/unit tests/contract tests/mcp` | 253 passed |
| `uv run pytest -q tests/mcp/test_stdio.py` | 4 passed |
| `uv run pytest -q tests/mcp/test_streamable_http.py` | 3 passed |
| `uv run pytest -q tests/security` | 51 passed |
| `uv run pytest -q` | 304 passed |
| `uv build` | passed; `coinmarketcap_keyless_mcp-1.0.2-py3-none-any.whl`, `coinmarketcap_keyless_mcp-1.0.2.tar.gz` |
| `uv lock --check` | passed |
| `git diff --check` | passed |
| `pip-audit` over all locked dependency groups (`--strict --require-hashes`) | no known vulnerabilities |
| `scripts/qualify_packaging.py`, Python 3.11 legs | wheel and sdist: isolated install with no dev or build dependencies, 13-tool stdio discovery, fixture call, clean shutdown; wheel: Streamable HTTP discovery, fixture call, clean shutdown; installed version `1.0.2` |
| Mutation gate (`mutmut run`, then `scripts/mutation_gate.py --min-score 92`) | 93.0% on the identical runtime code at `ac7bc0b` (see `mutation-survivors.md`); CI reruns it on this candidate |

The Python 3.14 packaging legs can't run locally: this environment only has a 3.14 release candidate, which crashes inside pydantic. CI's `Packaging qualification` job runs both 3.11 and 3.14.

## Release gates (PLAN.md section 20)

| Gate | Status |
|---|---|
| GATE-001 Scope (13 tools, no DEX, no proxy) | passed: tool discovery tests |
| GATE-002 Authentication | passed: security tests show no API key or auth header is accepted or emitted |
| GATE-003 HTTP correctness | passed: fixed base URL, GET only, route allowlist tests |
| GATE-004 Unit/contract tests | passed |
| GATE-005 MCP discovery | passed |
| GATE-006 stdio | passed |
| GATE-007 Streamable HTTP | passed |
| GATE-008 Live capability | passed: 13/13 `SUPPORTED` on release commit `b486dec35b0a6849abaa5f0ade8633b08ebafa4a` |
| GATE-009 Rate-limit semantics | passed: 429 exhaustion is `RATE_LIMITED` (unit and security tests) |
| GATE-010 Diff review | passed: the release diff is the version, changelog and this file only |

### GATE-008: live capability

The canonical live verifier ran successfully on GitHub Actions against the exact `1.0.2` release commit:

- workflow run: `36883326560`
- qualified SHA: `b486dec35b0a6849abaa5f0ade8633b08ebafa4a`
- run window: `2026-10-01T15:19Z`
- command: `uv run python -m coinmarketcap_keyless_mcp.verify_live`
- verifier exit: `0`
- result: `13/13 SUPPORTED`
- evidence: `verification/live-capability-20261001T151943758586Z.json`
- artifact: `live-capability-b486dec35b0a` (artifact ID `11172931410`)
- artifact SHA-256: `390c1d05381b0494643fe7d7b34a45875c351d464111637b340b870c8702a32c`
- extracted JSON SHA-256: `a3368434d617bdc5d08caaf8e93900967443b318aaa7a5fdf2e13a099e708de6`
- fixed base URL: `https://pro-api.coinmarketcap.com/public-api`
- credentials: none

The GitHub-hosted runner connectivity preflight returned HTTP 200 before verification. The generated evidence contains exactly the 13 released routes, each with HTTP 200, provider error code 0, and classification `SUPPORTED`.

## Version decision

`1.0.2` is a patch release. The 13 tool names, routes and output envelope are unchanged, and no capability, credential path, DEX support or proxy behaviour was added.

There is one input-validation narrowing in a public schema. `symbols` and `convert` items now reject commas and whitespace and are capped at 64 characters. Before this, a comma-joined item such as `"USD,EUR,GBP,JPY"` got past the documented list-size and uniqueness bounds. This is treated as a bug fix that enforces the existing contract, so it's still a patch release. `PLAN.md` was updated in PR #10 to match. A client that relied on the bypass will now get `INVALID_ARGUMENT`.

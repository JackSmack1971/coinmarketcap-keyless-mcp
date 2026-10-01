# 1.0.2 release qualification evidence

## Candidate

- Base: `main` at `a3c363c` (merge of PR #12). Since `v1.0.1` it includes PRs #10, #11 and #12.
- Candidate changes: the version bump to `1.0.2` in `pyproject.toml` and `uv.lock`, the `CHANGELOG.md` section, and this file. Runtime code is unchanged from `a3c363c`.

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
| GATE-008 Live capability | **PENDING**: see below |
| GATE-009 Rate-limit semantics | passed: 429 exhaustion is `RATE_LIMITED` (unit and security tests) |
| GATE-010 Diff review | passed: the release diff is the version, changelog and this file only |

### GATE-008: live capability (pending)

The live verifier couldn't run from the qualification environment. Its network policy denies `pro-api.coinmarketcap.com` (the outbound proxy returned HTTP 403 on CONNECT). The most recent live evidence, `live-capability-20261001T051127293524Z.json` (all 13 `SUPPORTED`), was taken on `1.0.1` runtime code. Since then the client's request path has changed: request deadlines, request sharing, `Retry-After` handling, decoding and the depth limit. So that evidence doesn't cover this candidate.

**Do not tag `v1.0.2` until this command passes against the release commit:**

```bash
uv run python -m coinmarketcap_keyless_mcp.verify_live
```

It exits `0` only when every route is `SUPPORTED`. Commit the evidence JSON it writes under `verification/`, and record it here.

## Version decision

`1.0.2` is a patch release. The 13 tool names, routes and output envelope are unchanged, and no capability, credential path, DEX support or proxy behaviour was added.

There is one input-validation narrowing in a public schema. `symbols` and `convert` items now reject commas and whitespace and are capped at 64 characters. Before this, a comma-joined item such as `"USD,EUR,GBP,JPY"` got past the documented list-size and uniqueness bounds. This is treated as a bug fix that enforces the existing contract, so it's still a patch release. `PLAN.md` was updated in PR #10 to match. A client that relied on the bypass will now get `INVALID_ARGUMENT`.

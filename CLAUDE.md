@AGENTS.md

# Claude Code notes

`AGENTS.md` is the execution contract (it was written for Codex; the rules apply to Claude Code unchanged). This file only adds Claude-specific working notes. Do not duplicate AGENTS.md, PLAN.md or VERSION_CONTROL.md here, and do not `@`-import PLAN.md or HARDENING_PLAN.md (large). Read the relevant PLAN.md section when a task touches tools, schemas, routes, errors, retries, cache or transports.

## Repo map (actual layout; PLAN.md section 5 is a stale target tree)

- `src/coinmarketcap_keyless_mcp/client.py`: keyless HTTP client, retry/backoff, response-size and depth bounds, decoding, TTL cache, request coalescing.
- `contracts.py`: `BASE_URL`, `ROUTES`, `TOOL_CONTRACTS` (single source of truth for tool names, descriptions, routes).
- `models.py`: validation types and cross-field rules. `errors.py`: stable error taxonomy.
- `server.py`: the 13 MCP tools. `runtime.py`: stdio / Streamable HTTP entry points. `verify_live.py`: opt-in live verifier.
- `tests/{unit,contract,mcp,security}`, `scripts/{mutation_gate,qualify_packaging}.py`, `verification/` (evidence and reports).
- No `config.py`, `cache.py`, `tools/` or `tests/live/`, despite PLAN.md.

## Definition of done (matches CI)

```bash
uv sync --locked --all-groups
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
uv lock --check
git diff --check
```

The README and AGENTS.md test ladders omit ruff and `uv lock --check`; CI enforces them. Run focused tests first, then this set. `/verify` runs it. Report only commands that actually ran.

## Environment

- Local Python is 3.11 (`UV_PYTHON` is set in `.claude/settings.json`). The Python 3.14 and Windows legs run in CI only; 3.14 release candidates have crashed inside pydantic.
- The sandbox cannot reach `pro-api.coinmarketcap.com`. Never run `verify_live` here and never report a live result from here. Live qualification runs through the manual GitHub workflow `live-release-qualification.yml` with a full 40-character SHA (abbreviated SHAs are rejected). See the `release-qualify` skill.

## Fragile areas

- `server.py` tightens SDK tool models through private MCP internals (`_tool_manager`, `model_dump_one_level`). Do not refactor or "clean up" this, and do not bump `mcp` outside `>=2.2,<2.3` without requalifying.
- Mutation gate: `uv run mutmut run --max-children 4` then `uv run python scripts/mutation_gate.py --min-score 92` (CI limit is 20 minutes). The score is a ratchet: raise it, never lower it. Run it after changes to `client.py`, `contracts.py`, `models.py`, `server.py` or `errors.py`. Changing mutmut config invalidates results. Subprocess tests are deselected under mutmut because they import the installed package.
- Do not read `uv.lock` or `mutants/`. `uv.lock` changes only through `uv`.
- Public-contract changes (tool names, schemas, routes, error classes, output envelope) need an explicit plan change. Use the `invariants-reviewer` subagent before finishing any change to those files.

## Git

Follow `VERSION_CONTROL.md`. No commit, push, tag or PR without explicit authorization. No generated co-author or session trailers (attribution is blanked in settings).

**Standing authorization (granted by the repository owner, 2026-10-02):** on the active cloud-development branch, after each coherent implementation, remediation, contract-review or acceptance slice has passed its required verification, Claude may, without asking again:

1. stage only that slice's intended files (never `git add -A` or unrelated changes);
2. inspect the staged diff (`git diff --staged`) before committing;
3. create one coherent commit for the slice;
4. push the branch with a normal, non-force push.

This does not authorize merging, opening a PR, force-pushing, amending or rewriting published commits, tagging, releasing, or including unrelated changes; each still needs separate explicit authorization. A slice instruction that says not to commit or push overrides this standing authorization for that slice.

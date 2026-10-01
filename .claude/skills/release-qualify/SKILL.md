---
name: release-qualify
description: Qualify a release candidate of coinmarketcap-keyless-mcp and write the verification/release-<version>.md report. Use when asked to qualify, prepare or record a release. Never tags, pushes or publishes.
---

# Release qualification

Follow `VERSION_CONTROL.md`. No tag, push, release or publish without explicit authorization. Model the report on `verification/release-1.0.2.md`.

## 1. Offline qualification (run locally, record each real result)

```bash
uv sync --locked --all-groups
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q tests/unit tests/contract tests/mcp
uv run pytest -q tests/mcp/test_stdio.py
uv run pytest -q tests/mcp/test_streamable_http.py
uv run pytest -q tests/security
uv run pytest -q
uv build
uv lock --check
git diff --check
uv export --frozen --no-dev --no-emit-project --format requirements.txt -o runtime-requirements.txt
uvx --from "pip-audit>=2.7,<3" pip-audit --strict --disable-pip --require-hashes -r runtime-requirements.txt
uv run python scripts/qualify_packaging.py --artifacts dist
uv run mutmut run --max-children 4
uv run python scripts/mutation_gate.py --min-score 92
```

Python 3.14 legs run in CI only (the local environment is 3.11). Record that in the report, and confirm the CI `Packaging qualification` job covers 3.11 and 3.14. Delete `runtime-requirements.txt` afterwards.

## 2. Live capability (GATE-008): never run `verify_live` locally

The sandbox cannot reach `pro-api.coinmarketcap.com`. Ask the user to dispatch the manual workflow, or run it if authorized:

```bash
gh workflow run live-release-qualification.yml -f ref=<FULL 40-character SHA>
```

Abbreviated SHAs are rejected. The workflow requires 13/13 `SUPPORTED`, validates the evidence file and uploads it as an artifact. Record the workflow run ID, qualified SHA, evidence file name, artifact name and checksums in the report. Do not claim GATE-008 passed without a green run on the exact release commit.

## 3. Report

Create `verification/release-<version>.md` with: candidate (base commit, what changed), the offline table (command and real result), the PLAN.md section 20 gate table (GATE-001 to GATE-010, each with its evidence), the GATE-008 live detail, and the version decision. Keep payloads minimal; never retain full provider responses.

## 4. Version decision

Patch release only if the 13 tool names, routes and output envelope are unchanged and no capability, credential path, DEX or proxy behavior was added. Input-validation narrowing that enforces the existing contract is a patch (precedent: 1.0.2 `symbols`/`convert`); say so explicitly. Anything else stops the release and needs a separate plan and version decision.

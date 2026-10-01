---
description: Run the CI-equivalent offline verification and report only what actually ran
allowed-tools: Bash(uv sync:*), Bash(uv run pytest:*), Bash(uv run ruff:*), Bash(uv lock --check), Bash(git diff:*), Bash(git status:*)
---

Run the repository's CI-equivalent offline checks, in order, and stop at the first failure:

1. `uv sync --locked --all-groups`
2. `uv run ruff check src tests scripts`
3. `uv run ruff format --check src tests scripts`
4. `uv run pytest -q`
5. `uv lock --check`
6. `git diff --check`

Rules (from AGENTS.md):
- Report only commands that actually ran, with their real outcome. Do not claim a pass for anything skipped.
- Do not weaken, skip or delete a test to get a pass. Do not reclassify errors to make tests pass.
- Do not run live verification or the mutation gate here; say if the change touches `client.py`, `contracts.py`, `models.py`, `server.py` or `errors.py` and therefore needs the mutation gate in CI.
- If a format check fails, run `uv run ruff format` on the named files only, then re-run the failed step.

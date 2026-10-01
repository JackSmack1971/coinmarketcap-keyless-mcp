# H6 Release qualification evidence

## Candidate and CI

- Branch: `hardening/v1.0.1`
- Pre-release qualification head: `39eb71b57525a0d10858e60c383ba58e8fe923b0` (H5)
- Pre-release GitHub Actions run: [CI run 36818110835](https://github.com/JackSmack1971/coinmarketcap-keyless-mcp/actions/runs/36818110835)
- Matrix: Ubuntu / Python 3.11 — passed; Ubuntu / Python 3.14 — passed; Windows / Python 3.14 — passed.
- Each job passed locked dependency sync, its required offline tests, Ruff, wheel/sdist build, and lock consistency.

## Local offline qualification at H5 head

Environment: Windows 11 x86_64, PowerShell, CPython 3.14.3, uv 0.12.7.

| Command | Result |
|---|---:|
| `uv sync` | passed; 55 resolved, 53 checked |
| `uv run ruff check src tests` | passed |
| `uv run pytest tests/unit -q --disable-warnings` | 118 passed |
| `uv run pytest tests/contract -q --disable-warnings` | 9 passed |
| `uv run pytest tests/mcp -q --disable-warnings` | 32 passed |
| `uv run pytest tests/security -q --disable-warnings` | 43 passed |
| `uv run pytest -q --disable-warnings` | 202 passed |
| `uv build` | passed; wheel and sdist built |
| `uv lock --check` | passed |
| `git diff --check` | passed |

## Packaging qualification at H5 head

`uv run python scripts/qualify_packaging.py --artifacts <temporary-artifact-directory>` passed for the wheel and sdist on Python 3.11 and 3.14. Installed stdio smoke discovered all 13 tools, completed a fixture call, and shut down cleanly. The installed wheel Streamable HTTP smoke also passed on Windows / Python 3.14. H4's prior Ubuntu / Python 3.11 HTTP qualification remains recorded in `hardening-h4-packaging.md`.

## Fresh live capability evidence

- Evidence: `verification/live-capability-20261001T051127293524Z.json`
- Generated after the `1.0.1` version bump from the H5 runtime candidate, using the canonical serial verifier against `https://pro-api.coinmarketcap.com/public-api`, without credentials. The only source metadata edits at that point were the version, changelog, and H6 evidence; runtime code remained at the qualified H5 SHA above.
- Result: all 13 released routes classified `SUPPORTED`; no transient, rate-limited, unsupported, or contract-mismatch routes.
- The evidence retains route classifications and minimum-shape summaries only, not provider payloads.

## Post-bump release-candidate verification

After setting the package version to `1.0.1`:

- `uv sync` — passed; installed project distribution updated to `1.0.1`.
- `uv run ruff check src tests` — passed.
- `uv run pytest -q --disable-warnings` — 202 passed.
- `uv build` — passed; produced `coinmarketcap_keyless_mcp-1.0.1.tar.gz` and `coinmarketcap_keyless_mcp-1.0.1-py3-none-any.whl`.
- `uv lock --check` — passed.
- `git diff --check` — passed.
- `uv run python scripts/qualify_packaging.py --artifacts <temporary-artifact-directory>` — passed. Both artifacts installed and passed the 13-tool stdio qualification on Python 3.11 and 3.14; the wheel also passed installed Streamable HTTP discovery, fixture call, and clean shutdown on Windows / Python 3.14. Each installed distribution reported version `1.0.1`.
- Canonical live verification on the version-bumped candidate — `SUPPORTED=13` (evidence file above).

## Version decision and scope

H1–H5 are backward-compatible hardening and bug fixes. The release candidate version is `1.0.1`. The changelog covers CI/static gates, mutation/negative-path strengthening, streaming response bounds, isolated artifacts, compressed/deep JSON and security handling, cleanup reliability, and live route qualification. No README version reference required correction; its `0.1.0` mention describes the historical pre-release evidence accurately.

The 13-tool public contract is unchanged: no MCP names or schemas, routes, credentials/authentication, DEX support, proxy behavior, or new product capability were added.

Known limitations remain as documented by H5: this was a bounded local adversarial audit, not a third-party penetration test; only advertised gzip/deflate encodings are decoded; and a bounded raw input chunk may reach the decoder before the decoded-body cap is applied. Existing pytest-asyncio event-loop-policy deprecation warnings were emitted during test runs.

Final release commit, final CI run, and PR details are to be appended after their respective gates complete.

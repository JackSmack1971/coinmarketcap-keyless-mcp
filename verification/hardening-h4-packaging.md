# H4 Packaging and isolated install qualification

## Run identity

- Branch: `hardening/v1.0.1`
- Base commit: `313063a031e981086ec4a16bd98ed4740a09c10d`
- Qualification date: 2026-10-01
- Platforms: Windows 11 x86_64 for wheel/sdist matrix; Ubuntu 22.04 x86_64 under WSL2 for the required installed HTTP smoke
- uv: `0.12.7`
- Isolated interpreters: CPython `3.11.16` and `3.14.3`
- Build environment: project environment managed by uv; installed artifacts were tested only in separate temporary uv environments outside the checkout.

## Build and artifact inspection

Command:

```powershell
uv build --out-dir "$env:TEMP\cmc-h4-verified-artifacts"
```

Result: both artifacts built successfully.

- `coinmarketcap_keyless_mcp-1.0.0-py3-none-any.whl`
- `coinmarketcap_keyless_mcp-1.0.0.tar.gz`

Both artifacts report name `coinmarketcap-keyless-mcp`, version `1.0.0`, and `Requires-Python: >=3.11`. Wheel metadata declares only `httpx<1,>=0.27` and `mcp<3,>=2` as runtime requirements. The console entry point is `coinmarketcap-keyless-mcp = coinmarketcap_keyless_mcp.runtime:main`.

The wheel contains the nine expected package modules: `__init__.py`, `__main__.py`, `client.py`, `contracts.py`, `errors.py`, `models.py`, `runtime.py`, `server.py`, and `verify_live.py`. The sdist contains those sources, `README.md`, `pyproject.toml`, generated `PKG-INFO`, and Hatch's standard `.gitignore` file. It contains no tests, verification reports, `.github`, `uv.lock`, project instruction/plan files, `.git` directory, virtual environments, caches, logs, mutation output, temporary files, or secrets. Hatch always includes `.gitignore` in the sdist by backend convention; its presence is benign and contains no credentials or local state.

## Defect fixed

Before H4, Hatch's default sdist file selection included the repository's tests, verification reports, CI workflow, plans, governance files, and lockfile. Added an explicit sdist include set for the package source directory, README, and build configuration. The resulting sdist has 13 archive entries and is independently installable.

## Isolated installation and runtime results

The durable harness is `python scripts/qualify_packaging.py --artifacts <artifact-directory>`. It creates a fresh `uv venv --seed --python` for each artifact/interpreter pair, installs the wheel or sdist with `uv pip install --python <venv-python> <artifact>`, and runs all checks from a separate temporary working directory. `PYTHONPATH`, `PYTHONHOME`, and `PYTHONEXECUTABLE` are cleared in qualification subprocesses. No editable install is used.

| Artifact | Python | Install | Import origin | Console help and module help | Stdio discovery/call/shutdown |
|---|---:|---|---|---|---|
| Wheel | 3.11.16 | Pass | Isolated environment `site-packages` | Pass | 13 tools; fixture call passed; clean shutdown |
| Wheel | 3.14.3 | Pass | Isolated environment `site-packages` | Pass | 13 tools; fixture call passed; clean shutdown |
| sdist | 3.11.16 | Pass; backend built the installable package | Isolated environment `site-packages` | Pass | 13 tools; fixture call passed; clean shutdown |
| sdist | 3.14.3 | Pass; backend built the installable package | Isolated environment `site-packages` | Pass | 13 tools; fixture call passed; clean shutdown |

For each environment, the installed Windows console launcher existed in `Scripts`, `--help` succeeded, and a `mcp.Client` connected to that launcher over stdio and discovered exactly the names in the installed package's 13 `TOOL_CONTRACTS`. The harness asserted installed distribution version `1.0.0` and an import path under the isolated environment's `site-packages`. A second installed-package subprocess used `runtime.run_server` with a fixture `ClientFactory`; `cmc_fear_greed_latest` returned the fixture envelope without provider network access. Closing each client completed the stdio server subprocess cleanly. Direct `python -m coinmarketcap_keyless_mcp --help` also succeeded.

The required installed-wheel Streamable HTTP smoke test ran on Ubuntu WSL2/Python 3.11.16 with uv `0.12.7`, bootstrapped in a temporary tool environment under `/tmp`. It installed the wheel into a separate uv environment under `/tmp`, verified the package version and import path, started the package runtime on loopback, discovered the same 13 tools, made the fixture-backed `cmc_fear_greed_latest` call, and cancelled/shut down the server cleanly. The same smoke also passed on Windows/Python 3.14.3. No live CoinMarketCap calls were made.

## Dependency and contract audit

Each installed environment was checked for absence of `pytest`, `pytest-asyncio`, Ruff, mutmut, and Hatchling after installation. No development or build-only dependency was present in the target environments. Sdist build isolation successfully supplied the backend during installation; Hatchling was not left installed as a runtime requirement.

The wheel and sdist report the same version, runtime dependencies, and console entry point, and expose the same 13-tool stdio behavior. The packaging-only change does not alter MCP names, schemas, routes, output/error semantics, caching, response bounds, transports, CLI options, or keyless/authentication behavior.

## CI and limitations

No CI integration was added. H4 allows a CI packaging job only when the accepted plan explicitly requires it; the H4 plan specifies local artifact qualification and does not require adding that job.

The Windows runner's isolated WSL2 Ubuntu distro supplied the prescribed Ubuntu/Python 3.11 HTTP environment. WSL did not have uv preinstalled, so uv `0.12.7` was installed into a temporary Python virtual environment under `/tmp`; the installed application was qualified in another fresh `/tmp` environment. WSL emitted a benign warning that hardlinks were unavailable between the Windows artifact mount and Linux temporary filesystem; uv copied packages and all checks passed.

The generated artifacts and temporary environments remain under `%TEMP%`; no build artifacts or environments are tracked in the repository.

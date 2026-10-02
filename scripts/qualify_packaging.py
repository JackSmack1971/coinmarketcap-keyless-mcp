"""Build-artifact install qualification outside the source checkout.

Run with ``uv run python scripts/qualify_packaging.py --artifacts <directory>``.
The script creates four temporary uv environments (wheel/sdist x Python 3.11/3.14),
checks their installed console entry point and stdio MCP behavior, then runs one
installed-wheel Streamable HTTP discovery check.
"""

from __future__ import annotations

import argparse
import email
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "coinmarketcap_keyless_mcp"
CONSOLE = "coinmarketcap-keyless-mcp"
EXPECTED_MODULES = {
    "__init__.py",
    "__main__.py",
    "client.py",
    "contracts.py",
    "errors.py",
    "models.py",
    "runtime.py",
    "server.py",
    "verify_live.py",
}
FORBIDDEN_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "mutmut_cache"}

HARNESS = r"""
import asyncio, os, sys
from pathlib import Path
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from coinmarketcap_keyless_mcp.contracts import TOOL_CONTRACTS
from importlib.metadata import version

expected = [c.name for c in TOOL_CONTRACTS]
assert len(expected) == 22
package_path = Path(__import__("coinmarketcap_keyless_mcp").__file__).resolve()
assert Path(sys.prefix).resolve() in package_path.parents, (sys.prefix, package_path)
assert "src" not in package_path.parts
assert version("coinmarketcap-keyless-mcp") == os.environ["CMC_EXPECTED_VERSION"]

async def main():
    executable = os.environ["CMC_QUALIFY_CONSOLE"]
    async with Client(stdio_client(StdioServerParameters(command=executable))) as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
    assert names == expected, names

    fixture = "\n".join(["import asyncio", "from coinmarketcap_keyless_mcp import runtime", "class Fixture:", " async def get(self, route, params=None): return {'status': {'error_code': 0, 'notice': None}, 'data': {'fixture': True}}", "asyncio.run(runtime.run_server('stdio', client_factory=Fixture))"])
    params = StdioServerParameters(command=sys.executable, args=["-c", fixture])
    async with Client(stdio_client(params)) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == expected
        result = await client.call_tool("cmc_fear_greed_latest", {})
        assert not result.is_error
        assert result.structured_content == {"status":{"error_code":0,"notice":None},"data":{"fixture":True}}

asyncio.run(main())
print("installed import, 20-tool console discovery, mocked call, and clean stdio shutdown passed")
"""


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    print("+", subprocess.list2cmdline(args))
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, args, output=completed.stdout)
    return completed.stdout


def inspect_artifacts(artifacts: Path, version: str) -> tuple[Path, Path, list[str]]:
    wheel = next(artifacts.glob("*.whl"))
    sdist = next(artifacts.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
        metadata_name = next(n for n in wheel_names if n.endswith(".dist-info/METADATA"))
        wheel_metadata = email.message_from_bytes(archive.read(metadata_name))
        wheel_entry = next(n for n in wheel_names if n.endswith(".dist-info/entry_points.txt"))
        entry_text = archive.read(wheel_entry).decode()
    sdist_tar = tarfile.open(sdist, "r:gz")
    sdist_names = sdist_tar.getnames()
    sdist_root = sdist_names[0].split("/")[0]
    sdist_meta = email.message_from_bytes(sdist_tar.extractfile(f"{sdist_root}/PKG-INFO").read())
    for label, metadata in (("wheel", wheel_metadata), ("sdist", sdist_meta)):
        assert metadata["Name"] == "coinmarketcap-keyless-mcp", (label, metadata["Name"])
        assert metadata["Version"] == version, (label, metadata["Version"])
        assert metadata["Requires-Python"] == ">=3.11"
        requirements = metadata.get_all("Requires-Dist", [])
        assert any(req.lower().startswith("httpx") for req in requirements), requirements
        assert any(req.lower().startswith("mcp") for req in requirements), requirements
        assert not any(
            any(dev in req.lower() for dev in ("pytest", "ruff", "mutmut", "hatchling"))
            for req in requirements
        )
    assert "coinmarketcap-keyless-mcp = coinmarketcap_keyless_mcp.runtime:main" in entry_text
    modules = {
        Path(n).name for n in wheel_names if n.startswith(f"{PACKAGE}/") and n.endswith(".py")
    }
    assert modules == EXPECTED_MODULES, modules
    all_names = wheel_names + sdist_names
    path_parts = [set(Path(name.replace("\\", "/")).parts) for name in all_names]
    assert not any(parts & FORBIDDEN_PARTS for parts in path_parts)
    sdist_relative = [name.split("/", 1)[1] for name in sdist_names if "/" in name]
    assert not any(
        name.startswith(("tests/", ".github/", "verification/")) for name in sdist_relative
    )
    assert not any(
        name in {"AGENTS.md", "HARDENING_PLAN.md", "PLAN.md", "VERSION_CONTROL.md", "uv.lock"}
        for name in sdist_relative
    )
    assert f"{PACKAGE}/runtime.py" in wheel_names
    assert f"{PACKAGE}/__main__.py" in wheel_names
    sdist_files = {Path(n).name for n in sdist_names}
    assert EXPECTED_MODULES <= sdist_files
    print(
        f"wheel metadata: name={wheel_metadata['Name']} version={wheel_metadata['Version']} python={wheel_metadata['Requires-Python']} requirements={wheel_metadata.get_all('Requires-Dist', [])}"
    )
    print(f"entry point: {entry_text.strip()}")
    print(f"wheel package modules: {sorted(modules)}")
    print(
        f"sdist file count: {len(sdist_names)}; no tests, verification, .github, venv, git, or cache paths; backend includes its standard .gitignore"
    )
    sdist_tar.close()
    return wheel, sdist, wheel_metadata.get_all("Requires-Dist", [])


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def venv_python(venv: Path) -> Path:
    return venv_bin(venv) / ("python.exe" if os.name == "nt" else "python")


def console_path(venv: Path) -> Path:
    candidates = [venv_bin(venv) / f"{CONSOLE}.exe", venv_bin(venv) / CONSOLE]
    found = next((path for path in candidates if path.exists()), None)
    assert found is not None, candidates
    return found


def qualify_artifact(
    uv: str, artifact: Path, artifact_label: str, python: str, parent: Path
) -> None:
    venv = parent / f"{artifact_label}-py{python.replace('.', '')}"
    run([uv, "venv", "--seed", "--python", python, str(venv)], cwd=parent)
    python_exe = venv_python(venv)
    install_env = os.environ.copy()
    install_env["UV_PYTHON"] = python
    install_env.pop("PYTHONPATH", None)
    install_env.pop("PYTHONHOME", None)
    install_env.pop("PYTHONEXECUTABLE", None)
    run(
        [uv, "pip", "install", "--python", str(python_exe), str(artifact)],
        cwd=parent,
        env=install_env,
    )
    run(
        [
            str(python_exe),
            "-c",
            "import importlib.metadata as m; names={d.metadata['Name'].lower().replace('_','-') for d in m.distributions()}; forbidden={'pytest','pytest-asyncio','ruff','mutmut','hatchling'}; assert not names & forbidden, names & forbidden; print('no development or build-only dependencies installed')",
        ],
        cwd=parent,
        env=install_env,
    )
    script = console_path(venv)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONEXECUTABLE", None)
    env["CMC_QUALIFY_CONSOLE"] = str(script)
    env["CMC_EXPECTED_VERSION"] = version_from_artifact_metadata(artifact)
    run([str(script), "--help"], cwd=parent, env=env)
    run([str(python_exe), "-m", PACKAGE, "--help"], cwd=parent, env=env)
    harness_file = parent / "harness.py"
    harness_file.write_text(HARNESS, encoding="utf-8")
    run([str(python_exe), str(harness_file)], cwd=parent, env=env)
    print(
        f"{artifact_label} Python {python}: isolated import, console help/discovery, fixture call, shutdown passed"
    )


def qualify_http(uv: str, wheel: Path, parent: Path, python: str) -> None:
    venv = parent / f"wheel-http-py{python.replace('.', '')}"
    run([uv, "venv", "--seed", "--python", python, str(venv)], cwd=parent)
    python_exe = venv_python(venv)
    install_env = os.environ.copy()
    install_env["UV_PYTHON"] = python
    run(
        [uv, "pip", "install", "--python", str(python_exe), str(wheel)], cwd=parent, env=install_env
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONEXECUTABLE", None)
    env["CMC_EXPECTED_VERSION"] = version_from_artifact_metadata(wheel)
    harness = r"""import asyncio, os, socket, sys
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from coinmarketcap_keyless_mcp.contracts import TOOL_CONTRACTS
from importlib.metadata import version
from coinmarketcap_keyless_mcp.runtime import run_server
from pathlib import Path
package_path = Path(__import__("coinmarketcap_keyless_mcp").__file__).resolve()
assert Path(sys.prefix).resolve() in package_path.parents, (sys.prefix, package_path)
assert version("coinmarketcap-keyless-mcp") == os.environ["CMC_EXPECTED_VERSION"]
class Fixture:
 async def get(self, route, params=None): return {"status":{"error_code":0,"notice":None},"data":{"fixture":True}}
async def main():
 with socket.socket() as sock:
  sock.bind(("127.0.0.1", 0))
  port = sock.getsockname()[1]
 task = asyncio.create_task(run_server("streamable-http", port=port, client_factory=Fixture))
 url = f"http://127.0.0.1:{port}/mcp"
 try:
  for _ in range(100):
   if task.done(): task.result()
   try:
    async with Client(streamable_http_client(url)) as client:
     tools = await client.list_tools()
     assert [t.name for t in tools.tools] == [c.name for c in TOOL_CONTRACTS]
     result = await client.call_tool("cmc_fear_greed_latest", {})
     assert not result.is_error and result.structured_content == {"status":{"error_code":0,"notice":None},"data":{"fixture":True}}
     break
   except Exception:
    await asyncio.sleep(.1)
  else: raise RuntimeError("installed HTTP server readiness timed out")
 finally:
  task.cancel()
  try: await asyncio.wait_for(task, timeout=10)
  except asyncio.CancelledError: pass
asyncio.run(main())
print("installed Streamable HTTP startup, 20-tool discovery, fixture call, and clean shutdown passed")
"""
    harness_file = parent / "http_harness.py"
    harness_file.write_text(harness, encoding="utf-8")
    run([str(python_exe), str(harness_file)], cwd=parent, env=env)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--skip-http", action="store_true")
    parser.add_argument("--http-only", action="store_true")
    parser.add_argument(
        "--python", default="3.14", help="Python version for HTTP-only or HTTP smoke"
    )
    args = parser.parse_args()
    if args.http_only and args.skip_http:
        parser.error("--http-only cannot be combined with --skip-http")
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', project_text, re.M)
    assert match
    version = match.group(1)
    wheel, sdist, _ = inspect_artifacts(artifacts, version)
    uv = shutil.which("uv")
    assert uv
    with tempfile.TemporaryDirectory(prefix="cmc-h4-isolated-") as temporary:
        parent = Path(temporary).resolve()
        assert ROOT not in parent.parents
        if not args.http_only:
            for artifact, label in ((wheel, "wheel"), (sdist, "sdist")):
                for python in ("3.11", "3.14"):
                    qualify_artifact(uv, artifact.resolve(), label, python, parent)
        if not args.skip_http:
            qualify_http(uv, wheel.resolve(), parent, args.python)
    print("H4 packaging qualification passed")


def version_from_artifact_metadata(artifact: Path) -> str:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            return email.message_from_bytes(archive.read(name))["Version"]
    with tarfile.open(artifact, "r:gz") as archive:
        name = next(n for n in archive.getnames() if n.endswith("/PKG-INFO"))
        return email.message_from_bytes(archive.extractfile(name).read())["Version"]


if __name__ == "__main__":
    main()

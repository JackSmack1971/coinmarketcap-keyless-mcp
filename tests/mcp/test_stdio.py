from __future__ import annotations

import sys
from typing import Any

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from coinmarketcap_keyless_mcp.contracts import TOOL_CONTRACTS

NAMES = [contract.name for contract in TOOL_CONTRACTS]
ENVELOPE = {"status": {"error_code": 0, "notice": None}, "data": {"fixture": True}}


def _subprocess_code(error: bool = False) -> str:
    return f"""import asyncio
from coinmarketcap_keyless_mcp import runtime

class FixtureClient:
    async def get(self, route, params=None):
        if {error!r}:
            from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
            raise CmcClientError(ErrorCode.UPSTREAM_HTTP_ERROR, "fixture error")
        return {ENVELOPE!r}

asyncio.run(runtime.run_server("stdio", client_factory=FixtureClient))
"""


async def _discover_and_call(error: bool = False) -> tuple[list[str], Any]:
    params = StdioServerParameters(command=sys.executable, args=["-c", _subprocess_code(error)])
    async with Client(stdio_client(params)) as client:
        tools = await client.list_tools()
        result = await client.call_tool("cmc_fear_greed_latest", {})
    return [tool.name for tool in tools.tools], result


@pytest.mark.asyncio
async def test_stdio_subprocess_discovers_calls_and_shuts_down_cleanly() -> None:
    names, result = await _discover_and_call()
    assert names == NAMES
    assert not result.is_error
    assert result.structured_content == ENVELOPE


@pytest.mark.asyncio
async def test_stdio_handled_error_is_protocol_safe() -> None:
    names, result = await _discover_and_call(error=True)
    assert names == NAMES
    assert result.is_error
    assert "UPSTREAM_HTTP_ERROR" in result.content[0].text


def test_runtime_rejects_invalid_ports() -> None:
    from coinmarketcap_keyless_mcp.runtime import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--port", "0"])


@pytest.mark.asyncio
async def test_stdio_idle_disconnect_exits_and_closes_client() -> None:
    import asyncio

    code = _subprocess_code().replace(
        "    async def get(self, route, params=None):",
        "    async def aclose(self):\n        import sys\n        print('CLIENT_CLOSED', file=sys.stderr)\n\n    async def get(self, route, params=None):",
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(10):
        stdout, stderr = await process.communicate(b"")
    assert process.returncode == 0
    assert stdout == b""
    assert b"CLIENT_CLOSED" in stderr

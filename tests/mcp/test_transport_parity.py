from __future__ import annotations

import asyncio
import socket
import sys
from typing import Any

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from coinmarketcap_keyless_mcp.contracts import TOOL_CONTRACTS
from coinmarketcap_keyless_mcp.runtime import run_server
from coinmarketcap_keyless_mcp.server import create_server

NAMES = [contract.name for contract in TOOL_CONTRACTS]


class FixtureClient:
    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": {"error_code": 0}, "data": {}}


@pytest.mark.asyncio
async def test_in_process_surface_is_the_transport_parity_reference() -> None:
    async with Client(create_server(FixtureClient())) as client:
        tools = await client.list_tools()
    assert [tool.name for tool in tools.tools] == NAMES
    assert len(tools.tools) == 20


def _surface(tools) -> list[tuple[str, str | None, dict[str, Any]]]:
    return [(tool.name, tool.description, tool.input_schema) for tool in tools.tools]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stdio_code() -> str:
    return """import asyncio
from coinmarketcap_keyless_mcp import runtime
class FixtureClient:
    async def get(self, route, params=None):
        return {"status": {"error_code": 0}, "data": {}}
asyncio.run(runtime.run_server("stdio", client_factory=FixtureClient))
"""


@pytest.mark.asyncio
async def test_in_process_and_stdio_tool_names_are_identical() -> None:
    async with Client(create_server(FixtureClient())) as client:
        in_process = _surface(await client.list_tools())

    params = StdioServerParameters(command=sys.executable, args=["-c", _stdio_code()])
    async with Client(stdio_client(params)) as client:
        stdio = _surface(await client.list_tools())

    assert in_process == stdio
    assert [name for name, _, _ in stdio] == NAMES


@pytest.mark.streamable_http
@pytest.mark.asyncio
async def test_streamable_http_tool_names_match_in_process() -> None:
    async with Client(create_server(FixtureClient())) as client:
        in_process = _surface(await client.list_tools())

    port = _free_port()
    task = asyncio.create_task(
        run_server("streamable-http", port=port, client_factory=FixtureClient)
    )
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(50):
        try:
            async with streamable_http_client(url):
                break
        except Exception:
            await asyncio.sleep(0.05)
    try:
        async with Client(streamable_http_client(url)) as client:
            http = _surface(await client.list_tools())
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert in_process == http
    assert [name for name, _, _ in http] == NAMES

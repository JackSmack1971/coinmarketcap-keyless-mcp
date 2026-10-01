from __future__ import annotations

import asyncio
import socket
from typing import Any

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from coinmarketcap_keyless_mcp.contracts import TOOL_CONTRACTS
from coinmarketcap_keyless_mcp.runtime import run_server

NAMES = [contract.name for contract in TOOL_CONTRACTS]
ENVELOPE = {"status": {"error_code": 0, "notice": None}, "data": {"fixture": True}}


class FixtureClient:
    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return ENVELOPE


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for_server(url: str) -> None:
    async with httpx.AsyncClient() as http:
        for _ in range(50):
            try:
                response = await http.get(url)
                if response.status_code in {200, 400, 405, 406}:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    raise AssertionError("Streamable HTTP server did not become ready")


@pytest.mark.streamable_http
@pytest.mark.asyncio
async def test_streamable_http_discovers_calls_and_releases_port() -> None:
    port = _free_port()
    task = asyncio.create_task(
        run_server("streamable-http", port=port, client_factory=FixtureClient)
    )
    url = f"http://127.0.0.1:{port}/mcp"
    await _wait_for_server(url)
    try:
        async with Client(streamable_http_client(url)) as client:
            tools = await client.list_tools()
            result = await client.call_tool("cmc_fear_greed_latest", {})
        assert [tool.name for tool in tools.tools] == NAMES
        assert not result.is_error
        assert result.structured_content == ENVELOPE
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    await _wait_for_port_release(port)


async def _wait_for_port_release(port: int) -> None:
    for _ in range(50):
        with socket.socket() as sock:
            sock.settimeout(0.05)
            try:
                sock.bind(("127.0.0.1", port))
                return
            except OSError:
                pass
        await asyncio.sleep(0.05)
    raise AssertionError("Streamable HTTP port was not released")

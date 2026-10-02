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
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
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
    assert len(tools.tools) == 24


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


# --- v1.1 E2-B D3 call-result parity (verification/v1.1-e2b-contract-review.md) -------

D3_CALLS = [
    {"platform": "B² Network", "address": "0xAbC"},  # success, echoes the exact query
    {"platform": "Ethereum", "address": "0xA0b8", "network_slug": "x"},  # unknown field
    {"platform": "Ethereum&x=1", "address": "0xA0b8"},  # query delimiter
]


class EchoClient:
    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": {"error_code": 0}, "data": {"route": route, "params": params}}


def _echo_code() -> str:
    return """import asyncio
from coinmarketcap_keyless_mcp import runtime
class EchoClient:
    async def get(self, route, params=None):
        return {"status": {"error_code": 0}, "data": {"route": route, "params": params}}
asyncio.run(runtime.run_server("stdio", client_factory=EchoClient))
"""


async def _d3_results(client: Client) -> list[tuple[bool, Any]]:
    results = []
    for arguments in D3_CALLS:
        result = await client.call_tool("cmc_dex_token", arguments)
        results.append((result.is_error, result.structured_content))
    return results


@pytest.mark.asyncio
async def test_d3_call_results_match_across_in_process_and_stdio() -> None:
    async with Client(create_server(EchoClient())) as client:
        in_process = await _d3_results(client)
    params = StdioServerParameters(command=sys.executable, args=["-c", _echo_code()])
    async with Client(stdio_client(params)) as client:
        stdio = await _d3_results(client)
    assert in_process == stdio
    assert in_process[0] == (
        False,
        {
            "status": {"error_code": 0},
            "data": {
                "route": "/v1/dex/token",
                "params": {"platform": "B² Network", "address": "0xAbC"},
            },
        },
    )
    assert [is_error for is_error, _ in in_process] == [False, True, True]


@pytest.mark.streamable_http
@pytest.mark.asyncio
async def test_d3_call_results_match_across_in_process_and_streamable_http() -> None:
    async with Client(create_server(EchoClient())) as client:
        in_process = await _d3_results(client)

    port = _free_port()
    task = asyncio.create_task(run_server("streamable-http", port=port, client_factory=EchoClient))
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(50):
        try:
            async with streamable_http_client(url):
                break
        except Exception:
            await asyncio.sleep(0.05)
    try:
        async with Client(streamable_http_client(url)) as client:
            http = await _d3_results(client)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert in_process == http


# --- v1.1 E2-C D12 discovery and call-result parity (v1.1-e2c-contract-review.md) -----

D12_CALLS = [
    {"platform": "B² Network"},  # success, echoes the exact provider query
    {"platform": "Ethereum", "platformName": "x"},  # unknown field
    {"platform": "Ethereum#x"},  # query delimiter
    {},  # missing required platform
]


async def _d12_results(client: Client) -> list[tuple[Any, ...]]:
    tool = {t.name: t for t in (await client.list_tools()).tools}["cmc_dex_platform_detail"]
    results: list[tuple[Any, ...]] = [(tool.description, tool.input_schema)]
    for arguments in D12_CALLS:
        result = await client.call_tool("cmc_dex_platform_detail", arguments)
        results.append((result.is_error, result.structured_content))
    return results


@pytest.mark.asyncio
async def test_d12_discovery_and_results_match_across_in_process_and_stdio() -> None:
    async with Client(create_server(EchoClient())) as client:
        in_process = await _d12_results(client)
    params = StdioServerParameters(command=sys.executable, args=["-c", _echo_code()])
    async with Client(stdio_client(params)) as client:
        stdio = await _d12_results(client)
    assert in_process == stdio
    assert in_process[1] == (
        False,
        {
            "status": {"error_code": 0},
            "data": {
                "route": "/v1/dex/platform/detail",
                "params": {"platformName": "B² Network"},
            },
        },
    )
    assert [result[0] for result in in_process[1:]] == [False, True, True, True]


@pytest.mark.streamable_http
@pytest.mark.asyncio
async def test_d12_discovery_and_results_match_across_in_process_and_streamable_http() -> None:
    async with Client(create_server(EchoClient())) as client:
        in_process = await _d12_results(client)

    port = _free_port()
    task = asyncio.create_task(run_server("streamable-http", port=port, client_factory=EchoClient))
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(50):
        try:
            async with streamable_http_client(url):
                break
        except Exception:
            await asyncio.sleep(0.05)
    try:
        async with Client(streamable_http_client(url)) as client:
            http = await _d12_results(client)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert in_process == http


# --- v1.1 E2-D D16 discovery and call-result parity (v1.1-e2d-contract-review.md) -----

D16_CALLS = [
    {"platform": "B² Network", "address": "0xAbC"},  # success, echoes the exact provider query
    {"platform": "Ethereum", "address": "0xLIMIT"},  # upstream RATE_LIMITED
    {"platform": "Ethereum", "address": "0xA0b8", "tokenAddress": "0xA0b8"},  # unknown field
    {"platform": "Ethereum#x", "address": "0xA0b8"},  # query delimiter
    {"platform": "Ethereum"},  # missing required address
]


def _d16_echo_code() -> str:
    return """import asyncio
from coinmarketcap_keyless_mcp import runtime
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
class EchoClient:
    async def get(self, route, params=None):
        if params and params.get("tokenAddress") == "0xLIMIT":
            raise CmcClientError(ErrorCode.RATE_LIMITED, "limited", status_code=429, attempts=3)
        return {"status": {"error_code": 0}, "data": {"route": route, "params": params}}
asyncio.run(runtime.run_server("stdio", client_factory=EchoClient))
"""


class D16EchoClient:
    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if params and params.get("tokenAddress") == "0xLIMIT":
            raise CmcClientError(ErrorCode.RATE_LIMITED, "limited", status_code=429, attempts=3)
        return {"status": {"error_code": 0}, "data": {"route": route, "params": params}}


async def _d16_results(client: Client) -> list[tuple[Any, ...]]:
    tool = {t.name: t for t in (await client.list_tools()).tools}["cmc_dex_holders_count"]
    results: list[tuple[Any, ...]] = [(tool.name, tool.description, tool.input_schema)]
    for arguments in D16_CALLS:
        result = await client.call_tool("cmc_dex_holders_count", arguments)
        text = result.content[0].text if result.is_error else None
        results.append((result.is_error, result.structured_content, text))
    return results


def _assert_d16_reference(results: list[tuple[Any, ...]]) -> None:
    assert results[1] == (
        False,
        {
            "status": {"error_code": 0},
            "data": {
                "route": "/v1/dex/holders/count",
                "params": {"platform": "B² Network", "tokenAddress": "0xAbC"},
            },
        },
        None,
    )
    assert [result[0] for result in results[1:]] == [False, True, True, True, True]
    assert "RATE_LIMITED" in results[2][2]


@pytest.mark.asyncio
async def test_d16_discovery_and_results_match_across_in_process_and_stdio() -> None:
    async with Client(create_server(D16EchoClient())) as client:
        in_process = await _d16_results(client)
    params = StdioServerParameters(command=sys.executable, args=["-c", _d16_echo_code()])
    async with Client(stdio_client(params)) as client:
        stdio = await _d16_results(client)
    assert in_process == stdio
    _assert_d16_reference(in_process)


@pytest.mark.streamable_http
@pytest.mark.asyncio
async def test_d16_discovery_and_results_match_across_in_process_and_streamable_http() -> None:
    async with Client(create_server(D16EchoClient())) as client:
        in_process = await _d16_results(client)

    port = _free_port()
    task = asyncio.create_task(
        run_server("streamable-http", port=port, client_factory=D16EchoClient)
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
            http = await _d16_results(client)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert in_process == http
    _assert_d16_reference(in_process)


# --- v1.1 E2-E D8 discovery and call-result parity (v1.1-e2e-contract-review.md) -----

D8_CALLS = [
    {"platform": "B² Network", "address": "0xAbC"},  # success, echoes the exact provider query
    {"platform": "Ethereum", "address": "0xLIMIT"},  # upstream RATE_LIMITED
    {"platform": "Ethereum", "address": "0xA0b8", "platformName": "Ethereum"},  # unknown field
    {"platform": "Ethereum#x", "address": "0xA0b8"},  # query delimiter
    {"platform": "Ethereum"},  # missing required address
]


def _d8_echo_code() -> str:
    return """import asyncio
from coinmarketcap_keyless_mcp import runtime
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
class EchoClient:
    async def get(self, route, params=None):
        if params and params.get("address") == "0xLIMIT":
            raise CmcClientError(ErrorCode.RATE_LIMITED, "limited", status_code=429, attempts=3)
        return {"status": {"error_code": 0}, "data": [{"route": route, "params": params}]}
asyncio.run(runtime.run_server("stdio", client_factory=EchoClient))
"""


class D8EchoClient:
    async def get(self, route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if params and params.get("address") == "0xLIMIT":
            raise CmcClientError(ErrorCode.RATE_LIMITED, "limited", status_code=429, attempts=3)
        return {"status": {"error_code": 0}, "data": [{"route": route, "params": params}]}


async def _d8_results(client: Client) -> list[tuple[Any, ...]]:
    tool = {t.name: t for t in (await client.list_tools()).tools}["cmc_dex_security_detail"]
    results: list[tuple[Any, ...]] = [(tool.name, tool.description, tool.input_schema)]
    for arguments in D8_CALLS:
        result = await client.call_tool("cmc_dex_security_detail", arguments)
        text = result.content[0].text if result.is_error else None
        results.append((result.is_error, result.structured_content, text))
    return results


def _assert_d8_reference(results: list[tuple[Any, ...]]) -> None:
    assert results[1] == (
        False,
        {
            "status": {"error_code": 0},
            "data": [
                {
                    "route": "/v1/dex/security/detail",
                    "params": {"platformName": "B² Network", "address": "0xAbC"},
                }
            ],
        },
        None,
    )
    assert [result[0] for result in results[1:]] == [False, True, True, True, True]
    assert "RATE_LIMITED" in results[2][2]


@pytest.mark.asyncio
async def test_d8_discovery_and_results_match_across_in_process_and_stdio() -> None:
    async with Client(create_server(D8EchoClient())) as client:
        in_process = await _d8_results(client)
    params = StdioServerParameters(command=sys.executable, args=["-c", _d8_echo_code()])
    async with Client(stdio_client(params)) as client:
        stdio = await _d8_results(client)
    assert in_process == stdio
    _assert_d8_reference(in_process)


@pytest.mark.streamable_http
@pytest.mark.asyncio
async def test_d8_discovery_and_results_match_across_in_process_and_streamable_http() -> None:
    async with Client(create_server(D8EchoClient())) as client:
        in_process = await _d8_results(client)

    port = _free_port()
    task = asyncio.create_task(
        run_server("streamable-http", port=port, client_factory=D8EchoClient)
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
            http = await _d8_results(client)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert in_process == http
    _assert_d8_reference(in_process)

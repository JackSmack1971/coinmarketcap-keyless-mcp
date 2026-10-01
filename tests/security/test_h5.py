"""Bounded adversarial checks for the H5 security and failure boundaries."""

from __future__ import annotations

import asyncio
import gzip
import json
import sys

import httpx
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from coinmarketcap_keyless_mcp.client import DEFAULT_MAX_RESPONSE_BYTES, KeylessHttpClient
from coinmarketcap_keyless_mcp.contracts import BASE_URL, ROUTES, TOOL_CONTRACTS
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
from coinmarketcap_keyless_mcp.runtime import build_parser

ROUTE = ROUTES["cmc_quotes_latest"]
VALID = {"status": {"error_code": 0}, "data": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route",
    [
        "https://attacker.example/route",
        "//attacker.example/route",
        "ftp://attacker.example/route",
        "https:attacker.example/route",
        "\\\\attacker.example\\route",
        "/v1/../private",
        "/v1/%2e%2e/private",
        "/v1/%252e%252e/private",
        "/v1//cryptocurrency/map",
        ROUTE + "?x=1",
        ROUTE + "#fragment",
        ROUTE + "\\..\\private",
        "/v1/cryptocurrency/ｍａｐ",
        "https://user@attacker.example:443/" + ROUTE.lstrip("/"),
    ],
)
async def test_hostile_route_values_are_rejected_before_transport(route: str) -> None:
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=VALID)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(route)
    assert caught.value.code is ErrorCode.INVALID_ARGUMENT
    assert requests == []


@pytest.mark.asyncio
async def test_request_destination_and_headers_cannot_be_supplied_by_params() -> None:
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=VALID)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler)) as client:
        await client.get(
            ROUTE,
            {
                "Authorization": "Bearer attacker",
                "X-CMC_PRO_API_KEY": "attacker",
                "Cookie": "session=attacker",
                "Host": "attacker.example",
                "url": "https://attacker.example",
            },
        )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "pro-api.coinmarketcap.com"
    assert request.url.port is None
    assert request.url.path == "/public-api" + ROUTE
    assert "authorization" not in request.headers
    assert "x-cmc_pro_api_key" not in request.headers
    assert "cookie" not in request.headers
    assert request.headers["host"] == "pro-api.coinmarketcap.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'{"status":',
        b"null",
        b"[]",
        b'{"status":null,"data":[]}',
        b'{"status":"bad","data":[]}',
        b'{"status":{"error_code":[]},"data":[]}',
        b'{"status":{"error_code":0}}',
        b'{"status":{"error_code":1},"status":{"error_code":0},"data":[]}',
    ],
)
async def test_malformed_success_bodies_remain_contract_mismatches(body: bytes) -> None:
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
        cache_enabled=True,
        max_attempts=1,
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
        assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
        assert client._cache._entries == {}  # noqa: SLF001


@pytest.mark.asyncio
async def test_deep_json_is_contract_mismatch_then_valid_response_can_cache() -> None:
    deep = b'{"status":{"error_code":0},"data":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}"
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=deep if calls == 1 else json.dumps(VALID).encode())

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), max_attempts=1) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
        assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
        assert await client.get(ROUTE) == VALID
        assert await client.get(ROUTE) == VALID
    assert calls == 2


@pytest.mark.asyncio
async def test_gzip_expansion_is_bounded_after_httpx_decoding_and_not_cached() -> None:
    expanded = b'{"status":{"error_code":0},"data":"' + b"x" * DEFAULT_MAX_RESPONSE_BYTES + b'"}'
    compressed = gzip.compress(expanded)
    consumed = 0

    class CompressedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            for offset in range(0, len(compressed), 512):
                chunk = compressed[offset : offset + 512]
                consumed += len(chunk)
                yield chunk

        async def aclose(self):
            return None

    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"Content-Encoding": "gzip", "Content-Length": str(len(compressed))},
                stream=CompressedStream(),
            )
        return httpx.Response(200, json=VALID)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), max_attempts=1) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
        assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
        assert client._cache._entries == {}  # noqa: SLF001
        assert await client.get(ROUTE) == VALID
        assert await client.get(ROUTE) == VALID
    assert len(compressed) < DEFAULT_MAX_RESPONSE_BYTES
    assert consumed <= len(compressed)
    assert calls == 2


@pytest.mark.asyncio
async def test_malformed_compressed_body_is_contract_mismatch() -> None:
    class MalformedCompressedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"not a gzip stream"

        async def aclose(self):
            return None

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=MalformedCompressedStream(),
            )
        ),
        max_attempts=1,
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
    assert "compressed data" in caught.value.message


@pytest.mark.asyncio
async def test_extreme_decimal_content_length_rejected_without_integer_conversion() -> None:
    consumed = False

    class NeverRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            consumed = True
            yield b"unused"

        async def aclose(self):
            return None

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Length": "9" * 5000},
                stream=NeverRead(),
            )
        ),
        max_attempts=1,
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
    assert not consumed


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after", ["999999999999999999999999", "-1", "NaN", "Infinity", "bad"])
async def test_retry_after_abuse_is_capped_and_exhaustion_is_stable(retry_after: str) -> None:
    attempts = 0
    delays = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": retry_after})

    async def record(delay: float) -> None:
        delays.append(delay)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _sleep=record, _random_uniform=lambda low, high: high
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert attempts == 3
    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_alternating_retryable_statuses_exhaust_with_final_classification() -> None:
    statuses = iter((429, 503, 504))
    observed = []

    async def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        observed.append(status)
        return httpx.Response(status)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _sleep=lambda delay: _immediate()
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert observed == [429, 503, 504]
    assert caught.value.code is ErrorCode.UPSTREAM_5XX
    assert caught.value.attempts == 3


@pytest.mark.asyncio
async def test_retryable_status_followed_by_malformed_success_is_not_cached() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(502)
        if calls == 2:
            return httpx.Response(200, content=b"{truncated")
        return httpx.Response(200, json=VALID)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), _sleep=lambda delay: _immediate()
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
        assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
        assert caught.value.attempts == 2
        assert client._cache._entries == {}  # noqa: SLF001
        assert await client.get(ROUTE) == VALID
        assert await client.get(ROUTE) == VALID
    assert calls == 3


@pytest.mark.asyncio
async def test_provider_error_text_is_single_line_bounded_and_keeps_classification() -> None:
    hostile = "bad\r\nINFO: forged\x1b[31m\x9b" + "x" * 1000
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"status": {"error_code": 1006, "error_message": hostile}, "data": None}
            )
        ),
        max_attempts=1,
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
    assert caught.value.code is ErrorCode.UPSTREAM_APPLICATION_ERROR
    assert "\n" not in caught.value.message and "\r" not in caught.value.message
    assert "\x1b" not in caught.value.message
    assert len(caught.value.message) <= 256
    assert "forged" in caught.value.message


def test_environment_variables_do_not_configure_security_boundaries(monkeypatch) -> None:
    for name in (
        "CMC_API_KEY",
        "COINMARKETCAP_API_KEY",
        "X_CMC_PRO_API_KEY",
        "CMC_BASE_URL",
        "COINMARKETCAP_BASE_URL",
        "CMC_HOST",
    ):
        monkeypatch.setenv(name, "https://attacker.example/credential")
    client = KeylessHttpClient(cache_enabled=False)
    try:
        assert str(client._http.base_url) == BASE_URL + "/"
        assert "authorization" not in client._http.headers
        assert "x-cmc_pro_api_key" not in client._http.headers
        assert "cookie" not in client._http.headers
        assert client._http.headers["accept"] == "application/json"
    finally:
        asyncio.run(client.aclose())


def test_cli_transport_and_port_validation() -> None:
    parser = build_parser()
    assert parser.parse_args([]).transport == "stdio"
    assert parser.parse_args([]).host == "127.0.0.1"
    assert parser.parse_args(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "65535"]).host == "0.0.0.0"
    for args in (["--transport", "unknown"], ["--port", "x"], ["--port", "0"], ["--port", "65536"], ["--extra"]):
        with pytest.raises(SystemExit) as caught:
            parser.parse_args(args)
        assert caught.value.code == 2


@pytest.mark.asyncio
async def test_stdio_startup_discovery_call_failure_and_shutdown_keep_stdout_protocol_only() -> None:
    code = '''import asyncio
from coinmarketcap_keyless_mcp import runtime
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode
class Fixture:
 async def get(self, route, params=None):
  raise CmcClientError(ErrorCode.UPSTREAM_CONTRACT_MISMATCH, "safe failure")
 async def aclose(self):
  print("cleanup diagnostic", file=__import__("sys").stderr)
asyncio.run(runtime.run_server("stdio", client_factory=Fixture))
'''
    params = StdioServerParameters(command=sys.executable, args=["-c", code])
    async with asyncio.timeout(10):
        async with Client(stdio_client(params)) as client:
            tools = await client.list_tools()
            result = await client.call_tool("cmc_fear_greed_latest", {})
    assert [tool.name for tool in tools.tools] == [contract.name for contract in TOOL_CONTRACTS]
    assert result.is_error and "UPSTREAM_CONTRACT_MISMATCH" in result.content[0].text


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_owned_client_cleanup(monkeypatch) -> None:
    from coinmarketcap_keyless_mcp import runtime

    closing = asyncio.Event()
    finish = asyncio.Event()

    class OwnedClient:
        async def aclose(self):
            closing.set()
            await finish.wait()

    class WaitingServer:
        async def run_stdio_async(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "create_server", lambda client: WaitingServer())
    task = asyncio.create_task(runtime.run_server("stdio", client_factory=OwnedClient))
    async with asyncio.timeout(5):
        await asyncio.sleep(0)
        task.cancel()
        await closing.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_server_construction_failure_still_closes_client(monkeypatch) -> None:
    from coinmarketcap_keyless_mcp import runtime

    closed = asyncio.Event()

    class OwnedClient:
        async def aclose(self):
            closed.set()

    def fail_create_server(client):
        raise RuntimeError("internal setup failure")

    monkeypatch.setattr(runtime, "create_server", fail_create_server)
    with pytest.raises(RuntimeError, match="internal setup failure"):
        await runtime.run_server("stdio", client_factory=OwnedClient)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_cli_argument_failure_is_nonzero_and_traceback_free() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "coinmarketcap_keyless_mcp",
        "--transport",
        "unknown",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(10):
        stdout, stderr = await process.communicate()
    assert process.returncode == 2
    assert stdout == b""
    assert b"usage:" in stderr.lower()
    assert b"Traceback" not in stderr


def test_application_source_has_no_stdout_print_calls() -> None:
    from pathlib import Path

    source = Path(__file__).parents[2] / "src" / "coinmarketcap_keyless_mcp"
    runtime_sources = [path for path in source.glob("*.py") if path.name != "verify_live.py"]
    assert all("print(" not in path.read_text(encoding="utf-8") for path in runtime_sources)


async def _immediate() -> None:
    return None

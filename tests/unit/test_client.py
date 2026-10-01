import httpx
import pytest

from coinmarketcap_keyless_mcp.client import KeylessHttpClient, serialize_query
from coinmarketcap_keyless_mcp.contracts import BASE_URL, ROUTES
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode


def response(payload: object, status_code: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=payload, headers=headers)


async def run_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    async with KeylessHttpClient(_transport=transport, **kwargs) as client:
        return await client.get(ROUTES["cmc_quotes_latest"], {"ids": [1, 1027], "skip_invalid": False})


def test_query_serialization() -> None:
    assert serialize_query({"ids": [1, 1027], "skip_invalid": False, "omit": None}) == {
        "ids": "1,1027",
        "skip_invalid": "false",
    }


@pytest.mark.asyncio
async def test_fixed_base_url_get_and_no_auth_header() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    result = await run_client(handler)
    assert result["data"] == {"ok": True}
    assert seen["method"] == "GET"
    assert seen["url"] == f"{BASE_URL}/v3/cryptocurrency/quotes/latest?ids=1%2C1027&skip_invalid=false"
    assert "x-cmc_pro_api_key" not in seen["headers"]
    assert "authorization" not in seen["headers"]


@pytest.mark.asyncio
async def test_non_allowlisted_route_is_rejected_before_transport() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return response({})

    transport = httpx.MockTransport(handler)
    async with KeylessHttpClient(_transport=transport) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get("/v1/../private")
    assert caught.value.code is ErrorCode.INVALID_ARGUMENT
    assert not called


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", [0, "0"])
async def test_numeric_and_string_zero_are_success(error_code) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response({"status": {"error_code": error_code}, "data": []})

    assert (await run_client(handler))["data"] == []


@pytest.mark.asyncio
async def test_application_error_is_not_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response({"status": {"error_code": 1006, "error_message": "bad request"}, "data": None})

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_APPLICATION_ERROR
    assert caught.value.provider_error_code == 1006


@pytest.mark.asyncio
async def test_invalid_provider_error_code_is_contract_mismatch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response({"status": {"error_code": None}, "data": []})

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"status": {}}, {"status": {"error_code": 0}}])
async def test_malformed_envelopes_are_rejected(payload) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return response(payload)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


@pytest.mark.asyncio
async def test_malformed_json_is_contract_mismatch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH


@pytest.mark.asyncio
async def test_429_retries_then_succeeds_and_honors_retry_after() -> None:
    attempts = 0
    sleeps = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return response({}, 429, {"Retry-After": "0.25"})
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    result = await run_client(handler, _sleep=record_sleep)
    assert result["data"] == {"ok": True}
    assert attempts == 2
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_429_exhaustion_is_rate_limited() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response({}, 429)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler, _sleep=lambda delay: _immediate())
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert caught.value.attempts == 3
    assert attempts == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [502, 503, 504])
async def test_selected_5xx_retries_then_succeeds(status_code: int) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return response({}, status_code)
        return response({"status": {"error_code": 0}, "data": {"ok": True}})

    result = await run_client(handler, _sleep=lambda delay: _immediate())
    assert result["data"] == {"ok": True}
    assert attempts == 2


@pytest.mark.asyncio
async def test_deterministic_400_is_not_retried() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response({}, 400)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler)
    assert caught.value.code is ErrorCode.UPSTREAM_HTTP_ERROR
    assert caught.value.attempts == 1
    assert attempts == 1


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_classified() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(CmcClientError) as caught:
        await run_client(handler, _sleep=lambda delay: _immediate())
    assert caught.value.code is ErrorCode.UPSTREAM_TIMEOUT
    assert caught.value.attempts == 3
    assert attempts == 3


async def _immediate() -> None:
    return None

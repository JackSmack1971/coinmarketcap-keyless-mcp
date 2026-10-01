"""Bounded, event-driven resource qualification; no production network."""

import asyncio

import httpx
import pytest

from coinmarketcap_keyless_mcp.client import DEFAULT_MAX_RESPONSE_BYTES, KeylessHttpClient
from coinmarketcap_keyless_mcp.contracts import ROUTES
from coinmarketcap_keyless_mcp.errors import CmcClientError, ErrorCode

ROUTE = ROUTES["cmc_quotes_latest"]
PAYLOAD = {"status": {"error_code": 0}, "data": {"items": []}}
LIMIT = DEFAULT_MAX_RESPONSE_BYTES


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.consumed = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.consumed += len(chunk)
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [LIMIT - 1, LIMIT, LIMIT + 1])
@pytest.mark.parametrize("declared", [None, "1", "actual"])
async def test_stream_boundaries(size, declared):
    prefix = b'{"status":{"error_code":0},"data":[]}'
    body = prefix + b" " * (size - len(prefix))
    stream = Stream([body[i : i + 4096] for i in range(0, size, 4096)])
    headers = (
        {}
        if declared is None
        else {"Content-Length": str(size) if declared == "actual" else declared}
    )
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, stream=stream)
        )
    ) as client:
        if size <= LIMIT:
            assert (await client.get(ROUTE))["data"] == []
        else:
            with pytest.raises(CmcClientError) as caught:
                await client.get(ROUTE)
            assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
    assert stream.closed
    if declared == "actual" and size > LIMIT:
        assert stream.consumed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Content-Length": "1"},
        {"Transfer-Encoding": "chunked"},
        {"Content-Length": str(LIMIT * 4)},
    ],
)
async def test_oversized_stream_stops_early(headers):
    stream = Stream([b"x" * 4096] * (LIMIT // 4096 * 4))
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, stream=stream)
        )
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
        assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
        assert client._concurrency._value == 2
    assert stream.closed
    assert stream.consumed <= LIMIT + 4096
    assert stream.consumed < LIMIT * 4


@pytest.mark.asyncio
async def test_malformed_stream_below_limit():
    stream = Stream([b"not", b" json"])
    async with KeylessHttpClient(
        _transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(CmcClientError) as caught:
            await client.get(ROUTE)
        assert caught.value.code is ErrorCode.UPSTREAM_CONTRACT_MISMATCH
    assert stream.closed


class ObservedSemaphore(asyncio.Semaphore):
    """Observe all callers reaching acquire without scheduler sleeps."""

    def __init__(self, capacity, callers):
        super().__init__(capacity)
        self.callers = callers
        self.arrivals = 0
        self.arrived = asyncio.Event()

    async def acquire(self):
        self.arrivals += 1
        if self.arrivals == self.callers:
            self.arrived.set()
        return await super().acquire()


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity", [2, 3])
@pytest.mark.parametrize("mode", ["identical", "different", "disabled", "expired", "error"])
async def test_cache_contention(capacity, mode):
    now = [0.0]
    active = maximum = calls = 0
    release = asyncio.Event()
    entered = asyncio.Event()
    blocked = False

    async def handler(request):
        nonlocal active, maximum, calls
        calls += 1
        active += 1
        maximum = max(maximum, active)
        try:
            if blocked:
                if active == capacity:
                    entered.set()
                await release.wait()
            return httpx.Response(
                200,
                json=(
                    {"status": {"error_code": 1006}, "data": None}
                    if mode == "error"
                    else {"status": {"error_code": 0}, "data": {"items": [], "generation": calls}}
                ),
            )
        finally:
            active -= 1

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler),
        max_concurrency=capacity,
        cache_enabled=mode != "disabled",
        _monotonic=lambda: now[0],
    ) as client:
        assert client._concurrency._value == capacity
        if mode == "expired":
            await client.get(ROUTE)
            now[0] = 30.0
        blocked = True
        sem = ObservedSemaphore(capacity, 24)
        client._concurrency = sem
        tasks = [
            asyncio.create_task(client.get(ROUTE, {"id": i} if mode == "different" else None))
            for i in range(24)
        ]
        async with asyncio.timeout(5):
            await sem.arrived.wait()
            await entered.wait()
            assert active == capacity
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        assert maximum == capacity
        assert active == 0 and sem._value == capacity
        assert calls == 24 + (mode == "expired")
        if mode == "error":
            assert all(
                isinstance(result, CmcClientError)
                and result.code is ErrorCode.UPSTREAM_APPLICATION_ERROR
                for result in results
            )
            with pytest.raises(CmcClientError):
                await client.get(ROUTE)
            assert calls == 25
        else:
            assert all(
                result["data"]["generation"] > (1 if mode == "expired" else 0) for result in results
            )
            results[0]["data"]["items"].append("mutation")
            assert all(result["data"]["items"] == [] for result in results[1:])
            before = calls
            hits = await asyncio.gather(
                *(
                    client.get(ROUTE, {"id": i % 24} if mode == "different" else None)
                    for i in range(48)
                )
            )
            assert all(hit["data"]["items"] == [] for hit in hits)
            hits[0]["data"]["items"].append("cached caller mutation")
            assert all(hit["data"]["items"] == [] for hit in hits[1:])
            assert calls == before + (48 if mode == "disabled" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "timeout", "network", "provider"])
async def test_capacity_recovers_after_active_failure(failure):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    closed = asyncio.Event()

    class BlockingStream(Stream):
        async def __aiter__(self):
            entered.set()
            await release.wait()
            if failure == "timeout":
                raise httpx.ReadTimeout("fixture")
            if failure == "network":
                raise httpx.ReadError("fixture")
            yield b'{"status":{"error_code":1006},"data":null}'

        async def aclose(self):
            closed.set()

    def handler(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(200, stream=BlockingStream([]))
            if calls == 1
            else httpx.Response(200, json=PAYLOAD)
        )

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), max_concurrency=1, max_attempts=1
    ) as client:
        task = asyncio.create_task(client.get(ROUTE))
        async with asyncio.timeout(5):
            await entered.wait()
            sem = client._concurrency
            observed = ObservedSemaphore(0, 1)
            # Observe a real waiter on the same capacity, not a timing guess.
            original = sem.acquire

            async def acquire():
                observed.arrived.set()
                return await original()

            sem.acquire = acquire
            waiter = asyncio.create_task(client.get(ROUTE))
            await observed.arrived.wait()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            if failure == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                with pytest.raises(CmcClientError) as caught:
                    await task
                assert (
                    caught.value.code
                    is {
                        "timeout": ErrorCode.UPSTREAM_TIMEOUT,
                        "network": ErrorCode.UPSTREAM_NETWORK_ERROR,
                        "provider": ErrorCode.UPSTREAM_APPLICATION_ERROR,
                    }[failure]
                )
            assert closed.is_set()
            assert sem._value == 1
            assert (await client.get(ROUTE)) == PAYLOAD
            assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("cancel", [False, True])
async def test_retry_sleep_releases_capacity(status, cancel):
    sleeping = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    streams = []

    async def sleep(delay):
        sleeping.set()
        await release.wait()

    def handler(request):
        nonlocal calls
        calls += 1
        stream = Stream([b"ignored"])
        streams.append(stream)
        if request.url.params.get("id") == "retry":
            return httpx.Response(status, stream=stream)
        return httpx.Response(200, json=PAYLOAD)

    async with KeylessHttpClient(
        _transport=httpx.MockTransport(handler), max_concurrency=1, _sleep=sleep
    ) as client:
        task = asyncio.create_task(client.get(ROUTE, {"id": "retry"}))
        async with asyncio.timeout(5):
            await sleeping.wait()
            assert streams[0].closed and streams[0].consumed == 0
            assert await client.get(ROUTE, {"id": "other"}) == PAYLOAD
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                with pytest.raises(CmcClientError) as caught:
                    await task
                assert caught.value.code is (
                    ErrorCode.RATE_LIMITED if status == 429 else ErrorCode.UPSTREAM_5XX
                )
                assert caught.value.attempts == 3
            assert client._concurrency._value == 1
            assert len(client._cache._entries) == 1  # Only the successful other key.
            before = calls
            release.set()
            with pytest.raises(CmcClientError):
                await client.get(ROUTE, {"id": "retry"})
            assert calls == before + 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_close_after_requests_is_idempotent(failed):
    class Transport(httpx.MockTransport):
        closed = 0

        async def aclose(self):
            self.closed += 1

    transport = Transport(lambda request: httpx.Response(400 if failed else 200, json=PAYLOAD))
    client = KeylessHttpClient(_transport=transport)
    if failed:
        with pytest.raises(CmcClientError):
            await client.get(ROUTE)
    else:
        await client.get(ROUTE)
    await client.aclose()
    await client.aclose()
    assert transport.closed == 1 and client._http.is_closed
    if not failed:
        assert await client.get(ROUTE) == PAYLOAD  # Existing cache-only behavior.
    with pytest.raises(RuntimeError, match="closed"):
        await client.get(ROUTE, {"id": "uncached"})


@pytest.mark.asyncio
async def test_shutdown_during_active_request_with_request_cancellation():
    entered = asyncio.Event()
    closing = asyncio.Event()
    finish_close = asyncio.Event()

    class ActiveStream(Stream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"unreachable"

    stream = ActiveStream([])

    class Transport(httpx.MockTransport):
        async def aclose(self):
            closing.set()
            await finish_close.wait()

    client = KeylessHttpClient(
        _transport=Transport(lambda request: httpx.Response(200, stream=stream))
    )
    task = asyncio.create_task(client.get(ROUTE))
    async with asyncio.timeout(5):
        await entered.wait()
        close = asyncio.create_task(client.aclose())
        await closing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        finish_close.set()
        await close
    assert stream.closed and client._http.is_closed
    assert client._concurrency._value == 2
    assert client._cache._entries == {}


@pytest.mark.asyncio
async def test_retry_success_is_cached_only_after_completion():
    sleeping = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def sleep(delay):
        sleeping.set()
        await release.wait()

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, json=PAYLOAD)

    async with KeylessHttpClient(_transport=httpx.MockTransport(handler), _sleep=sleep) as client:
        task = asyncio.create_task(client.get(ROUTE))
        async with asyncio.timeout(5):
            await sleeping.wait()
            assert client._cache._entries == {}
            release.set()
            assert await task == PAYLOAD
        assert await client.get(ROUTE) == PAYLOAD
        assert calls == 2


@pytest.mark.asyncio
async def test_cache_storage_copy_and_exact_expiry_under_lock_contention():
    from coinmarketcap_keyless_mcp.client import _TtlCache

    now = [0.0]
    cache = _TtlCache(lambda: now[0])
    source = {"items": []}
    await cache.set("key", source, 30.0)
    source["items"].append("external mutation")
    assert await cache.get("key") == {"items": []}
    await cache._lock.acquire()
    reached = asyncio.Barrier(25)

    async def read():
        await reached.wait()
        return await cache.get("key")

    tasks = [asyncio.create_task(read()) for _ in range(24)]
    async with asyncio.timeout(5):
        await reached.wait()
        now[0] = 30.0
        cache._lock.release()
        assert await asyncio.gather(*tasks) == [None] * 24
    assert cache._entries == {}

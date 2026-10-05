"""Runtime entry points for the supported MCP transports."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from .client import KeylessHttpClient
from .remote_auth import RemoteOAuthConfig, configure_remote_oauth
from .server import create_server

Transport = Literal["stdio", "streamable-http"]
ClientFactory = Callable[[], KeylessHttpClient]
CLEANUP_TIMEOUT_SECONDS = 10.0

logger = logging.getLogger(__name__)


async def _complete_cleanup(
    awaitable: Awaitable[object], timeout: float = CLEANUP_TIMEOUT_SECONDS
) -> None:
    """Finish owned cleanup despite repeated cancellation, but never wait forever."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    cleanup = asyncio.ensure_future(awaitable)
    while not cleanup.done():
        remaining = deadline - loop.time()
        if remaining <= 0:
            cleanup.cancel()
            logger.warning("cleanup did not finish within %.1f seconds; abandoning it", timeout)
            return
        try:
            await asyncio.wait({cleanup}, timeout=remaining)
        except asyncio.CancelledError:
            continue
    cleanup.result()


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


async def run_server(
    transport: Transport = "stdio",
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    client_factory: ClientFactory = KeylessHttpClient,
) -> None:
    """Run one transport using the shared MCP server construction path."""

    client = client_factory()
    try:
        server = create_server(client)
        if transport == "stdio":
            await server.run_stdio_async()
        elif transport == "streamable-http":
            authenticated = False
            if not _is_loopback(host):
                auth_config = RemoteOAuthConfig.from_env()
                if auth_config is None:
                    raise RuntimeError(
                        "non-loopback Streamable HTTP requires OAuth: set CMC_MCP_PUBLIC_URL "
                        "and CMC_MCP_OAUTH_SIGNING_KEY"
                    )
                configure_remote_oauth(server, auth_config)
                authenticated = True
            await _run_streamable_http(
                server,
                host=host,
                port=port,
                authenticated=authenticated,
            )
        else:  # pragma: no cover - argparse constrains the production path.
            raise ValueError(f"unsupported transport: {transport}")
    finally:
        close = getattr(client, "aclose", None)
        if close is not None:
            await _complete_cleanup(close())


async def _run_streamable_http(
    server: object,
    *,
    host: str,
    port: int,
    authenticated: bool = False,
) -> None:
    """Serve the SDK's Streamable HTTP app with cancellable cleanup."""

    import uvicorn

    if not _is_loopback(host):
        if not authenticated:
            raise RuntimeError("non-loopback Streamable HTTP must be authenticated")
        logger.info("serving authenticated Streamable HTTP on non-loopback host %s", host)
    app = server.streamable_http_app(host=host)  # type: ignore[attr-defined]
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    http_server = uvicorn.Server(config)
    try:
        await http_server.serve()
    except asyncio.CancelledError:
        http_server.should_exit = True
        await _complete_cleanup(http_server.shutdown())
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CoinMarketCap keyless MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=_port, default=8000, help="HTTP bind port")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server(args.transport, host=args.host, port=args.port))

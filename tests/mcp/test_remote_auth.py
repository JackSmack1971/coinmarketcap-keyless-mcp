from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from coinmarketcap_keyless_mcp.remote_auth import RemoteOAuth, RemoteOAuthConfig
from coinmarketcap_keyless_mcp.runtime import run_server


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def _app(oauth: RemoteOAuth) -> Starlette:
    return Starlette(
        routes=[
            Route(
                "/.well-known/oauth-authorization-server",
                oauth.metadata,
                methods=["GET"],
            ),
            Route("/authorize", oauth.authorize, methods=["GET"]),
            Route("/token", oauth.token, methods=["POST"]),
        ]
    )


def test_remote_oauth_config_requires_complete_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMC_MCP_PUBLIC_URL", "https://example.test")
    monkeypatch.delenv("CMC_MCP_OAUTH_SIGNING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="requires both"):
        RemoteOAuthConfig.from_env()


@pytest.mark.asyncio
async def test_non_loopback_streamable_http_fails_closed_without_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CMC_MCP_PUBLIC_URL", raising=False)
    monkeypatch.delenv("CMC_MCP_OAUTH_SIGNING_KEY", raising=False)

    class FixtureClient:
        async def get(self, route, params=None):  # pragma: no cover - no tool call is made
            raise AssertionError("upstream should not be called")

        async def aclose(self):
            return None

    with pytest.raises(RuntimeError, match="requires OAuth"):
        await run_server(
            "streamable-http",
            host="0.0.0.0",
            port=8000,
            client_factory=FixtureClient,
        )


@pytest.mark.asyncio
async def test_oauth_code_pkce_access_refresh_and_replay() -> None:
    config = RemoteOAuthConfig(
        issuer_url="https://example.test",
        resource_url="https://example.test/mcp",
        signing_key=b"k" * 32,
    )
    oauth = RemoteOAuth(config)
    callback_id = "privatePlugin123"
    client_id = f"https://chatgpt.com/oauth/{callback_id}/client.json"
    redirect_uri = f"https://chatgpt.com/connector/oauth/{callback_id}"
    verifier = "v" * 64

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(oauth)),
        base_url="https://example.test",
    ) as client:
        metadata = await client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        assert metadata.json()["client_id_metadata_document_supported"] is True
        assert metadata.json()["token_endpoint_auth_methods_supported"] == ["none"]

        authorize = await client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
                "scope": "cmc:read",
                "resource": config.resource_url,
                "state": "state-1",
            },
            follow_redirects=False,
        )
        assert authorize.status_code == 302
        query = parse_qs(urlparse(authorize.headers["location"]).query)
        code = query["code"][0]
        assert query["state"] == ["state-1"]

        token = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "resource": config.resource_url,
            },
        )
        assert token.status_code == 200
        body = token.json()
        verified = await oauth.verify_token(body["access_token"])
        assert verified is not None
        assert verified.client_id == client_id
        assert verified.resource == config.resource_url
        assert verified.scopes == ["cmc:read"]

        replay = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"

        refreshed = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": body["refresh_token"],
                "scope": "cmc:read",
                "resource": config.resource_url,
            },
        )
        assert refreshed.status_code == 200
        assert await oauth.verify_token(refreshed.json()["access_token"]) is not None

        refresh_replay = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": body["refresh_token"],
            },
        )
        assert refresh_replay.status_code == 400
        assert refresh_replay.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_authorize_rejects_wrong_resource_and_redirect() -> None:
    oauth = RemoteOAuth(
        RemoteOAuthConfig(
            issuer_url="https://example.test",
            resource_url="https://example.test/mcp",
            signing_key=b"z" * 32,
        )
    )
    callback_id = "privatePlugin123"
    client_id = f"https://chatgpt.com/oauth/{callback_id}/client.json"
    base = {
        "response_type": "code",
        "client_id": client_id,
        "code_challenge": _challenge("x" * 64),
        "code_challenge_method": "S256",
        "scope": "cmc:read",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(oauth)),
        base_url="https://example.test",
    ) as client:
        bad_redirect = await client.get(
            "/authorize",
            params={
                **base,
                "redirect_uri": "https://attacker.test/cb",
                "resource": "https://example.test/mcp",
            },
        )
        assert bad_redirect.status_code == 400
        assert bad_redirect.json()["error"] == "invalid_request"

        bad_resource = await client.get(
            "/authorize",
            params={
                **base,
                "redirect_uri": f"https://chatgpt.com/connector/oauth/{callback_id}",
                "resource": "https://other.test/mcp",
            },
        )
        assert bad_resource.status_code == 400
        assert bad_resource.json()["error"] == "invalid_target"


@pytest.mark.asyncio
async def test_malformed_tokens_and_form_bodies_fail_closed() -> None:
    oauth = RemoteOAuth(
        RemoteOAuthConfig(
            issuer_url="https://example.test",
            resource_url="https://example.test/mcp",
            signing_key=b"m" * 32,
        )
    )
    assert await oauth.verify_token("v1.@@@.@@@") is None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(oauth)),
        base_url="https://example.test",
    ) as client:
        response = await client.post(
            "/token",
            content=b"\xff\xfe",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

"""OAuth 2.1 boundary for internet-facing Streamable HTTP deployments.

CoinMarketCap remains keyless. This module authenticates only the remote MCP
transport so a public deployment cannot be used anonymously to consume the
host's keyless upstream rate limit.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)

_SCOPE = "cmc:read"
_CODE_TTL_SECONDS = 120
_ACCESS_TTL_SECONDS = 3600
_REFRESH_TTL_SECONDS = 30 * 24 * 3600
_CALLBACK_CLIENT_RE = re.compile(
    r"^https://chatgpt\.com/oauth/([A-Za-z0-9_-]{8,160})/client\.json$"
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class RemoteOAuthConfig:
    issuer_url: str
    resource_url: str
    signing_key: bytes
    allowed_client_id: str | None = None

    @classmethod
    def from_env(cls) -> "RemoteOAuthConfig | None":
        public_url = os.environ.get("CMC_MCP_PUBLIC_URL", "").strip().rstrip("/")
        key = os.environ.get("CMC_MCP_OAUTH_SIGNING_KEY", "")
        if not public_url and not key:
            return None
        if not public_url or not key:
            raise RuntimeError(
                "remote OAuth requires both CMC_MCP_PUBLIC_URL and CMC_MCP_OAUTH_SIGNING_KEY"
            )
        parsed = urlparse(public_url)
        is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
            raise RuntimeError("CMC_MCP_PUBLIC_URL must use HTTPS unless it is loopback")
        if parsed.query or parsed.fragment or not parsed.netloc:
            raise RuntimeError("CMC_MCP_PUBLIC_URL must be an origin URL without query or fragment")
        if len(key.encode("utf-8")) < 32:
            raise RuntimeError("CMC_MCP_OAUTH_SIGNING_KEY must contain at least 32 bytes")
        return cls(
            issuer_url=public_url,
            resource_url=f"{public_url}/mcp",
            signing_key=key.encode("utf-8"),
            allowed_client_id=os.environ.get("CMC_MCP_ALLOWED_CLIENT_ID") or None,
        )


class RemoteOAuth:
    """Small stateless OAuth authorization server plus MCP token verifier.

    The authorization server accepts only ChatGPT callback-specific CIMD client
    identifiers. Authorization codes and tokens are HMAC signed; no credential
    or token database is required. A bounded in-memory replay set rejects reuse
    within a running process; short authorization-code lifetimes bound restart
    exposure.
    """

    def __init__(self, config: RemoteOAuthConfig):
        self.config = config
        self._used_codes: dict[str, int] = {}
        self._used_refresh: dict[str, int] = {}

    def _accepted_client(self, client_id: str) -> tuple[str, str] | None:
        if self.config.allowed_client_id and client_id != self.config.allowed_client_id:
            return None
        match = _CALLBACK_CLIENT_RE.fullmatch(client_id)
        if not match:
            return None
        callback_id = match.group(1)
        return client_id, f"https://chatgpt.com/connector/oauth/{callback_id}"

    def _sign(self, kind: str, payload: dict[str, Any], ttl: int) -> str:
        now = int(time.time())
        body = {
            "v": 1,
            "kind": kind,
            "iat": now,
            "exp": now + ttl,
            "jti": secrets.token_urlsafe(18),
            **payload,
        }
        encoded = _b64url(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        signature = _b64url(
            hmac.new(
                self.config.signing_key,
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"v1.{encoded}.{signature}"

    def _verify(self, token: str, kind: str) -> dict[str, Any] | None:
        try:
            version, encoded, signature = token.split(".", 2)
            if version != "v1":
                return None
            expected = _b64url(
                hmac.new(
                    self.config.signing_key,
                    encoded.encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(_b64url_decode(encoded))
            if not isinstance(payload, dict):
                return None
            if payload.get("v") != 1 or payload.get("kind") != kind:
                return None
            if int(payload.get("exp", 0)) <= int(time.time()):
                return None
            return payload
        except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _form(body: bytes) -> dict[str, str] | None:
        try:
            parsed = parse_qs(
                body.decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=False,
            )
        except UnicodeDecodeError:
            return None
        return {key: values[0] for key, values in parsed.items() if len(values) == 1}

    @staticmethod
    def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
        return JSONResponse(
            {"error": error, "error_description": description},
            status_code=status,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    async def metadata(self, request: Request) -> Response:
        del request
        base = self.config.issuer_url
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/authorize",
                "token_endpoint": f"{base}/token",
                "scopes_supported": [_SCOPE],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "client_id_metadata_document_supported": True,
            },
            headers={"Cache-Control": "public, max-age=300"},
        )

    async def authorize(self, request: Request) -> Response:
        q = request.query_params
        client_id = q.get("client_id", "")
        accepted = self._accepted_client(client_id)
        if not accepted:
            return self._oauth_error("unauthorized_client", "client is not allowed")
        _, expected_redirect = accepted
        redirect_uri = q.get("redirect_uri", "")
        if redirect_uri != expected_redirect:
            return self._oauth_error("invalid_request", "redirect_uri is not registered")
        if q.get("response_type") != "code":
            return self._oauth_error(
                "unsupported_response_type",
                "response_type must be code",
            )
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            return self._oauth_error("invalid_request", "PKCE S256 is required")
        resource = q.get("resource")
        if resource != self.config.resource_url:
            return self._oauth_error(
                "invalid_target",
                "resource does not match this MCP server",
            )
        requested_scope = q.get("scope", _SCOPE).strip() or _SCOPE
        scopes = requested_scope.split()
        if set(scopes) != {_SCOPE}:
            return self._oauth_error("invalid_scope", f"only {_SCOPE} is supported")
        code = self._sign(
            "code",
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": q["code_challenge"],
                "resource": resource,
                "scopes": scopes,
            },
            _CODE_TTL_SECONDS,
        )
        logger.info("authorized ChatGPT OAuth client %s", client_id)
        params = {"code": code}
        if q.get("state") is not None:
            params["state"] = q["state"]
        return RedirectResponse(
            f"{redirect_uri}?{urlencode(params)}",
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    def _purge_replays(self, store: dict[str, int]) -> None:
        now = int(time.time())
        expired = [jti for jti, exp in store.items() if exp <= now]
        for jti in expired:
            store.pop(jti, None)
        if len(store) > 4096:
            for jti, _ in sorted(store.items(), key=lambda item: item[1])[: len(store) - 4096]:
                store.pop(jti, None)

    def _consume(self, payload: dict[str, Any], store: dict[str, int]) -> bool:
        self._purge_replays(store)
        jti = str(payload.get("jti", ""))
        if not jti or jti in store:
            return False
        store[jti] = int(payload["exp"])
        return True

    def _issue_tokens(self, client_id: str, scopes: list[str]) -> dict[str, Any]:
        common = {
            "client_id": client_id,
            "resource": self.config.resource_url,
            "scopes": scopes,
        }
        access = self._sign("access", common, _ACCESS_TTL_SECONDS)
        refresh = self._sign("refresh", common, _REFRESH_TTL_SECONDS)
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": _ACCESS_TTL_SECONDS,
            "scope": " ".join(scopes),
            "refresh_token": refresh,
        }

    async def token(self, request: Request) -> Response:
        form = self._form(await request.body())
        if form is None:
            return self._oauth_error("invalid_request", "token request body must be UTF-8 form data")
        client_id = form.get("client_id", "")
        if not self._accepted_client(client_id):
            return self._oauth_error("invalid_client", "client is not allowed", 401)
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            payload = self._verify(form.get("code", ""), "code")
            if payload is None or payload.get("client_id") != client_id:
                return self._oauth_error("invalid_grant", "authorization code is invalid")
            if form.get("redirect_uri") != payload.get("redirect_uri"):
                return self._oauth_error("invalid_grant", "redirect_uri does not match")
            if form.get("resource") not in {None, "", self.config.resource_url}:
                return self._oauth_error("invalid_target", "resource does not match")
            verifier = form.get("code_verifier", "")
            challenge = _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
            if not verifier or not hmac.compare_digest(
                challenge,
                str(payload.get("code_challenge", "")),
            ):
                return self._oauth_error("invalid_grant", "PKCE verification failed")
            if not self._consume(payload, self._used_codes):
                return self._oauth_error(
                    "invalid_grant",
                    "authorization code was already used",
                )
            return JSONResponse(
                self._issue_tokens(
                    client_id,
                    list(payload.get("scopes") or [_SCOPE]),
                ),
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        if grant_type == "refresh_token":
            payload = self._verify(form.get("refresh_token", ""), "refresh")
            if payload is None or payload.get("client_id") != client_id:
                return self._oauth_error("invalid_grant", "refresh token is invalid")
            if payload.get("resource") != self.config.resource_url:
                return self._oauth_error("invalid_target", "resource does not match")
            if not self._consume(payload, self._used_refresh):
                return self._oauth_error(
                    "invalid_grant",
                    "refresh token was already used",
                )
            granted = list(payload.get("scopes") or [_SCOPE])
            requested = form.get("scope")
            scopes = requested.split() if requested else granted
            if not set(scopes).issubset(set(granted)) or set(scopes) != {_SCOPE}:
                return self._oauth_error(
                    "invalid_scope",
                    "requested scope is not granted",
                )
            return JSONResponse(
                self._issue_tokens(client_id, scopes),
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        return self._oauth_error(
            "unsupported_grant_type",
            "unsupported grant_type",
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        payload = self._verify(token, "access")
        if payload is None:
            return None
        if payload.get("resource") != self.config.resource_url:
            return None
        client_id = str(payload.get("client_id", ""))
        if not self._accepted_client(client_id):
            return None
        scopes = list(payload.get("scopes") or [])
        if _SCOPE not in scopes:
            return None
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(payload["exp"]),
            resource=self.config.resource_url,
            subject="private-chatgpt-plugin",
            claims={"iss": self.config.issuer_url},
        )


def configure_remote_oauth(server: Any, config: RemoteOAuthConfig) -> RemoteOAuth:
    """Install remote OAuth on an already-constructed MCPServer.

    The repository already deliberately hardens MCP v2 through qualified private
    internals. This uses the same narrow seam so stdio construction stays
    unchanged while Streamable HTTP gains the SDK's bearer middleware and RFC
    9728 protected-resource metadata.
    """

    oauth = RemoteOAuth(config)
    server.settings.auth = AuthSettings(
        issuer_url=config.issuer_url,
        resource_server_url=config.resource_url,
        required_scopes=[_SCOPE],
        validate_token_resource=True,
    )
    server._token_verifier = oauth  # noqa: SLF001
    server._auth_server_provider = None  # noqa: SLF001
    server.custom_route(
        "/.well-known/oauth-authorization-server",
        methods=["GET"],
    )(oauth.metadata)
    server.custom_route("/authorize", methods=["GET"])(oauth.authorize)
    server.custom_route("/token", methods=["POST"])(oauth.token)
    return oauth

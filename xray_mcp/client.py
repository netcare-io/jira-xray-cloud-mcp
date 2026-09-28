# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Async client for the Xray Cloud REST v2 and GraphQL APIs."""

import asyncio
import copy
import hashlib
import time
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx2
from fastmcp.exceptions import ToolError

from xray_mcp.config import Settings

# Xray tokens live 24h; refresh well before that so a long call never races expiry.
TOKEN_TTL_SECONDS = 23 * 60 * 60

# Upper bound for cached tokens in auth_mode 'headers' (one per API key); oldest are dropped first.
MAX_CACHED_TOKENS = 1000

CLIENT_ID_HEADER = "x-xray-client-id"
CLIENT_SECRET_HEADER = "x-xray-client-secret"

# Paths that stay usable in read-only mode even though they are POSTs.
_READ_ONLY_POST_PATHS = {"/authenticate", "/graphql"}


class XrayApiError(ToolError):
    """An Xray API call failed; the message is safe to show to the model."""


def graphql_operation_types(document: str) -> set[str]:
    """Return the operation types (query/mutation/subscription) defined in a GraphQL document.

    Only top-level keywords count, so a field or argument named ``mutation`` inside a
    selection set is not mistaken for an operation. Strings and comments are skipped.
    """
    ops: set[str] = set()
    depth = 0
    i, n = 0, len(document)
    at_depth0_start = True
    while i < n:
        ch = document[i]
        if ch == "#":
            while i < n and document[i] != "\n":
                i += 1
            continue
        if document.startswith('"""', i):
            end = document.find('"""', i + 3)
            i = n if end == -1 else end + 3
            continue
        if ch == '"':
            i += 1
            while i < n and document[i] != '"':
                i += 2 if document[i] == "\\" else 1
            i += 1
            continue
        if ch in "{(":
            if depth == 0 and ch == "{" and at_depth0_start:
                ops.add("query")  # anonymous shorthand query: { ... }
            depth += 1
            at_depth0_start = False
        elif ch in "})":
            depth -= 1
            if depth == 0:
                at_depth0_start = True
        elif depth == 0 and (ch.isalpha() or ch == "_"):
            j = i
            while j < n and (document[j].isalnum() or document[j] == "_"):
                j += 1
            word = document[i:j]
            if word in ("query", "mutation", "subscription"):
                ops.add(word)
            at_depth0_start = False
            i = j
            continue
        i += 1
    return ops


@dataclass(frozen=True)
class Credentials:
    """An Xray API key (Xray Global Settings > API Keys)."""

    client_id: str
    client_secret: str = field(repr=False)

    @property
    def cache_key(self) -> str:
        # Keyed by id and secret, so a wrong secret never reuses a token issued for the right one.
        return hashlib.sha256(f"{self.client_id}\0{self.client_secret}".encode()).hexdigest()


def credentials_from_headers(headers: Mapping[str, str]) -> Credentials | None:
    """Read the Xray API key from request headers (lower-case names, as FastMCP provides them)."""
    client_id = headers.get(CLIENT_ID_HEADER, "").strip()
    client_secret = headers.get(CLIENT_SECRET_HEADER, "").strip()
    return Credentials(client_id, client_secret) if client_id and client_secret else None


class XrayClient:
    """Xray API client. One instance per server holds the connection pool and the token cache;
    ``with_credentials`` returns a view that authenticates as a given API key (auth_mode 'headers').
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._http = httpx2.AsyncClient(base_url=settings.api_url, timeout=settings.timeout, transport=transport)
        self._credentials: Credentials | None = None
        if settings.auth_mode == "env" and settings.client_id and settings.client_secret:
            self._credentials = Credentials(settings.client_id, settings.client_secret.get_secret_value())
        # Shared by all views: cache key -> (token, monotonic expiry).
        self._tokens: dict[str, tuple[str, float]] = {}
        # One lock per API key while a token is being fetched; entries vanish once no request holds them.
        self._token_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    @property
    def settings(self) -> Settings:
        return self._settings

    def with_credentials(self, credentials: Credentials | None) -> "XrayClient":
        """A view of this client that authenticates as ``credentials``, sharing pool and token cache."""
        view = copy.copy(self)
        view._credentials = credentials
        return view

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_token(self, *, force: bool = False) -> str:
        credentials = self._credentials
        if credentials is None:
            if self._settings.auth_mode == "headers":
                raise XrayApiError(
                    "Xray credentials missing: send the X-Xray-Client-Id and X-Xray-Client-Secret HTTP headers "
                    "(an Xray API key from Xray Global Settings > API Keys). XRAY_AUTH_MODE=headers needs the "
                    "HTTP transport."
                )
            raise XrayApiError(
                "Xray credentials are not configured. Set XRAY_CLIENT_ID and XRAY_CLIENT_SECRET "
                "(Xray Global Settings > API Keys)."
            )
        key = credentials.cache_key
        lock = self._token_locks.get(key)
        if lock is None:
            lock = self._token_locks[key] = asyncio.Lock()
        async with lock:
            cached = self._tokens.get(key)
            if not force and cached and time.monotonic() < cached[1]:
                return cached[0]
            resp = await self._http.post(
                "/authenticate",
                json={"client_id": credentials.client_id, "client_secret": credentials.client_secret},
            )
            if resp.status_code != 200:
                raise XrayApiError(f"Xray authentication failed (HTTP {resp.status_code}): {_snippet(resp)}")
            # The endpoint answers with a JSON-encoded string.
            try:
                token = resp.json()
            except ValueError:
                token = resp.text
            token = str(token).strip().strip('"')
            self._store_token(key, token)
            return token

    def _store_token(self, key: str, token: str) -> None:
        now = time.monotonic()
        for k in [k for k, (_, expires) in self._tokens.items() if expires <= now]:
            del self._tokens[k]
        while len(self._tokens) >= MAX_CACHED_TOKENS:
            del self._tokens[next(iter(self._tokens))]  # oldest first
        self._tokens.pop(key, None)
        self._tokens[key] = (token, now + TOKEN_TTL_SECONDS)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: str | bytes | None = None,
        files: dict[str, tuple[str, bytes | str, str]] | None = None,
        headers: dict[str, str] | None = None,
        response: Literal["json", "bytes"] = "json",
    ) -> Any:
        """Call a REST v2 endpoint (path relative to ``/api/v2``) and return the decoded body."""
        if self._settings.read_only and method.upper() != "GET" and path not in _READ_ONLY_POST_PATHS:
            raise XrayApiError(f"Refusing {method} {path}: the server runs in read-only mode.")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        resp = None
        for attempt in range(2):
            token = await self._get_token(force=attempt > 0)
            resp = await self._http.request(
                method,
                path,
                params=params,
                json=json,
                content=content,
                files=files,
                headers={**(headers or {}), "Authorization": f"Bearer {token}"},
            )
            # A token revoked or expired server-side: re-authenticate once.
            if resp.status_code != 401:
                break
        assert resp is not None
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After")
            raise XrayApiError(
                "Xray rate limit exceeded (HTTP 429)" + (f"; retry after {retry}s." if retry else ".")
            )
        if resp.status_code >= 400:
            raise XrayApiError(f"Xray API {method} {path} failed (HTTP {resp.status_code}): {_snippet(resp)}")
        if response == "bytes":
            return resp.content
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL document and return its ``data``; GraphQL errors raise."""
        if self._settings.read_only and graphql_operation_types(query) - {"query"}:
            raise XrayApiError("Refusing GraphQL mutation: the server runs in read-only mode.")
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = {k: v for k, v in variables.items() if v is not None}
        body = await self.request("POST", "/graphql", json=payload)
        if not isinstance(body, dict):
            raise XrayApiError(f"Unexpected GraphQL response: {str(body)[:500]}")
        if body.get("errors"):
            messages = "; ".join(str(e.get("message", e)) for e in body["errors"])
            raise XrayApiError(f"Xray GraphQL error: {messages}")
        return body.get("data") or {}


def _snippet(resp: httpx2.Response, limit: int = 1000) -> str:
    text = resp.text.strip()
    return text[:limit] + ("…" if len(text) > limit else "") if text else "<empty body>"

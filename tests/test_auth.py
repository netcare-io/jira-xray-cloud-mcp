# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Credentials from the environment or from HTTP request headers (XRAY_AUTH_MODE)."""

import httpx2
import pytest
from fastmcp.utilities.tests import asgi_client

from tests.conftest import FakeXray, make_settings
from xray_mcp import client as client_module
from xray_mcp.client import Credentials, XrayApiError, XrayClient, credentials_from_headers
from xray_mcp.server import create_server

KEY_A = {"X-Xray-Client-Id": "id-a", "X-Xray-Client-Secret": "secret-a"}
KEY_B = {"X-Xray-Client-Id": "id-b", "X-Xray-Client-Secret": "secret-b"}
QUERY = "{ getIssueLinkTypes { id } }"


def header_server(fake: FakeXray, **overrides):
    settings = make_settings(auth_mode="headers", client_id=None, client_secret=None, **overrides)
    return create_server(settings, transport=httpx2.MockTransport(fake.handler))


def auth_bodies(fake: FakeXray) -> list[dict]:
    return [c.json for c in fake.calls if c.path == "/api/v2/authenticate"]


def test_credentials_from_headers() -> None:
    assert credentials_from_headers({"x-xray-client-id": " a ", "x-xray-client-secret": "b"}) == Credentials("a", "b")
    assert credentials_from_headers({"x-xray-client-id": "a"}) is None
    assert credentials_from_headers({}) is None
    assert "secret" not in repr(Credentials("a", "secret"))


async def test_views_share_the_token_cache_per_key(fake) -> None:
    client = XrayClient(make_settings(auth_mode="headers"), transport=httpx2.MockTransport(fake.handler))
    a, b = Credentials("id-a", "secret-a"), Credentials("id-b", "secret-b")
    await client.with_credentials(a).graphql(QUERY)
    await client.with_credentials(a).graphql(QUERY)
    await client.with_credentials(b).graphql(QUERY)
    # Same id, other secret: must not reuse key A's token.
    await client.with_credentials(Credentials("id-a", "wrong")).graphql(QUERY)
    assert [body["client_id"] for body in auth_bodies(fake)] == ["id-a", "id-b", "id-a"]
    await client.aclose()


async def test_headers_mode_ignores_env_credentials(fake) -> None:
    client = XrayClient(make_settings(auth_mode="headers"), transport=httpx2.MockTransport(fake.handler))
    with pytest.raises(XrayApiError, match="X-Xray-Client-Id and X-Xray-Client-Secret"):
        await client.graphql(QUERY)
    assert fake.calls == []


async def test_token_cache_is_bounded(fake, monkeypatch) -> None:
    monkeypatch.setattr(client_module, "MAX_CACHED_TOKENS", 2)
    client = XrayClient(make_settings(auth_mode="headers"), transport=httpx2.MockTransport(fake.handler))
    for i in range(3):
        await client.with_credentials(Credentials(f"id-{i}", "s")).graphql(QUERY)
    await client.with_credentials(Credentials("id-0", "s")).graphql(QUERY)  # evicted, fetched again
    await client.with_credentials(Credentials("id-2", "s")).graphql(QUERY)  # still cached
    assert [body["client_id"] for body in auth_bodies(fake)] == ["id-0", "id-1", "id-2", "id-0"]


async def test_headers_mode_over_http(fake) -> None:
    server = header_server(fake)
    async with asgi_client(server, headers=KEY_A) as client:
        await client.call_tool("xray_get_issue_link_types", {})
        await client.call_tool("xray_get_issue_link_types", {})
    async with asgi_client(server, headers=KEY_B) as client:
        await client.call_tool("xray_get_issue_link_types", {})
    assert auth_bodies(fake) == [
        {"client_id": "id-a", "client_secret": "secret-a"},
        {"client_id": "id-b", "client_secret": "secret-b"},
    ]
    assert [c.headers["Authorization"] for c in fake.graphql_calls] == [
        "Bearer token-1",
        "Bearer token-1",
        "Bearer token-2",
    ]


async def test_headers_mode_without_headers(fake) -> None:
    async with asgi_client(header_server(fake)) as client:
        result = await client.call_tool("xray_get_issue_link_types", {}, raise_on_error=False)
        # Tools that need no Xray call keep working.
        listing = await client.call_tool("xray_list_toolsets", {})
    assert result.is_error
    assert "X-Xray-Client-Id" in result.content[0].text
    assert listing.data["auth_mode"] == "headers"
    assert fake.calls == []


async def test_env_mode_ignores_headers(fake) -> None:
    server = create_server(make_settings(), transport=httpx2.MockTransport(fake.handler))
    async with asgi_client(server, headers=KEY_A) as client:
        await client.call_tool("xray_get_issue_link_types", {})
    assert auth_bodies(fake) == [{"client_id": "id", "client_secret": "secret"}]

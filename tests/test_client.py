# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Authentication, error mapping and the read-only guard of the Xray client."""

import httpx2
import pytest

from tests.conftest import FakeXray, make_settings
from xray_mcp.client import XrayApiError, XrayClient, graphql_operation_types


def client_for(fake: FakeXray, **overrides) -> XrayClient:
    return XrayClient(make_settings(**overrides), transport=httpx2.MockTransport(fake.handler))


async def test_token_is_cached_and_sent(fake) -> None:
    client = client_for(fake)
    await client.graphql("{ getIssueLinkTypes { id } }")
    await client.request("GET", "/import/test/bulk/j1/status")
    assert fake.token_requests == 1
    auth = fake.calls[0]
    assert auth.json == {"client_id": "id", "client_secret": "secret"}
    assert all(c.headers["Authorization"] == "Bearer token-1" for c in fake.calls[1:])
    await client.aclose()


async def test_reauthenticates_once_on_401(fake) -> None:
    rejected: list[str] = []

    def rest(call):
        if call.headers["Authorization"] == "Bearer token-1":
            rejected.append(call.path)
            return httpx2.Response(401, text="expired")
        return None

    fake.rest = rest
    client = client_for(fake)
    assert await client.request("GET", "/backup/j/status") == {"ok": True}
    assert fake.token_requests == 2
    assert rejected == ["/api/v2/backup/j/status"]


async def test_http_errors_become_tool_errors(fake) -> None:
    fake.rest = lambda call: httpx2.Response(400, text="No execution results provided")
    with pytest.raises(XrayApiError, match="HTTP 400.*No execution results"):
        await client_for(fake).request("POST", "/import/execution", json={})


async def test_rate_limit_message(fake) -> None:
    fake.rest = lambda call: httpx2.Response(429, headers={"Retry-After": "30"})
    with pytest.raises(XrayApiError, match="rate limit.*30s"):
        await client_for(fake).request("GET", "/backup/j/status")


async def test_failed_authentication(fake) -> None:
    def handler(request):
        return httpx2.Response(401, text="bad credentials")

    client = XrayClient(make_settings(), transport=httpx2.MockTransport(handler))
    with pytest.raises(XrayApiError, match="authentication failed.*bad credentials"):
        await client.graphql("{ getIssueLinkTypes { id } }")


async def test_missing_credentials(fake) -> None:
    client = client_for(fake, client_id=None, client_secret=None)
    with pytest.raises(XrayApiError, match="XRAY_CLIENT_ID"):
        await client.graphql("{ getIssueLinkTypes { id } }")
    assert fake.calls == []


async def test_read_only_guard_blocks_writes(fake) -> None:
    client = client_for(fake, read_only=True)
    with pytest.raises(XrayApiError, match="read-only"):
        await client.graphql('mutation { deleteTest(issueId: "1") }')
    with pytest.raises(XrayApiError, match="read-only"):
        await client.request("POST", "/import/execution", json={})
    # Queries and GETs still work.
    await client.graphql("{ getIssueLinkTypes { id } }")
    await client.request("GET", "/backup/j/status")


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("{ getTests(limit: 1) { total } }", {"query"}),
        ("query Q($x: Int!) { getTests(limit: $x) { total } }", {"query"}),
        ('mutation { deleteTest(issueId: "1") }', {"mutation"}),
        ("  # comment mentioning mutation\n query { a }", {"query"}),
        ('query { getTests(jql: "mutation {") { total } }', {"query"}),
        ('query { a(s: """mutation { x }""") }', {"query"}),
        ("fragment F on Test { issueId } query { getTest { ...F } }", {"query"}),
        ("query A { a } mutation B { b }", {"query", "mutation"}),
        ("{ mutation { x } }", {"query"}),
        ("subscription { s }", {"subscription"}),
    ],
)
def test_graphql_operation_types(document: str, expected: set[str]) -> None:
    assert graphql_operation_types(document) == expected

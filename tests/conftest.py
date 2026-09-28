# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from typing import Any

import graphql
import httpx2
import pytest
from fastmcp import Client

from xray_mcp.config import Settings
from xray_mcp.server import create_server

_BUILTIN_SCALARS = {"String", "Int", "Float", "Boolean", "ID"}
_BUILTIN_DIRECTIVES = {"@skip", "@include", "@deprecated"}


@cache
def xray_schema() -> graphql.GraphQLSchema:
    """Turn the bundled graphdoc-style schema ('Query getTests { getTests(...): T }') into real SDL."""
    text = files("xray_mcp").joinpath("xray_schema.graphql").read_text(encoding="utf-8")
    queries: list[str] = []
    mutations: list[str] = []
    others: list[str] = []
    for block in re.split(r"\n(?=(?:Query|Mutation|type|input|enum|scalar|interface|union|directive) )", text):
        block = block.strip()
        header = block.split("\n", 1)[0].split()
        if not header or header[0] == "#":
            continue
        kind, name = header[0], header[1]
        if kind in ("Query", "Mutation"):
            body = block.split("\n", 1)[1].rsplit("}", 1)[0]
            (queries if kind == "Query" else mutations).append(body)
        elif (kind == "scalar" and name in _BUILTIN_SCALARS) or (kind == "directive" and name in _BUILTIN_DIRECTIVES):
            continue
        else:
            others.append(block)
    sdl = "type Query {\n" + "\n".join(queries) + "\n}\ntype Mutation {\n" + "\n".join(mutations) + "\n}\n"
    sdl += "\n\n".join(others)
    # graphdoc numbers comment lines inside input types ("2#   Id of ..."); make them plain comments.
    return graphql.build_schema(re.sub(r"^\s*\d+#", " #", sdl, flags=re.M))


def assert_valid_graphql(query: str, variables: dict[str, Any] | None) -> None:
    """Validate document and variables against the Xray schema (execution errors are ignored)."""
    result = graphql.graphql_sync(xray_schema(), query, variable_values=variables or {})
    # Validation and variable-coercion errors have no path; execution errors (null resolvers) do.
    static_errors = [e for e in result.errors or [] if e.path is None]
    assert not static_errors, f"Invalid GraphQL: {static_errors}\n{query}\nvariables={variables}"


def fake_issue_id(key: str) -> str:
    """Deterministic id for a key: CALC-12 -> '1000012'."""
    return str(1_000_000 + int(key.rsplit("-", 1)[1]))


@dataclass
class Call:
    method: str
    path: str
    params: dict[str, str]
    headers: httpx2.Headers
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class FakeXray:
    """Stands in for xray.cloud.getxray.app: records calls and validates GraphQL."""

    calls: list[Call] = field(default_factory=list)
    # Test hooks: return a response for a request, or None to fall back to the defaults.
    rest: Callable[[Call], httpx2.Response | None] | None = None
    graphql_data: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None
    graphql_response: Callable[[str, dict[str, Any]], httpx2.Response | None] | None = None
    token_requests: int = 0

    @property
    def graphql_calls(self) -> list[Call]:
        return [c for c in self.calls if c.path == "/api/v2/graphql"]

    @property
    def rest_calls(self) -> list[Call]:
        return [c for c in self.calls if c.path not in ("/api/v2/graphql", "/api/v2/authenticate")]

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        call = Call(
            method=request.method,
            path=request.url.path,
            params=dict(request.url.params),
            headers=request.headers,
            body=request.read(),
        )
        self.calls.append(call)
        if call.path == "/api/v2/authenticate":
            self.token_requests += 1
            return httpx2.Response(200, json=f"token-{self.token_requests}")
        if call.path == "/api/v2/graphql":
            payload = call.json
            query, variables = payload["query"], payload.get("variables") or {}
            assert_valid_graphql(query, variables)
            if self.graphql_response and (resp := self.graphql_response(query, variables)) is not None:
                return resp
            data = self.graphql_data(query, variables) if self.graphql_data else None
            return httpx2.Response(200, json={"data": data if data is not None else self._default_data(query, variables)})
        if self.rest:
            resp = self.rest(call)
            if resp is not None:
                return resp
        return httpx2.Response(200, json={"ok": True})

    @staticmethod
    def _default_data(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        jql = variables.get("jql", "")
        match = re.match(r"^\s*(\w+)\(jql", query.split("{", 1)[1]) if "{" in query else None
        if isinstance(jql, str) and jql.startswith("key in (") and match:
            keys = re.findall(r'"([^"]+)"', jql)
            op = match.group(1)
            return {op: {"results": [{"issueId": fake_issue_id(k), "jira": {"key": k}} for k in keys]}}
        if "getProjectSettings(" in query:
            return {"getProjectSettings": {"projectId": "10000"}}
        return {}


@pytest.fixture
def fake() -> FakeXray:
    return FakeXray()


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"client_id": "id", "client_secret": "secret", "toolsets": "all", **overrides}
    return Settings(**values)


@pytest.fixture
def connect(fake: FakeXray):
    """``async with connect(**settings) as client`` – an MCP client on a server wired to the fake."""

    def _connect(**overrides: Any) -> Client:
        server = create_server(make_settings(**overrides), transport=httpx2.MockTransport(fake.handler))
        return Client(server)

    return _connect

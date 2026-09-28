# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Raw GraphQL access, for everything the dedicated tools do not cover."""

import difflib
import re
from functools import cache
from importlib.resources import files
from typing import Annotated, Any

from pydantic import Field

from xray_mcp.client import XrayClient, graphql_operation_types
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import XRAY

toolset = Toolset(
    "graphql",
    "Raw Xray GraphQL queries and mutations, plus a schema lookup to write them.",
)

Variables = Annotated[dict[str, Any] | None, Field(description="GraphQL variables.")]


@cache
def _schema_blocks() -> dict[str, str]:
    """Definitions of the bundled schema by name. Operations are keyed 'Query.x' / 'Mutation.x'."""
    text = files("xray_mcp").joinpath("xray_schema.graphql").read_text(encoding="utf-8")
    blocks: dict[str, str] = {}
    for block in re.split(r"\n(?=(?:Query|Mutation|type|input|enum|scalar|interface|union|directive) )", text):
        header = block.split("\n", 1)[0].split()
        if len(header) < 2 or header[0] == "#":
            continue
        kind, name = header[0], header[1].lstrip("@")
        key = f"{kind}.{name}" if kind in ("Query", "Mutation") else name
        blocks[key] = block.strip()
    return blocks


@toolset.tool(read_only=True)
async def xray_graphql_schema(
    names: Annotated[
        list[str] | None,
        Field(
            description=(
                "Operation or type names, e.g. ['getTests', 'TestResults', 'createTest']. "
                "Omit to list all queries and mutations."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Look up the Xray GraphQL schema: signatures and field docs of queries, mutations and types."""
    blocks = _schema_blocks()
    if not names:
        return {
            "queries": sorted(k.split(".", 1)[1] for k in blocks if k.startswith("Query.")),
            "mutations": sorted(k.split(".", 1)[1] for k in blocks if k.startswith("Mutation.")),
        }
    found: dict[str, str] = {}
    missing: dict[str, list[str]] = {}
    for name in names:
        key = next((k for k in (name, f"Query.{name}", f"Mutation.{name}") if k in blocks), None)
        if key:
            found[name] = blocks[key]
        else:
            plain = [k.split(".", 1)[-1] for k in blocks]
            missing[name] = difflib.get_close_matches(name, plain, n=5)
    return {"definitions": found, **({"not_found_did_you_mean": missing} if missing else {})}


@toolset.tool(read_only=True)
async def xray_graphql_query(
    query: Annotated[str, Field(description="GraphQL query document (no mutations).")],
    variables: Variables = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Run a read-only Xray GraphQL query. Entities are addressed by issue id; every list needs limit (max 100)."""
    if graphql_operation_types(query) - {"query"}:
        raise ValueError("Only queries are allowed here; use xray_graphql_mutation for mutations.")
    return {"data": await client.graphql(query, variables)}


@toolset.tool(read_only=False)
async def xray_graphql_mutation(
    mutation: Annotated[str, Field(description="GraphQL mutation document.")],
    variables: Variables = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Run an Xray GraphQL mutation not covered by a dedicated tool."""
    return {"data": await client.graphql(mutation, variables)}

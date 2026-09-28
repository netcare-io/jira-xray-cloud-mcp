# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Change history of Xray issues."""

from typing import Annotated, Any, Literal

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import XRAY, IssueRef, Limit, Start, resolve_id

toolset = Toolset("history", "Change history of Tests, Preconditions, Test Sets, Test Plans and Test Executions.")

_GET_QUERY = {
    "test": "getTest",
    "precondition": "getPrecondition",
    "test_set": "getTestSet",
    "test_plan": "getTestPlan",
    "test_execution": "getTestExecution",
}


@toolset.tool(read_only=True)
async def xray_get_issue_history(
    issue: IssueRef,
    issue_type: Annotated[
        Literal["test", "precondition", "test_set", "test_plan", "test_execution"],
        Field(description="Xray issue type of the issue."),
    ],
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get the Xray change history of an issue: who changed what (steps, definition, links...) and when (paginated)."""
    op = _GET_QUERY[issue_type]
    data = await client.graphql(
        f"query($id: String, $limit: Int!, $start: Int) {{ {op}(issueId: $id) {{"
        " history(limit: $limit, start: $start) {"
        " total start limit results { version user date action changes { field change } } } } }",
        {"id": await resolve_id(client, issue_type, issue), "limit": limit, "start": start},
    )
    return (data.get(op) or {}).get("history") or {}

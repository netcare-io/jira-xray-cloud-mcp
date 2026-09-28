# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Xray configuration: statuses, link types, project settings, step libraries."""

from typing import Annotated, Any, Literal

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import XRAY, Limit, Start, compact, resolve_id, resolve_project_id

toolset = Toolset(
    "settings", "Xray configuration: test/step statuses, issue link types, project settings, step libraries."
)

OptionalProject = Annotated[
    str | None, Field(description="Jira project key or id; omit for the global configuration.")
]


@toolset.tool(read_only=True)
async def xray_get_statuses(project: OptionalProject = None, client: XrayClient = XRAY) -> dict[str, Any]:
    """List the test run statuses and step statuses available (globally or for a project)."""
    project_id = await resolve_project_id(client, project) if project else None
    data = await client.graphql(
        "query($p: String) {"
        " getStatuses(projectId: $p) { name description final color coverageStatus }"
        " getStepStatuses(projectId: $p) { name description color testStatus { name } } }",
        compact(p=project_id),
    )
    return {"test_statuses": data.get("getStatuses"), "step_statuses": data.get("getStepStatuses")}


@toolset.tool(read_only=True)
async def xray_get_issue_link_types(client: XrayClient = XRAY) -> dict[str, Any]:
    """List the Jira issue link types known to Xray (used for requirement coverage)."""
    data = await client.graphql("{ getIssueLinkTypes { id name } }")
    return {"issue_link_types": data.get("getIssueLinkTypes")}


@toolset.tool(read_only=True)
async def xray_get_project_settings(
    projects: Annotated[list[str], Field(description="Jira project keys or ids.")],
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get Xray project settings: test types, test environments, coverage, step fields, test run custom fields."""
    data = await client.graphql(
        "query($p: [String], $limit: Int!) { getProjectsSettings(projectIdsOrKeys: $p, limit: $limit) {"
        " total warnings results { projectId testEnvironments defectIssueTypes"
        " testTypeSettings { defaultTestTypeId testTypes { id name kind } }"
        " testCoverageSettings { coverableIssueTypeIds epicIssuesRelation issueSubTasksRelation"
        " issueLinkTypeId issueLinkTypeDirection }"
        " testStepSettings { fields { id name type required disabled values } }"
        " testRunCustomFieldSettings { fields { id name type required values } } } } }",
        {"p": projects, "limit": min(max(len(projects), 1), 100)},
    )
    return data.get("getProjectsSettings") or {}


@toolset.tool(read_only=True)
async def xray_get_step_library(
    kind: Annotated[
        Literal["manual", "bdd"], Field(description="'manual' step library or 'bdd' (Gherkin) step library.")
    ] = "manual",
    project: OptionalProject = None,
    search: Annotated[str | None, Field(description="Full-text search on the steps.")] = None,
    test: Annotated[str | None, Field(description="Only steps used by this Test (key or id).")] = None,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search the reusable manual or BDD (Gherkin) step library."""
    op, selection = (
        ("getManualStepLibrary", "id projectId action data result description labels associatedTests dateModified")
        if kind == "manual"
        else ("getBDDStepLibrary", "id definition description labels associatedTests lastModified library { id name }")
    )
    data = await client.graphql(
        "query($p: String, $s: String, $t: String, $limit: Int!, $start: Int) {"
        f" {op}(projectId: $p, search: $s, testIssueId: $t, limit: $limit, start: $start) {{"
        f" total start limit results {{ {selection} }} }} }}",
        compact(
            p=await resolve_project_id(client, project) if project else None,
            s=search,
            t=await resolve_id(client, "test", test) if test else None,
            limit=limit,
            start=start,
        ),
    )
    return data.get(op) or {}

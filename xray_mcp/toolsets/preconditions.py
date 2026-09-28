# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Precondition issues."""

from typing import Annotated, Any

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import (
    ISSUE_SUMMARY,
    XRAY,
    ExtraJiraFields,
    IssueRef,
    IssueRefs,
    JiraFields,
    Limit,
    ModifiedSince,
    Start,
    change_tests,
    compact,
    delete_issue,
    jira_fields,
    jira_payload,
    related,
    resolve_id,
    resolve_ids,
    search_issues,
)

toolset = Toolset("preconditions", "Precondition issues and their linked Tests.")

PRECONDITION = f"{ISSUE_SUMMARY} preconditionType {{ name kind }} definition folder {{ path }}"
PreconditionType = Annotated[
    str | None, Field(description="Precondition type name, e.g. 'Manual', 'Cucumber', 'Generic'.")
]


@toolset.tool(read_only=True)
async def xray_get_precondition(
    precondition: IssueRef, fields: JiraFields = None, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Get a Precondition with its type, definition, folder and the Tests it is linked to."""
    data = await client.graphql(
        "query($id: String, $jiraFields: [String]) {"
        f" getPrecondition(issueId: $id) {{ {PRECONDITION} {related('tests')} }} }}",
        {"id": await resolve_id(client, "precondition", precondition), "jiraFields": jira_fields(fields)},
    )
    return {"precondition": data.get("getPrecondition")}


@toolset.tool(read_only=True)
async def xray_get_preconditions(
    jql: Annotated[str | None, Field(description="JQL filter.")] = None,
    preconditions: Annotated[list[str] | None, Field(description="Restrict to these keys or ids.")] = None,
    project: Annotated[str | None, Field(description="Jira project key or id.")] = None,
    precondition_type: PreconditionType = None,
    modified_since: ModifiedSince = None,
    fields: JiraFields = None,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search Preconditions by JQL, keys, project or type (paginated)."""
    return await search_issues(
        client,
        "getPreconditions",
        PRECONDITION,
        kind="precondition",
        jql=jql,
        issues=preconditions,
        project=project,
        modified_since=modified_since,
        limit=limit,
        start=start,
        fields=fields,
        extra_args={
            "preconditionType": ("TestTypeInput", {"name": precondition_type} if precondition_type else None)
        },
    )


@toolset.tool(read_only=False)
async def xray_create_precondition(
    project: Annotated[str, Field(description="Jira project key or id.")],
    summary: str,
    precondition_type: PreconditionType = "Manual",
    definition: Annotated[str | None, Field(description="Precondition text / Gherkin background.")] = None,
    tests: Annotated[list[str] | None, Field(description="Test keys or ids to link.")] = None,
    folder_path: Annotated[str | None, Field(description="Test Repository folder, e.g. '/Setup'.")] = None,
    extra_fields: ExtraJiraFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Create a Precondition issue, optionally linked to Tests."""
    data = await client.graphql(
        "mutation($type: UpdatePreconditionTypeInput, $definition: String, $tests: [String],"
        " $folderPath: String, $jira: JSON!) {"
        " createPrecondition(preconditionType: $type, definition: $definition, testIssueIds: $tests,"
        ' folderPath: $folderPath, jira: $jira) { warnings precondition { issueId jira(fields: ["key", "summary"]) } } }',
        compact(
            type={"name": precondition_type} if precondition_type else None,
            definition=definition,
            tests=await resolve_ids(client, "test", tests),
            folderPath=folder_path,
            jira=jira_payload(project, summary, extra_fields),
        ),
    )
    return data.get("createPrecondition") or {}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_precondition(
    precondition: IssueRef,
    precondition_type: PreconditionType = None,
    definition: str | None = None,
    folder_path: Annotated[str | None, Field(description="Move to this Test Repository folder.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Update type, definition and/or folder of a Precondition."""
    update = compact(
        preconditionType={"name": precondition_type} if precondition_type else None,
        definition=definition,
        folderPath=folder_path,
    )
    if not update:
        raise ValueError("Pass at least one of precondition_type, definition, folder_path.")
    data = await client.graphql(
        "mutation($id: String!, $data: UpdatePreconditionInput) { updatePrecondition(issueId: $id, data: $data) {"
        " issueId preconditionType { name kind } definition folder { path } } }",
        {"id": await resolve_id(client, "precondition", precondition), "data": update},
    )
    return {"precondition": data.get("updatePrecondition")}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_delete_precondition(precondition: IssueRef, client: XrayClient = XRAY) -> dict[str, Any]:
    """Delete a Precondition issue permanently."""
    return await delete_issue(client, "deletePrecondition", "precondition", precondition)


@toolset.tool(read_only=False, idempotent=True)
async def xray_add_tests_to_precondition(
    precondition: IssueRef, tests: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Link Tests to a Precondition."""
    return await change_tests(client, "addTestsToPrecondition", "precondition", precondition, tests, add=True)


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_tests_from_precondition(
    precondition: IssueRef, tests: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Unlink Tests from a Precondition."""
    return await change_tests(client, "removeTestsFromPrecondition", "precondition", precondition, tests, add=False)

# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Test Set issues."""

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

toolset = Toolset("test_sets", "Test Set issues and their Tests.")


@toolset.tool(read_only=True)
async def xray_get_test_set(test_set: IssueRef, fields: JiraFields = None, client: XrayClient = XRAY) -> dict[str, Any]:
    """Get a Test Set with the Tests it contains."""
    data = await client.graphql(
        "query($id: String, $jiraFields: [String]) {"
        f" getTestSet(issueId: $id) {{ {ISSUE_SUMMARY} {related('tests')} }} }}",
        {"id": await resolve_id(client, "test_set", test_set), "jiraFields": jira_fields(fields)},
    )
    return {"test_set": data.get("getTestSet")}


@toolset.tool(read_only=True)
async def xray_get_test_sets(
    jql: Annotated[str | None, Field(description="JQL filter.")] = None,
    test_sets: Annotated[list[str] | None, Field(description="Restrict to these keys or ids.")] = None,
    project: Annotated[str | None, Field(description="Jira project key or id.")] = None,
    modified_since: ModifiedSince = None,
    fields: JiraFields = None,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search Test Sets by JQL, keys or project (paginated)."""
    return await search_issues(
        client,
        "getTestSets",
        ISSUE_SUMMARY + " tests(limit: 1) { total }",
        kind="test_set",
        jql=jql,
        issues=test_sets,
        project=project,
        modified_since=modified_since,
        limit=limit,
        start=start,
        fields=fields,
    )


@toolset.tool(read_only=False)
async def xray_create_test_set(
    project: Annotated[str, Field(description="Jira project key or id.")],
    summary: str,
    tests: Annotated[list[str] | None, Field(description="Test keys or ids to add.")] = None,
    extra_fields: ExtraJiraFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Create a Test Set issue, optionally with Tests."""
    data = await client.graphql(
        "mutation($tests: [String], $jira: JSON!) { createTestSet(testIssueIds: $tests, jira: $jira) {"
        ' warnings testSet { issueId jira(fields: ["key", "summary"]) } } }',
        compact(tests=await resolve_ids(client, "test", tests), jira=jira_payload(project, summary, extra_fields)),
    )
    return data.get("createTestSet") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_delete_test_set(test_set: IssueRef, client: XrayClient = XRAY) -> dict[str, Any]:
    """Delete a Test Set issue permanently (the Tests are kept)."""
    return await delete_issue(client, "deleteTestSet", "test_set", test_set)


@toolset.tool(read_only=False, idempotent=True)
async def xray_add_tests_to_test_set(test_set: IssueRef, tests: IssueRefs, client: XrayClient = XRAY) -> dict[str, Any]:
    """Add Tests to a Test Set."""
    return await change_tests(client, "addTestsToTestSet", "test_set", test_set, tests, add=True)


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_tests_from_test_set(
    test_set: IssueRef, tests: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Remove Tests from a Test Set."""
    return await change_tests(client, "removeTestsFromTestSet", "test_set", test_set, tests, add=False)

# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Test Plan issues."""

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

toolset = Toolset("test_plans", "Test Plan issues, their Tests and Test Executions.")


@toolset.tool(read_only=True)
async def xray_get_test_plan(
    test_plan: IssueRef,
    fields: JiraFields = None,
    include_test_status: Annotated[
        bool, Field(description="Include each Test's consolidated status within this plan.")
    ] = False,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get a Test Plan with its Tests, Test Executions and folder structure."""
    issue_id = await resolve_id(client, "test_plan", test_plan)
    tests = related("tests")
    if include_test_status:
        tests = (
            'tests(limit: 100) { total results { issueId jira(fields: ["key", "summary"])'
            " status(testPlan: $id) { name color final } } }"
        )
    data = await client.graphql(
        "query($id: String, $jiraFields: [String]) {"
        f" getTestPlan(issueId: $id) {{ {ISSUE_SUMMARY} {tests} {related('testExecutions')}"
        " folders { name path testsCount folders } } }",
        {"id": issue_id, "jiraFields": jira_fields(fields)},
    )
    return {"test_plan": data.get("getTestPlan")}


@toolset.tool(read_only=True)
async def xray_get_test_plans(
    jql: Annotated[str | None, Field(description="JQL filter.")] = None,
    test_plans: Annotated[list[str] | None, Field(description="Restrict to these keys or ids.")] = None,
    project: Annotated[str | None, Field(description="Jira project key or id.")] = None,
    modified_since: ModifiedSince = None,
    fields: JiraFields = None,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search Test Plans by JQL, keys or project (paginated)."""
    return await search_issues(
        client,
        "getTestPlans",
        ISSUE_SUMMARY + " tests(limit: 1) { total } testExecutions(limit: 1) { total }",
        kind="test_plan",
        jql=jql,
        issues=test_plans,
        project=project,
        modified_since=modified_since,
        limit=limit,
        start=start,
        fields=fields,
    )


@toolset.tool(read_only=False)
async def xray_create_test_plan(
    project: Annotated[str, Field(description="Jira project key or id.")],
    summary: str,
    tests: Annotated[list[str] | None, Field(description="Test keys or ids to add.")] = None,
    saved_filter: Annotated[
        str | None, Field(description="Jira filter id whose Tests are added to the plan.")
    ] = None,
    extra_fields: ExtraJiraFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Create a Test Plan issue, optionally with Tests (e.g. fixVersions via extra_fields)."""
    data = await client.graphql(
        "mutation($filter: String, $tests: [String], $jira: JSON!) {"
        " createTestPlan(savedFilter: $filter, testIssueIds: $tests, jira: $jira) {"
        ' warnings testPlan { issueId jira(fields: ["key", "summary"]) } } }',
        compact(
            filter=saved_filter,
            tests=await resolve_ids(client, "test", tests),
            jira=jira_payload(project, summary, extra_fields),
        ),
    )
    return data.get("createTestPlan") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_delete_test_plan(test_plan: IssueRef, client: XrayClient = XRAY) -> dict[str, Any]:
    """Delete a Test Plan issue permanently."""
    return await delete_issue(client, "deleteTestPlan", "test_plan", test_plan)


@toolset.tool(read_only=False, idempotent=True)
async def xray_add_tests_to_test_plan(
    test_plan: IssueRef, tests: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Add Tests to a Test Plan."""
    return await change_tests(client, "addTestsToTestPlan", "test_plan", test_plan, tests, add=True)


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_tests_from_test_plan(
    test_plan: IssueRef, tests: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Remove Tests from a Test Plan."""
    return await change_tests(client, "removeTestsFromTestPlan", "test_plan", test_plan, tests, add=False)


async def _change_executions(
    client: XrayClient, op: str, test_plan: str, executions: list[str], *, add: bool
) -> dict[str, Any]:
    selection = " { addedTestExecutions warning }" if add else ""
    data = await client.graphql(
        f"mutation($id: String!, $ids: [String]!) {{ {op}(issueId: $id, testExecIssueIds: $ids){selection} }}",
        {
            "id": await resolve_id(client, "test_plan", test_plan),
            "ids": await resolve_ids(client, "test_execution", executions),
        },
    )
    result = data.get(op)
    return result if isinstance(result, dict) else {"result": result}


@toolset.tool(read_only=False, idempotent=True)
async def xray_add_test_executions_to_test_plan(
    test_plan: IssueRef, test_executions: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Associate Test Executions with a Test Plan."""
    return await _change_executions(client, "addTestExecutionsToTestPlan", test_plan, test_executions, add=True)


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_test_executions_from_test_plan(
    test_plan: IssueRef, test_executions: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Remove Test Executions from a Test Plan."""
    return await _change_executions(
        client, "removeTestExecutionsFromTestPlan", test_plan, test_executions, add=False
    )

# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Test Execution issues."""

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

toolset = Toolset(
    "test_executions", "Test Execution issues, their Tests and Test Environments."
)

Environments = Annotated[list[str], Field(description="Test Environment names, e.g. ['Chrome', 'staging'].")]


@toolset.tool(read_only=True)
async def xray_get_test_execution(
    test_execution: IssueRef,
    fields: JiraFields = None,
    runs_limit: Annotated[int, Field(ge=1, le=100, description="Max test runs to include.")] = 100,
    runs_start: Annotated[int, Field(ge=0, description="Offset into the test runs.")] = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get a Test Execution with environments, Test Plans and its test runs (test + status)."""
    data = await client.graphql(
        "query($id: String, $jiraFields: [String], $limit: Int!, $start: Int) {"
        f" getTestExecution(issueId: $id) {{ {ISSUE_SUMMARY} testEnvironments {related('testPlans')}"
        " testRuns(limit: $limit, start: $start) { total start limit results {"
        ' id status { name color } assigneeId executedById startedOn finishedOn defects'
        ' test { issueId jira(fields: ["key", "summary"]) } } } } }',
        {
            "id": await resolve_id(client, "test_execution", test_execution),
            "jiraFields": jira_fields(fields),
            "limit": runs_limit,
            "start": runs_start,
        },
    )
    return {"test_execution": data.get("getTestExecution")}


@toolset.tool(read_only=True)
async def xray_get_test_executions(
    jql: Annotated[str | None, Field(description="JQL filter.")] = None,
    test_executions: Annotated[list[str] | None, Field(description="Restrict to these keys or ids.")] = None,
    project: Annotated[str | None, Field(description="Jira project key or id.")] = None,
    modified_since: ModifiedSince = None,
    fields: JiraFields = None,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search Test Executions by JQL, keys or project (paginated)."""
    return await search_issues(
        client,
        "getTestExecutions",
        ISSUE_SUMMARY + " testEnvironments tests(limit: 1) { total }",
        kind="test_execution",
        jql=jql,
        issues=test_executions,
        project=project,
        modified_since=modified_since,
        limit=limit,
        start=start,
        fields=fields,
    )


@toolset.tool(read_only=False)
async def xray_create_test_execution(
    project: Annotated[str, Field(description="Jira project key or id.")],
    summary: str,
    tests: Annotated[list[str] | None, Field(description="Test keys or ids to run.")] = None,
    test_environments: Annotated[list[str] | None, Field(description="Test Environment names.")] = None,
    extra_fields: ExtraJiraFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Create a Test Execution issue with Tests (one test run per Test). Link it to a plan via the test_plans tools."""
    data = await client.graphql(
        "mutation($tests: [String], $envs: [String], $jira: JSON!) {"
        " createTestExecution(testIssueIds: $tests, testEnvironments: $envs, jira: $jira) {"
        ' warnings createdTestEnvironments testExecution { issueId jira(fields: ["key", "summary"]) } } }',
        compact(
            tests=await resolve_ids(client, "test", tests),
            envs=test_environments,
            jira=jira_payload(project, summary, extra_fields),
        ),
    )
    return data.get("createTestExecution") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_delete_test_execution(test_execution: IssueRef, client: XrayClient = XRAY) -> dict[str, Any]:
    """Delete a Test Execution issue permanently, including its test runs."""
    return await delete_issue(client, "deleteTestExecution", "test_execution", test_execution)


@toolset.tool(read_only=False, idempotent=True)
async def xray_add_tests_to_test_execution(
    test_execution: IssueRef, tests: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Add Tests to a Test Execution (creates a test run per Test)."""
    return await change_tests(client, "addTestsToTestExecution", "test_execution", test_execution, tests, add=True)


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_tests_from_test_execution(
    test_execution: IssueRef, tests: IssueRefs, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Remove Tests from a Test Execution, deleting their test runs."""
    return await change_tests(
        client, "removeTestsFromTestExecution", "test_execution", test_execution, tests, add=False
    )


@toolset.tool(read_only=False, idempotent=True)
async def xray_add_test_environments(
    test_execution: IssueRef, test_environments: Environments, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Add Test Environments to a Test Execution; unknown environments are created."""
    data = await client.graphql(
        "mutation($id: String!, $envs: [String]!) {"
        " addTestEnvironmentsToTestExecution(issueId: $id, testEnvironments: $envs) {"
        " associatedTestEnvironments createdTestEnvironments warning } }",
        {"id": await resolve_id(client, "test_execution", test_execution), "envs": test_environments},
    )
    return data.get("addTestEnvironmentsToTestExecution") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_test_environments(
    test_execution: IssueRef, test_environments: Environments, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Remove Test Environments from a Test Execution."""
    data = await client.graphql(
        "mutation($id: String!, $envs: [String]!) {"
        " removeTestEnvironmentsFromTestExecution(issueId: $id, testEnvironments: $envs) }",
        {"id": await resolve_id(client, "test_execution", test_execution), "envs": test_environments},
    )
    return {"result": data.get("removeTestEnvironmentsFromTestExecution")}

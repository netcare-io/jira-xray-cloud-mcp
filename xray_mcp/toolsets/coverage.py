# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Requirement coverage: coverable issues (stories, requirements) and their Tests."""

from typing import Annotated, Any

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import (
    XRAY,
    IssueRef,
    JiraFields,
    Limit,
    Start,
    compact,
    jira_fields,
    related,
    resolve_id,
    resolve_ids,
)

toolset = Toolset("coverage", "Requirement coverage: coverable issues, their covering Tests and coverage status.")

Environment = Annotated[str | None, Field(description="Calculate coverage for this Test Environment.")]
Version = Annotated[str | None, Field(description="Calculate coverage for this version name.")]
TestPlan = Annotated[str | None, Field(description="Calculate coverage within this Test Plan (key or id).")]
IsFinal = Annotated[bool | None, Field(description="Whether final statuses take precedence.")]

COVERABLE = (
    "issueId jira(fields: $jiraFields)"
    " status(environment: $env, isFinal: $isFinal, version: $version, testPlan: $testPlan) { name description color }"
)
STATUS_VARS = "$env: String, $isFinal: Boolean, $version: String, $testPlan: String, $jiraFields: [String]"


async def _status_vars(
    client: XrayClient, env: str | None, is_final: bool | None, version: str | None, test_plan: str | None, fields: list[str] | None
) -> dict[str, Any]:
    return compact(
        env=env,
        isFinal=is_final,
        version=version,
        testPlan=await resolve_id(client, "test_plan", test_plan) if test_plan else None,
        jiraFields=jira_fields(fields),
    )


@toolset.tool(read_only=True)
async def xray_get_coverable_issue(
    issue: IssueRef,
    environment: Environment = None,
    version: Version = None,
    test_plan: TestPlan = None,
    is_final: IsFinal = None,
    fields: JiraFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get the coverage status of a requirement / story and the Tests covering it."""
    variables = await _status_vars(client, environment, is_final, version, test_plan, fields)
    data = await client.graphql(
        f"query($id: String!, {STATUS_VARS}) {{ getCoverableIssue(issueId: $id) {{ {COVERABLE} {related('tests')} }} }}",
        {"id": await resolve_id(client, "coverable", issue), **variables},
    )
    return {"coverable_issue": data.get("getCoverableIssue")}


@toolset.tool(read_only=True)
async def xray_get_coverable_issues(
    jql: Annotated[str | None, Field(description="JQL filter, e.g. 'project = CALC AND issuetype = Story'.")] = None,
    issues: Annotated[list[str] | None, Field(description="Restrict to these issue keys or ids.")] = None,
    environment: Environment = None,
    version: Version = None,
    test_plan: TestPlan = None,
    is_final: IsFinal = None,
    fields: JiraFields = None,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search coverable issues (requirements, stories...) with their coverage status (paginated)."""
    variables = await _status_vars(client, environment, is_final, version, test_plan, fields)
    data = await client.graphql(
        f"query($jql: String, $ids: [String], $limit: Int!, $start: Int, {STATUS_VARS}) {{"
        " getCoverableIssues(jql: $jql, issueIds: $ids, limit: $limit, start: $start) {"
        f" total start limit warnings results {{ {COVERABLE} tests(limit: 1) {{ total }} }} }} }}",
        compact(
            jql=jql,
            ids=await resolve_ids(client, "coverable", issues),
            limit=limit,
            start=start,
            **variables,
        ),
    )
    return data.get("getCoverableIssues") or {}

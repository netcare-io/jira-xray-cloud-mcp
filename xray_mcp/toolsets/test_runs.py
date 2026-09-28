# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Test runs: execution results of a Test within a Test Execution."""

from typing import Annotated, Any

from pydantic import BaseModel, Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import (
    TEST_RUN_DETAIL,
    TEST_RUN_SUMMARY,
    XRAY,
    AttachmentData,
    Limit,
    ModifiedSince,
    Start,
    compact,
    resolve_id,
    resolve_ids,
)

toolset = Toolset(
    "test_runs", "Test run results: status, comments, defects, evidence, step results and progress."
)

TestRunId = Annotated[str, Field(description="Test run id, from xray_get_test_execution or xray_get_test_runs.")]
StepId = Annotated[str, Field(description="Step id of the test run step, from xray_get_test_run.")]
IterationRank = Annotated[
    str | None, Field(description="Iteration rank for data-driven runs, from xray_get_test_run.")
]
Status = Annotated[
    str, Field(description="Status name as configured in Xray, e.g. 'PASSED', 'FAILED', 'TODO', 'EXECUTING'.")
]


class CustomFieldValue(BaseModel):
    id: str = Field(description="Test run custom field id.")
    value: Any = Field(description="New value.")


@toolset.tool(read_only=True)
async def xray_get_test_run(
    test_run_id: Annotated[str | None, Field(description="Test run id.")] = None,
    test: Annotated[str | None, Field(description="Test key or id (with test_execution).")] = None,
    test_execution: Annotated[str | None, Field(description="Test Execution key or id (with test).")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get one test run in full detail (steps, evidence, defects, examples, iterations), by id or by Test + Test Execution."""
    if test_run_id:
        data = await client.graphql(
            f"query($id: String) {{ getTestRunById(id: $id) {{ {TEST_RUN_DETAIL} }} }}", {"id": test_run_id}
        )
        return {"test_run": data.get("getTestRunById")}
    if not (test and test_execution):
        raise ValueError("Pass test_run_id, or both test and test_execution.")
    data = await client.graphql(
        f"query($t: String, $e: String) {{ getTestRun(testIssueId: $t, testExecIssueId: $e) {{ {TEST_RUN_DETAIL} }} }}",
        {
            "t": await resolve_id(client, "test", test),
            "e": await resolve_id(client, "test_execution", test_execution),
        },
    )
    return {"test_run": data.get("getTestRun")}


@toolset.tool(read_only=True)
async def xray_get_test_runs(
    test_run_ids: Annotated[list[str] | None, Field(description="Fetch exactly these test run ids.")] = None,
    tests: Annotated[list[str] | None, Field(description="Filter by Test keys or ids.")] = None,
    test_executions: Annotated[list[str] | None, Field(description="Filter by Test Execution keys or ids.")] = None,
    test_plans: Annotated[list[str] | None, Field(description="Filter by Test Plan keys or ids.")] = None,
    assignees: Annotated[list[str] | None, Field(description="Filter by assignee Atlassian account ids.")] = None,
    statuses: Annotated[list[str] | None, Field(description="Filter by status names, e.g. ['FAILED'].")] = None,
    modified_since: ModifiedSince = None,
    include_steps: Annotated[bool, Field(description="Include step results and evidence.")] = False,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search test runs by Tests, Test Executions, Test Plans, assignees or statuses (paginated)."""
    selection = TEST_RUN_DETAIL if include_steps else TEST_RUN_SUMMARY
    if test_run_ids:
        data = await client.graphql(
            "query($ids: [String], $limit: Int!, $start: Int) {"
            f" getTestRunsById(ids: $ids, limit: $limit, start: $start) {{ total start limit results {{ {selection} }} }} }}",
            {"ids": test_run_ids, "limit": limit, "start": start},
        )
        return data.get("getTestRunsById") or {}
    if not any((tests, test_executions, test_plans, assignees, statuses)):
        raise ValueError("Pass test_run_ids or at least one filter (tests, test_executions, test_plans, ...).")
    data = await client.graphql(
        "query($tests: [String], $execs: [String], $assignees: [String], $statuses: [String], $plans: [String],"
        " $limit: Int!, $start: Int, $modifiedSince: String) {"
        " getTestRuns(testIssueIds: $tests, testExecIssueIds: $execs, testRunAssignees: $assignees,"
        " statuses: $statuses, testPlanIssueIds: $plans, limit: $limit, start: $start, modifiedSince: $modifiedSince)"
        f" {{ total start limit results {{ {selection} }} }} }}",
        compact(
            tests=await resolve_ids(client, "test", tests),
            execs=await resolve_ids(client, "test_execution", test_executions),
            plans=await resolve_ids(client, "test_plan", test_plans),
            assignees=assignees,
            statuses=statuses,
            limit=limit,
            start=start,
            modifiedSince=modified_since,
        ),
    )
    return data.get("getTestRuns") or {}


@toolset.tool(read_only=True)
async def xray_get_test_progress(
    test_plan: Annotated[
        str | None, Field(description="Test Plan key or id: counts each Test's consolidated status in the plan.")
    ] = None,
    test_execution: Annotated[
        str | None, Field(description="Test Execution key or id: counts its test runs by status.")
    ] = None,
    environment: Annotated[str | None, Field(description="With test_plan: status in this Test Environment.")] = None,
    list_statuses: Annotated[
        list[str] | None, Field(description="List the Tests with these statuses (up to 100). Default: ['FAILED'].")
    ] = None,
    max_tests: Annotated[
        int, Field(ge=1, le=10000, description="Stop counting after this many Tests (one API call per 100).")
    ] = 1000,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Count the Tests of a Test Plan or Test Execution per status, e.g. to answer 'how far along is it?'."""
    if (test_plan is None) == (test_execution is None):
        raise ValueError("Pass exactly one of test_plan or test_execution.")
    if test_plan:
        op, connection = "getTestPlan", "tests"
        query = (
            "query($id: String, $limit: Int!, $start: Int, $env: String) { getTestPlan(issueId: $id) {"
            ' tests(limit: $limit, start: $start) { total results { jira(fields: ["key"])'
            " status(testPlan: $id, environment: $env) { name final } } } } }"
        )
        variables = compact(id=await resolve_id(client, "test_plan", test_plan), env=environment)
    else:
        if environment:
            raise ValueError("environment only applies to test_plan.")
        op, connection = "getTestExecution", "testRuns"
        query = (
            "query($id: String, $limit: Int!, $start: Int) { getTestExecution(issueId: $id) {"
            " testRuns(limit: $limit, start: $start) { total results { status { name final }"
            ' test { jira(fields: ["key"]) } } } } }'
        )
        variables = {"id": await resolve_id(client, "test_execution", test_execution)}
    wanted = {s.upper() for s in (list_statuses if list_statuses is not None else ["FAILED"])}
    by_status: dict[str, int] = {}
    listed: list[dict[str, Any]] = []
    done = counted = total = 0
    while counted < max_tests:
        data = await client.graphql(query, {**variables, "limit": min(100, max_tests - counted), "start": counted})
        page = (data.get(op) or {}).get(connection) or {}
        total = page.get("total") or 0
        results = page.get("results") or []
        for item in results:
            status = item.get("status") or {}
            name = status.get("name") or "UNKNOWN"
            by_status[name] = by_status.get(name, 0) + 1
            done += bool(status.get("final"))
            if name.upper() in wanted and len(listed) < 100:
                jira = (item.get("test") or item).get("jira") or {}
                listed.append({"key": jira.get("key"), "status": name})
        counted += len(results)
        if not results or counted >= total:
            break
    return {
        "total": total,
        "counted": counted,
        "truncated": counted < total,
        "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        # Tests whose status is final (execution finished), e.g. PASSED or FAILED but not TODO / EXECUTING.
        "done": done,
        "done_percent": round(100 * done / counted, 1) if counted else 0.0,
        "tests": listed,
    }


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_run(
    test_run_id: TestRunId,
    status: Annotated[str | None, Field(description="New status name, e.g. 'PASSED' or 'FAILED'.")] = None,
    comment: str | None = None,
    started_on: Annotated[str | None, Field(description="ISO 8601 start timestamp.")] = None,
    finished_on: Annotated[str | None, Field(description="ISO 8601 finish timestamp.")] = None,
    assignee_id: Annotated[str | None, Field(description="Atlassian account id of the assignee.")] = None,
    executed_by_id: Annotated[str | None, Field(description="Atlassian account id of the executor.")] = None,
    custom_fields: Annotated[list[CustomFieldValue] | None, Field(description="Test run custom fields.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Update a test run: status, comment, timestamps, assignee, executor and custom fields."""
    details = compact(
        comment=comment,
        startedOn=started_on,
        finishedOn=finished_on,
        assigneeId=assignee_id,
        executedById=executed_by_id,
        customFields=[f.model_dump() for f in custom_fields] if custom_fields else None,
    )
    if not details and status is None:
        raise ValueError("Nothing to update.")
    out: dict[str, Any] = {}
    if details:
        data = await client.graphql(
            "mutation($id: String!, $comment: String, $startedOn: String, $finishedOn: String,"
            " $assigneeId: String, $executedById: String, $customFields: [CustomFieldInput]) {"
            " updateTestRun(id: $id, comment: $comment, startedOn: $startedOn, finishedOn: $finishedOn,"
            " assigneeId: $assigneeId, executedById: $executedById, customFields: $customFields) { warnings } }",
            {"id": test_run_id, **details},
        )
        out["updateTestRun"] = data.get("updateTestRun")
    if status is not None:
        data = await client.graphql(
            "mutation($id: String!, $status: String!) { updateTestRunStatus(id: $id, status: $status) }",
            {"id": test_run_id, "status": status},
        )
        out["updateTestRunStatus"] = data.get("updateTestRunStatus")
    return out


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_reset_test_run(test_run_id: TestRunId, client: XrayClient = XRAY) -> dict[str, Any]:
    """Reset a test run to its initial state, discarding status, comments, evidence and step results."""
    data = await client.graphql("mutation($id: String!) { resetTestRun(id: $id) }", {"id": test_run_id})
    return {"result": data.get("resetTestRun")}


@toolset.tool(read_only=False)
async def xray_set_test_run_timer(
    test_run_id: TestRunId,
    running: Annotated[bool | None, Field(description="True starts, False pauses the timer.")] = None,
    reset: Annotated[bool | None, Field(description="True resets the timer.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Start, pause or reset the execution timer of a test run."""
    data = await client.graphql(
        "mutation($id: String!, $running: Boolean, $reset: Boolean) {"
        " setTestRunTimer(testRunId: $id, running: $running, reset: $reset) }",
        compact(id=test_run_id, running=running, reset=reset),
    )
    return {"result": data.get("setTestRunTimer")}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_run_defects(
    test_run_id: TestRunId,
    add: Annotated[list[str] | None, Field(description="Defect issue keys or ids to link.")] = None,
    remove: Annotated[list[str] | None, Field(description="Defect issue keys or ids to unlink.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Link and/or unlink defects on a test run."""
    if not add and not remove:
        raise ValueError("Pass add and/or remove.")
    out: dict[str, Any] = {}
    if add:
        data = await client.graphql(
            "mutation($id: String!, $issues: [String]!) {"
            " addDefectsToTestRun(id: $id, issues: $issues) { addedDefects warnings } }",
            {"id": test_run_id, "issues": add},
        )
        out["added"] = data.get("addDefectsToTestRun")
    if remove:
        data = await client.graphql(
            "mutation($id: String!, $issues: [String]!) { removeDefectsFromTestRun(id: $id, issues: $issues) }",
            {"id": test_run_id, "issues": remove},
        )
        out["removed"] = data.get("removeDefectsFromTestRun")
    return out


@toolset.tool(read_only=False)
async def xray_add_test_run_evidence(
    test_run_id: TestRunId, evidence: list[AttachmentData], client: XrayClient = XRAY
) -> dict[str, Any]:
    """Attach evidence files (base64 or uploaded attachment ids) to a test run."""
    data = await client.graphql(
        "mutation($id: String!, $evidence: [AttachmentDataInput]!) {"
        " addEvidenceToTestRun(id: $id, evidence: $evidence) { addedEvidence warnings } }",
        {"id": test_run_id, "evidence": [e.to_graphql() for e in evidence]},
    )
    return data.get("addEvidenceToTestRun") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_test_run_evidence(
    test_run_id: TestRunId,
    evidence_ids: list[str] | None = None,
    evidence_filenames: list[str] | None = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Remove evidence from a test run by id and/or filename."""
    if not evidence_ids and not evidence_filenames:
        raise ValueError("Pass evidence_ids and/or evidence_filenames.")
    data = await client.graphql(
        "mutation($id: String!, $ids: [String], $names: [String]) {"
        " removeEvidenceFromTestRun(id: $id, evidenceIds: $ids, evidenceFilenames: $names) { removedEvidence warnings } }",
        compact(id=test_run_id, ids=evidence_ids, names=evidence_filenames),
    )
    return data.get("removeEvidenceFromTestRun") or {}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_run_step(
    test_run_id: TestRunId,
    step_id: StepId,
    status: Annotated[str | None, Field(description="Step status name, e.g. 'PASSED'.")] = None,
    comment: str | None = None,
    actual_result: str | None = None,
    add_defects: Annotated[list[str] | None, Field(description="Defect keys or ids to link.")] = None,
    remove_defects: Annotated[list[str] | None, Field(description="Defect keys or ids to unlink.")] = None,
    add_evidence: list[AttachmentData] | None = None,
    remove_evidence_ids: list[str] | None = None,
    remove_evidence_filenames: list[str] | None = None,
    iteration_rank: IterationRank = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Record the result of one test run step: status, comment, actual result, defects and evidence."""
    evidence = compact(
        add=[e.to_graphql() for e in add_evidence] if add_evidence else None,
        removeIds=remove_evidence_ids,
        removeFilenames=remove_evidence_filenames,
    )
    defects = compact(add=add_defects, remove=remove_defects)
    update = compact(
        status=status,
        comment=comment,
        actualResult=actual_result,
        evidence=evidence or None,
        defects=defects or None,
    )
    if not update:
        raise ValueError("Nothing to update.")
    data = await client.graphql(
        "mutation($runId: String!, $stepId: String!, $data: UpdateTestRunStepInput!, $rank: String) {"
        " updateTestRunStep(testRunId: $runId, stepId: $stepId, updateData: $data, iterationRank: $rank) {"
        " addedDefects removedDefects addedEvidence removedEvidence warnings } }",
        compact(runId=test_run_id, stepId=step_id, data=update, rank=iteration_rank),
    )
    return data.get("updateTestRunStep") or {}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_run_iteration_status(
    test_run_id: TestRunId,
    iteration_rank: Annotated[str, Field(description="Iteration rank, from xray_get_test_run.")],
    status: Status,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Set the status of one iteration of a data-driven test run."""
    data = await client.graphql(
        "mutation($id: String!, $rank: String!, $status: String!) {"
        " updateIterationStatus(testRunId: $id, iterationRank: $rank, status: $status) { warnings } }",
        {"id": test_run_id, "rank": iteration_rank, "status": status},
    )
    return data.get("updateIterationStatus") or {}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_run_example_status(
    example_id: Annotated[str, Field(description="Scenario Outline example id, from xray_get_test_run.")],
    status: Status,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Set the status of one Cucumber Scenario Outline example in a test run."""
    data = await client.graphql(
        "mutation($id: String!, $status: String!) {"
        " updateTestRunExampleStatus(exampleId: $id, status: $status) { warnings } }",
        {"id": example_id, "status": status},
    )
    return data.get("updateTestRunExampleStatus") or {}


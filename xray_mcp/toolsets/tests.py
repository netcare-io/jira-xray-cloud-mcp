# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Test issues: definitions, steps, versions, associations, datasets."""

from typing import Annotated, Any

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import (
    EXPANDED_STEPS,
    REQUIREMENTS,
    STEPS,
    XRAY,
    ExtraJiraFields,
    IssueRef,
    JiraFields,
    Limit,
    ModifiedSince,
    Start,
    StepInput,
    compact,
    jira_fields,
    jira_payload,
    related,
    resolve_id,
    resolve_ids,
    resolve_project_id,
    test_selection,
)

toolset = Toolset("tests", "Test issues: steps, Gherkin / unstructured definitions, versions, datasets and links.")

VersionId = Annotated[int | None, Field(description="Test version id; default is the current version.")]
TestTypeName = Annotated[str, Field(description="Xray test type name, e.g. 'Manual', 'Cucumber', 'Generic'.")]
IncludeRequirements = Annotated[
    bool, Field(description="Also list the requirements (coverable issues) each Test covers.")
]


@toolset.tool(read_only=True)
async def xray_get_test(
    test: IssueRef,
    fields: JiraFields = None,
    include_relations: Annotated[
        bool, Field(description="Also list linked Preconditions, Test Sets, Test Plans and Test Executions.")
    ] = False,
    include_requirements: IncludeRequirements = False,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get one Xray Test with its type, steps / Gherkin / unstructured definition, folder and Jira fields."""
    issue_id = await resolve_id(client, "test", test)
    selection = test_selection()
    if include_relations:
        selection += " " + " ".join(
            related(f) for f in ("preconditions", "testSets", "testPlans", "testExecutions")
        )
    if include_requirements:
        selection += " " + REQUIREMENTS
    data = await client.graphql(
        f"query($id: String, $jiraFields: [String]) {{ getTest(issueId: $id) {{ {selection} }} }}",
        {"id": issue_id, "jiraFields": jira_fields(fields)},
    )
    return {"test": data.get("getTest")}


@toolset.tool(read_only=True)
async def xray_get_tests(
    jql: Annotated[str | None, Field(description="JQL filter, e.g. 'project = CALC AND labels = smoke'.")] = None,
    tests: Annotated[list[str] | None, Field(description="Restrict to these Test keys or ids.")] = None,
    project: Annotated[str | None, Field(description="Restrict to a Jira project (key or id).")] = None,
    test_type: Annotated[str | None, Field(description="Restrict to a test type name, e.g. 'Manual'.")] = None,
    folder_path: Annotated[
        str | None, Field(description="Restrict to a Test Repository folder path, e.g. '/Regression/API'.")
    ] = None,
    include_subfolders: Annotated[bool, Field(description="With folder_path: include descendant folders.")] = False,
    modified_since: ModifiedSince = None,
    include_steps: Annotated[bool, Field(description="Include manual steps of each test.")] = False,
    include_definition: Annotated[
        bool, Field(description="Include Gherkin / unstructured definitions of each test.")
    ] = False,
    expand_call_tests: Annotated[
        bool,
        Field(description="Include steps with 'Call Test' steps replaced by the called Tests' steps (implies include_steps)."),
    ] = False,
    include_requirements: IncludeRequirements = False,
    fields: JiraFields = None,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Search Xray Tests by JQL, keys, project, test type or Test Repository folder (paginated)."""
    project_id = await resolve_project_id(client, project) if project else None
    folder = None
    if folder_path:
        if not project_id:
            raise ValueError("folder_path requires project.")
        folder = {"path": folder_path, "includeDescendants": include_subfolders}
    op = "getExpandedTests" if expand_call_tests else "getTests"
    selection = test_selection(
        steps=include_steps or expand_call_tests, definition=include_definition, expanded=expand_call_tests
    )
    if include_requirements:
        selection += " " + REQUIREMENTS
    data = await client.graphql(
        "query($jql: String, $ids: [String], $projectId: String, $testType: TestTypeInput, "
        "$modifiedSince: String, $limit: Int!, $start: Int, $folder: FolderSearchInput, $jiraFields: [String]) {"
        f" {op}(jql: $jql, issueIds: $ids, projectId: $projectId, testType: $testType,"
        " modifiedSince: $modifiedSince, limit: $limit, start: $start, folder: $folder) {"
        f" total start limit results {{ {selection} }} }} }}",
        compact(
            jql=jql,
            ids=await resolve_ids(client, "test", tests),
            projectId=project_id,
            testType={"name": test_type} if test_type else None,
            modifiedSince=modified_since,
            limit=limit,
            start=start,
            folder=folder,
            jiraFields=jira_fields(fields),
        ),
    )
    return data.get(op) or {}


@toolset.tool(read_only=True)
async def xray_get_expanded_test(
    test: IssueRef,
    version_id: VersionId = None,
    fields: JiraFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get a Test with 'Call Test' steps expanded inline into the steps of the called tests."""
    issue_id = await resolve_id(client, "test", test)
    data = await client.graphql(
        "query($id: String!, $versionId: Int, $jiraFields: [String]) {"
        " getExpandedTest(issueId: $id, versionId: $versionId) {"
        " issueId versionId projectId testType { name kind } folder { path } jira(fields: $jiraFields)"
        f" unstructured gherkin scenarioType warnings {EXPANDED_STEPS} }} }}",
        compact(id=issue_id, versionId=version_id, jiraFields=jira_fields(fields)),
    )
    return {"test": data.get("getExpandedTest")}


@toolset.tool(read_only=True)
async def xray_get_test_versions(
    test: IssueRef,
    include_archived: Annotated[bool, Field(description="Also list archived versions.")] = False,
    include_definition: Annotated[
        bool, Field(description="Include steps and Gherkin / unstructured definition of each version.")
    ] = False,
    limit: Limit = 50,
    start: Start = 0,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """List the versions of a Test (ids for the version_id parameters of the other tools; paginated)."""
    selection = "id name default archived testType { name kind }"
    if include_definition:
        selection += f" {STEPS} unstructured gherkin scenarioType"
    data = await client.graphql(
        "query($id: String, $limit: Int!, $start: Int, $archived: Boolean) { getTest(issueId: $id) {"
        " issueId testVersions(limit: $limit, start: $start, archived: $archived) {"
        f" total start limit results {{ {selection} }} }} }} }}",
        {"id": await resolve_id(client, "test", test), "limit": limit, "start": start, "archived": include_archived},
    )
    test_data = data.get("getTest") or {}
    return test_data.get("testVersions") or {}


DATASET = (
    "id testIssueId testExecIssueId testPlanIssueId testStepId callTestIssueId"
    " parameters { name type projectListId combinations listValues } rows { order Values }"
)


@toolset.tool(read_only=True)
async def xray_get_datasets(
    tests: Annotated[
        list[str],
        Field(
            min_length=1,
            description=(
                "Test keys or ids. One Test (with at most one Test Plan / Execution) returns the dataset in effect "
                "there; otherwise all datasets stored for these Tests and the given overrides."
            ),
        ),
    ],
    test_executions: Annotated[
        list[str] | None, Field(description="Dataset overrides on these Test Executions.")
    ] = None,
    test_plans: Annotated[list[str] | None, Field(description="Dataset overrides on these Test Plans.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get the datasets (parameters and rows) of data-driven Tests, optionally as overridden on Test Plans / Executions."""
    test_ids = await resolve_ids(client, "test", tests) or []
    exec_ids = await resolve_ids(client, "test_execution", test_executions) or []
    plan_ids = await resolve_ids(client, "test_plan", test_plans) or []
    if len(test_ids) == 1 and len(exec_ids) <= 1 and len(plan_ids) <= 1:
        data = await client.graphql(
            "query($t: String!, $e: String, $p: String) {"
            f" getDataset(testIssueId: $t, testExecIssueId: $e, testPlanIssueId: $p) {{ {DATASET} }} }}",
            compact(t=test_ids[0], e=exec_ids[0] if exec_ids else None, p=plan_ids[0] if plan_ids else None),
        )
        dataset = data.get("getDataset")
        return {"datasets": [dataset] if dataset else []}
    data = await client.graphql(
        "query($t: [String], $e: [String], $p: [String]) {"
        f" getDatasets(testIssueIds: $t, testExecIssueIds: $e, testPlanIssueIds: $p) {{ {DATASET} }} }}",
        compact(t=test_ids, e=exec_ids or None, p=plan_ids or None),
    )
    return {"datasets": data.get("getDatasets") or []}


@toolset.tool(read_only=False)
async def xray_create_test(
    project: Annotated[str, Field(description="Jira project key or id.")],
    summary: str,
    test_type: TestTypeName = "Manual",
    steps: Annotated[list[StepInput] | None, Field(description="Steps, for step-based (manual) tests.")] = None,
    gherkin: Annotated[str | None, Field(description="Gherkin scenario, for Cucumber tests.")] = None,
    unstructured: Annotated[str | None, Field(description="Free-text definition, for Generic tests.")] = None,
    preconditions: Annotated[list[str] | None, Field(description="Precondition keys or ids to link.")] = None,
    folder_path: Annotated[str | None, Field(description="Test Repository folder, e.g. '/Regression'.")] = None,
    extra_fields: ExtraJiraFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Create an Xray Test issue (manual steps, Gherkin or unstructured definition)."""
    data = await client.graphql(
        "mutation($testType: UpdateTestTypeInput, $steps: [CreateStepInput], $unstructured: String,"
        " $gherkin: String, $pre: [String], $folderPath: String, $jira: JSON!) {"
        " createTest(testType: $testType, steps: $steps, unstructured: $unstructured, gherkin: $gherkin,"
        " preconditionIssueIds: $pre, folderPath: $folderPath, jira: $jira) {"
        ' warnings test { issueId testType { name kind } jira(fields: ["key", "summary"]) } } }',
        compact(
            testType={"name": test_type},
            steps=[s.model_dump(exclude_none=True) for s in steps] if steps else None,
            unstructured=unstructured,
            gherkin=gherkin,
            pre=await resolve_ids(client, "precondition", preconditions),
            folderPath=folder_path,
            jira=jira_payload(project, summary, extra_fields),
        ),
    )
    return data.get("createTest") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_delete_test(test: IssueRef, client: XrayClient = XRAY) -> dict[str, Any]:
    """Delete a Test issue permanently (Jira issue included)."""
    data = await client.graphql(
        "mutation($id: String!) { deleteTest(issueId: $id) }", {"id": await resolve_id(client, "test", test)}
    )
    return {"result": data.get("deleteTest")}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_type(
    test: IssueRef, test_type: TestTypeName, version_id: VersionId = None, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Change the test type of a Test (e.g. Manual -> Cucumber)."""
    data = await client.graphql(
        "mutation($id: String!, $v: Int, $t: UpdateTestTypeInput!) {"
        " updateTestType(issueId: $id, versionId: $v, testType: $t) { issueId testType { name kind } } }",
        compact(id=await resolve_id(client, "test", test), v=version_id, t={"name": test_type}),
    )
    return {"test": data.get("updateTestType")}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_definition(
    test: IssueRef,
    gherkin: Annotated[str | None, Field(description="New Gherkin scenario (Cucumber tests).")] = None,
    unstructured: Annotated[str | None, Field(description="New free-text definition (Generic tests).")] = None,
    version_id: VersionId = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Replace the Gherkin or unstructured definition of a Test. Use the step tools for manual tests."""
    if (gherkin is None) == (unstructured is None):
        raise ValueError("Pass exactly one of gherkin or unstructured.")
    issue_id = await resolve_id(client, "test", test)
    if gherkin is not None:
        data = await client.graphql(
            "mutation($id: String!, $v: Int, $g: String!) {"
            " updateGherkinTestDefinition(issueId: $id, versionId: $v, gherkin: $g) { issueId gherkin } }",
            compact(id=issue_id, v=version_id, g=gherkin),
        )
        return {"test": data.get("updateGherkinTestDefinition")}
    data = await client.graphql(
        "mutation($id: String!, $v: Int, $u: String!) {"
        " updateUnstructuredTestDefinition(issueId: $id, versionId: $v, unstructured: $u) { issueId unstructured } }",
        compact(id=issue_id, v=version_id, u=unstructured),
    )
    return {"test": data.get("updateUnstructuredTestDefinition")}


@toolset.tool(read_only=False)
async def xray_add_test_step(
    test: IssueRef,
    action: str,
    data: str | None = None,
    result: str | None = None,
    call_test: Annotated[
        str | None, Field(description="Make this a 'Call Test' step calling this Test (key or id).")
    ] = None,
    version_id: VersionId = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Append a step to a manual Test."""
    step = compact(
        action=action,
        data=data,
        result=result,
        callTestIssueId=await resolve_id(client, "test", call_test) if call_test else None,
    )
    out = await client.graphql(
        "mutation($id: String!, $v: Int, $step: CreateStepInput!) {"
        " addTestStep(issueId: $id, versionId: $v, step: $step) { id action data result callTestIssueId } }",
        compact(id=await resolve_id(client, "test", test), v=version_id, step=step),
    )
    return {"step": out.get("addTestStep")}


@toolset.tool(read_only=False, idempotent=True)
async def xray_update_test_step(
    step_id: Annotated[str, Field(description="Step id, from xray_get_test.")],
    action: str | None = None,
    data: str | None = None,
    result: str | None = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Update action, data and/or expected result of a manual test step."""
    out = await client.graphql(
        "mutation($id: String!, $step: UpdateStepInput!) {"
        " updateTestStep(stepId: $id, step: $step) { warnings addedAttachments removedAttachments } }",
        {"id": step_id, "step": compact(action=action, data=data, result=result)},
    )
    return out.get("updateTestStep") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_test_step(
    step_id: Annotated[str, Field(description="Step id, from xray_get_test.")], client: XrayClient = XRAY
) -> dict[str, Any]:
    """Remove one step from a manual Test."""
    out = await client.graphql("mutation($id: String!) { removeTestStep(stepId: $id) }", {"id": step_id})
    return {"result": out.get("removeTestStep")}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_all_test_steps(
    test: IssueRef, version_id: VersionId = None, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Remove all steps from a manual Test."""
    out = await client.graphql(
        "mutation($id: String!, $v: Int) { removeAllTestSteps(issueId: $id, versionId: $v) }",
        compact(id=await resolve_id(client, "test", test), v=version_id),
    )
    return {"result": out.get("removeAllTestSteps")}


# parameter -> (issue kind, add mutation, remove mutation, id-list argument, add result field)
_ASSOCIATIONS = {
    "preconditions": ("precondition", "addPreconditionsToTest", "removePreconditionsFromTest",
                      "preconditionIssueIds", "addedPreconditions"),
    "test_sets": ("test_set", "addTestSetsToTest", "removeTestSetsFromTest", "testSetIssueIds", "addedTestSets"),
    "test_plans": ("test_plan", "addTestPlansToTest", "removeTestPlansFromTest", "testPlanIssueIds", "addedTestPlans"),
    "test_executions": ("test_execution", "addTestExecutionsToTest", "removeTestExecutionsFromTest",
                        "testExecIssueIds", "addedTestExecutions"),
}  # fmt: skip

# Only these mutations take a versionId argument.
_VERSIONED = {"addPreconditionsToTest", "removePreconditionsFromTest", "addTestExecutionsToTest"}


async def _change_associations(
    client: XrayClient, test: str, groups: dict[str, list[str] | None], version_id: int | None, *, add: bool
) -> dict[str, Any]:
    if not any(groups.values()):
        raise ValueError("Pass at least one of preconditions, test_sets, test_plans, test_executions.")
    issue_id = await resolve_id(client, "test", test)
    out: dict[str, Any] = {}
    for param, refs in groups.items():
        if not refs:
            continue
        kind, add_op, remove_op, arg, added_field = _ASSOCIATIONS[param]
        op = add_op if add else remove_op
        version = op in _VERSIONED and version_id is not None
        selection = f" {{ {added_field} warning }}" if add else ""
        data = await client.graphql(
            f"mutation($id: String!, $ids: [String]!{', $v: Int' if version else ''}) {{"
            f" {op}(issueId: $id, {arg}: $ids{', versionId: $v' if version else ''}){selection} }}",
            compact(id=issue_id, ids=await resolve_ids(client, kind, refs), v=version_id if version else None),
        )
        out[param] = data.get(op)
    return out


AssocRefs = Annotated[list[str] | None, Field(description="Issue keys or ids.")]


@toolset.tool(read_only=False, idempotent=True)
async def xray_add_test_associations(
    test: IssueRef,
    preconditions: AssocRefs = None,
    test_sets: AssocRefs = None,
    test_plans: AssocRefs = None,
    test_executions: AssocRefs = None,
    version_id: Annotated[
        int | None, Field(description="Test version, for preconditions / test executions.")
    ] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Link one Test to Preconditions, Test Sets, Test Plans and/or Test Executions."""
    groups = dict(
        preconditions=preconditions, test_sets=test_sets, test_plans=test_plans, test_executions=test_executions
    )
    return await _change_associations(client, test, groups, version_id, add=True)


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_remove_test_associations(
    test: IssueRef,
    preconditions: AssocRefs = None,
    test_sets: AssocRefs = None,
    test_plans: AssocRefs = None,
    test_executions: AssocRefs = None,
    version_id: Annotated[int | None, Field(description="Test version, for preconditions only.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Unlink one Test from Preconditions, Test Sets, Test Plans and/or Test Executions."""
    groups = dict(
        preconditions=preconditions, test_sets=test_sets, test_plans=test_plans, test_executions=test_executions
    )
    return await _change_associations(client, test, groups, version_id, add=False)


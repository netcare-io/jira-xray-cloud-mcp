# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Test Repository folders of a project, and Test Plan folders."""

from typing import Annotated, Any

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import XRAY, compact, resolve_id, resolve_ids, resolve_project_id

toolset = Toolset(
    "test_repository",
    "Folder tree of a project's Test Repository or of a Test Plan.",
)

Project = Annotated[
    str | None, Field(description="Jira project key or id (for Test Repository folders).")
]
TestPlan = Annotated[
    str | None, Field(description="Test Plan key or id (for Test Plan folders instead of the repository).")
]
FolderPath = Annotated[str, Field(description="Folder path, e.g. '/Regression/API'. '/' is the root.")]
Index = Annotated[int | None, Field(ge=0, description="Position among sibling folders / issues.")]

FOLDER_RESULT = "{ folder { name path testsCount preconditionsCount issuesCount } warnings }"


async def _scope(client: XrayClient, project: str | None, test_plan: str | None) -> dict[str, str]:
    if bool(project) == bool(test_plan):
        raise ValueError("Pass exactly one of project or test_plan.")
    if project:
        return {"projectId": await resolve_project_id(client, project)}
    assert test_plan is not None
    return {"testPlanId": await resolve_id(client, "test_plan", test_plan)}


@toolset.tool(read_only=True)
async def xray_get_folder(
    path: FolderPath = "/",
    project: Project = None,
    test_plan: TestPlan = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get a folder with its counts and complete subfolder tree. Use xray_get_tests(folder_path=...) for its Tests."""
    scope = await _scope(client, project, test_plan)
    data = await client.graphql(
        "query($projectId: String, $testPlanId: String, $path: String!) {"
        " getFolder(projectId: $projectId, testPlanId: $testPlanId, path: $path) {"
        " name path issuesCount testsCount preconditionsCount folders } }",
        {**scope, "path": path},
    )
    return {"folder": data.get("getFolder")}


@toolset.tool(read_only=False)
async def xray_create_folder(
    path: Annotated[str, Field(description="Path of the new folder, e.g. '/Regression/API'.")],
    project: Project = None,
    test_plan: TestPlan = None,
    tests: Annotated[list[str] | None, Field(description="Test keys or ids to move into the folder.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Create a folder in a project's Test Repository or in a Test Plan, optionally with Tests."""
    scope = await _scope(client, project, test_plan)
    data = await client.graphql(
        "mutation($projectId: String, $testPlanId: String, $path: String!, $tests: [String]) {"
        f" createFolder(projectId: $projectId, testPlanId: $testPlanId, path: $path, testIssueIds: $tests) {FOLDER_RESULT} }}",
        compact(**scope, path=path, tests=await resolve_ids(client, "test", tests)),
    )
    return data.get("createFolder") or {}


@toolset.tool(read_only=False, idempotent=True)
async def xray_rename_folder(
    path: FolderPath,
    new_name: Annotated[str, Field(description="New folder name (not a path).")],
    project: Project = None,
    test_plan: TestPlan = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Rename a folder."""
    scope = await _scope(client, project, test_plan)
    data = await client.graphql(
        "mutation($projectId: String, $testPlanId: String, $path: String!, $newName: String!) {"
        f" renameFolder(projectId: $projectId, testPlanId: $testPlanId, path: $path, newName: $newName) {FOLDER_RESULT} }}",
        {**scope, "path": path, "newName": new_name},
    )
    return data.get("renameFolder") or {}


@toolset.tool(read_only=False, idempotent=True)
async def xray_move_folder(
    path: FolderPath,
    destination_path: Annotated[str, Field(description="Parent folder to move into, e.g. '/Archive'.")],
    project: Project = None,
    test_plan: TestPlan = None,
    index: Index = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Move a folder (with its content) below another folder."""
    scope = await _scope(client, project, test_plan)
    data = await client.graphql(
        "mutation($projectId: String, $testPlanId: String, $path: String!, $dest: String!, $index: Int) {"
        " moveFolder(projectId: $projectId, testPlanId: $testPlanId, path: $path, destinationPath: $dest,"
        f" index: $index) {FOLDER_RESULT} }}",
        compact(**scope, path=path, dest=destination_path, index=index),
    )
    return data.get("moveFolder") or {}


@toolset.tool(read_only=False, destructive=True, idempotent=True)
async def xray_delete_folder(
    path: FolderPath, project: Project = None, test_plan: TestPlan = None, client: XrayClient = XRAY
) -> dict[str, Any]:
    """Delete a folder and its subfolders. The Test / Precondition issues in it are not deleted."""
    scope = await _scope(client, project, test_plan)
    data = await client.graphql(
        "mutation($projectId: String, $testPlanId: String, $path: String!) {"
        " deleteFolder(projectId: $projectId, testPlanId: $testPlanId, path: $path) }",
        {**scope, "path": path},
    )
    return {"result": data.get("deleteFolder")}


@toolset.tool(read_only=False, idempotent=True)
async def xray_move_to_folder(
    path: FolderPath,
    tests: Annotated[list[str] | None, Field(description="Test keys or ids.")] = None,
    preconditions: Annotated[
        list[str] | None, Field(description="Precondition keys or ids (repository folders only).")
    ] = None,
    project: Project = None,
    test_plan: TestPlan = None,
    index: Index = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Move Tests (and, in the Test Repository, Preconditions) into a folder."""
    scope = await _scope(client, project, test_plan)
    test_ids = await resolve_ids(client, "test", tests) or []
    if "testPlanId" in scope:
        if preconditions:
            raise ValueError("Test Plan folders hold Tests only.")
        data = await client.graphql(
            "mutation($testPlanId: String, $path: String!, $ids: [String]!, $index: Int) {"
            f" addTestsToFolder(testPlanId: $testPlanId, path: $path, testIssueIds: $ids, index: $index) {FOLDER_RESULT} }}",
            compact(**scope, path=path, ids=test_ids, index=index),
        )
        return data.get("addTestsToFolder") or {}
    issue_ids = test_ids + (await resolve_ids(client, "precondition", preconditions) or [])
    if not issue_ids:
        raise ValueError("Pass tests and/or preconditions.")
    data = await client.graphql(
        "mutation($projectId: String!, $path: String!, $ids: [String]!, $index: Int) {"
        f" addIssuesToFolder(projectId: $projectId, path: $path, issueIds: $ids, index: $index) {FOLDER_RESULT} }}",
        compact(**scope, path=path, ids=issue_ids, index=index),
    )
    return data.get("addIssuesToFolder") or {}


@toolset.tool(read_only=False, idempotent=True)
async def xray_remove_from_folder(
    tests: Annotated[list[str] | None, Field(description="Test keys or ids.")] = None,
    preconditions: Annotated[
        list[str] | None, Field(description="Precondition keys or ids (repository folders only).")
    ] = None,
    project: Project = None,
    test_plan: TestPlan = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Take Tests / Preconditions out of their folder. The issues themselves are not deleted."""
    scope = await _scope(client, project, test_plan)
    test_ids = await resolve_ids(client, "test", tests) or []
    if "testPlanId" in scope:
        if preconditions:
            raise ValueError("Test Plan folders hold Tests only.")
        data = await client.graphql(
            "mutation($testPlanId: String, $ids: [String]!) {"
            " removeTestsFromFolder(testPlanId: $testPlanId, testIssueIds: $ids) }",
            {**scope, "ids": test_ids},
        )
        return {"result": data.get("removeTestsFromFolder")}
    issue_ids = test_ids + (await resolve_ids(client, "precondition", preconditions) or [])
    if not issue_ids:
        raise ValueError("Pass tests and/or preconditions.")
    data = await client.graphql(
        "mutation($projectId: String!, $ids: [String]!) { removeIssuesFromFolder(projectId: $projectId, issueIds: $ids) }",
        {**scope, "ids": issue_ids},
    )
    return {"result": data.get("removeIssuesFromFolder")}


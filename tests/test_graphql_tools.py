# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Every GraphQL-backed tool sends documents that are valid against the Xray schema."""

from typing import Any

import httpx2
import pytest

from tests.conftest import fake_issue_id
from xray_mcp.toolsets import ALL_TOOLSETS

EVIDENCE = [{"filename": "log.txt", "mime_type": "text/plain", "data": "aGVsbG8="}]

# Tool name -> list of argument sets. Several sets where a tool has distinct code paths.
CASES: dict[str, list[dict[str, Any]]] = {
    # tests
    "xray_get_test": [
        {"test": "CALC-1"},
        {"test": "123", "include_relations": True, "include_requirements": True, "fields": ["summary"]},
    ],
    "xray_get_tests": [
        {"jql": "project = CALC"},
        {
            "tests": ["CALC-1", "42"],
            "project": "CALC",
            "test_type": "Manual",
            "folder_path": "/Regression",
            "include_subfolders": True,
            "modified_since": "2026-01-01",
            "include_steps": True,
            "include_definition": True,
            "include_requirements": True,
            "limit": 10,
            "start": 5,
        },
        {"project": "CALC", "folder_path": "/UI", "expand_call_tests": True, "include_definition": True},
    ],
    "xray_get_expanded_test": [{"test": "CALC-1", "version_id": 2}],
    "xray_get_test_versions": [
        {"test": "CALC-1"},
        {"test": "CALC-1", "include_archived": True, "include_definition": True, "limit": 10, "start": 10},
    ],
    "xray_get_datasets": [
        {"tests": ["CALC-1"]},
        {"tests": ["CALC-1"], "test_executions": ["CALC-2"], "test_plans": ["CALC-3"]},
        {"tests": ["CALC-1", "CALC-6"], "test_executions": ["CALC-2", "CALC-7"]},
    ],
    "xray_create_test": [
        {"project": "CALC", "summary": "Login"},
        {
            "project": "10000",
            "summary": "Login",
            "test_type": "Manual",
            "steps": [{"action": "open", "data": "x", "result": "ok"}],
            "preconditions": ["CALC-9"],
            "folder_path": "/UI",
            "extra_fields": {"labels": ["smoke"]},
        },
        {"project": "CALC", "summary": "BDD", "test_type": "Cucumber", "gherkin": "Given x"},
    ],
    "xray_delete_test": [{"test": "CALC-1"}],
    "xray_update_test_type": [{"test": "CALC-1", "test_type": "Generic", "version_id": 1}],
    "xray_update_test_definition": [
        {"test": "CALC-1", "gherkin": "Given a"},
        {"test": "CALC-1", "unstructured": "free text", "version_id": 3},
    ],
    "xray_add_test_step": [{"test": "CALC-1", "action": "a", "data": "d", "result": "r", "call_test": "CALC-7"}],
    "xray_update_test_step": [{"step_id": "s1", "action": "a2"}],
    "xray_remove_test_step": [{"step_id": "s1"}],
    "xray_remove_all_test_steps": [{"test": "CALC-1", "version_id": 1}],
    "xray_add_test_associations": [
        {
            "test": "CALC-1",
            "preconditions": ["CALC-2"],
            "test_sets": ["CALC-3"],
            "test_plans": ["CALC-4"],
            "test_executions": ["CALC-5"],
            "version_id": 1,
        }
    ],
    "xray_remove_test_associations": [
        {
            "test": "CALC-1",
            "preconditions": ["CALC-2"],
            "test_sets": ["CALC-3"],
            "test_plans": ["CALC-4"],
            "test_executions": ["CALC-5"],
            "version_id": 1,
        }
    ],
    # preconditions
    "xray_get_precondition": [{"precondition": "CALC-9"}],
    "xray_get_preconditions": [
        {"jql": "project = CALC"},
        {"preconditions": ["CALC-9"], "project": "CALC", "precondition_type": "Manual", "limit": 5},
    ],
    "xray_create_precondition": [
        {
            "project": "CALC",
            "summary": "Logged in",
            "definition": "user is logged in",
            "tests": ["CALC-1"],
            "folder_path": "/Setup",
        }
    ],
    "xray_update_precondition": [{"precondition": "CALC-9", "definition": "new", "folder_path": "/X"}],
    "xray_delete_precondition": [{"precondition": "CALC-9"}],
    "xray_add_tests_to_precondition": [{"precondition": "CALC-9", "tests": ["CALC-1"]}],
    "xray_remove_tests_from_precondition": [{"precondition": "CALC-9", "tests": ["CALC-1"]}],
    # test sets
    "xray_get_test_set": [{"test_set": "CALC-3"}],
    "xray_get_test_sets": [{"jql": "project = CALC", "modified_since": "2026-01-01"}],
    "xray_create_test_set": [{"project": "CALC", "summary": "Smoke", "tests": ["CALC-1"]}],
    "xray_delete_test_set": [{"test_set": "CALC-3"}],
    "xray_add_tests_to_test_set": [{"test_set": "CALC-3", "tests": ["CALC-1", "CALC-2"]}],
    "xray_remove_tests_from_test_set": [{"test_set": "CALC-3", "tests": ["CALC-1"]}],
    # test plans
    "xray_get_test_plan": [{"test_plan": "CALC-4"}, {"test_plan": "CALC-4", "include_test_status": True}],
    "xray_get_test_plans": [{"project": "CALC"}],
    "xray_create_test_plan": [{"project": "CALC", "summary": "R1", "tests": ["CALC-1"], "saved_filter": "10"}],
    "xray_delete_test_plan": [{"test_plan": "CALC-4"}],
    "xray_add_tests_to_test_plan": [{"test_plan": "CALC-4", "tests": ["CALC-1"]}],
    "xray_remove_tests_from_test_plan": [{"test_plan": "CALC-4", "tests": ["CALC-1"]}],
    "xray_add_test_executions_to_test_plan": [{"test_plan": "CALC-4", "test_executions": ["CALC-5"]}],
    "xray_remove_test_executions_from_test_plan": [{"test_plan": "CALC-4", "test_executions": ["CALC-5"]}],
    # test executions
    "xray_get_test_execution": [{"test_execution": "CALC-5", "runs_limit": 10, "runs_start": 10}],
    "xray_get_test_executions": [{"jql": "project = CALC"}],
    "xray_create_test_execution": [
        {"project": "CALC", "summary": "Run", "tests": ["CALC-1"], "test_environments": ["Chrome"]}
    ],
    "xray_delete_test_execution": [{"test_execution": "CALC-5"}],
    "xray_add_tests_to_test_execution": [{"test_execution": "CALC-5", "tests": ["CALC-1"]}],
    "xray_remove_tests_from_test_execution": [{"test_execution": "CALC-5", "tests": ["CALC-1"]}],
    "xray_add_test_environments": [{"test_execution": "CALC-5", "test_environments": ["Chrome"]}],
    "xray_remove_test_environments": [{"test_execution": "CALC-5", "test_environments": ["Chrome"]}],
    # test runs
    "xray_get_test_run": [{"test_run_id": "run1"}, {"test": "CALC-1", "test_execution": "CALC-5"}],
    "xray_get_test_runs": [
        {"test_run_ids": ["run1", "run2"], "include_steps": True},
        {
            "tests": ["CALC-1"],
            "test_executions": ["CALC-5"],
            "test_plans": ["CALC-4"],
            "assignees": ["acc-1"],
            "statuses": ["FAILED"],
            "modified_since": "2026-01-01",
        },
    ],
    "xray_get_test_progress": [
        {"test_plan": "CALC-4", "environment": "Chrome"},
        {"test_execution": "CALC-5", "list_statuses": ["FAILED", "TODO"], "max_tests": 250},
    ],
    "xray_update_test_run": [
        {
            "test_run_id": "run1",
            "status": "PASSED",
            "comment": "ok",
            "started_on": "2026-01-01T10:00:00Z",
            "finished_on": "2026-01-01T10:05:00Z",
            "assignee_id": "acc-1",
            "executed_by_id": "acc-2",
            "custom_fields": [{"id": "cf1", "value": "x"}],
        },
        {"test_run_id": "run1", "status": "FAILED"},
    ],
    "xray_reset_test_run": [{"test_run_id": "run1"}],
    "xray_set_test_run_timer": [{"test_run_id": "run1", "running": True}],
    "xray_update_test_run_defects": [{"test_run_id": "run1", "add": ["CALC-99"], "remove": ["CALC-98"]}],
    "xray_add_test_run_evidence": [{"test_run_id": "run1", "evidence": EVIDENCE}],
    "xray_remove_test_run_evidence": [{"test_run_id": "run1", "evidence_ids": ["e1"], "evidence_filenames": ["a.txt"]}],
    "xray_update_test_run_step": [
        {
            "test_run_id": "run1",
            "step_id": "s1",
            "status": "FAILED",
            "comment": "broken",
            "actual_result": "500",
            "add_defects": ["CALC-99"],
            "remove_defects": ["CALC-98"],
            "add_evidence": EVIDENCE,
            "remove_evidence_ids": ["e1"],
            "remove_evidence_filenames": ["old.png"],
            "iteration_rank": "0",
        }
    ],
    "xray_update_test_run_iteration_status": [{"test_run_id": "run1", "iteration_rank": "0", "status": "PASSED"}],
    "xray_update_test_run_example_status": [{"example_id": "ex1", "status": "PASSED"}],
    # test repository
    "xray_get_folder": [{"project": "CALC"}, {"test_plan": "CALC-4", "path": "/A"}],
    "xray_create_folder": [{"project": "CALC", "path": "/A", "tests": ["CALC-1"]}, {"test_plan": "CALC-4", "path": "/A"}],
    "xray_rename_folder": [{"project": "CALC", "path": "/A", "new_name": "B"}],
    "xray_move_folder": [{"project": "CALC", "path": "/A", "destination_path": "/B", "index": 0}],
    "xray_delete_folder": [{"project": "CALC", "path": "/A"}],
    "xray_move_to_folder": [
        {"project": "CALC", "path": "/A", "tests": ["CALC-1"], "preconditions": ["CALC-9"], "index": 1},
        {"test_plan": "CALC-4", "path": "/A", "tests": ["CALC-1"]},
    ],
    "xray_remove_from_folder": [
        {"project": "CALC", "tests": ["CALC-1"], "preconditions": ["CALC-9"]},
        {"test_plan": "CALC-4", "tests": ["CALC-1"]},
    ],
    # coverage
    "xray_get_coverable_issue": [
        {"issue": "CALC-20"},
        {"issue": "CALC-20", "environment": "Chrome", "version": "1.0", "test_plan": "CALC-4", "is_final": True},
    ],
    "xray_get_coverable_issues": [{"jql": "issuetype = Story", "issues": ["CALC-20"], "version": "1.0"}],
    # history
    "xray_get_issue_history": [
        {"issue": "CALC-1", "issue_type": "test"},
        {"issue": "CALC-9", "issue_type": "precondition", "limit": 10, "start": 10},
        {"issue": "CALC-3", "issue_type": "test_set"},
        {"issue": "CALC-4", "issue_type": "test_plan"},
        {"issue": "CALC-5", "issue_type": "test_execution"},
    ],
    # settings
    "xray_get_statuses": [{}, {"project": "CALC"}],
    "xray_get_issue_link_types": [{}],
    "xray_get_project_settings": [{"projects": ["CALC", "10001"]}],
    "xray_get_step_library": [
        {"kind": "manual", "project": "CALC", "search": "login"},
        {"kind": "bdd", "test": "CALC-1"},
    ],
    # graphql
    "xray_graphql_query": [
        {"query": "query($id: String) { getTest(issueId: $id) { issueId } }", "variables": {"id": "1"}}
    ],
    "xray_graphql_mutation": [
        {"mutation": "mutation($id: String!) { deleteTest(issueId: $id) }", "variables": {"id": "1"}}
    ],
}

# Tools that do not speak GraphQL (REST or local only); covered by other test modules.
NON_GRAPHQL = {
    "xray_import_execution_results_json",
    "xray_import_execution_results_xml",
    "xray_import_tests_bulk",
    "xray_get_import_tests_status",
    "xray_import_cucumber_features",
    "xray_export_cucumber_features",
    "xray_upload_attachment",
    "xray_get_attachment",
    "xray_get_backup_status",
    "xray_download_backup",
    "xray_graphql_schema",
}
# xray_create_backup is REST but resolves project keys through GraphQL.
CASES["xray_create_backup"] = [{"projects": ["CALC"], "with_attachments": True}]


def test_every_tool_has_a_case() -> None:
    all_tools = {spec.name for ts in ALL_TOOLSETS for spec in ts.tools}
    assert all_tools - NON_GRAPHQL - set(CASES) == set(), "add a CASES entry for new GraphQL tools"
    assert set(CASES) - all_tools == set(), "CASES lists tools that do not exist"


@pytest.mark.parametrize(
    ("tool", "args"), [(tool, args) for tool, arg_sets in CASES.items() for args in arg_sets]
)
async def test_graphql_documents_are_valid(connect, fake, tool: str, args: dict[str, Any]) -> None:
    async with connect() as client:
        result = await client.call_tool(tool, args)
    assert not result.is_error, result.content
    # conftest validates each document; make sure GraphQL was actually exercised.
    assert fake.graphql_calls


async def test_keys_are_resolved_to_ids(connect, fake) -> None:
    async with connect() as client:
        await client.call_tool("xray_add_tests_to_test_set", {"test_set": "CALC-3", "tests": ["CALC-1", "77"]})
    mutation = fake.graphql_calls[-1].json
    assert mutation["variables"] == {"id": fake_issue_id("CALC-3"), "ids": [fake_issue_id("CALC-1"), "77"]}


async def test_unknown_key_is_reported(connect, fake) -> None:
    fake.graphql_data = lambda q, v: {"getTests": {"results": []}} if "key in" in str(v.get("jql")) else None
    async with connect() as client:
        result = await client.call_tool("xray_get_test", {"test": "CALC-404"}, raise_on_error=False)
    assert result.is_error
    assert "No Test found for: CALC-404" in result.content[0].text


async def test_invalid_reference_is_rejected_before_any_call(connect, fake) -> None:
    async with connect() as client:
        result = await client.call_tool("xray_get_test", {"test": 'x") OR key = ("Y'}, raise_on_error=False)
    assert result.is_error
    assert fake.graphql_calls == []


async def test_graphql_query_tool_rejects_mutations(connect, fake) -> None:
    async with connect() as client:
        result = await client.call_tool(
            "xray_graphql_query", {"query": 'mutation { deleteTest(issueId: "1") }'}, raise_on_error=False
        )
    assert result.is_error
    assert fake.graphql_calls == []


async def test_graphql_errors_surface_as_tool_errors(connect, fake) -> None:
    fake.graphql_response = lambda q, v: httpx2.Response(200, json={"errors": [{"message": "Issue not found"}]})
    async with connect() as client:
        result = await client.call_tool("xray_get_test", {"test": "5"}, raise_on_error=False)
    assert result.is_error
    assert "Issue not found" in result.content[0].text


async def test_schema_lookup(connect) -> None:
    async with connect() as client:
        listing = (await client.call_tool("xray_graphql_schema", {})).data
        lookup = (await client.call_tool("xray_graphql_schema", {"names": ["getTests", "TestRun", "getTestz"]})).data
    assert "getTests" in listing["queries"] and "createTest" in listing["mutations"]
    assert "getTests(jql: String" in lookup["definitions"]["getTests"]
    assert "type TestRun" in lookup["definitions"]["TestRun"]
    assert "getTests" in lookup["not_found_did_you_mean"]["getTestz"]


async def test_fake_rejects_documents_that_do_not_match_the_schema(connect) -> None:
    # Guards the validity checks above: an invalid document must fail the tool call.
    async with connect() as client:
        result = await client.call_tool(
            "xray_graphql_query", {"query": "{ getTests(limit: 1) { results { nope } } }"}, raise_on_error=False
        )
    assert result.is_error


async def test_progress_pages_through_runs_and_counts(connect, fake) -> None:
    statuses = ["PASSED"] * 120 + ["FAILED"] * 20 + ["TODO"] * 10

    def data(query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
        if "getTestExecution(" not in query:
            return None
        page = statuses[variables["start"] : variables["start"] + variables["limit"]]
        results = [
            {"status": {"name": s, "final": s != "TODO"}, "test": {"jira": {"key": f"CALC-{variables['start'] + i}"}}}
            for i, s in enumerate(page)
        ]
        return {"getTestExecution": {"testRuns": {"total": len(statuses), "results": results}}}

    fake.graphql_data = data
    async with connect() as client:
        out = (await client.call_tool("xray_get_test_progress", {"test_execution": "CALC-5"})).data
        capped = (await client.call_tool("xray_get_test_progress", {"test_execution": "CALC-5", "max_tests": 100})).data
    assert out["by_status"] == {"PASSED": 120, "FAILED": 20, "TODO": 10}
    assert (out["total"], out["counted"], out["truncated"], out["done"]) == (150, 150, False, 140)
    assert out["done_percent"] == 93.3
    assert out["tests"][0] == {"key": "CALC-120", "status": "FAILED"} and len(out["tests"]) == 20
    assert (capped["counted"], capped["truncated"]) == (100, True)


async def test_progress_needs_exactly_one_scope(connect) -> None:
    async with connect() as client:
        result = await client.call_tool("xray_get_test_progress", {}, raise_on_error=False)
    assert result.is_error


async def test_datasets_single_test_uses_effective_dataset(connect, fake) -> None:
    async with connect() as client:
        await client.call_tool("xray_get_datasets", {"tests": ["CALC-1"], "test_plans": ["CALC-3"]})
        await client.call_tool("xray_get_datasets", {"tests": ["CALC-1", "CALC-2"]})
    queries = [c.json["query"] for c in fake.graphql_calls if "ataset" in c.json["query"]]
    assert "getDataset(" in queries[0] and "getDatasets(" in queries[1]

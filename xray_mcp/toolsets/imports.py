# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""REST imports/exports: execution results, bulk test import, Cucumber feature files."""

import io
import json
import zipfile
from typing import Annotated, Any, Literal

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import XRAY, compact, decode_base64

toolset = Toolset(
    "imports",
    "Test result imports (Xray JSON, Cucumber, Behave, JUnit, TestNG, NUnit, xUnit, Robot), "
    "bulk Test imports, Cucumber feature file import/export.",
)

JsonDoc = str | dict[str, Any] | list[Any]
IssueFields = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Jira issue payload for the Test Execution created by the import, e.g. "
            '{"fields": {"project": {"key": "CALC"}, "summary": "Nightly run", "issuetype": {"name": "Test Execution"}}}.'
        )
    ),
]
TestInfo = Annotated[
    dict[str, Any] | None,
    Field(description='Jira payload applied to Tests created by the import, e.g. {"fields": {"labels": ["auto"]}}.'),
]


def _json_text(doc: JsonDoc, what: str) -> str:
    if isinstance(doc, str):
        try:
            json.loads(doc)
        except ValueError as exc:
            raise ValueError(f"{what} is not valid JSON: {exc}") from exc
        return doc
    return json.dumps(doc)


def _json_part(name: str, doc: dict[str, Any]) -> tuple[str, str, str]:
    return (f"{name}.json", json.dumps(doc), "application/json")


@toolset.tool(read_only=False)
async def xray_import_execution_results_json(
    results: Annotated[JsonDoc, Field(description="The results document (JSON object/array or its text).")],
    format: Annotated[
        Literal["xray", "cucumber", "behave"],
        Field(description="'xray' = Xray JSON, 'cucumber' = Cucumber JSON report, 'behave' = Behave JSON report."),
    ] = "xray",
    test_execution_info: IssueFields = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Import JSON test results into Xray, creating or updating a Test Execution.

    Xray JSON can target an existing execution via "testExecutionKey" or describe a new one in "info".
    Pass test_execution_info to control all Jira fields of the created Test Execution (multipart import).
    """
    base = "/import/execution" if format == "xray" else f"/import/execution/{format}"
    body = _json_text(results, "results")
    if test_execution_info is None:
        return await client.request(
            "POST", base, content=body, headers={"Content-Type": "application/json"}
        )
    return await client.request(
        "POST",
        base + "/multipart",
        files={
            "results": ("results.json", body, "application/json"),
            "info": _json_part("info", test_execution_info),
        },
    )


@toolset.tool(read_only=False)
async def xray_import_execution_results_xml(
    results: Annotated[str, Field(description="The XML report content.")],
    format: Annotated[Literal["junit", "testng", "nunit", "xunit", "robot"], Field(description="Report format.")],
    project_key: Annotated[str | None, Field(description="Project for a new Test Execution.")] = None,
    test_execution_key: Annotated[str | None, Field(description="Import into this existing Test Execution.")] = None,
    test_plan_key: Annotated[str | None, Field(description="Link the Test Execution to this Test Plan.")] = None,
    test_environments: Annotated[list[str] | None, Field(description="Test Environment names.")] = None,
    revision: Annotated[str | None, Field(description="Source code revision.")] = None,
    fix_version: Annotated[str | None, Field(description="Fix version of the Test Execution.")] = None,
    test_execution_info: IssueFields = None,
    test_info: TestInfo = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Import an XML test report (JUnit, TestNG, NUnit, xUnit, Robot Framework) into Xray.

    Either use the simple parameters (project_key, test_execution_key, ...), or pass
    test_execution_info / test_info for full control over the created issues (multipart import).
    """
    params = compact(
        projectKey=project_key,
        testExecKey=test_execution_key,
        testPlanKey=test_plan_key,
        testEnvironments=";".join(test_environments) if test_environments else None,
        revision=revision,
        fixVersion=fix_version,
    )
    path = f"/import/execution/{format}"
    if test_execution_info is None and test_info is None:
        if not params:
            raise ValueError("Pass project_key or test_execution_key (or test_execution_info).")
        return await client.request(
            "POST", path, params=params, content=results, headers={"Content-Type": "text/xml"}
        )
    if params:
        raise ValueError(
            "With test_execution_info / test_info, put project, test plan, environments etc. into "
            "test_execution_info instead of the simple parameters."
        )
    files: dict[str, tuple[str, bytes | str, str]] = {"results": ("results.xml", results, "text/xml")}
    files["info"] = _json_part("info", test_execution_info or {"fields": {}})
    if test_info is not None:
        files["testInfo"] = _json_part("testInfo", test_info)
    return await client.request("POST", path + "/multipart", files=files)


@toolset.tool(read_only=False)
async def xray_import_tests_bulk(
    tests: Annotated[
        list[dict[str, Any]],
        Field(
            max_length=1000,
            description=(
                "Tests to create/update (max 1000). Each: {'testtype': 'Manual'|'Cucumber'|'Generic', "
                "'fields': {'summary': ..., 'project': {'key': ...}}, 'steps': [{'action','data','result'}], "
                "'gherkin_def': ..., 'unstructured_def': ..., 'xray_test_repository_folder': '/path', "
                "'xray_test_sets': [...], 'xray_preconditions': [...], 'update': {...}}."
            ),
        ),
    ],
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Start an asynchronous bulk import of Tests. Poll xray_get_import_tests_status with the returned jobId."""
    return await client.request("POST", "/import/test/bulk", json=tests)


@toolset.tool(read_only=True)
async def xray_get_import_tests_status(
    job_id: Annotated[str, Field(description="jobId returned by xray_import_tests_bulk.")],
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Get status, progress and per-test results/errors of a bulk test import job."""
    return await client.request("GET", f"/import/test/bulk/{job_id}/status")


@toolset.tool(read_only=False)
async def xray_import_cucumber_features(
    project: Annotated[str, Field(description="Jira project key or id.")],
    feature: Annotated[str | None, Field(description="Content of a single .feature file.")] = None,
    zip_base64: Annotated[str | None, Field(description="Base64 zip containing several .feature files.")] = None,
    filename: Annotated[str | None, Field(description="File name, e.g. 'login.feature'.")] = None,
    source: Annotated[
        str | None, Field(description="Name of the import source, used to match previously imported scenarios.")
    ] = None,
    test_info: TestInfo = None,
    precondition_info: Annotated[
        dict[str, Any] | None, Field(description="Jira payload applied to created Preconditions.")
    ] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Create or update Cucumber Tests and Preconditions from .feature files (single file or zip)."""
    if (feature is None) == (zip_base64 is None):
        raise ValueError("Pass exactly one of feature or zip_base64.")
    if feature is not None:
        part: tuple[str, bytes | str, str] = (filename or "import.feature", feature.encode(), "text/plain")
    else:
        assert zip_base64 is not None
        part = (filename or "features.zip", decode_base64(zip_base64, "zip_base64"), "application/zip")
    files: dict[str, tuple[str, bytes | str, str]] = {"file": part}
    if test_info is not None:
        files["testInfo"] = _json_part("testInfo", test_info)
    if precondition_info is not None:
        files["precondInfo"] = _json_part("precondInfo", precondition_info)
    params = compact(
        projectId=project if project.isdigit() else None,
        projectKey=None if project.isdigit() else project,
        source=source,
    )
    return await client.request("POST", "/import/feature", params=params, files=files)


@toolset.tool(read_only=True)
async def xray_export_cucumber_features(
    keys: Annotated[
        list[str] | None, Field(description="Issue keys (Tests, Test Sets, Test Plans, Test Executions, requirements).")
    ] = None,
    filter_id: Annotated[str | None, Field(description="Jira saved filter id.")] = None,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Export Cucumber Tests as .feature files; returns each file's name and content."""
    if not keys and not filter_id:
        raise ValueError("Pass keys and/or filter_id.")
    content = await client.request(
        "GET",
        "/export/cucumber",
        params=compact(keys=";".join(keys) if keys else None, filter=filter_id),
        response="bytes",
    )
    if len(content) > client.settings.max_download_bytes:
        raise ValueError(f"Export is {len(content)} bytes, above XRAY_MAX_DOWNLOAD_BYTES.")
    files: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if sum(i.file_size for i in archive.infolist()) > client.settings.max_download_bytes:
            raise ValueError("Unpacked export is above XRAY_MAX_DOWNLOAD_BYTES; export fewer issues.")
        for info in archive.infolist():
            if not info.is_dir():
                files[info.filename] = archive.read(info).decode("utf-8", errors="replace")
    return {"files": files}

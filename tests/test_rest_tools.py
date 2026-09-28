# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""REST-backed tools: endpoints, parameters, content types and multipart parts."""

import base64
import io
import json
import zipfile
from email.parser import BytesParser
from email.policy import default

import httpx2

from tests.conftest import Call


def multipart_parts(call: Call) -> dict[str, tuple[str | None, bytes]]:
    """Parse a multipart/form-data body into {part name: (filename, content)}."""
    raw = b"Content-Type: " + call.headers["content-type"].encode() + b"\r\n\r\n" + call.body
    message = BytesParser(policy=default).parsebytes(raw)
    parts = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        parts[name] = (part.get_filename(), part.get_payload(decode=True))
    return parts


async def test_import_xray_json(connect, fake) -> None:
    fake.rest = lambda call: httpx2.Response(200, json={"id": "10200", "key": "CALC-24"})
    results = {"testExecutionKey": "CALC-5", "tests": [{"testKey": "CALC-1", "status": "PASSED"}]}
    async with connect() as client:
        out = (await client.call_tool("xray_import_execution_results_json", {"results": results})).data
    assert out == {"id": "10200", "key": "CALC-24"}
    call = fake.rest_calls[0]
    assert (call.method, call.path) == ("POST", "/api/v2/import/execution")
    assert call.headers["content-type"] == "application/json"
    assert call.json == results


async def test_import_cucumber_multipart(connect, fake) -> None:
    info = {"fields": {"project": {"key": "CALC"}, "summary": "BDD run"}}
    async with connect() as client:
        await client.call_tool(
            "xray_import_execution_results_json",
            {"results": "[]", "format": "cucumber", "test_execution_info": info},
        )
    call = fake.rest_calls[0]
    assert call.path == "/api/v2/import/execution/cucumber/multipart"
    parts = multipart_parts(call)
    assert parts["results"][1] == b"[]"
    assert json.loads(parts["info"][1]) == info


async def test_import_json_rejects_invalid_json(connect, fake) -> None:
    async with connect() as client:
        result = await client.call_tool(
            "xray_import_execution_results_json", {"results": "{not json"}, raise_on_error=False
        )
    assert result.is_error
    assert fake.rest_calls == []


async def test_import_junit_with_query_params(connect, fake) -> None:
    async with connect() as client:
        await client.call_tool(
            "xray_import_execution_results_xml",
            {
                "results": "<testsuite/>",
                "format": "junit",
                "project_key": "CALC",
                "test_plan_key": "CALC-4",
                "test_environments": ["Chrome", "Linux"],
                "revision": "abc123",
            },
        )
    call = fake.rest_calls[0]
    assert call.path == "/api/v2/import/execution/junit"
    assert call.params == {
        "projectKey": "CALC",
        "testPlanKey": "CALC-4",
        "testEnvironments": "Chrome;Linux",
        "revision": "abc123",
    }
    assert call.headers["content-type"] == "text/xml"
    assert call.body == b"<testsuite/>"


async def test_import_robot_multipart(connect, fake) -> None:
    async with connect() as client:
        await client.call_tool(
            "xray_import_execution_results_xml",
            {
                "results": "<robot/>",
                "format": "robot",
                "test_execution_info": {"fields": {"project": {"key": "CALC"}}},
                "test_info": {"fields": {"labels": ["auto"]}},
            },
        )
    call = fake.rest_calls[0]
    assert call.path == "/api/v2/import/execution/robot/multipart"
    parts = multipart_parts(call)
    assert set(parts) == {"results", "info", "testInfo"}
    assert parts["results"][1] == b"<robot/>"


async def test_import_xml_rejects_mixed_modes(connect, fake) -> None:
    async with connect() as client:
        result = await client.call_tool(
            "xray_import_execution_results_xml",
            {"results": "<x/>", "format": "nunit", "project_key": "CALC", "test_info": {}},
            raise_on_error=False,
        )
    assert result.is_error
    assert fake.rest_calls == []


async def test_bulk_import_and_status(connect, fake) -> None:
    fake.rest = lambda call: httpx2.Response(
        200, json={"jobId": "j1"} if call.method == "POST" else {"status": "successful"}
    )
    tests = [{"testtype": "Manual", "fields": {"summary": "a", "project": {"key": "CALC"}}}]
    async with connect() as client:
        started = (await client.call_tool("xray_import_tests_bulk", {"tests": tests})).data
        status = (await client.call_tool("xray_get_import_tests_status", {"job_id": "j1"})).data
    assert started == {"jobId": "j1"} and status == {"status": "successful"}
    assert fake.rest_calls[0].json == tests
    assert fake.rest_calls[1].path == "/api/v2/import/test/bulk/j1/status"


async def test_import_feature_file(connect, fake) -> None:
    async with connect() as client:
        await client.call_tool(
            "xray_import_cucumber_features",
            {"project": "CALC", "feature": "Feature: Login", "filename": "login.feature", "source": "repo"},
        )
    call = fake.rest_calls[0]
    assert call.path == "/api/v2/import/feature"
    assert call.params == {"projectKey": "CALC", "source": "repo"}
    assert multipart_parts(call)["file"] == ("login.feature", b"Feature: Login")


async def test_export_cucumber_unzips(connect, fake) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("1_CALC-1.feature", "Feature: A")
    fake.rest = lambda call: httpx2.Response(200, content=buf.getvalue())
    async with connect() as client:
        out = (await client.call_tool("xray_export_cucumber_features", {"keys": ["CALC-1", "CALC-2"]})).data
    assert out == {"files": {"1_CALC-1.feature": "Feature: A"}}
    assert fake.rest_calls[0].params == {"keys": "CALC-1;CALC-2"}


async def test_attachment_upload_and_download(connect, fake) -> None:
    def rest(call):
        if call.method == "POST":
            return httpx2.Response(200, json={"id": "att-1", "filename": "a.png"})
        return httpx2.Response(200, content=b"\x89PNG\x00\xff")

    fake.rest = rest
    async with connect() as client:
        up = (
            await client.call_tool(
                "xray_upload_attachment",
                {"filename": "a.png", "content_base64": base64.b64encode(b"img").decode(), "mime_type": "image/png"},
            )
        ).data
        down = (await client.call_tool("xray_get_attachment", {"attachment_id": "att-1"})).data
    assert up["id"] == "att-1"
    assert multipart_parts(fake.rest_calls[0])["attachment"] == ("a.png", b"img")
    assert fake.rest_calls[1].path == "/api/v2/attachments/att-1"
    assert base64.b64decode(down["base64"]) == b"\x89PNG\x00\xff"


async def test_download_size_limit(connect, fake) -> None:
    fake.rest = lambda call: httpx2.Response(200, content=b"x" * 100)
    async with connect(max_download_bytes=10) as client:
        result = await client.call_tool("xray_get_attachment", {"attachment_id": "a"}, raise_on_error=False)
    assert result.is_error
    assert "XRAY_MAX_DOWNLOAD_BYTES" in result.content[0].text


async def test_backup(connect, fake) -> None:
    fake.rest = lambda call: httpx2.Response(200, json={"jobId": "b1"})
    async with connect() as client:
        await client.call_tool("xray_create_backup", {"projects": ["CALC"], "exclude_issue_history": True})
        await client.call_tool("xray_get_backup_status", {"job_id": "b1"})
    create, status = fake.rest_calls
    assert create.path == "/api/v2/backup"
    assert create.json == {"projectIds": ["10000"], "excludeIssueHistory": True}
    assert status.path == "/api/v2/backup/b1/status"

# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Shared parameter types, the client dependency, and issue key -> id resolution."""

import base64
import binascii
import re
from typing import Annotated, Any, Literal

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from xray_mcp.client import XrayApiError, XrayClient, credentials_from_headers


def _get_client(ctx: Context = CurrentContext()) -> XrayClient:
    client: XrayClient = ctx.lifespan_context["xray"]
    if client.settings.auth_mode == "headers":
        # Missing headers bind no credentials; the first API call then explains what to send.
        return client.with_credentials(credentials_from_headers(get_http_headers()))
    return client


# Injected into every tool; hidden from the tool's input schema.
XRAY = Depends(_get_client)

DEFAULT_JIRA_FIELDS = ["key", "summary", "status", "issuetype", "project", "assignee", "labels"]

IssueRef = Annotated[str, Field(description="Jira issue key (e.g. 'CALC-12') or numeric issue id.")]
IssueRefs = Annotated[list[str], Field(description="Jira issue keys (e.g. 'CALC-12') or numeric issue ids.")]
Limit = Annotated[int, Field(ge=1, le=100, description="Page size (1-100).")]
Start = Annotated[int, Field(ge=0, description="Page offset (index of the first result).")]
JiraFields = Annotated[
    list[str] | None,
    Field(description=f"Jira fields to return in 'jira'. Default: {DEFAULT_JIRA_FIELDS}."),
]
ExtraJiraFields = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Additional Jira fields for the new issue, in Jira REST format, e.g. "
            '{"description": "...", "labels": ["smoke"], "fixVersions": [{"name": "1.0"}]}.'
        )
    ),
]
ModifiedSince = Annotated[
    str | None, Field(description="Only return issues modified after this date (ISO 8601, e.g. '2026-01-31').")
]
ProjectRef = Annotated[str, Field(description="Jira project key (e.g. 'CALC') or numeric project id.")]


class StepInput(BaseModel):
    """A manual test step."""

    action: str = Field(description="What the tester does.")
    data: str | None = Field(default=None, description="Input data for the step.")
    result: str | None = Field(default=None, description="Expected result.")


class AttachmentData(BaseModel):
    """A file to attach, inline as base64 or by id of a file uploaded via xray_upload_attachment."""

    filename: str | None = Field(default=None, description="File name, required with 'data'.")
    mime_type: str | None = Field(default=None, description="Content type, e.g. 'image/png'.")
    data: str | None = Field(default=None, description="File content, base64 encoded.")
    attachment_id: str | None = Field(default=None, description="Id returned by xray_upload_attachment.")

    def to_graphql(self) -> dict[str, Any]:
        out = {
            "filename": self.filename,
            "mimeType": self.mime_type,
            "data": self.data,
            "attachmentId": self.attachment_id,
        }
        return {k: v for k, v in out.items() if v is not None}


def jira_fields(fields: list[str] | None) -> list[str]:
    return fields or DEFAULT_JIRA_FIELDS


def jira_payload(project_key: str, summary: str, extra: dict[str, Any] | None) -> dict[str, Any]:
    """Build the ``jira: JSON!`` argument of Xray's create mutations."""
    fields: dict[str, Any] = dict(extra or {})
    fields["summary"] = summary
    fields["project"] = {"id": project_key} if project_key.isdigit() else {"key": project_key}
    return {"fields": fields}


def compact(**values: Any) -> dict[str, Any]:
    """Drop None values, so optional GraphQL/REST arguments are left out."""
    return {k: v for k, v in values.items() if v is not None}


# --- issue key -> issue id resolution -------------------------------------------------

_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")

IssueKind = Literal["test", "precondition", "test_set", "test_plan", "test_execution", "coverable"]

_LIST_QUERY: dict[str, str] = {
    "test": "getTests",
    "precondition": "getPreconditions",
    "test_set": "getTestSets",
    "test_plan": "getTestPlans",
    "test_execution": "getTestExecutions",
    "coverable": "getCoverableIssues",
}

_KIND_LABEL = {
    "test": "Test",
    "precondition": "Precondition",
    "test_set": "Test Set",
    "test_plan": "Test Plan",
    "test_execution": "Test Execution",
    "coverable": "coverable issue",
}


async def resolve_ids(client: XrayClient, kind: IssueKind, refs: list[str] | None) -> list[str] | None:
    """Map issue keys to Xray issue ids (numeric refs pass through), preserving order.

    Xray's GraphQL API only accepts issue ids; keys are looked up through the matching
    ``get<Kind>s(jql: "key in (...)")`` query, which also verifies the issue type.
    """
    if refs is None:
        return None
    keys: list[str] = []
    for ref in refs:
        ref = ref.strip()
        if ref.isdigit():
            continue
        if not _KEY_RE.match(ref):
            raise XrayApiError(f"{ref!r} is neither a Jira issue key nor a numeric issue id.")
        keys.append(ref.upper())
    found: dict[str, str] = {}
    unique = list(dict.fromkeys(keys))
    op = _LIST_QUERY[kind]
    for i in range(0, len(unique), 100):
        chunk = unique[i : i + 100]
        # Keys are validated against _KEY_RE above, so quoting them into JQL is safe.
        jql = "key in (" + ",".join(f'"{k}"' for k in chunk) + ")"
        data = await client.graphql(
            f"query($jql: String!, $limit: Int!) {{ {op}(jql: $jql, limit: $limit) "
            '{ results { issueId jira(fields: ["key"]) } } }',
            {"jql": jql, "limit": len(chunk)},
        )
        for item in (data.get(op) or {}).get("results") or []:
            key = str((item.get("jira") or {}).get("key", "")).upper()
            if key:
                found[key] = item["issueId"]
    missing = [k for k in unique if k not in found]
    if missing:
        raise XrayApiError(f"No {_KIND_LABEL[kind]} found for: {', '.join(missing)}")
    return [ref.strip() if ref.strip().isdigit() else found[ref.strip().upper()] for ref in refs]


async def resolve_id(client: XrayClient, kind: IssueKind, ref: str) -> str:
    ids = await resolve_ids(client, kind, [ref])
    assert ids is not None
    return ids[0]


async def resolve_project_id(client: XrayClient, project: str) -> str:
    """Folder mutations need the numeric Jira project id; look keys up via project settings."""
    if project.isdigit():
        return project
    data = await client.graphql(
        "query($p: String) { getProjectSettings(projectIdOrKey: $p) { projectId } }", {"p": project}
    )
    project_id = (data.get("getProjectSettings") or {}).get("projectId")
    if not project_id:
        raise XrayApiError(f"Jira project {project!r} not found or Xray not enabled for it.")
    return project_id


# --- GraphQL selections ------------------------------------------------------------------

KEY_ONLY = 'issueId jira(fields: ["key", "summary"])'

STEPS = "steps { id action data result callTestIssueId attachments { id filename } }"

# Steps of an ExpandedTest: 'Call Test' steps replaced by the called Test's steps.
EXPANDED_STEPS = "steps { id action data result calledTestIssueId parentTestIssueId attachments { id filename } }"

TEST_SUMMARY = "issueId projectId lastModified testType { name kind } folder { path } jira(fields: $jiraFields)"


def test_selection(*, steps: bool = True, definition: bool = True, expanded: bool = False) -> str:
    parts = [TEST_SUMMARY]
    if steps:
        parts.append(EXPANDED_STEPS if expanded else STEPS)
    if definition:
        parts.append("unstructured gherkin scenarioType")
    return " ".join(parts)


def related(field_name: str, limit: int = 100) -> str:
    """Selection for a related-issue connection: ids and keys of the first ``limit`` items."""
    return f"{field_name}(limit: {limit}) {{ total results {{ {KEY_ONLY} }} }}"


# Requirements (coverable issues) a Test covers.
REQUIREMENTS = related("coverableIssues")

TEST_RUN_SUMMARY = (
    "id status { name color } comment startedOn finishedOn assigneeId executedById defects lastModified "
    "test { issueId jira(fields: [\"key\", \"summary\"]) } "
    "testExecution { issueId jira(fields: [\"key\", \"summary\"]) } "
    "testType { name kind }"
)

TEST_RUN_DETAIL = (
    TEST_RUN_SUMMARY
    + " unstructured gherkin scenarioType"
    + " evidence { id filename size createdOn downloadLink }"
    + " steps { id status { name } action data result actualResult comment defects"
    + " evidence { id filename } attachments { id filename } }"
    + " examples { id status { name } duration }"
    + " customFields { id name values }"
    + " parameters { name value }"
    + " iterations(limit: 100) { total results { rank status { name } parameters { name value } } }"
    + " testVersion { id name }"
)


# --- shared operations ---------------------------------------------------------------------


async def search_issues(
    client: XrayClient,
    op: str,
    selection: str,
    *,
    kind: IssueKind,
    jql: str | None,
    issues: list[str] | None,
    project: str | None,
    modified_since: str | None,
    limit: int,
    start: int,
    fields: list[str] | None,
    extra_args: dict[str, tuple[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one of the ``get<Kind>s`` search queries, which share the same core arguments.

    ``extra_args`` maps argument name -> (GraphQL type, value) for query-specific arguments.
    """
    args: dict[str, tuple[str, Any]] = {
        "jql": ("String", jql),
        "issueIds": ("[String]", await resolve_ids(client, kind, issues)),
        "projectId": ("String", await resolve_project_id(client, project) if project else None),
        "modifiedSince": ("String", modified_since),
        "limit": ("Int!", limit),
        "start": ("Int", start),
        **(extra_args or {}),
    }
    decl = ", ".join(f"${name}: {gql_type}" for name, (gql_type, _) in args.items())
    call = ", ".join(f"{name}: ${name}" for name in args)
    data = await client.graphql(
        f"query({decl}, $jiraFields: [String]) {{ {op}({call}) {{ total start limit results {{ {selection} }} }} }}",
        compact(jiraFields=jira_fields(fields), **{name: value for name, (_, value) in args.items()}),
    )
    return data.get(op) or {}


async def change_tests(
    client: XrayClient, op: str, kind: IssueKind, issue: str, tests: list[str], *, add: bool
) -> dict[str, Any]:
    """Run an ``addTestsTo<X>`` / ``removeTestsFrom<X>`` mutation for a container issue."""
    selection = " { addedTests warning }" if add else ""
    data = await client.graphql(
        f"mutation($id: String!, $ids: [String]!) {{ {op}(issueId: $id, testIssueIds: $ids){selection} }}",
        {"id": await resolve_id(client, kind, issue), "ids": await resolve_ids(client, "test", tests)},
    )
    result = data.get(op)
    return result if isinstance(result, dict) else {"result": result}


async def delete_issue(client: XrayClient, op: str, kind: IssueKind, issue: str) -> dict[str, Any]:
    data = await client.graphql(
        f"mutation($id: String!) {{ {op}(issueId: $id) }}", {"id": await resolve_id(client, kind, issue)}
    )
    return {"result": data.get(op)}


ISSUE_SUMMARY = "issueId projectId lastModified jira(fields: $jiraFields)"


def inline_file(content: bytes, *, max_bytes: int, filename: str | None = None) -> dict[str, Any]:
    """Return file content for the model: UTF-8 text as-is, anything else base64 encoded."""
    if len(content) > max_bytes:
        raise XrayApiError(
            f"File is {len(content)} bytes, above the inline limit of {max_bytes} bytes (XRAY_MAX_DOWNLOAD_BYTES)."
        )
    out: dict[str, Any] = compact(filename=filename, size=len(content))
    try:
        out["text"] = content.decode("utf-8")
    except UnicodeDecodeError:
        out["base64"] = base64.b64encode(content).decode("ascii")
    return out


def decode_base64(data: str, what: str) -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{what} is not valid base64: {exc}") from exc

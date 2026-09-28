# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Xray data backups (REST, admin). Opt-in: not part of the default toolsets."""

from typing import Annotated, Any

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import XRAY, compact, inline_file, resolve_project_id

toolset = Toolset("backup", "Xray data backups (requires Xray admin).", default=False)


@toolset.tool(read_only=False)
async def xray_create_backup(
    projects: Annotated[list[str] | None, Field(description="Only these Jira projects (keys or ids).")] = None,
    modified_since: Annotated[str | None, Field(description="Partial backup of data modified since this date.")] = None,
    with_attachments: bool = False,
    exclude_issue_history: bool = False,
    exclude_archived_test_runs: bool = False,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Start an asynchronous Xray backup job. Poll xray_get_backup_status with the returned jobId."""
    body = compact(
        projectIds=[await resolve_project_id(client, p) for p in projects] if projects else None,
        modifiedSince=modified_since,
        withAttachment=with_attachments or None,
        excludeIssueHistory=exclude_issue_history or None,
        excludeArchivedTestRuns=exclude_archived_test_runs or None,
    )
    return await client.request("POST", "/backup", json=body or None)


@toolset.tool(read_only=True)
async def xray_get_backup_status(
    job_id: Annotated[str, Field(description="jobId returned by xray_create_backup.")], client: XrayClient = XRAY
) -> dict[str, Any]:
    """Get the status of a backup job."""
    return await client.request("GET", f"/backup/{job_id}/status")


@toolset.tool(read_only=True)
async def xray_download_backup(
    attachments: Annotated[bool, Field(description="Download the attachments archive instead of the data.")] = False,
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Download the latest backup (zip, base64) if it fits the inline size limit."""
    path = "/backup/file/attachment" if attachments else "/backup/file"
    content = await client.request("GET", path, response="bytes")
    return inline_file(
        content,
        max_bytes=client.settings.max_download_bytes,
        filename="xray-backup-attachments.zip" if attachments else "xray-backup.zip",
    )

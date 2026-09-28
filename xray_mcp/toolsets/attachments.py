# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Xray attachment storage (REST)."""

from typing import Annotated, Any

from pydantic import Field

from xray_mcp.client import XrayClient
from xray_mcp.registry import Toolset
from xray_mcp.toolsets._common import XRAY, decode_base64, inline_file

toolset = Toolset("attachments", "Files in Xray's attachment storage.")


@toolset.tool(read_only=False)
async def xray_upload_attachment(
    filename: str,
    content_base64: Annotated[str | None, Field(description="File content, base64 encoded.")] = None,
    text: Annotated[str | None, Field(description="File content as text (UTF-8), instead of base64.")] = None,
    mime_type: Annotated[str, Field(description="Content type, e.g. 'image/png'.")] = "application/octet-stream",
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Upload a file; the returned id can be used as attachment_id in evidence / step attachments."""
    if (content_base64 is None) == (text is None):
        raise ValueError("Pass exactly one of content_base64 or text.")
    content = text.encode() if text is not None else decode_base64(content_base64 or "", "content_base64")
    return await client.request("POST", "/attachments", files={"attachment": (filename, content, mime_type)})


@toolset.tool(read_only=True)
async def xray_get_attachment(
    attachment_id: Annotated[str, Field(description="Attachment or evidence id.")],
    client: XrayClient = XRAY,
) -> dict[str, Any]:
    """Download an attachment or evidence file; text files come back as text, others as base64."""
    content = await client.request("GET", f"/attachments/{attachment_id}", response="bytes")
    return inline_file(content, max_bytes=client.settings.max_download_bytes)

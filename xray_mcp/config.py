# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Server configuration, read from ``XRAY_*`` environment variables."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE_URL = "https://xray.cloud.getxray.app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XRAY_", extra="ignore")

    auth_mode: Literal["env", "headers"] = Field(
        default="env",
        description=(
            "Where the Xray API key comes from: 'env' (XRAY_CLIENT_ID / XRAY_CLIENT_SECRET, one key for "
            "the server) or 'headers' (X-Xray-Client-Id / X-Xray-Client-Secret on every HTTP request)."
        ),
    )
    client_id: str | None = Field(default=None, description="Xray API key client id (auth_mode 'env').")
    client_secret: SecretStr | None = Field(default=None, description="Xray API key client secret (auth_mode 'env').")
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        description="Xray Cloud base URL; regional hosts are us./eu./au.xray.cloud.getxray.app.",
    )
    read_only: bool = Field(default=False, description="Register read tools only.")
    # Kept as raw strings: pydantic-settings would otherwise expect JSON for a list.
    toolsets: str = Field(
        default="default",
        description=(
            "Comma-separated toolset selection, applied left to right. Tokens: 'default', 'all', a toolset "
            "('tests_read'), a group ('tests' = tests_read + tests_write), '*' wildcards, '-token' to remove. "
            "Example: 'default,backup,-*_write,test_runs_write'."
        ),
    )
    tools: str = Field(
        default="",
        description=(
            "Comma-separated tool names added to ('name') or removed from ('-name') the toolset selection, "
            "applied left to right; '*' wildcards allowed. Example: '-xray_delete_*,xray_get_test_run'."
        ),
    )
    timeout: float = Field(default=60.0, gt=0, description="HTTP timeout in seconds.")
    max_download_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        description="Largest file an attachment/backup/export tool returns inline.",
    )

    @property
    def api_url(self) -> str:
        return self.base_url.rstrip("/") + "/api/v2"

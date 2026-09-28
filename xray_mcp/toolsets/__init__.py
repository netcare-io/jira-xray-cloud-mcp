# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""All available toolsets, in the order they are listed and registered."""

from xray_mcp.registry import Toolset
from xray_mcp.toolsets import (
    attachments,
    backup,
    coverage,
    graphql,
    history,
    imports,
    preconditions,
    settings,
    test_executions,
    test_plans,
    test_repository,
    test_runs,
    test_sets,
    tests,
)

ALL_TOOLSETS: list[Toolset] = [
    tests.toolset,
    preconditions.toolset,
    test_sets.toolset,
    test_plans.toolset,
    test_executions.toolset,
    test_runs.toolset,
    test_repository.toolset,
    coverage.toolset,
    history.toolset,
    settings.toolset,
    imports.toolset,
    attachments.toolset,
    backup.toolset,
    graphql.toolset,
]

# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Toolset and tool selection, and the read-only switch."""

import pytest

from xray_mcp.registry import select_tools, select_toolsets, toolset_parts
from xray_mcp.toolsets import ALL_TOOLSETS

ALL_PARTS = [part.name for part in toolset_parts(ALL_TOOLSETS)]
WRITE_TOOLS = {spec.name for ts in ALL_TOOLSETS for spec in ts.tools if not spec.read_only}


def names(spec: str) -> list[str]:
    return [part.name for part in select_toolsets(spec, ALL_TOOLSETS)]


def tools(toolsets: str, tools_spec: str) -> list[str]:
    return [spec.name for _, spec in select_tools(toolsets, tools_spec, ALL_TOOLSETS).tools]


def test_toolsets_are_split_into_read_and_write_halves() -> None:
    assert {"tests_read", "tests_write", "coverage_read"} <= set(ALL_PARTS)
    assert "coverage_write" not in ALL_PARTS  # no write tools, so no write half
    for part in toolset_parts(ALL_TOOLSETS):
        assert part.tools and all(spec.read_only == (part.access == "read") for spec in part.tools)


def test_default_excludes_opt_in_toolsets() -> None:
    assert not {"backup_read", "backup_write"} & set(names("default"))
    assert "tests_write" in names("default")
    assert names("") == names("default")


def test_all_groups_and_order() -> None:
    assert names("all") == ALL_PARTS
    assert names("test_runs, tests") == ["tests_read", "tests_write", "test_runs_read", "test_runs_write"]
    assert names("test_runs_write,tests_read") == ["tests_read", "test_runs_write"]  # declaration order
    assert names("default,backup") == ALL_PARTS


def test_exclusion_and_wildcards() -> None:
    assert names("all,-backup,-graphql") == [n for n in ALL_PARTS if not n.startswith(("backup_", "graphql_"))]
    assert names("*_read") == [n for n in ALL_PARTS if n.endswith("_read")]
    assert names("default,-*_write,test_runs_write") == [
        n for n in names("default") if n.endswith("_read") or n == "test_runs_write"
    ]
    assert names("tests,-tests") == []


@pytest.mark.parametrize("spec", ["default,testz", "tests_writ", "foo_*", "-nope"])
def test_unknown_toolset_fails_fast(spec: str) -> None:
    with pytest.raises(ValueError, match="Unknown Xray toolset"):
        select_toolsets(spec, ALL_TOOLSETS)


def test_every_tool_belongs_to_exactly_one_toolset() -> None:
    tool_names = [spec.name for ts in ALL_TOOLSETS for spec in ts.tools]
    assert len(tool_names) == len(set(tool_names))
    assert all(name.startswith("xray_") for name in tool_names)


def test_tool_filter_adds_and_removes() -> None:
    base = tools("tests_read", "")
    assert "xray_get_test" in base and "xray_create_test" not in base
    assert tools("tests_read", "xray_create_test") == [*base, "xray_create_test"]
    assert "xray_get_test" not in tools("tests_read", "-xray_get_test")
    # Left to right: a later token wins.
    assert "xray_get_test" in tools("tests_read", "-xray_get_test,xray_get_test")
    # Tools from toolsets that are not selected at all.
    assert tools("tests_read", "xray_get_test_run,xray_update_test_run")[-2:] == [
        "xray_get_test_run",
        "xray_update_test_run",
    ]


def test_tool_filter_wildcards() -> None:
    selected = tools("all", "-xray_delete_*")
    assert not [n for n in selected if n.startswith("xray_delete_")]
    assert "xray_create_test" in selected
    added = set(tools("coverage", "xray_get_test_run*")) - set(tools("coverage", ""))
    assert added == {"xray_get_test_run", "xray_get_test_runs"}


def test_unknown_tool_fails_fast_with_suggestion() -> None:
    with pytest.raises(ValueError, match="Unknown Xray tool 'xray_get_tset'.*xray_get_test"):
        select_tools("default", "xray_get_tset", ALL_TOOLSETS)
    with pytest.raises(ValueError, match="Unknown Xray tool"):
        select_tools("default", "-xray_nothing_*", ALL_TOOLSETS)


async def test_selected_toolsets_limit_registered_tools(connect) -> None:
    async with connect(toolsets="test_runs_read") as client:
        registered = {t.name for t in await client.list_tools()}
    expected = {spec.name for spec in next(p for p in toolset_parts(ALL_TOOLSETS) if p.name == "test_runs_read").tools}
    assert registered == expected | {"xray_list_toolsets"}


async def test_tool_filter_on_the_server(connect) -> None:
    async with connect(toolsets="tests_read", tools="-xray_get_datasets,xray_get_test_run") as client:
        registered = {t.name for t in await client.list_tools()}
    assert "xray_get_datasets" not in registered
    assert {"xray_get_test", "xray_get_test_run"} <= registered


async def test_read_only_registers_no_write_tools(connect) -> None:
    async with connect(read_only=True, tools="xray_delete_test") as client:
        listed = await client.list_tools()
    registered = {t.name for t in listed}
    # Read-only wins over XRAY_TOOLS.
    assert registered & WRITE_TOOLS == set()
    assert "xray_get_test" in registered
    assert all(t.annotations.read_only_hint for t in listed)


async def test_write_tool_cannot_be_called_in_read_only_mode(connect, fake) -> None:
    async with connect(read_only=True) as client:
        result = await client.call_tool("xray_delete_test", {"test": "1"}, raise_on_error=False)
    assert result.is_error
    assert fake.calls == []


async def test_annotations_and_tags(connect) -> None:
    async with connect() as client:
        listed = {t.name: t for t in await client.list_tools()}
    delete = listed["xray_delete_test"]
    assert delete.annotations.read_only_hint is False
    assert delete.annotations.destructive_hint is True
    assert set(delete.meta["fastmcp"]["tags"]) == {"toolset:tests_write", "write"}
    get = listed["xray_get_test"]
    assert get.annotations.read_only_hint is True
    assert set(get.meta["fastmcp"]["tags"]) == {"toolset:tests_read", "read"}


async def test_list_toolsets(connect) -> None:
    async with connect(toolsets="tests,graphql", tools="-xray_get_datasets", read_only=True) as client:
        info = (await client.call_tool("xray_list_toolsets", {})).data
    assert info["read_only"] is True and info["auth_mode"] == "env"
    by_name = {ts["name"]: ts for ts in info["toolsets"]}
    assert list(by_name) == ALL_PARTS
    assert by_name["tests_read"]["group"] == "tests" and by_name["tests_read"]["access"] == "read"
    assert by_name["tests_read"]["enabled"] and not by_name["test_runs_read"]["enabled"]
    assert "xray_get_test" in by_name["tests_read"]["tools"]
    assert "xray_get_datasets" not in by_name["tests_read"]["tools"]
    # Selected, but read-only mode registers none of its tools.
    assert by_name["graphql_write"]["enabled"] and by_name["graphql_write"]["tools"] == []
    assert by_name["test_runs_read"]["tools"] == []

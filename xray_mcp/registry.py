# Copyright (c) 2026 netcare GmbH. All rights reserved.
# SPDX-License-Identifier: MIT

"""Toolsets: named groups of tools, split into read and write halves that can be switched on/off."""

import difflib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations


@dataclass(frozen=True)
class ToolSpec:
    fn: Callable[..., Any]
    read_only: bool
    destructive: bool
    idempotent: bool

    @property
    def name(self) -> str:
        return self.fn.__name__


@dataclass
class Toolset:
    name: str
    description: str
    # Part of the 'default' selection; opt-in toolsets (e.g. backup) set this to False.
    default: bool = True
    tools: list[ToolSpec] = field(default_factory=list)

    def tool(
        self,
        *,
        read_only: bool,
        destructive: bool = False,
        idempotent: bool | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Declare a tool of this toolset. Read tools are idempotent unless stated otherwise."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.tools.append(
                ToolSpec(
                    fn=fn,
                    read_only=read_only,
                    destructive=destructive and not read_only,
                    idempotent=read_only if idempotent is None else idempotent,
                )
            )
            return fn

        return decorator


@dataclass(frozen=True)
class ToolsetPart:
    """The read or the write half of a toolset: the unit that XRAY_TOOLSETS selects."""

    toolset: Toolset
    access: Literal["read", "write"]

    @property
    def name(self) -> str:
        return f"{self.toolset.name}_{self.access}"

    @property
    def tools(self) -> list[ToolSpec]:
        return [spec for spec in self.toolset.tools if spec.read_only == (self.access == "read")]


@dataclass(frozen=True)
class Selection:
    parts: list[ToolsetPart]  # chosen by XRAY_TOOLSETS
    tools: list[tuple[ToolsetPart, ToolSpec]]  # after XRAY_TOOLS; read-only filtering happens at registration


def toolset_parts(available: Iterable[Toolset]) -> list[ToolsetPart]:
    """All non-empty toolset halves, in declaration order (read before write)."""
    parts = [ToolsetPart(ts, access) for ts in available for access in ("read", "write")]
    return [part for part in parts if part.tools]


def _apply(
    spec: str, names: list[str], aliases: dict[str, list[str]], selected: set[str], unknown: Callable[[str], str]
) -> list[str]:
    """Apply comma-separated tokens left to right: ``name`` adds, ``-name`` removes.

    A token is an alias or an fnmatch pattern over ``names``. A token that matches nothing
    raises, so a typo in the configuration fails at startup instead of silently changing tools.
    """
    selected = set(selected)
    for token in (t.strip() for t in spec.split(",")):
        if not token:
            continue
        remove = token.startswith("-")
        pattern = token[1:].strip() if remove else token
        matched = aliases.get(pattern) or [n for n in names if fnmatchcase(n, pattern)]
        if not matched:
            raise ValueError(unknown(pattern))
        if remove:
            selected.difference_update(matched)
        else:
            selected.update(matched)
    # Keep declaration order, independent of token order.
    return [n for n in names if n in selected]


def select_toolsets(spec: str, available: Iterable[Toolset]) -> list[ToolsetPart]:
    """Resolve a selection like ``"default,backup,-*_write"`` against the toolset halves.

    Tokens: ``default`` (the halves of default toolsets), ``all``, a half (``tests_read``), a
    group (``tests`` = ``tests_read`` + ``tests_write``), or a wildcard pattern (``*_read``).
    An empty selection means ``default``.
    """
    toolsets = list(available)
    parts = {part.name: part for part in toolset_parts(toolsets)}
    groups = {ts.name: [p.name for p in parts.values() if p.toolset is ts] for ts in toolsets}
    aliases = {
        "all": list(parts),
        "default": [n for n, part in parts.items() if part.toolset.default],
        **groups,
    }

    def unknown(name: str) -> str:
        valid = ", ".join(["all", "default", *groups, *parts])
        return f"Unknown Xray toolset {name!r} in XRAY_TOOLSETS. Valid: {valid}"

    names = _apply(spec if spec.strip() else "default", list(parts), aliases, set(), unknown)
    return [parts[n] for n in names]


def select_tools(toolsets: str, tools: str, available: Iterable[Toolset]) -> Selection:
    """Select toolset halves (XRAY_TOOLSETS), then add or remove single tools (XRAY_TOOLS)."""
    available = list(available)
    chosen = select_toolsets(toolsets, available)
    part_of = {spec.name: (part, spec) for part in toolset_parts(available) for spec in part.tools}

    def unknown(name: str) -> str:
        close = difflib.get_close_matches(name, part_of, n=3)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        return f"Unknown Xray tool {name!r} in XRAY_TOOLS.{hint}"

    initial = {spec.name for part in chosen for spec in part.tools}
    names = _apply(tools, list(part_of), {}, initial, unknown)
    return Selection(parts=chosen, tools=[part_of[n] for n in names])


def register_tools(mcp: FastMCP, tools: Iterable[tuple[ToolsetPart, ToolSpec]], *, read_only: bool) -> list[str]:
    """Register the selected tools; write tools are skipped in read-only mode.

    Filtering happens here rather than via visibility transforms, so a tool that is not
    allowed does not exist on the server at all and cannot be called.
    """
    registered: list[str] = []
    for part, spec in tools:
        if read_only and not spec.read_only:
            continue
        mcp.tool(
            spec.fn,
            name=spec.name,
            tags={f"toolset:{part.name}", part.access},
            annotations=ToolAnnotations(
                read_only_hint=spec.read_only,
                destructive_hint=spec.destructive,
                idempotent_hint=spec.idempotent,
                open_world_hint=True,
            ),
        )
        registered.append(spec.name)
    return registered

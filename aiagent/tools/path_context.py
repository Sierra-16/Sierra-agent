from __future__ import annotations

import os


_workspace: str | None = None


def set_tool_workspace(workspace: str | None) -> None:
    global _workspace
    _workspace = os.path.abspath(workspace or os.getcwd())


def get_tool_workspace() -> str:
    return _workspace or os.path.abspath(os.getcwd())


def resolve_workspace_path(path: str | None = None) -> str:
    raw = str(path or ".").strip() or "."
    expanded = os.path.expanduser(os.path.expandvars(raw))
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    return os.path.abspath(os.path.join(get_tool_workspace(), expanded))

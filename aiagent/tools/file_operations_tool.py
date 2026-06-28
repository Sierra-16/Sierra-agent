from __future__ import annotations

import json
import os
import shutil

from .path_context import resolve_workspace_path
from .registry import registry


FILE_INFO_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "File or directory path. Relative paths resolve under the user workspace.",
        }
    },
    "required": ["path"],
}

PATCH_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Text file to edit. Relative paths resolve under the user workspace.",
        },
        "old_text": {
            "type": "string",
            "description": "Exact text to replace. Must be unique unless replace_all is true.",
        },
        "new_text": {
            "type": "string",
            "description": "Replacement text.",
        },
        "replace_all": {
            "type": "boolean",
            "description": "Replace every occurrence instead of requiring a unique match.",
        },
    },
    "required": ["file_path", "old_text", "new_text"],
}

DELETE_PATH_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "File or directory to delete. Relative paths resolve under the user workspace.",
        },
        "recursive": {
            "type": "boolean",
            "description": "Required to delete non-empty directories.",
        },
    },
    "required": ["path"],
}

MOVE_PATH_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": "Source file or directory. Relative paths resolve under the user workspace.",
        },
        "destination": {
            "type": "string",
            "description": "Destination path. Relative paths resolve under the user workspace.",
        },
        "overwrite": {
            "type": "boolean",
            "description": "Allow replacing an existing destination.",
        },
    },
    "required": ["source", "destination"],
}

COPY_PATH_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": "Source file or directory. Relative paths resolve under the user workspace.",
        },
        "destination": {
            "type": "string",
            "description": "Destination path. Relative paths resolve under the user workspace.",
        },
        "overwrite": {
            "type": "boolean",
            "description": "Allow replacing an existing destination.",
        },
    },
    "required": ["source", "destination"],
}

MAKE_DIRECTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Directory to create. Relative paths resolve under the user workspace.",
        }
    },
    "required": ["path"],
}


def file_info(path: str) -> str:
    resolved = resolve_workspace_path(path)
    try:
        stat = os.stat(resolved)
        return json.dumps(
            {
                "path": resolved,
                "requested_path": path,
                "exists": True,
                "is_file": os.path.isfile(resolved),
                "is_directory": os.path.isdir(resolved),
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps(
            {
                "path": resolved,
                "requested_path": path,
                "exists": False,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def patch_file(
    file_path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> str:
    resolved = resolve_workspace_path(file_path)
    if old_text == "":
        return json.dumps({"error": "old_text cannot be empty"}, ensure_ascii=False)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_text)
        if count == 0:
            return json.dumps({"error": "old_text not found", "file_path": resolved}, ensure_ascii=False)
        if count > 1 and not replace_all:
            return json.dumps(
                {
                    "error": "old_text matched multiple times; set replace_all=true or provide more context",
                    "file_path": resolved,
                    "matches": count,
                },
                ensure_ascii=False,
            )
        limit = -1 if replace_all else 1
        updated = content.replace(old_text, new_text, limit)
        with open(resolved, "w", encoding="utf-8", newline="") as f:
            f.write(updated)
        replaced = count if replace_all else 1
        return json.dumps(
            {
                "file_path": resolved,
                "requested_path": file_path,
                "replaced": replaced,
                "status": "ok",
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps({"error": f"File not found: {resolved}"}, ensure_ascii=False)
    except PermissionError:
        return json.dumps({"error": f"Permission denied: {resolved}"}, ensure_ascii=False)
    except UnicodeDecodeError:
        return json.dumps({"error": f"File is not valid UTF-8 text: {resolved}"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def delete_path(path: str, recursive: bool = False) -> str:
    resolved = resolve_workspace_path(path)
    safety_error = _reject_broad_path(resolved)
    if safety_error:
        return json.dumps({"error": safety_error, "path": resolved}, ensure_ascii=False)
    try:
        if os.path.isdir(resolved) and not os.path.islink(resolved):
            if recursive:
                shutil.rmtree(resolved)
            else:
                if os.listdir(resolved):
                    return json.dumps(
                        {
                            "error": "Directory is not empty; set recursive=true to delete it",
                            "path": resolved,
                        },
                        ensure_ascii=False,
                    )
                os.rmdir(resolved)
            kind = "directory"
        else:
            os.remove(resolved)
            kind = "file"
        return json.dumps(
            {
                "path": resolved,
                "requested_path": path,
                "deleted": True,
                "kind": kind,
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps({"error": f"Path not found: {resolved}"}, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({"error": str(exc), "path": resolved}, ensure_ascii=False)


def move_path(source: str, destination: str, overwrite: bool = False) -> str:
    src = resolve_workspace_path(source)
    dst = resolve_workspace_path(destination)
    safety_error = _reject_broad_path(src)
    if safety_error:
        return json.dumps({"error": safety_error, "source": src}, ensure_ascii=False)
    try:
        if os.path.exists(dst):
            if not overwrite:
                return json.dumps({"error": f"Destination exists: {dst}"}, ensure_ascii=False)
            _remove_existing_destination(dst)
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.move(src, dst)
        return json.dumps(
            {
                "source": src,
                "destination": dst,
                "moved": True,
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps({"error": f"Source not found: {src}"}, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({"error": str(exc), "source": src, "destination": dst}, ensure_ascii=False)


def copy_path(source: str, destination: str, overwrite: bool = False) -> str:
    src = resolve_workspace_path(source)
    dst = resolve_workspace_path(destination)
    try:
        if os.path.exists(dst):
            if not overwrite:
                return json.dumps({"error": f"Destination exists: {dst}"}, ensure_ascii=False)
            _remove_existing_destination(dst)
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dst)
            kind = "directory"
        else:
            shutil.copy2(src, dst)
            kind = "file"
        return json.dumps(
            {
                "source": src,
                "destination": dst,
                "copied": True,
                "kind": kind,
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps({"error": f"Source not found: {src}"}, ensure_ascii=False)
    except OSError as exc:
        return json.dumps({"error": str(exc), "source": src, "destination": dst}, ensure_ascii=False)


def make_directory(path: str) -> str:
    resolved = resolve_workspace_path(path)
    safety_error = _reject_broad_path(resolved)
    if safety_error:
        return json.dumps({"error": safety_error, "path": resolved}, ensure_ascii=False)
    try:
        os.makedirs(resolved, exist_ok=True)
        return json.dumps(
            {
                "path": resolved,
                "requested_path": path,
                "created": True,
            },
            ensure_ascii=False,
        )
    except OSError as exc:
        return json.dumps({"error": str(exc), "path": resolved}, ensure_ascii=False)


def _remove_existing_destination(path: str) -> None:
    safety_error = _reject_broad_path(path)
    if safety_error:
        raise OSError(safety_error)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def _reject_broad_path(path: str) -> str:
    resolved = os.path.abspath(path)
    home = os.path.abspath(os.path.expanduser("~"))
    anchor = os.path.abspath(os.path.splitdrive(resolved)[0] + os.sep)
    if resolved in {anchor, home}:
        return f"Refusing to modify broad path: {resolved}"
    return ""


registry.register(
    name="file_info",
    description="Inspect whether a file or directory exists and return size/type metadata.",
    parameters=FILE_INFO_SCHEMA,
    handler=file_info,
    toolset="file",
)

registry.register(
    name="patch_file",
    description=(
        "Edit a UTF-8 text file by exact string replacement. Use this for small, targeted edits "
        "instead of shell commands."
    ),
    parameters=PATCH_FILE_SCHEMA,
    handler=patch_file,
    toolset="file",
    max_result_size_chars=100_000,
)

registry.register(
    name="delete_path",
    description="Delete a file or directory. Non-empty directories require recursive=true.",
    parameters=DELETE_PATH_SCHEMA,
    handler=delete_path,
    toolset="file",
    max_result_size_chars=100_000,
)

registry.register(
    name="move_path",
    description="Move or rename a file or directory.",
    parameters=MOVE_PATH_SCHEMA,
    handler=move_path,
    toolset="file",
    max_result_size_chars=100_000,
)

registry.register(
    name="copy_path",
    description="Copy a file or directory.",
    parameters=COPY_PATH_SCHEMA,
    handler=copy_path,
    toolset="file",
    max_result_size_chars=100_000,
)

registry.register(
    name="make_directory",
    description="Create a directory, including missing parents.",
    parameters=MAKE_DIRECTORY_SCHEMA,
    handler=make_directory,
    toolset="file",
    max_result_size_chars=100_000,
)

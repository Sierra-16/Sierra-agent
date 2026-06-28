import glob
import json
import os

from .path_context import resolve_workspace_path
from .registry import registry


SEARCH_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Glob pattern, such as '*.py' or '**/*.py'.",
        },
        "dir_path": {
            "type": "string",
            "description": "Base directory. Relative paths resolve under the user workspace.",
        },
        "offset": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of matches to skip. Defaults to 0.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "description": "Maximum number of matches to return. Defaults to 100.",
        },
    },
    "required": ["pattern"],
}


DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def search_files(pattern: str, dir_path: str = ".", offset: int = 0, limit: int = DEFAULT_LIMIT) -> str:
    resolved_dir = resolve_workspace_path(dir_path)
    try:
        search_path = os.path.join(resolved_dir, pattern)
        matches = sorted(glob.glob(search_path, recursive=True), key=str.lower)
        offset = max(0, _coerce_int(offset, 0))
        limit = min(max(_coerce_int(limit, DEFAULT_LIMIT), 1), MAX_LIMIT)
        paged_matches = matches[offset:offset + limit]
        next_offset = offset + len(paged_matches)
        has_more = next_offset < len(matches)
        return json.dumps(
            {
                "pattern": pattern,
                "dir_path": resolved_dir,
                "requested_dir_path": dir_path,
                "matches": paged_matches,
                "total": len(matches),
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                "next_offset": next_offset if has_more else None,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


registry.register(
    name="search_files",
    description="Search files with a glob pattern. Relative base paths resolve under the user workspace.",
    parameters=SEARCH_FILES_SCHEMA,
    handler=search_files,
    toolset="file",
    max_result_size_chars=100_000,
)


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

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
    },
    "required": ["pattern"],
}


def search_files(pattern: str, dir_path: str = ".") -> str:
    resolved_dir = resolve_workspace_path(dir_path)
    try:
        search_path = os.path.join(resolved_dir, pattern)
        matches = sorted(glob.glob(search_path, recursive=True), key=str.lower)
        return json.dumps(
            {
                "pattern": pattern,
                "dir_path": resolved_dir,
                "requested_dir_path": dir_path,
                "matches": matches,
                "total": len(matches),
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
)

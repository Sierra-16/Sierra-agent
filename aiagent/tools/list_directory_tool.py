import json
import os

from .path_context import resolve_workspace_path
from .registry import registry


LIST_DIR_SCHEMA = {
    "type": "object",
    "properties": {
        "dir_path": {
            "type": "string",
            "description": "Directory to list. Relative paths resolve under the user workspace.",
        }
    },
    "required": [],
}


def list_directory(dir_path: str = ".") -> str:
    resolved_dir = resolve_workspace_path(dir_path)
    try:
        items = sorted(os.listdir(resolved_dir), key=str.lower)
        files = []
        dirs = []
        for name in items:
            full = os.path.join(resolved_dir, name)
            if os.path.isdir(full):
                dirs.append(name + "/")
            else:
                size = os.path.getsize(full)
                files.append(f"{name} ({size} bytes)")
        return json.dumps(
            {
                "dir_path": resolved_dir,
                "requested_path": dir_path,
                "directories": dirs,
                "files": files,
                "total": len(items),
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps({"error": f"Directory not found: {resolved_dir}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


registry.register(
    name="list_directory",
    description="List files and directories. Relative paths resolve under the user workspace.",
    parameters=LIST_DIR_SCHEMA,
    handler=list_directory,
)

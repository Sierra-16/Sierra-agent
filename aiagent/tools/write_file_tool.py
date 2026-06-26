import json
import os

from .path_context import resolve_workspace_path
from .registry import registry


WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to write. Relative paths resolve under the user workspace.",
        },
        "content": {
            "type": "string",
            "description": "Text content to write.",
        },
    },
    "required": ["file_path", "content"],
}


def write_file(file_path: str, content: str) -> str:
    resolved_path = resolve_workspace_path(file_path)
    try:
        dir_path = os.path.dirname(resolved_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(resolved_path, "w", encoding="utf-8") as f:
            f.write(content)

        return json.dumps(
            {
                "file_path": resolved_path,
                "requested_path": file_path,
                "written": len(content),
                "status": "ok",
            },
            ensure_ascii=False,
        )
    except PermissionError:
        return json.dumps({"error": f"Permission denied: {resolved_path}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


registry.register(
    name="write_file",
    description="Write text to a file. Relative paths resolve under the user workspace.",
    parameters=WRITE_FILE_SCHEMA,
    handler=write_file,
)

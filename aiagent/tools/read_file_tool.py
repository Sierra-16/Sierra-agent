import json

from .path_context import resolve_workspace_path
from .registry import registry


READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to read. Relative paths resolve under the user workspace.",
        }
    },
    "required": ["file_path"],
}


def read_file(file_path: str) -> str:
    resolved_path = resolve_workspace_path(file_path)
    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            content = f.read()
        original_length = len(content)
        if original_length > 5000:
            content = content[:5000] + f"\n...(content truncated, total {original_length} chars)"
        return json.dumps(
            {
                "file_path": resolved_path,
                "requested_path": file_path,
                "content": content,
            },
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return json.dumps({"error": f"File not found: {resolved_path}"}, ensure_ascii=False)
    except PermissionError:
        return json.dumps({"error": f"Permission denied: {resolved_path}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


registry.register(
    name="read_file",
    description="Read a text file. Relative paths resolve under the user workspace.",
    parameters=READ_FILE_SCHEMA,
    handler=read_file,
)

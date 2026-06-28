import json

from .path_context import resolve_workspace_path
from .registry import registry


READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to read. Relative paths resolve under the user workspace.",
        },
        "offset": {
            "type": "integer",
            "minimum": 1,
            "description": "1-based line number to start reading from. Defaults to 1.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 2000,
            "description": "Maximum number of lines to return. Defaults to 500.",
        },
    },
    "required": ["file_path"],
}


DEFAULT_LIMIT = 500
MAX_LIMIT = 2000
MAX_LINE_CHARS = 2000


def read_file(file_path: str, offset: int = 1, limit: int = DEFAULT_LIMIT) -> str:
    resolved_path = resolve_workspace_path(file_path)
    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        offset = _coerce_int(offset, 1)
        limit = min(max(_coerce_int(limit, DEFAULT_LIMIT), 1), MAX_LIMIT)
        start_index = max(0, offset - 1)
        selected = lines[start_index:start_index + limit]
        truncated_lines = [_truncate_line(line.rstrip("\n\r")) for line in selected]
        content = "\n".join(truncated_lines)
        end_line = start_index + len(selected)
        has_more = end_line < len(lines)
        return json.dumps(
            {
                "file_path": resolved_path,
                "requested_path": file_path,
                "content": content,
                "offset": offset,
                "limit": limit,
                "start_line": offset if selected else None,
                "end_line": end_line if selected else None,
                "total_lines": len(lines),
                "has_more": has_more,
                "next_offset": end_line + 1 if has_more else None,
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
    toolset="file",
    max_result_size_chars=100_000,
)


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_LINE_CHARS:
        return line
    return line[:MAX_LINE_CHARS] + f"... [line truncated, {len(line)} chars]"

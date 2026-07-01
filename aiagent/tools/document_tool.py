from __future__ import annotations

import json
from pathlib import Path

from aiagent.document_extract import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_PAGES,
    SUPPORTED_DOCUMENT_EXTENSIONS,
    extract_document_file,
)

from .path_context import resolve_workspace_path
from .registry import registry


READ_DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": (
                "PDF, Word, PowerPoint, Excel, or RTF file to parse. "
                "Relative paths resolve under the user workspace."
            ),
        },
        "max_chars": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 120000,
            "description": f"Maximum extracted characters to return. Defaults to {DEFAULT_MAX_CHARS}.",
        },
        "max_pages": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
            "description": (
                "Maximum PDF pages, PPT slides, or XLSX sheets to parse. "
                f"Defaults to {DEFAULT_MAX_PAGES}."
            ),
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Include PDF metadata when available. Defaults to true.",
        },
    },
    "required": ["file_path"],
}


def read_document(
    file_path: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_pages: int = DEFAULT_MAX_PAGES,
    include_metadata: bool = True,
) -> str:
    resolved_path = resolve_workspace_path(file_path)
    result = extract_document_file(
        resolved_path,
        max_chars=max_chars,
        max_pages=max_pages,
        include_metadata=include_metadata,
    )
    result["requested_path"] = file_path
    result["file_path"] = str(Path(resolved_path))
    return json.dumps(result, ensure_ascii=False)


registry.register(
    name="read_document",
    description=(
        "Extract readable text from document files such as PDF, DOCX, PPTX, XLSX, and RTF. "
        "Use this instead of read_file for binary office documents or PDFs. "
        f"Supported extensions: {', '.join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))}."
    ),
    parameters=READ_DOCUMENT_SCHEMA,
    handler=read_document,
    toolset="file",
    emoji="📄",
    max_result_size_chars=120_000,
)

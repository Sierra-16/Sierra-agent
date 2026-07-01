from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SUPPORTED_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".rtf",
}

LEGACY_UNSUPPORTED_EXTENSIONS = {".doc", ".ppt", ".xls"}

DEFAULT_MAX_CHARS = 30000
MAX_MAX_CHARS = 120000
DEFAULT_MAX_PAGES = 30
MAX_MAX_PAGES = 200
MAX_ZIP_MEMBER_BYTES = 25 * 1024 * 1024

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def extract_document_file(
    file_path: str | Path,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_pages: int = DEFAULT_MAX_PAGES,
    include_metadata: bool = True,
) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    max_chars = _clamp_int(max_chars, DEFAULT_MAX_CHARS, 1000, MAX_MAX_CHARS)
    max_pages = _clamp_int(max_pages, DEFAULT_MAX_PAGES, 1, MAX_MAX_PAGES)

    if not path.exists():
        return {"error": f"File not found: {path}", "file_path": str(path)}
    if not path.is_file():
        return {"error": f"Not a file: {path}", "file_path": str(path)}

    ext = path.suffix.lower()
    if ext in LEGACY_UNSUPPORTED_EXTENSIONS:
        return {
            "error": (
                f"{ext} is a legacy binary Office format. Please convert it to "
                f"{ext}x, PDF, or install a dedicated converter before parsing."
            ),
            "file_path": str(path),
            "kind": ext.lstrip("."),
        }

    if ext == ".pdf":
        result = _extract_pdf(path, max_chars=max_chars, max_pages=max_pages)
    elif ext == ".docx":
        result = _extract_docx(path, max_chars=max_chars)
    elif ext == ".pptx":
        result = _extract_pptx(path, max_chars=max_chars, max_pages=max_pages)
    elif ext == ".xlsx":
        result = _extract_xlsx(path, max_chars=max_chars, max_pages=max_pages)
    elif ext == ".rtf":
        result = _extract_rtf(path, max_chars=max_chars)
    else:
        result = {
            "error": f"Unsupported document type: {ext or '(no extension)'}",
            "file_path": str(path),
            "supported_extensions": sorted(SUPPORTED_DOCUMENT_EXTENSIONS),
        }

    result.setdefault("file_path", str(path))
    result.setdefault("requested_path", str(file_path))
    result.setdefault("extension", ext)
    if not include_metadata:
        result.pop("metadata", None)
    return result


def is_supported_document_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS


def is_legacy_office_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in LEGACY_UNSUPPORTED_EXTENSIONS


def _extract_pdf(path: Path, *, max_chars: int, max_pages: int) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        return {
            "error": "PDF extraction requires pypdf. Install with: python -m pip install pypdf",
            "file_path": str(path),
            "kind": "pdf",
            "details": str(exc),
        }

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return {"error": f"Unable to read PDF: {exc}", "file_path": str(path), "kind": "pdf"}

    pages = []
    warnings = []
    page_count = len(reader.pages)
    for index, page in enumerate(reader.pages[:max_pages], 1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            warnings.append(f"Page {index}: text extraction failed: {exc}")
            text = ""
        text = _normalize_text(text)
        pages.append(f"[Page {index}]\n{text}" if text else f"[Page {index}]\n")

    content, truncated = _truncate("\n\n".join(pages).strip(), max_chars)
    if page_count > max_pages:
        warnings.append(f"Only the first {max_pages} of {page_count} pages were extracted.")
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")

    metadata = {}
    try:
        if reader.metadata:
            metadata = {
                str(key).lstrip("/"): str(value)
                for key, value in dict(reader.metadata).items()
                if value is not None
            }
    except Exception:
        metadata = {}

    return {
        "kind": "pdf",
        "parser": "pypdf",
        "page_count": page_count,
        "pages_extracted": min(page_count, max_pages),
        "text": content,
        "chars": len(content),
        "truncated": truncated,
        "warnings": warnings,
        "metadata": metadata,
    }


def _extract_docx(path: Path, *, max_chars: int) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            parts = []
            for name in _sorted_docx_parts(archive.namelist()):
                xml = _read_zip_text(archive, name)
                extracted = _extract_wordprocessing_xml(xml)
                if extracted:
                    label = _docx_part_label(name)
                    parts.append(f"[{label}]\n{extracted}" if label else extracted)
    except zipfile.BadZipFile:
        return {"error": "Invalid DOCX file.", "file_path": str(path), "kind": "docx"}
    except Exception as exc:
        return {"error": f"Unable to read DOCX: {exc}", "file_path": str(path), "kind": "docx"}

    content, truncated = _truncate(_normalize_text("\n\n".join(parts)), max_chars)
    warnings = []
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")
    return {
        "kind": "docx",
        "parser": "office-open-xml",
        "text": content,
        "chars": len(content),
        "truncated": truncated,
        "warnings": warnings,
    }


def _extract_pptx(path: Path, *, max_chars: int, max_pages: int) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            slide_names = sorted(
                (name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)),
                key=_natural_sort_key,
            )
            parts = []
            for index, name in enumerate(slide_names[:max_pages], 1):
                xml = _read_zip_text(archive, name)
                text = _extract_drawing_text(xml)
                if text:
                    parts.append(f"[Slide {index}]\n{text}")
    except zipfile.BadZipFile:
        return {"error": "Invalid PPTX file.", "file_path": str(path), "kind": "pptx"}
    except Exception as exc:
        return {"error": f"Unable to read PPTX: {exc}", "file_path": str(path), "kind": "pptx"}

    content, truncated = _truncate(_normalize_text("\n\n".join(parts)), max_chars)
    warnings = []
    if len(slide_names) > max_pages:
        warnings.append(f"Only the first {max_pages} of {len(slide_names)} slides were extracted.")
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")
    return {
        "kind": "pptx",
        "parser": "office-open-xml",
        "slide_count": len(slide_names),
        "slides_extracted": min(len(slide_names), max_pages),
        "text": content,
        "chars": len(content),
        "truncated": truncated,
        "warnings": warnings,
    }


def _extract_xlsx(path: Path, *, max_chars: int, max_pages: int) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = _read_shared_strings(archive)
            sheet_names = sorted(
                (name for name in archive.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", name)),
                key=_natural_sort_key,
            )
            parts = []
            for index, name in enumerate(sheet_names[:max_pages], 1):
                rows = _extract_sheet_rows(_read_zip_text(archive, name), shared_strings)
                if rows:
                    parts.append(f"[Sheet {index}]\n" + "\n".join(rows))
    except zipfile.BadZipFile:
        return {"error": "Invalid XLSX file.", "file_path": str(path), "kind": "xlsx"}
    except Exception as exc:
        return {"error": f"Unable to read XLSX: {exc}", "file_path": str(path), "kind": "xlsx"}

    content, truncated = _truncate(_normalize_text("\n\n".join(parts)), max_chars)
    warnings = []
    if len(sheet_names) > max_pages:
        warnings.append(f"Only the first {max_pages} of {len(sheet_names)} sheets were extracted.")
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")
    return {
        "kind": "xlsx",
        "parser": "office-open-xml",
        "sheet_count": len(sheet_names),
        "sheets_extracted": min(len(sheet_names), max_pages),
        "text": content,
        "chars": len(content),
        "truncated": truncated,
        "warnings": warnings,
    }


def _extract_rtf(path: Path, *, max_chars: int) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"error": f"Unable to read RTF: {exc}", "file_path": str(path), "kind": "rtf"}
    text = _rtf_to_text(raw)
    content, truncated = _truncate(_normalize_text(text), max_chars)
    warnings = []
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")
    return {
        "kind": "rtf",
        "parser": "rtf-basic-text",
        "text": content,
        "chars": len(content),
        "truncated": truncated,
        "warnings": warnings,
    }


def _sorted_docx_parts(names: list[str]) -> list[str]:
    selected = ["word/document.xml"]
    selected.extend(sorted(name for name in names if re.match(r"word/header\d+\.xml$", name)))
    selected.extend(sorted(name for name in names if re.match(r"word/footer\d+\.xml$", name)))
    return [name for name in selected if name in names]


def _docx_part_label(name: str) -> str:
    if name == "word/document.xml":
        return "Document"
    return Path(name).stem.title()


def _read_zip_text(archive: zipfile.ZipFile, name: str) -> str:
    info = archive.getinfo(name)
    if info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(f"{name} is too large to parse safely")
    return archive.read(name).decode("utf-8", errors="replace")


def _extract_wordprocessing_xml(xml: str) -> str:
    root = ET.fromstring(xml)
    body = root.find(f".//{W_NS}body")
    nodes = list(body) if body is not None else list(root)
    lines = []
    for node in nodes:
        if node.tag == f"{W_NS}p":
            text = _paragraph_text(node, W_NS)
            if text:
                lines.append(text)
        elif node.tag == f"{W_NS}tbl":
            table_lines = _table_text(node)
            if table_lines:
                lines.extend(table_lines)
    if not lines:
        text = _paragraph_text(root, W_NS)
        if text:
            lines.append(text)
    return "\n".join(lines)


def _table_text(table: ET.Element) -> list[str]:
    rows = []
    for row in table.findall(f".//{W_NS}tr"):
        cells = []
        for cell in row.findall(f"./{W_NS}tc"):
            cell_lines = []
            for paragraph in cell.findall(f".//{W_NS}p"):
                text = _paragraph_text(paragraph, W_NS)
                if text:
                    cell_lines.append(text)
            cells.append(" ".join(cell_lines).strip())
        row_text = " | ".join(cell for cell in cells if cell)
        if row_text:
            rows.append(row_text)
    return rows


def _extract_drawing_text(xml: str) -> str:
    root = ET.fromstring(xml)
    lines = []
    for paragraph in root.findall(f".//{A_NS}p"):
        text = _paragraph_text(paragraph, A_NS)
        if text:
            lines.append(text)
    return "\n".join(lines)


def _paragraph_text(node: ET.Element, namespace: str) -> str:
    parts = []
    for child in node.iter():
        if child.tag == f"{namespace}t" and child.text:
            parts.append(child.text)
        elif child.tag == f"{namespace}tab":
            parts.append("\t")
        elif child.tag == f"{namespace}br":
            parts.append("\n")
    return _normalize_inline("".join(parts))


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(_read_zip_text(archive, "xl/sharedStrings.xml"))
    values = []
    for item in root.findall(f".//{S_NS}si"):
        texts = [text.text or "" for text in item.findall(f".//{S_NS}t")]
        values.append(_normalize_inline("".join(texts)))
    return values


def _extract_sheet_rows(xml: str, shared_strings: list[str]) -> list[str]:
    root = ET.fromstring(xml)
    rows = []
    for row in root.findall(f".//{S_NS}row"):
        values = []
        for cell in row.findall(f"./{S_NS}c"):
            value = _cell_value(cell, shared_strings)
            if value:
                values.append(value)
        if values:
            rows.append(" | ".join(values))
    return rows


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        texts = [text.text or "" for text in cell.findall(f".//{S_NS}t")]
        return _normalize_inline("".join(texts))
    value_node = cell.find(f"./{S_NS}v")
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    return raw


def _rtf_to_text(raw: str) -> str:
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace(r"\par", "\n").replace(r"\line", "\n")
    text = text.replace("{", " ").replace("}", " ").replace("\\", " ")
    return text


def _natural_sort_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _normalize_inline(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_normalize_inline(line) for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def result_to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)

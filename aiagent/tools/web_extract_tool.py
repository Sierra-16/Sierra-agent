from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .registry import registry


WEB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "urls": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
            "description": "HTTP/HTTPS URLs to extract. Supports HTML/text and PDF URLs.",
        },
        "max_chars_per_url": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 30000,
            "description": "Maximum extracted characters per URL. Defaults to 8000.",
        },
        "max_pdf_pages": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "description": "Maximum PDF pages to extract. Defaults to 20.",
        },
    },
    "required": ["urls"],
}

MAX_URLS = 5
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024


class MarkdownExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._skip_depth = 0
        self._tag_stack: list[str] = []
        self._current_link: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
            return
        self._tag_stack.append(tag)
        if tag in {"p", "div", "section", "article", "br", "li"}:
            self._newline()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._newline()
            self.parts.append("#" * int(tag[1]))
            self.parts.append(" ")
        if tag == "a":
            href = attrs_dict.get("href", "")
            self._current_link = {
                "url": urljoin(self.base_url, href) if href else "",
                "text": "",
            }

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if tag == "a" and self._current_link is not None:
            if self._current_link.get("url"):
                self.links.append(self._current_link)
            self._current_link = None
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._newline()
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = " ".join(str(data or "").split())
        if not text:
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self.title = text
            return
        if self._current_link is not None:
            existing = self._current_link.get("text", "")
            self._current_link["text"] = (existing + " " + text).strip()[:200]
        self.parts.append(text)
        self.parts.append(" ")

    def markdown(self) -> str:
        raw = "".join(self.parts)
        lines = []
        for line in raw.splitlines():
            cleaned = " ".join(line.split())
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    def _newline(self) -> None:
        if self.parts and not str(self.parts[-1]).endswith("\n"):
            self.parts.append("\n")


def web_extract(
    urls: list[str],
    max_chars_per_url: int = 8000,
    max_pdf_pages: int = 20,
) -> str:
    if not isinstance(urls, list) or not urls:
        return json.dumps({"error": "urls must be a non-empty list"}, ensure_ascii=False)
    max_chars = max(1000, min(30000, _coerce_int(max_chars_per_url, 8000)))
    max_pages = max(1, min(100, _coerce_int(max_pdf_pages, 20)))
    results = [
        _extract_one(str(url), max_chars=max_chars, max_pdf_pages=max_pages)
        for url in urls[:MAX_URLS]
    ]
    return json.dumps({"results": results, "total": len(results)}, ensure_ascii=False)


def _extract_one(url: str, *, max_chars: int, max_pdf_pages: int) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "url": url, "error": "web_extract only supports http and https URLs"}
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "SierraAgent/1.0 (+web_extract)",
                "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
            final_url = response.geturl()
            status = getattr(response, "status", 200)
            content_type = response.headers.get("content-type", "")
        if len(raw) > MAX_DOWNLOAD_BYTES:
            return {
                "ok": False,
                "url": final_url,
                "status": status,
                "content_type": content_type,
                "error": f"response too large; limit is {MAX_DOWNLOAD_BYTES} bytes",
            }
        lowered_type = content_type.lower()
        if "application/pdf" in lowered_type or final_url.lower().split("?", 1)[0].endswith(".pdf"):
            return _extract_pdf(final_url, status, content_type, raw, max_chars, max_pdf_pages)
        return _extract_text_or_html(final_url, status, content_type, raw, max_chars)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": url, "error": f"HTTP {exc.code}: {exc.reason}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "url": url, "error": f"request failed: {exc.reason}"}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def _extract_text_or_html(url: str, status: int, content_type: str, raw: bytes, max_chars: int) -> dict:
    text = raw.decode(_charset_from_content_type(content_type), errors="replace")
    if "<html" in text[:1000].lower() or "text/html" in content_type.lower():
        parser = MarkdownExtractor(url)
        parser.feed(text)
        markdown = parser.markdown()
        title = parser.title.strip()
        links = _dedupe_links(parser.links)[:50]
    else:
        markdown = text
        title = ""
        links = []
    truncated = len(markdown) > max_chars
    if truncated:
        markdown = markdown[:max_chars] + "\n...[truncated]"
    return {
        "ok": True,
        "url": url,
        "status": status,
        "content_type": content_type,
        "title": title,
        "markdown": markdown,
        "links": links,
        "truncated": truncated,
    }


def _extract_pdf(
    url: str,
    status: int,
    content_type: str,
    raw: bytes,
    max_chars: int,
    max_pdf_pages: int,
) -> dict:
    try:
        from pypdf import PdfReader
    except Exception:
        return {
            "ok": False,
            "url": url,
            "status": status,
            "content_type": content_type,
            "error": "PDF extraction requires pypdf. Install with: python -m pip install pypdf",
        }
    reader = PdfReader(io.BytesIO(raw))
    page_count = len(reader.pages)
    texts = []
    for index, page in enumerate(reader.pages[:max_pdf_pages], 1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            texts.append(f"## Page {index}\n{page_text.strip()}")
    markdown = "\n\n".join(texts)
    truncated = len(markdown) > max_chars or page_count > max_pdf_pages
    if len(markdown) > max_chars:
        markdown = markdown[:max_chars] + "\n...[truncated]"
    return {
        "ok": True,
        "url": url,
        "status": status,
        "content_type": content_type,
        "title": "",
        "markdown": markdown,
        "page_count": page_count,
        "pages_extracted": min(page_count, max_pdf_pages),
        "truncated": truncated,
    }


def _charset_from_content_type(content_type: str) -> str:
    for part in str(content_type or "").split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip() or "utf-8"
    return "utf-8"


def _dedupe_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    deduped = []
    for link in links:
        url = link.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append({"url": url, "text": link.get("text", "")})
    return deduped


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


registry.register(
    name="web_extract",
    description=(
        "Extract readable markdown from up to 5 web page or PDF URLs. "
        "Use after web_search when the page content itself is needed."
    ),
    parameters=WEB_EXTRACT_SCHEMA,
    handler=web_extract,
    toolset="web",
    max_result_size_chars=100_000,
)

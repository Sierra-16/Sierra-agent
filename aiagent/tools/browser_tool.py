from __future__ import annotations

import json
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .registry import registry


class BrowserTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.links.append({"href": href, "text": ""})

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text or self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(text)
            return
        self.text_parts.append(text)
        if self.links and not self.links[-1]["text"]:
            self.links[-1]["text"] = text[:120]


def browser_fetch(url: str, max_chars: int = 8000) -> str:
    """Fetch a web page and return title, readable text, and links."""
    max_chars = max(1000, min(20000, int(max_chars or 8000)))
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return json.dumps({
            "ok": False,
            "error": "browser_fetch only supports http and https URLs",
        }, ensure_ascii=False)
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "SierraAgent/1.0 (+browser_fetch)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(max_chars * 4)
            final_url = response.geturl()
            status = getattr(response, "status", 200)
            content_type = response.headers.get("content-type", "")
        html = raw.decode("utf-8", errors="replace")
        parser = BrowserTextParser()
        parser.feed(html)
        text = " ".join(parser.text_parts)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
        links = []
        seen = set()
        for link in parser.links:
            href = urljoin(final_url, link["href"])
            if href in seen:
                continue
            seen.add(href)
            links.append({"url": href, "text": link.get("text", "")})
            if len(links) >= 20:
                break
        return json.dumps({
            "ok": True,
            "url": final_url,
            "status": status,
            "content_type": content_type,
            "title": " ".join(parser.title_parts).strip(),
            "text": text,
            "links": links,
        }, ensure_ascii=False)
    except urllib.error.HTTPError as exc:
        return json.dumps({"ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


registry.register(
    name="browser_fetch",
    description=(
        "Fetch a web page like a lightweight browser and return title, readable text, "
        "and up to 20 links. This is read-only and does not execute page actions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_chars": {
                "type": "integer",
                "minimum": 1000,
                "maximum": 20000,
                "description": "Maximum readable text characters to return",
            },
        },
        "required": ["url"],
    },
    handler=browser_fetch,
)

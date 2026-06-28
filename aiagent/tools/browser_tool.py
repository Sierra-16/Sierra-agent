from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .path_context import resolve_workspace_path
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


BROWSER_INSTALL_HINT = (
    "Playwright is required for browser_* tools. Install it with: "
    "python -m pip install playwright && python -m playwright install chromium"
)


class BrowserSession:
    def __init__(self):
        self._lock = threading.RLock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._ref_map: dict[str, str] = {}
        self._console_messages: list[dict] = []

    def ensure_page(self, headless: bool = True):
        with self._lock:
            error = self._ensure_started(headless=headless)
            if error:
                return None, error
            return self._page, None

    def close(self) -> dict:
        with self._lock:
            errors = []
            for item in (self._context, self._browser, self._playwright):
                if item is None:
                    continue
                try:
                    item.close() if hasattr(item, "close") else item.stop()
                except Exception as exc:
                    errors.append(str(exc))
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._ref_map = {}
            self._console_messages = []
            return {"ok": not errors, "errors": errors}

    def selector_for(self, ref_or_selector: str) -> str:
        value = str(ref_or_selector or "").strip()
        return self._ref_map.get(value, value)

    def remember_refs(self, refs: dict[str, str]) -> None:
        self._ref_map = refs

    def add_console_message(self, message) -> None:
        try:
            self._console_messages.append({
                "type": message.type,
                "text": message.text,
                "timestamp": time.time(),
            })
            self._console_messages = self._console_messages[-200:]
        except Exception:
            pass

    def console_messages(self, clear: bool = False) -> list[dict]:
        messages = list(self._console_messages)
        if clear:
            self._console_messages = []
        return messages

    def _ensure_started(self, headless: bool = True) -> str:
        if self._page is not None:
            return ""
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return BROWSER_INSTALL_HINT
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=bool(headless))
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=1,
            )
            self._page = self._context.new_page()
            self._page.on("console", self.add_console_message)
            return ""
        except Exception as exc:
            self.close()
            return f"{exc}\n{BROWSER_INSTALL_HINT}"


browser_session = BrowserSession()


def browser_navigate(url: str, wait_until: str = "domcontentloaded", headless: bool = True) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _browser_error("browser_navigate only supports http and https URLs")
    page, error = browser_session.ensure_page(headless=headless)
    if error:
        return _browser_error(error)
    try:
        response = page.goto(url, wait_until=_safe_wait_until(wait_until), timeout=30_000)
        return json.dumps({
            "ok": True,
            "url": page.url,
            "title": page.title(),
            "status": response.status if response is not None else None,
        }, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_snapshot(full: bool = False, max_chars: int = 12000) -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    max_chars = max(1000, min(50000, _coerce_int(max_chars, 12000)))
    try:
        payload = page.evaluate(
            """({ full, maxChars }) => {
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.visibility !== 'hidden' &&
                        style.display !== 'none' && rect.width > 0 && rect.height > 0;
                };
                const cssEscape = (value) => {
                    if (window.CSS && CSS.escape) return CSS.escape(value);
                    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
                };
                const selectorFor = (el) => {
                    if (el.id) return '#' + cssEscape(el.id);
                    const testId = el.getAttribute('data-testid') || el.getAttribute('data-test');
                    if (testId) return `[data-testid="${testId.replace(/"/g, '\\"')}"]`;
                    const parts = [];
                    let node = el;
                    while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 5) {
                        let part = node.tagName.toLowerCase();
                        if (node.classList && node.classList.length) {
                            part += '.' + Array.from(node.classList).slice(0, 2).map(cssEscape).join('.');
                        }
                        const parent = node.parentElement;
                        if (parent) {
                            const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
                            if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
                        }
                        parts.unshift(part);
                        node = parent;
                    }
                    return parts.join(' > ');
                };
                const text = (document.body ? document.body.innerText : document.documentElement.innerText || '').trim();
                const candidates = Array.from(document.querySelectorAll(
                    'a,button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"]'
                )).filter(visible).slice(0, 80);
                const elements = candidates.map((el, index) => ({
                    ref: `e${index + 1}`,
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || '',
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 160),
                    href: el.href || '',
                    selector: selectorFor(el),
                }));
                return {
                    url: location.href,
                    title: document.title,
                    text: full ? text : text.slice(0, maxChars),
                    truncated: !full && text.length > maxChars,
                    elements,
                };
            }""",
            {"full": bool(full), "maxChars": max_chars},
        )
        refs = {
            item["ref"]: item["selector"]
            for item in payload.get("elements", [])
            if item.get("ref") and item.get("selector")
        }
        browser_session.remember_refs(refs)
        payload["ok"] = True
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_click(ref: str) -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    selector = browser_session.selector_for(ref)
    try:
        page.locator(selector).first.click(timeout=10_000)
        return json.dumps({"ok": True, "url": page.url, "clicked": ref}, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_type(ref: str, text: str, clear: bool = True, press_enter: bool = False) -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    selector = browser_session.selector_for(ref)
    try:
        locator = page.locator(selector).first
        if clear:
            locator.fill(str(text or ""), timeout=10_000)
        else:
            locator.type(str(text or ""), timeout=10_000)
        if press_enter:
            locator.press("Enter")
        return json.dumps({"ok": True, "url": page.url, "typed": len(str(text or ""))}, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_scroll(direction: str = "down", amount: int = 700) -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    amount = max(100, min(3000, _coerce_int(amount, 700)))
    dy = -amount if str(direction).lower() == "up" else amount
    try:
        page.mouse.wheel(0, dy)
        return json.dumps({"ok": True, "url": page.url, "direction": direction, "amount": amount}, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_back() -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    try:
        response = page.go_back(wait_until="domcontentloaded", timeout=15_000)
        return json.dumps({
            "ok": True,
            "url": page.url,
            "title": page.title(),
            "status": response.status if response is not None else None,
        }, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_press(key: str) -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    try:
        page.keyboard.press(str(key or ""))
        return json.dumps({"ok": True, "url": page.url, "key": key}, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_screenshot(path: str | None = None, full_page: bool = False) -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    if path:
        target = Path(resolve_workspace_path(path))
    else:
        target = Path(tempfile.gettempdir()) / "sierra-browser" / f"screenshot-{int(time.time() * 1000)}.png"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=bool(full_page))
        return json.dumps({"ok": True, "path": str(target), "url": page.url}, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_console(expression: str | None = None, clear: bool = False) -> str:
    page, error = browser_session.ensure_page()
    if error:
        return _browser_error(error)
    try:
        result = None
        if expression:
            result = page.evaluate(str(expression))
        return json.dumps({
            "ok": True,
            "result": result,
            "messages": browser_session.console_messages(clear=clear),
        }, ensure_ascii=False)
    except Exception as exc:
        return _browser_error(str(exc))


def browser_close() -> str:
    return json.dumps(browser_session.close(), ensure_ascii=False)


def _browser_error(error: str) -> str:
    return json.dumps({"ok": False, "error": error}, ensure_ascii=False)


def _safe_wait_until(value: str) -> str:
    value = str(value or "domcontentloaded")
    return value if value in {"commit", "domcontentloaded", "load", "networkidle"} else "domcontentloaded"


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_navigate",
    description="Open a real Chromium browser page with Playwright and navigate to an http/https URL.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to open"},
            "wait_until": {
                "type": "string",
                "enum": ["commit", "domcontentloaded", "load", "networkidle"],
                "description": "Navigation wait condition. Defaults to domcontentloaded.",
            },
            "headless": {
                "type": "boolean",
                "description": "Launch Chromium headless. Defaults to true.",
            },
        },
        "required": ["url"],
    },
    handler=browser_navigate,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_snapshot",
    description="Read the current browser page title, URL, visible text, and clickable/input element refs.",
    parameters={
        "type": "object",
        "properties": {
            "full": {"type": "boolean", "description": "Return full page text instead of a capped preview."},
            "max_chars": {"type": "integer", "minimum": 1000, "maximum": 50000},
        },
    },
    handler=browser_snapshot,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_click",
    description="Click an element by ref from browser_snapshot or by CSS selector.",
    parameters={
        "type": "object",
        "properties": {"ref": {"type": "string", "description": "Element ref or CSS selector"}},
        "required": ["ref"],
    },
    handler=browser_click,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_type",
    description="Type into an input element by ref from browser_snapshot or by CSS selector.",
    parameters={
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Element ref or CSS selector"},
            "text": {"type": "string", "description": "Text to enter"},
            "clear": {"type": "boolean", "description": "Clear existing input first. Defaults to true."},
            "press_enter": {"type": "boolean", "description": "Press Enter after typing."},
        },
        "required": ["ref", "text"],
    },
    handler=browser_type,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_scroll",
    description="Scroll the current browser page up or down.",
    parameters={
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down"]},
            "amount": {"type": "integer", "minimum": 100, "maximum": 3000},
        },
    },
    handler=browser_scroll,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_back",
    description="Navigate the browser page back in history.",
    parameters={"type": "object", "properties": {}},
    handler=browser_back,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_press",
    description="Press a keyboard key in the current browser page.",
    parameters={
        "type": "object",
        "properties": {"key": {"type": "string", "description": "Key name such as Enter, Escape, ArrowDown"}},
        "required": ["key"],
    },
    handler=browser_press,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_screenshot",
    description="Save a screenshot of the current browser page to a PNG file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Optional output PNG path."},
            "full_page": {"type": "boolean", "description": "Capture the full scrollable page."},
        },
    },
    handler=browser_screenshot,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_console",
    description="Read console messages and optionally evaluate JavaScript in the current browser page.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Optional JavaScript expression to evaluate."},
            "clear": {"type": "boolean", "description": "Clear stored console messages after reading."},
        },
    },
    handler=browser_console,
    toolset="browser",
    max_result_size_chars=100_000,
)

registry.register(
    name="browser_close",
    description="Close the active Playwright browser session.",
    parameters={"type": "object", "properties": {}},
    handler=browser_close,
    toolset="browser",
    max_result_size_chars=100_000,
)

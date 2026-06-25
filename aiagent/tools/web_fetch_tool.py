from .registry import registry
import json
import urllib.request
import urllib.error
from html.parser import HTMLParser

WEB_FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "要抓取的网页URL，如 'https://example.com'"
        }
    },
    "required": ["url"]
}

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
    def handle_data(self, data):
        t = data.strip()
        if t:
            self.text.append(t)

def web_fetch(url: str) -> str:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SierraAgent/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()

        content = raw.decode("utf-8", errors="replace")

        extractor = TextExtractor()
        extractor.feed(content)
        text = " ".join(extractor.text)

        if len(text) > 5000:
            text = text[:5000] + f"\n...(内容已截断，共 {len(text)} 字)"

        return json.dumps({"url": url, "content": text, "status": resp.status})

    except urllib.error.HTTPError as e:
        return json.dumps({"error": f"HTTP {e.code}: {e.reason}"})
    except urllib.error.URLError as e:
        return json.dumps({"error": f"请求失败: {str(e.reason)}"})
    except TimeoutError:
        return json.dumps({"error": "请求超时"})
    except Exception as e:
        return json.dumps({"error": str(e)})
    

registry.register(
    name="web_fetch",
    description="抓取指定 URL 的网页内容，提取纯文本返回",
    parameters=WEB_FETCH_SCHEMA,
    handler=web_fetch
)


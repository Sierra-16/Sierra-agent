from .registry import registry
import json
import urllib.request
import urllib.parse
import urllib.error
import os

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词，如 'Python 异步编程教程'"
        },
        "count": {
            "type": "integer",
            "description": "返回结果数量，默认 5，最大 50"
        }
    },
    "required": ["query"]
}


def _load_config():
    """读取 config.json 获取搜索后端配置"""
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
    config_path = os.path.abspath(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- 后端实现 ----------

def _search_serpapi(query: str, api_key: str, num: int) -> list:
    """通过 SerpAPI 搜索 (默认 Google)"""
    if not api_key:
        raise ValueError("SerpAPI 需要 API Key，请在 config.json 中配置 search_api_key")
    params = urllib.parse.urlencode({
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "num": num,
    })
    url = f"https://serpapi.com/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "SierraAgent/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []
    for r in data.get("organic_results", [])[:num]:
        results.append({
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
        })
    return results


def _search_bing(query: str, api_key: str, num: int) -> list:
    """通过 Azure Bing Search API 搜索"""
    if not api_key:
        raise ValueError("Bing Search API 需要 API Key，请在 config.json 中配置 search_api_key")
    params = urllib.parse.urlencode({
        "q": query,
        "count": num,
        "mkt": "zh-CN",
    })
    url = f"https://api.bing.microsoft.com/v7.0/search?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "SierraAgent/1.0",
        "Ocp-Apim-Subscription-Key": api_key,
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []
    for r in data.get("webPages", {}).get("value", [])[:num]:
        results.append({
            "title": r.get("name", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
        })
    return results

def _search_duckduckgo(query: str, api_key: str, num: int) -> list:
    """通过 DuckDuckGo Instant Answer API 搜索（免费、无需 Key）"""
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "no_html": "1",
    })
    url = f"https://api.duckduckgo.com/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "SierraAgent/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []

    # 最佳匹配摘要放第一条
    abstract = data.get("Abstract", "")
    abstract_url = data.get("AbstractURL", "")
    if abstract and abstract_url:
        results.append({
            "title": "DuckDuckGo 摘要",
            "url": abstract_url,
            "snippet": abstract,
        })

    # RelatedTopics 补后面的
    for item in data.get("RelatedTopics", []):
        text = item.get("Text", "")
        url_item = item.get("FirstURL", "")
        if text and url_item:
            results.append({
                "title": text[:30] + ("..." if len(text) > 30 else ""),
                "url": url_item,
                "snippet": text,
            })

    return results[:num]


def _search_bocha(query: str, api_key: str, num: int) -> list:
    """通过博查 API 搜索（国内直连，手机号注册即可）"""
    if not api_key:
        raise ValueError("博查需要 API Key，请在 config.json 中配置 search_api_key")
    body = json.dumps({
    "query": query,
    "freshness": "noLimit",
    "summary": True,
    "count": num,
}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.bocha.cn/v1/web-search",
        data=body,
        headers={
            "User-Agent": "SierraAgent/1.0",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []
    for r in data.get("data", {}).get("webPages", {}).get("value", [])[:num]:
        results.append({
            "title": r.get("name", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
        })
    return results


# ---------- 后端注册表 ----------

BACKENDS = {
    "serpapi": _search_serpapi,
    "bing": _search_bing,
    "bocha": _search_bocha,
    "duckduckgo": _search_duckduckgo
}


# ---------- Handler ----------

def web_search(query: str, count: int = 5) -> str:
    try:
        config = _load_config()
        backend_name = config.get("search", {}).get("backend", "serpapi")
        api_key = config.get("search", {}).get("api_key", "")

        # if not api_key or api_key.startswith("your-"):
        #     return json.dumps({
        #         "error": f"未配置 search_api_key，请在 config.json 中填入你的 {backend_name} API Key"
        #     }, ensure_ascii=False)

        search_fn = BACKENDS.get(backend_name)
        if not search_fn:
            return json.dumps({
                "error": f"不支持的后端: {backend_name}，可选: {', '.join(BACKENDS.keys())}"
            }, ensure_ascii=False)

        num = min(max(count, 1), 50)
        results = search_fn(query, api_key, num)

        return json.dumps({
            "backend": backend_name,
            "query": query,
            "results": results,
            "total": len(results),
        }, ensure_ascii=False)

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return json.dumps({"error": f"搜索 API 返回 {e.code}: {body[:300]}"}, ensure_ascii=False)
    except urllib.error.URLError as e:
        return json.dumps({"error": f"网络请求失败: {str(e.reason)}"}, ensure_ascii=False)
    except TimeoutError:
        return json.dumps({"error": "搜索请求超时"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


registry.register(
    name="web_search",
    description="搜索互联网，返回网页标题、URL 和摘要。适用于查找最新信息、教程、文档等",
    parameters=WEB_SEARCH_SCHEMA,
    handler=web_search
)

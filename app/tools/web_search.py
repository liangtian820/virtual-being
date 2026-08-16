"""通用网页搜索工具（迭代 5，M6.3）：Bing 免费端点（本机实测可达，无需 key）。

设计：
- 只负责"搜"，不负责"说"——结果由人格 Agent 人设包装（沿用能力 Agent 原则）。
- Bing HTML 结果页解析（bs4），返回结构化 [{title, url, snippet}]（默认 3 条）。
- 失败/无结果返回 []（由上层如实告知，绝不编造结果）。
- 网络操作带超时；解析失败降级为空结果（不抛异常）。
- M6.9（WO-20260816-39）：超时 10s→(connect 3s, read 6s)；按 query 缓存 ~10 分钟
  （data/search_cache），重复/近似查询命中缓存 ≤5s（基线『搜新闻』29.3s → ≤15s）。
"""
import logging
import re
from typing import List, Dict

import requests

from app.tools.search_cache import search_cache

logger = logging.getLogger(__name__)

_BING_URL = "https://www.bing.com/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/145.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_MAX_RESULTS = 3
# M6.9：connect 3s / read 6s（基线 10s 单超时 → 失败快速降级）
_TIMEOUT = (3, 6)


def _parse_bing(html: str) -> List[Dict[str, str]]:
    """解析 Bing 结果页：<li class="b_algo"> 的标题/链接/摘要。"""
    from bs4 import BeautifulSoup  # 惰性导入（仅本工具使用）
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict[str, str]] = []
    for li in soup.select("li.b_algo"):
        a = li.find("h2")
        link = a.find("a") if a else None
        if not link or not link.get("href"):
            continue
        title = link.get_text(strip=True)
        url = link.get("href", "")
        snippet = ""
        p = li.find("p")
        if p:
            snippet = p.get_text(strip=True)
        elif li.find("div", class_=re.compile(r"b_caption|b_snippet")):
            cap = li.find("div", class_=re.compile(r"b_caption|b_snippet"))
            snippet = cap.get_text(strip=True)
        results.append({"title": title, "url": url, "snippet": snippet[:200]})
        if len(results) >= _MAX_RESULTS:
            break
    return results


def search(query: str, timeout: int = None) -> List[Dict[str, str]]:
    """执行 Bing 搜索，返回最多 3 条结果；失败/无结果返回 []（不抛异常）。

    M6.9：按 query 缓存（命中直接返回，不发起网络请求）。
    """
    if timeout is None:
        timeout = _TIMEOUT
    cached = search_cache.get(f"bing:{query}")
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            _BING_URL,
            params={"q": query, "mkt": "zh-CN"},
            headers=_HEADERS,
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning("Bing search HTTP %s", resp.status_code)
            return []
        results = _parse_bing(resp.text)
        search_cache.set(f"bing:{query}", results)
        return results
    except requests.RequestException as exc:
        logger.warning("Bing search failed: %s", exc)
        return []
    except Exception as exc:  # 解析类异常也降级
        logger.warning("Bing search parse failed: %s", exc)
        return []


def search_text(query: str, timeout: int = None) -> str:
    """搜索并格式化为文本（供 _execute_tool 使用）；无结果返回明确说明。"""
    items = search(query, timeout=timeout)
    if not items:
        return "（联网搜索没有查到结果）"
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it['title']}\n   链接：{it['url']}\n   摘要：{it['snippet']}")
    return "\n".join(lines)

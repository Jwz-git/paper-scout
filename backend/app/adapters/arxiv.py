import asyncio
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional
import httpx

from backend.app.domain.models import Paper
from urllib.parse import urlparse

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _clean_text(val: Optional[str]) -> str:
    if not val:
        return ""
    # 将多个连续空格或换行替换为单个空格
    return re.sub(r"\s+", " ", val).strip()


class ArXivError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _validate_source_url(url: str):
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ArXivError("invalid_feed", "arXiv 来源链接格式无效。") from exc
    if (parsed.scheme not in ("http", "https")
            or hostname not in {"arxiv.org", "export.arxiv.org"}
            or parsed.username is not None or parsed.password is not None):
        raise ArXivError("invalid_feed", "arXiv 来源链接必须是无凭据的官方 HTTP/HTTPS 地址。")
    return parsed


def parse_arxiv_feed(xml_text: str) -> List[Paper]:
    """解析 arXiv Atom 响应；服务错误和无结果严格区分。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ArXivError("invalid_xml", "arXiv 响应不是有效 XML。") from exc
    if root.tag != f"{{{ATOM_NS['atom']}}}feed":
        raise ArXivError("invalid_feed", "arXiv 响应不是 Atom feed。")
    papers: List[Paper] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        raw_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS).strip()
        parsed_id = _validate_source_url(raw_id)
        if parsed_id.path == "/api/errors":
            summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
            raise ArXivError("api_error", f"arXiv 查询失败：{summary}")
        if parsed_id.hostname != "arxiv.org" or not parsed_id.path.startswith("/abs/"):
            raise ArXivError("invalid_feed", "arXiv 论文条目缺少有效来源 ID。")
        source_id = parsed_id.path[len("/abs/"):]

        title = _clean_text(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
        published_str = entry.findtext("atom:published", default="", namespaces=ATOM_NS).strip()

        year: Optional[int] = None
        if published_str:
            try:
                # 示例格式: 2022-03-16T22:39:46Z
                dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                year = dt.year
            except ValueError as exc:
                raise ArXivError("invalid_feed", "arXiv published 日期格式无效。") from exc

        authors: List[str] = []
        for author in entry.findall("atom:author", ATOM_NS):
            name = author.findtext("atom:name", default="", namespaces=ATOM_NS).strip()
            if name:
                authors.append(name)

        doi = entry.findtext("arxiv:doi", default=None, namespaces=ATOM_NS)
        if doi:
            doi = doi.strip()

        primary_cat_elem = entry.find("arxiv:primary_category", ATOM_NS)
        primary_category = (
            primary_cat_elem.attrib.get("term") if primary_cat_elem is not None else None
        )

        categories: List[str] = []
        for cat in entry.findall("atom:category", ATOM_NS):
            term = cat.attrib.get("term")
            if term and term not in categories:
                categories.append(term)

        pdf_url: Optional[str] = None
        abs_url: str = raw_id
        for link in entry.findall("atom:link", ATOM_NS):
            rel = link.attrib.get("rel")
            title_attr = link.attrib.get("title")
            href = link.attrib.get("href", "")
            if rel == "alternate" and href:
                _validate_source_url(href)
                abs_url = href
            elif rel == "related" and title_attr == "pdf" and href:
                _validate_source_url(href)
                pdf_url = href

        paper = Paper(
            id=f"arxiv:{source_id}",
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            source="arxiv",
            source_id=source_id,
            url=abs_url,
            pdf_url=pdf_url,
            abstract=summary,
            primary_category=primary_category,
            categories=categories,
            fetched_at=datetime.now(timezone.utc),
        )
        papers.append(paper)

    return papers


class ArXivAdapter:
    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        user_agent: str = "PaperScout/0.1",
        rate_limit_seconds: float = 3.0,
        timeout_seconds: float = 20.0,
        *,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.user_agent = user_agent
        self.rate_limit_seconds = rate_limit_seconds
        self.timeout_seconds = timeout_seconds
        self._client = client
        self._last_request_time: float = 0.0

    async def _enforce_rate_limit(self) -> None:
        """遵循 arXiv API 速率限制规则（请求间隔 >= 3秒）"""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            wait_time = self.rate_limit_seconds - elapsed
            await asyncio.sleep(wait_time)
        self._last_request_time = time.monotonic()

    async def search(
        self,
        query: str,
        start: int = 0,
        max_results: int = 10,
        sort_by: str = "relevance",
        sort_order: str = "descending",
        *,
        on_request: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> List[Paper]:
        """向 arXiv API 发起查询并返回 Paper 对象列表"""
        await self._enforce_rate_limit()

        params = {
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/atom+xml",
        }

        if on_request is not None:
            await on_request()
        try:
            if self._client is not None:
                resp = await self._client.get(self.BASE_URL, params=params, headers=headers, timeout=self.timeout_seconds)
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(self.BASE_URL, params=params, headers=headers)
            if resp.status_code == 429:
                raise ArXivError("rate_limited", "arXiv 速率限制已触发 (HTTP 429)，请稍后重试。")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ArXivError("http_error", f"arXiv 请求失败，HTTP {exc.response.status_code}。") from exc
        except httpx.TimeoutException as exc:
            raise ArXivError("timeout", "arXiv 请求超时。") from exc
        except httpx.RequestError as exc:
            raise ArXivError("network_error", "arXiv 网络请求失败。") from exc
        return parse_arxiv_feed(resp.text)

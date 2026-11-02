import asyncio
import ipaddress
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from backend.app.domain.models import SourceText, SourceType

ALLOWED_DOMAINS = {"arxiv.org", "export.arxiv.org"}
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_PAGES_LIMIT = 50


class PdfError(RuntimeError):
    """可识别的外部下载、安全或内容解析错误。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _resolve_pdf_target(url: str, allowed_domains: Optional[set] = None) -> tuple:
    allowed = ALLOWED_DOMAINS if allowed_domains is None else allowed_domains
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise PdfError("unsafe_url", "PDF URL 格式无效。") from exc
    if parsed.scheme not in ("http", "https"):
        raise PdfError("unsafe_url", "不安全的 URL 协议；仅允许 http/https。")
    if not hostname or hostname not in allowed:
        raise PdfError("unsafe_url", "PDF 目标不在允许的学术源白名单内。")
    if parsed.username is not None or parsed.password is not None or port not in (None, 80, 443):
        raise PdfError("unsafe_url", "PDF URL 不允许凭据或非标准端口。")
    try:
        addresses = socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PdfError("dns_error", "无法解析 PDF 目标域名。") from exc
    if not addresses:
        raise PdfError("dns_error", "PDF 目标域名没有可用地址。")
    for _, _, _, _, address in addresses:
        if not ipaddress.ip_address(address[0]).is_global:
            raise PdfError("unsafe_url", "PDF 目标 IP 不是公网地址，禁止访问。")
    return hostname, addresses[0][4][0]


def validate_pdf_url(url: str, allowed_domains: Optional[set] = None) -> None:
    _resolve_pdf_target(url, allowed_domains)


class PDFAdapter:
    def __init__(self, max_bytes: int = MAX_DOWNLOAD_BYTES, max_pages: int = MAX_PAGES_LIMIT,
                 timeout_seconds: float = 30.0, *, parse_timeout_seconds: float = 10.0,
                 max_redirects: int = 5, allowed_domains: Optional[set] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.parse_timeout_seconds = parse_timeout_seconds
        self.max_redirects = max_redirects
        self.allowed_domains = allowed_domains
        self._transport = transport

    async def download_and_extract(self, pdf_url: str, paper_id: str, *,
                                   on_request: Optional[Callable[[], Awaitable[None]]] = None) -> List[SourceText]:
        """每跳先校验并固定连接 IP，再调用计数/检查点；不自动重试。"""
        current_url = pdf_url
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False,
                                     trust_env=False, transport=self._transport,
                                     limits=httpx.Limits(max_keepalive_connections=0)) as client:
            for redirect_count in range(self.max_redirects + 1):
                hostname, address = await asyncio.to_thread(_resolve_pdf_target, current_url, self.allowed_domains)
                # 连接校验过的数字 IP，避免 httpx 第二次解析原域名造成 DNS TOCTOU。
                # Host 与 TLS SNI 仍为原域名，正常进行证书校验；禁用环境代理。
                target = httpx.URL(current_url)
                pinned_url = target.copy_with(host=address)
                headers = {"User-Agent": "PaperScout/0.1", "Accept": "application/pdf", "Host": target.netloc.decode("ascii")}
                if on_request is not None:
                    await on_request()
                try:
                    async with client.stream("GET", pinned_url, headers=headers,
                                             extensions={"sni_hostname": hostname}) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("location")
                            if not location:
                                raise PdfError("invalid_redirect", "PDF 重定向缺少目标地址。")
                            if redirect_count == self.max_redirects:
                                raise PdfError("redirect_limit", "PDF 重定向次数超出限制。")
                            current_url = urljoin(current_url, location)
                            continue
                        if response.status_code != 200:
                            raise PdfError("http_error", f"PDF 下载失败，HTTP {response.status_code}。")
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(content) + len(chunk) > self.max_bytes:
                                raise PdfError("size_limit", "PDF 文件体积超出下载限制。")
                            content.extend(chunk)
                except httpx.TimeoutException as exc:
                    raise PdfError("download_timeout", "PDF 下载请求超时。") from exc
                except httpx.RequestError as exc:
                    raise PdfError("network_error", "PDF 下载网络请求失败。") from exc
                break
        return await self._extract_async(bytes(content), paper_id, current_url)

    def _parser_command(self) -> list:
        return [sys.executable, str(Path(__file__).with_name("_pdf_parser.py")), str(self.max_pages)]

    async def _extract_async(self, data: bytes, paper_id: str, source_url: Optional[str]) -> List[SourceText]:
        command = self._parser_command()
        process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.PIPE,
                                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(data), self.parse_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise PdfError("parse_timeout", "PDF 解析超时，解析子进程已终止。") from exc
        finally:
            # 也覆盖 CancelledError；先 kill 再排空管道并回收，不能只取消等待。
            if process.returncode is None:
                process.kill()
                await process.communicate()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
        return self._source_texts(json.loads(stdout), paper_id, source_url)

    def extract_from_bytes(self, data: bytes, paper_id: str, source_url: Optional[str] = None) -> List[SourceText]:
        """解析超时会终止并回收子进程；程序异常保留为进程失败而不吞噬。"""
        if len(data) > self.max_bytes:
            raise PdfError("size_limit", "PDF 字节体积超出解析输入限制。")
        command = self._parser_command()
        try:
            completed = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=self.parse_timeout_seconds, check=True)
        except subprocess.TimeoutExpired as exc:
            # subprocess.run 的 timeout 已 kill 并 wait，不是仅取消线程等待。
            raise PdfError("parse_timeout", "PDF 解析超时，解析子进程已终止。") from exc
        return self._source_texts(json.loads(completed.stdout), paper_id, source_url)

    def _source_texts(self, result: dict, paper_id: str, source_url: Optional[str]) -> List[SourceText]:
        if "error" in result:
            error = result["error"]
            raise PdfError(error["code"], error["message"])
        texts = [SourceText(id=f"{paper_id}:p{page['page_number']}", paper_id=paper_id,
                            source_type=SourceType.FULLTEXT, source_url=source_url, **page)
                 for page in result["pages"]]
        if result["total_pages"] > self.max_pages:
            texts.append(SourceText(id=f"{paper_id}:fulltext:page_limit", paper_id=paper_id,
                                    source_type=SourceType.FULLTEXT, source_url=source_url,
                                    page_number=None, content="", status="page_limit"))
        return texts

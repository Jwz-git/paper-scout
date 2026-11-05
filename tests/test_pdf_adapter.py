import asyncio
import io
import socket
import subprocess
import sys

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.app.adapters import _pdf_parser
from backend.app.adapters.pdf import PDFAdapter, PdfError, validate_pdf_url
from backend.app.domain.models import SourceType


PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_IP, port)),
    ])


def sample_pdf(*, with_text=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    if with_text:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 10 100 Td (Test paper text) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_allowed_pdf_urls_validate_without_network():
    validate_pdf_url("https://arxiv.org/pdf/example")
    validate_pdf_url("http://export.arxiv.org/pdf/example")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/test.pdf", "http://localhost:8000/test.pdf",
                                 "https://arxiv.org.evil.test/pdf/x", "https://unknown.arxiv.org/pdf/x",
                                 "https://user:password@arxiv.org/pdf/x", "https://arxiv.org:8000/pdf/x"])
def test_unsafe_targets_are_rejected(url):
    with pytest.raises(PdfError) as error:
        validate_pdf_url(url)
    assert error.value.code == "unsafe_url"


def test_private_dns_result_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(PdfError) as error:
        validate_pdf_url("https://arxiv.org/pdf/x")
    assert error.value.code == "unsafe_url"


def test_extract_text_pages_and_blank_pages_keep_real_page_numbers():
    texts = PDFAdapter().extract_from_bytes(sample_pdf(with_text=True), "paper", "https://arxiv.org/pdf/x")
    assert [(text.page_number, text.status) for text in texts] == [(1, "ok"), (2, "not_read")]
    assert texts[0].content == "Test paper text"
    assert all(text.source_type == SourceType.FULLTEXT for text in texts)


def test_page_limit_is_not_reported_as_complete_fulltext():
    texts = PDFAdapter(max_pages=1).extract_from_bytes(sample_pdf(), "paper")
    assert len(texts) == 2
    assert texts[0].page_number == 1
    assert texts[-1].status == "page_limit"
    assert texts[-1].page_number is None and texts[-1].content == ""


def test_corrupt_pdf_raises_content_error_instead_of_fake_page_one():
    with pytest.raises(PdfError) as error:
        PDFAdapter().extract_from_bytes(b"This is not PDF", "paper")
    assert error.value.code == "parse_failed"


def test_download_pins_validated_ip_and_counts_each_redirect_before_request(monkeypatch):
    dns_calls, events = [], []
    def resolve(host, port, **kwargs):
        dns_calls.append(host)
        # 如果 HTTP 层再次解析原域名，第二次解析将返回私网地址。
        address = PUBLIC_IP if len(dns_calls) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    def handler(request):
        events.append("request")
        assert request.url.host == PUBLIC_IP
        assert request.headers["host"] == "arxiv.org"
        assert request.extensions["sni_hostname"] == "arxiv.org"
        return httpx.Response(200, content=sample_pdf())
    async def checkpoint():
        events.append("checkpoint")
    adapter = PDFAdapter(transport=httpx.MockTransport(handler))
    texts = asyncio.run(adapter.download_and_extract("https://arxiv.org/pdf/x", "paper", on_request=checkpoint))
    assert dns_calls == ["arxiv.org"]
    assert events == ["checkpoint", "request"]
    assert len(texts) == 2


def test_redirect_is_checked_before_access_and_does_not_auto_follow():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
    with pytest.raises(PdfError) as error:
        asyncio.run(PDFAdapter(transport=httpx.MockTransport(handler)).download_and_extract("https://arxiv.org/pdf/x", "paper"))
    assert error.value.code == "unsafe_url"
    assert len(requests) == 1


def test_redirect_to_allowed_name_with_private_dns_is_never_requested(monkeypatch):
    def resolve(host, port, **kwargs):
        ip = PUBLIC_IP if host == "arxiv.org" else "10.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    requested = []
    def handler(request):
        requested.append(request)
        return httpx.Response(302, headers={"location": "https://export.arxiv.org/pdf/x"})
    with pytest.raises(PdfError) as error:
        asyncio.run(PDFAdapter(transport=httpx.MockTransport(handler)).download_and_extract("https://arxiv.org/pdf/x", "paper"))
    assert error.value.code == "unsafe_url" and len(requested) == 1


def test_checkpoint_can_halt_redirect_without_request_and_exception_is_not_swallowed():
    events = []
    class Halt(RuntimeError):
        pass
    def handler(request):
        events.append("request")
        return httpx.Response(302, headers={"location": "/pdf/final"})
    async def checkpoint():
        events.append("checkpoint")
        if events.count("checkpoint") == 2:
            raise Halt("stop")
    with pytest.raises(Halt):
        asyncio.run(PDFAdapter(transport=httpx.MockTransport(handler)).download_and_extract("https://arxiv.org/pdf/x", "paper", on_request=checkpoint))
    assert events == ["checkpoint", "request", "checkpoint"]


def test_successful_redirect_counts_two_requests_and_records_final_url():
    events = []
    def handler(request):
        events.append("request")
        if request.url.path == "/pdf/start":
            return httpx.Response(302, headers={"location": "/pdf/final"})
        return httpx.Response(200, content=sample_pdf())
    async def checkpoint():
        events.append("checkpoint")
    texts = asyncio.run(PDFAdapter(transport=httpx.MockTransport(handler)).download_and_extract(
        "https://arxiv.org/pdf/start", "paper", on_request=checkpoint))
    assert events == ["checkpoint", "request", "checkpoint", "request"]
    assert all(text.source_url == "https://arxiv.org/pdf/final" for text in texts)


def test_download_byte_and_redirect_limits_are_explicit():
    with pytest.raises(PdfError) as error:
        asyncio.run(PDFAdapter(max_bytes=5, transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"123456"))).download_and_extract("https://arxiv.org/pdf/x", "paper"))
    assert error.value.code == "size_limit"
    requests = []
    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "/pdf/x"})
    with pytest.raises(PdfError) as error:
        asyncio.run(PDFAdapter(max_redirects=1, transport=httpx.MockTransport(redirect)).download_and_extract("https://arxiv.org/pdf/x", "paper"))
    assert error.value.code == "redirect_limit" and len(requests) == 2


def test_parse_timeout_really_kills_and_reaps_process(monkeypatch):
    original_popen = subprocess.Popen
    children = []
    def start_blocked_parser(command, **kwargs):
        process = original_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(subprocess, "Popen", start_blocked_parser)
    with pytest.raises(PdfError) as error:
        PDFAdapter(parse_timeout_seconds=0.1).extract_from_bytes(sample_pdf(), "paper")
    assert error.value.code == "parse_timeout"
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].returncode != 0


def test_async_parse_cancellation_really_kills_and_reaps_process(monkeypatch):
    original_create = asyncio.create_subprocess_exec
    async def run():
        children = []
        started = asyncio.Event()
        async def start_blocked_parser(*command, **kwargs):
            process = await original_create(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
            children.append(process)
            started.set()
            return process
        monkeypatch.setattr(asyncio, "create_subprocess_exec", start_blocked_parser)
        adapter = PDFAdapter(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=sample_pdf())))
        task = asyncio.create_task(adapter.download_and_extract("https://arxiv.org/pdf/x", "paper"))
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(children) == 1 and children[0].returncode is not None
        assert children[0].returncode != 0
    asyncio.run(run())


def test_unexpected_parser_exception_on_untrusted_pdf_is_parse_failure(monkeypatch):
    def broken_reader(*args):
        raise KeyError("/Root")
    monkeypatch.setattr(_pdf_parser, "PdfReader", broken_reader)
    assert _pdf_parser.parse_pdf(b"sample", 2)["error"]["code"] == "parse_failed"

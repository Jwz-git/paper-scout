import asyncio
import time
from pathlib import Path

import httpx
import pytest

from backend.app.adapters.arxiv import ArXivAdapter, ArXivError, parse_arxiv_feed


SAMPLE = (Path(__file__).parent / "fixtures" / "arxiv_sample.xml").read_text(encoding="utf-8")
ERROR_FEED = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/api/errors#incorrect_id_format_for_1234.12345</id>
<title>Error</title><summary>incorrect id format for 1234.12345</summary>
</entry></feed>'''


def test_parse_arxiv_feed_fixture():
    papers = parse_arxiv_feed(SAMPLE)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.id == "arxiv:2203.08975v2"
    assert paper.source_id == "2203.08975v2" and paper.source == "arxiv"
    assert "Multi-Agent Deep Reinforcement Learning" in paper.title
    assert paper.year == 2022
    assert paper.authors == ["Changxi Zhu", "Mehdi Dastani"]
    assert paper.doi == "10.1007/s10458-023-09633-6"
    assert paper.primary_category == "cs.MA" and "cs.LG" in paper.categories
    assert paper.pdf_url == "http://arxiv.org/pdf/2203.08975v2"
    assert "survey recent works" in paper.abstract


@pytest.mark.parametrize("link_path,href", [
    ("abs", "javascript:alert(1)"),
    ("abs", "https://arxiv.org.evil.test/abs/x"),
    ("abs", "https://user:password@arxiv.org/abs/x"),
    ("pdf", "javascript:alert(1)"),
])
def test_malicious_metadata_links_are_invalid_feed(link_path, href):
    old = f'href="http://arxiv.org/{link_path}/2203.08975v2"'
    feed = SAMPLE.replace(old, f'href="{href}"')
    with pytest.raises(ArXivError) as error:
        parse_arxiv_feed(feed)
    assert error.value.code == "invalid_feed"


def test_missing_pdf_link_remains_missing_instead_of_inventing_url():
    feed = SAMPLE.replace('<link href="http://arxiv.org/pdf/2203.08975v2" rel="related" type="application/pdf" title="pdf"/>', "")
    assert parse_arxiv_feed(feed)[0].pdf_url is None


@pytest.mark.parametrize("feed,code", [("<feed", "invalid_xml"), ("<html>error</html>", "invalid_feed"), (ERROR_FEED, "api_error")])
def test_failed_xml_and_atom_error_are_not_success_or_papers(feed, code):
    with pytest.raises(ArXivError) as error:
        parse_arxiv_feed(feed)
    assert error.value.code == code


def test_valid_empty_feed_is_a_real_empty_result():
    assert parse_arxiv_feed('<feed xmlns="http://www.w3.org/2005/Atom"/>') == []


def test_pause_during_rate_wait_is_checked_before_http_request():
    class Halt(RuntimeError):
        pass

    async def run():
        waiting, release = asyncio.Event(), asyncio.Event()
        events = []
        paused = False

        async def wait_for_rate():
            events.append("rate_wait")
            waiting.set()
            await release.wait()

        async def checkpoint():
            events.append("checkpoint")
            if paused:
                raise Halt("paused")

        def handler(request):
            pytest.fail("等待中暂停后不得发起 HTTP 请求")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = ArXivAdapter(rate_limit_seconds=0, client=client)
            adapter._enforce_rate_limit = wait_for_rate
            task = asyncio.create_task(adapter.search("ti:agent", on_request=checkpoint))
            await waiting.wait()
            assert events == ["rate_wait"]
            paused = True
            release.set()
            with pytest.raises(Halt, match="paused"):
                await task
            assert events == ["rate_wait", "checkpoint"]
    asyncio.run(run())


def test_rate_limit_enforcement():
    async def run():
        adapter = ArXivAdapter(rate_limit_seconds=0.05)
        start_time = time.monotonic()
        await adapter._enforce_rate_limit()
        await adapter._enforce_rate_limit()
        assert time.monotonic() - start_time >= 0.045
    asyncio.run(run())


def test_search_uses_mock_transport_and_exact_query_parameters():
    def handler(request):
        assert str(request.url).startswith(ArXivAdapter.BASE_URL)
        assert dict(request.url.params) == {"search_query": "ti:agent", "start": "2", "max_results": "1",
                                           "sortBy": "submittedDate", "sortOrder": "descending"}
        assert request.headers["user-agent"] == "PaperScout-test"
        return httpx.Response(200, text=SAMPLE)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = ArXivAdapter(user_agent="PaperScout-test", rate_limit_seconds=0, client=client)
            papers = await adapter.search("ti:agent", start=2, max_results=1, sort_by="submittedDate")
            assert papers[0].source_id == "2203.08975v2"
    asyncio.run(run())


@pytest.mark.parametrize("status,body,code", [(200, ERROR_FEED, "api_error"), (429, "rate limited", "rate_limited"),
                                             (503, "unavailable", "server_error"), (404, "missing", "http_error"),
                                             (200, "<bad", "invalid_xml")])
def test_search_service_failure_is_explicit_with_mock_transport(status, body, code):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, text=body))) as client:
            adapter = ArXivAdapter(rate_limit_seconds=0, client=client, retry_delay_seconds=0)
            with pytest.raises(ArXivError) as error:
                await adapter.search("ti:agent")
            assert error.value.code == code
    asyncio.run(run())


def test_transient_failures_retry_with_each_attempt_counted():
    responses = [httpx.Response(429), httpx.Response(503), httpx.Response(200, text=SAMPLE)]
    counted = []
    async def on_request():
        counted.append(1)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: responses.pop(0))) as client:
            adapter = ArXivAdapter(rate_limit_seconds=0, client=client, retry_delay_seconds=0)
            papers = await adapter.search("ti:agent", on_request=on_request)
            assert papers and len(counted) == 3
            responses.extend([httpx.Response(503)] * 3)
            with pytest.raises(ArXivError):
                await adapter.search("ti:agent", on_request=on_request)
            assert len(counted) == 6 and not responses
    asyncio.run(run())

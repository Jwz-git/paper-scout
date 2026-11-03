"""报告快照、中文/分页导出和下载不调用模型的定向验证。"""
from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.reports import markdown, pdf, word
from backend.app.storage.database import Database
from backend.app.domain.models import Task
from tests.test_analysis import ResearchModel, ResearchSearch, run_research


@pytest.fixture
def completed(tmp_path):
    db = Database(tmp_path / 'reports.db')
    db.create_task(Task(id='t', topic='Agents'))
    run, model, _ = run_research(db, ResearchModel(), ResearchSearch(2), max_rounds=1)
    yield db, db.get_report(run.id), model, tmp_path
    db.close()


def test_three_formats_keep_report_identity_facts_and_missing_data(completed):
    db, report, _, _ = completed
    md = markdown(report)
    document = Document(BytesIO(word(report)))
    doc_text = '\n'.join([p.text for p in document.paragraphs] + [cell.text for table in document.tables for row in table.rows for cell in row.cells])
    pdf_doc = PdfReader(BytesIO(pdf(report)))
    pdf_text = '\n'.join(page.extract_text() for page in pdf_doc.pages)
    for text in (md, doc_text, pdf_text):
        assert report.id in text and '研究范围' in text and '缺口' in text
        assert report.document.evidence[0].id in text
        assert report.document.evidence[0].quote in text.replace('\n', '')
        assert report.stop_reason in text
    assert len(pdf_doc.pages) > 1
    assert all('/FontFile2' in font.get_object()['/FontDescriptor'].get_object()
        for page in pdf_doc.pages for font in page['/Resources']['/Font'].get_object().values()
        if '/FontDescriptor' in font.get_object())


def test_long_table_rows_and_markup_are_text_not_commands(completed):
    _, report, _, _ = completed
    report = report.model_copy(deep=True)
    report.document.analyses[0].fields[0].value = ('中文长表格 <tag> & | 科研证据 ' * 120)
    report.document.analyses[0].fields[0].note = 'x' * 400
    pdf_bytes = pdf(report)
    assert len(PdfReader(BytesIO(pdf_bytes)).pages) > 2
    doc = Document(BytesIO(word(report)))
    assert any('<tag> & |' in cell.text for table in doc.tables for row in table.rows for cell in row.cells)


def test_downloads_bind_report_id_and_never_generate(completed):
    db, original, model, path = completed
    new = original.model_copy(deep=True)
    new.id, new.title = uuid4().hex, '新版本报告'
    new.content_markdown = markdown(new)
    db.save_report(new)
    cfg = Settings(_env_file=None, data_dir=path, llm_base_url='', llm_model='', llm_api_key='')
    calls = len(model.requests)
    with TestClient(create_app(config=cfg, db=db, run_worker=False), base_url='http://127.0.0.1') as client:
        assert client.get('/api/runs/r/report').json()['id'] == new.id
        assert client.get('/api/runs/r/report', params={'report_id':original.id}).json()['id'] == original.id
        for suffix, media in [('md','text/markdown'),('docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document'),('pdf','application/pdf')]:
            response = client.get('/api/runs/r/report.' + suffix, params={'report_id':original.id})
            assert response.status_code == 200 and media in response.headers['content-type']
        assert client.get('/api/runs/r/report.pdf?report_id=foreign').status_code == 404
        assert client.get('/api/runs/r/analysis?revision=999').status_code == 404
        data = client.get('/api/runs/r/analysis').json()
        assert data['analyses'] and data['assessment']['field_counts']
        detail = client.get('/api/runs/r/papers/p0').json()
        assert detail['analysis']['fields'] and detail['selection']['reason']
    assert len(model.requests) == calls

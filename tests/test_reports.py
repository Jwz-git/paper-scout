"""报告快照、中文/分页导出和下载不调用模型的定向验证。"""
from urllib.parse import quote
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
from backend.app.domain.models import Paper
from tests.agent_fakes import paper, research


@pytest.fixture
def completed(tmp_path):
    db = Database(tmp_path / 'reports.db')
    _, task_id, model = research(db)
    run = db.agent_run(task_id)
    yield db, run.id, db.get_report(run.id), model, tmp_path
    db.close()


def test_three_formats_keep_report_identity_facts_and_missing_data(completed):
    _, _, report, _, _ = completed
    md = markdown(report)
    document = Document(BytesIO(word(report)))
    doc_text = '\n'.join([p.text for p in document.paragraphs] + [cell.text for table in document.tables for row in table.rows for cell in row.cells])
    pdf_doc = PdfReader(BytesIO(pdf(report)))
    pdf_text = '\n'.join(page.extract_text() for page in pdf_doc.pages)
    for text in (md, doc_text, pdf_text):
        assert report.id in text and '研究范围' in text and '缺口' in text
        assert report.document.evidence[0].id in text
        assert report.document.evidence[0].quote in text.replace('\n', '')
        assert report.gaps[0] in text.replace('\n', '')
    assert len(pdf_doc.pages) > 1
    assert all('/FontFile2' in font.get_object()['/FontDescriptor'].get_object()
        for page in pdf_doc.pages for font in page['/Resources']['/Font'].get_object().values()
        if '/FontDescriptor' in font.get_object())


def test_long_table_rows_and_markup_are_text_not_commands(completed):
    _, _, report, _, _ = completed
    report = report.model_copy(deep=True)
    report.document.analyses[0].fields[0].value = ('中文长表格 <tag> & | 科研证据 ' * 120)
    report.document.analyses[0].fields[0].note = 'x' * 400
    pdf_bytes = pdf(report)
    assert len(PdfReader(BytesIO(pdf_bytes)).pages) > 2
    doc = Document(BytesIO(word(report)))
    assert any('<tag> & |' in cell.text for table in doc.tables for row in table.rows for cell in row.cells)


def test_downloads_bind_report_id_and_never_generate(completed):
    db, run_id, original, model, path = completed
    new = original.model_copy(deep=True)
    new.id, new.title = uuid4().hex, '新版本报告'
    new.content_markdown = markdown(new)
    db.save_report(new)
    cfg = Settings(_env_file=None, data_dir=path, llm_base_url='', llm_model='', llm_api_key='')
    calls = len(model.requests)
    base = f'/api/runs/{run_id}'
    with TestClient(create_app(config=cfg, db=db, run_worker=False), base_url='http://127.0.0.1') as client:
        assert client.get(base + '/report').json()['id'] == new.id
        assert client.get(base + '/report', params={'report_id':original.id}).json()['id'] == original.id
        for suffix, media in [('md','text/markdown'),('docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document'),('pdf','application/pdf')]:
            response = client.get(base + '/report.' + suffix, params={'report_id':original.id})
            assert response.status_code == 200 and media in response.headers['content-type']
        assert client.get(base + '/report.pdf?report_id=foreign').status_code == 404
        assert client.get(base + '/analysis?revision=999').status_code == 404
        data = client.get(base + '/analysis').json()
        assert data['analyses'] and data['assessment']['field_counts']
        detail = client.get(base + '/papers/' + quote(paper(0).id, safe='')).json()
        assert detail['analysis']['fields'] and detail['selection']['reason'] and detail['selected']
        legacy = Paper(id='arxiv:cond-mat/0102536v1', source_id='cond-mat/0102536v1', title='Legacy id', url='https://arxiv.org/abs/cond-mat/0102536v1')
        db.save_papers([legacy], run_id)
        response = client.get(base + '/papers/' + quote(legacy.id, safe=''))
        assert response.status_code == 200 and response.json()['paper']['id'] == legacy.id
    assert len(model.requests) == calls

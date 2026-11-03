"""科研闭环的离线反例；人工替身只验证控制与证据契约，不评估语义正确率。"""
import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.adapters.llm import LLMResponse, LLMUsage
from backend.app.analysis import (
    AnalysisError, FIELD_LABELS, ExtractionOutput, Quote, compare_experiments, evaluate, evidence_for,
    extract_result, paper_groups, screen_result, source_inputs,
)
from backend.app.domain.models import (
    Experiment, Paper, PaperAnalysis, Run, RunMessage, RunStatus, SourceText, SourceType, Task, TaskInput,
)
from backend.app.storage.database import Database
from backend.app.workflow.engine import WorkflowEngine
from tests.analysis_samples import analysis_response, planned


class ResearchModel:
    def __init__(self, hook=None, complete=True, supplement=None):
        self.requests = []
        self.hook, self.complete, self.supplement = hook, complete, supplement

    async def generate(self, messages, **kwargs):
        request = json.loads(messages[-1].content)
        self.requests.append(request)
        if request.get("operation"):
            result = analysis_response(request, complete=self.complete)
        elif request["supplements"]:
            result = planned({"queries":[], "subproblems":["agents"], "keep_paper_ids":[p["id"] for p in request["papers"]], **(self.supplement or {})})
        else:
            result = planned({"queries":[f'all:agents{len(self.requests)}'], "subproblems":["agents"]})
        if self.hook:
            self.hook(request, result)
        return LLMResponse(content=json.dumps(result), parsed_json=result, usage=LLMUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7))


class ResearchSearch:
    def __init__(self, count=6):
        self.calls = []
        self.papers = [Paper(id=f"p{i}", source_id=f"fixture-{i}", title=f"人工样例 {i}",
            url=f"https://arxiv.org/abs/fixture-{i}", year=2024,
            abstract=f"Artificial fixture {i}: agents use method M on dataset D. Score 80 percent. Limited to this setting.") for i in range(count)]

    async def search(self, query, **kwargs):
        await kwargs["on_request"]()
        self.calls.append(query)
        return self.papers


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / 'analysis.db')
    db.create_task(Task(id="t", topic="Agents"))
    yield db
    db.close()


def run_research(store, model=None, search=None, **kwargs):
    store.create_run(Run(id="r", task_id="t", initial_topic="Agents", **kwargs))
    model, search = model or ResearchModel(), search or ResearchSearch()
    engine = WorkflowEngine(store, llm_adapter=model, arxiv_adapter=search)
    return asyncio.run(engine.execute_run("r")), model, search


def test_real_state_machine_reaches_completed_only_with_report_and_evidence(store):
    run, model, _ = run_research(store)
    report = store.get_report('r')
    assert run.status == RunStatus.COMPLETED and report.document.assessment.sufficient
    assert run.total_calls == 10 and run.model_calls == 9
    assert len(report.document.analyses) == 6 and len(report.document.sections) == 3
    assert all(f.evidence_ids for a in report.document.analyses for f in a.fields)
    assert '未进行人工语义复核' in report.content_markdown
    assert len([r for r in model.requests if r.get('operation') == 'extract']) == 6


def test_unicode_nonzero_windows_reject_quotes_from_unsupplied_text():
    source = SourceText(id='s', paper_id='p', source_type=SourceType.FULLTEXT,
        page_number=3, content='x' * 3000 + '😀有效证据' + 'y' * 4000)
    run = Run(id='r', task_id='t', initial_topic='T', current_input=TaskInput(topic='T'))
    window = next(s for s in source_inputs([source]) if s['location_start'] == 3000)
    payload = analysis_response({'operation':'extract', 'sources':[window], 'fields':list(FIELD_LABELS)})
    result, refs = extract_result(payload, run, Paper(id='p', source_id='p', title='P', url='https://arxiv.org/abs/p'), [window])
    assert refs[0].location_start == 3000 and refs[0].quote.startswith('😀')
    assert source.content[refs[0].location_start:refs[0].location_end] == refs[0].quote
    bad = payload['fields'][0]['citations'][0]
    bad['quote'] = 'x'
    with pytest.raises(AnalysisError, match='提供'):
        extract_result(payload, run, Paper(id='p', source_id='p', title='P', url='https://arxiv.org/abs/p'), [window])
    assert result.ranges[0].page_number == 3


def test_quote_position_is_derived_from_exact_text_inside_provided_window():
    text, quote = '前缀😀 unique fact. 后缀', '😀 unique fact.'
    window = {'source_text_id':'s', 'page_number':7, 'content':text,
              'location_start':3000, 'location_end':3000 + len(text)}
    ref = evidence_for([Quote(source_text_id='s', quote=quote)], [window], 'p')[0]
    assert ref.location_start == 3002 and ref.location_end == 3002 + len(quote)
    assert ref.page_number == 7 and ref.paper_id == 'p'
    assert text[ref.location_start - 3000:ref.location_end - 3000] == quote


@pytest.mark.parametrize('texts, quote', [(['same same'], 'same'), (['same', 'same'], 'same'), (['aaaa'], 'aaa')])
def test_ambiguous_quotes_are_not_assigned_the_first_matching_location(texts, quote):
    windows = [{'source_text_id':'s', 'page_number':1, 'content':text,
                'location_start':i * 3000, 'location_end':i * 3000 + len(text)} for i, text in enumerate(texts)]
    with pytest.raises(AnalysisError, match='多次'):
        evidence_for([Quote(source_text_id='s', quote=quote)], windows, 'p')


@pytest.mark.parametrize('text', [' Leading quote.', 'Trailing quote. ', '\n😀 Exact quote.\t'])
def test_screening_preserves_quote_whitespace_and_global_range(text):
    paper = ResearchSearch(1).papers[0]
    run = Run(id='r', task_id='t', initial_topic='T', current_input=TaskInput(topic='T'), subproblems=['agents'])
    source = {'source_text_id':'s', 'source_type':'abstract', 'page_number':None,
              'location_start':3000, 'location_end':3000 + len(text), 'content':text}
    request = {'operation':'screen', 'subproblems':run.subproblems,
               'papers':[{'id':paper.id, 'sources':[source]}]}
    selections, refs = screen_result(analysis_response(request), run, [paper], {paper.id:[source]})
    assert selections[0].relevant and selections[0].evidence_ids == [refs[0].id]
    assert refs[0].quote == text
    assert (refs[0].location_start, refs[0].location_end) == (3000, 3000 + len(text))


@pytest.mark.parametrize('fault, diagnostic', [
    ('missing_paper', '筛选结果必须覆盖本次每篇候选论文'),
    ('unknown_subproblem', '筛选结果引用了未知子问题'),
    ('missing_basis', '相关论文必须关联子问题和实际依据'),
    ('foreign_source', '引用不属于本次提供的来源范围'),
    ('wrong_quote', '引用与原文不一致'),
])
def test_screening_failure_keeps_safe_reason_and_unreviewed_candidates(store, fault, diagnostic):
    def hook(request, response):
        if request.get('operation') != 'screen':
            return
        selection = response['selections'][0]
        if fault == 'missing_paper':
            response['selections'].pop()
        elif fault == 'unknown_subproblem':
            selection['subproblems'] = ['private_raw_output']
        elif fault == 'missing_basis':
            selection['citations'] = []
        elif fault == 'foreign_source':
            selection['citations'][0]['source_text_id'] = 'private_raw_output'
        else:
            selection['citations'][0]['quote'] = 'private_raw_output'
    run, model, _ = run_research(store, ResearchModel(hook=hook), ResearchSearch(2))
    assert run.status == RunStatus.PARTIAL and run.total_calls == 3 and run.model_calls == 2
    assert diagnostic in run.stop_reason and 'private_raw_output' not in run.stop_reason
    events = [e for e in store.list_events('r') if e.category == 'service_error']
    assert len(events) == 1 and events[0].message == run.stop_reason
    assert store.list_selections('r', 1) == [] and store.list_analyses('r') == []
    assert not any(r.get('operation') in ('extract', 'synthesize') for r in model.requests)
    report = store.get_report('r')
    assert report.stop_reason == run.stop_reason and report.document.sources
    assert '候选论文组（筛选未完成） 2/6' in report.gaps
    assert any('2篇候选尚未完成相关性筛选' in gap for gap in report.gaps)


def test_missing_values_cannot_be_filled_without_evidence():
    source = {'source_text_id':'s', 'content':'Only a method.', 'location_start':0}
    payload = analysis_response({'operation':'extract', 'sources':[source], 'fields':list(FIELD_LABELS)})
    assert ExtractionOutput.model_validate(payload).fields[2].value is None
    payload['fields'][2]['value'] = 'Invented dataset'
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(payload)


def test_doi_and_versions_group_but_similar_titles_remain_candidates():
    papers = ResearchSearch(4).papers
    papers[0].doi, papers[1].doi = 'https://doi.org/10.123/ABC', '10.123/abc'
    papers[2].source_id, papers[3].source_id = '1234.12345v1', '1234.12345v2'
    groups, _ = paper_groups(papers)
    assert groups['p0'] == groups['p1'] and groups['p2'] == groups['p3']
    papers[3].source_id = 'different'
    papers[2].title = papers[3].title = 'Nearly identical paper title'
    papers[2].authors = papers[3].authors = ['Fixture Author']
    groups, candidates = paper_groups(papers)
    assert groups['p2'] != groups['p3'] and ['p2', 'p3'] in candidates


@pytest.mark.parametrize('change,status', [({},'comparable'), ({'split':'other test split'},'not_comparable'), ({'compute':None},'insufficient')])
def test_comparison_requires_all_experimental_conditions(change, status):
    values = dict(dataset='D', dataset_version='1', split='test', metric='accuracy', value='80', unit='percent', direction='higher', protocol='one trial', compute='CPU', evidence_ids=['e'])
    left = Experiment(id='a', paper_id='p0', **values)
    right = Experiment(id='b', paper_id='p1', **{**values, **change})
    analyses = [PaperAnalysis(id=str(i), run_id='r', paper_id=f'p{i}', analysis_revision=1, round_number=1, status='completed', experiments=[e]) for i,e in enumerate([left,right])]
    comparisons = compare_experiments(analyses, {'p0':'p0','p1':'p1'})
    assert comparisons[0].status == status
    assert compare_experiments(analyses, {'p0':'same','p1':'same'}) == []


@pytest.mark.parametrize('operation', ['extract', 'synthesize'])
def test_pause_persists_analysis_or_summary_before_resuming(store, operation):
    paused = False
    def hook(request, response):
        nonlocal paused
        if not paused and request.get('operation') == operation:
            paused = True
            store.pause_run('r')
    model = ResearchModel(hook=hook)
    run, _, search = run_research(store, model)
    assert run.status == RunStatus.PAUSED
    completed_before = [r.get('paper_id') for r in model.requests if r.get('operation') == 'extract']
    assert store.list_analyses('r')
    if operation == 'synthesize':
        assert run.pending_sections
    store.transition('r', [RunStatus.PAUSED], RunStatus.QUEUED)
    final = asyncio.run(WorkflowEngine(store, llm_adapter=model, arxiv_adapter=search).execute_run('r'))
    assert final.status == RunStatus.COMPLETED
    extract_ids = [r.get('paper_id') for r in model.requests if r.get('operation') == 'extract']
    assert all(extract_ids.count(pid) == 1 for pid in completed_before)
    assert sum(r.get('operation') == 'synthesize' for r in model.requests) == 1


@pytest.mark.parametrize('new_focus', [False, True])
def test_supplement_without_queries_reuses_or_reextracts_by_contract(store, new_focus):
    paused = False
    def hook(request, response):
        nonlocal paused
        if not paused and request.get('operation') == 'extract':
            paused = True
            store.pause_run('r')
    model = ResearchModel(hook=hook, supplement={'revised_scope':{'topic':'Agents','focus_dimensions':['novelty']}} if new_focus else None)
    run, _, search = run_research(store, model, ResearchSearch(1), max_rounds=1)
    old = store.list_analyses('r', 1)[0]
    store.save_run_message(RunMessage(id='m', run_id='r', content='仅根据已有资料，补充分析'))
    store.transition('r', [RunStatus.PAUSED], RunStatus.QUEUED)
    final = asyncio.run(WorkflowEngine(store, llm_adapter=model, arxiv_adapter=search).execute_run('r'))
    current = store.list_analyses('r', 2)[0]
    assert final.analysis_revision == 2 and len(search.calls) == 1
    assert store.list_analyses('r', 1)[0] == old
    calls = [r for r in model.requests if r.get('operation') == 'extract']
    assert len(calls) == (2 if new_focus else 1)
    assert ('novelty' in [f.field_name for f in current.fields]) == new_focus
    assert current.reused_from == (None if new_focus else old.id)


def test_invalid_analysis_is_recorded_not_disguised_as_empty_fields(store):
    def hook(request, response):
        if request.get('operation') == 'extract':
            response['fields'][0]['citations'][0]['source_text_id'] = 'foreign'
    run, _, _ = run_research(store, ResearchModel(hook=hook), ResearchSearch(1))
    assert run.status == RunStatus.PARTIAL
    assert store.list_analyses('r')[0].status == 'failed'
    assert not store.list_analyses('r')[0].fields
    assert 'AnalysisError' in run.stop_reason and store.get_report('r')


def test_limit_does_not_add_free_report_call(store):
    run, model, _ = run_research(store, max_calls=4)
    assert run.status == RunStatus.PARTIAL and run.total_calls == 3
    assert not any(r.get('operation') in ('extract', 'synthesize') for r in model.requests)
    assert store.get_report('r').document.sections == []


def test_missing_fields_drive_distinct_queries_then_no_progress_stops(store):
    run, model, search = run_research(store, ResearchModel(complete=False), ResearchSearch(2), max_rounds=5)
    assert run.status == RunStatus.PARTIAL
    assert len(set(search.calls)) == len(search.calls) == 3
    assert '连续两轮' in run.stop_reason
    plans = [r for r in model.requests if 'supplements' in r]
    assert plans[1]['gaps'] and all(q.subproblems == ['agents'] for q in store.list_queries('r'))


def test_six_versions_do_not_satisfy_six_papers(store):
    search = ResearchSearch()
    for paper in search.papers:
        paper.doi = '10.123/same'
    run, _, _ = run_research(store, search=search, max_rounds=1)
    assert run.status == RunStatus.PARTIAL
    assessment = store.list_assessments('r')[-1]
    assert len(set(assessment.paper_groups.values())) == 1
    assert len(assessment.supporting_papers['agents']) == 1


@pytest.mark.parametrize('operation', ['screen', 'extract', 'synthesize'])
def test_cancellation_during_analysis_never_starts_later_work(store, operation):
    def hook(request, response):
        if request.get('operation') == operation:
            store.cancel_run('r')
    run, model, _ = run_research(store, ResearchModel(hook=hook), ResearchSearch(1), max_rounds=1)
    assert run.status == RunStatus.CANCELLED and store.get_report('r') is None
    assert model.requests[-1].get('operation') == operation


def test_timed_out_extraction_records_failed_attempt_and_unknown_usage(store):
    class SlowModel(ResearchModel):
        async def generate(self, messages, **kwargs):
            request = json.loads(messages[-1].content)
            if request.get('operation') == 'extract':
                self.requests.append(request)
                await asyncio.Event().wait()
            return await super().generate(messages, **kwargs)
    run, _, _ = run_research(store, SlowModel(), ResearchSearch(1), max_seconds=.1)
    assert run.status == RunStatus.PARTIAL and run.total_calls == 4
    assert run.token_usage['total_tokens'] is None
    assert store.list_analyses('r')[0].status == 'failed'
    assert store.list_analyses('r')[0].ranges


def test_report_failure_cannot_publish_completed(store, monkeypatch):
    def fail(report):
        raise RuntimeError('deliberate storage failure')
    monkeypatch.setattr(store, 'save_report', fail)
    with pytest.raises(RuntimeError, match='deliberate'):
        run_research(store)
    assert store.get_run('r').status == RunStatus.FAILED and store.get_report('r') is None


def test_analysis_survives_reopen_and_trash_cleans_new_relations(store):
    run_research(store, search=ResearchSearch(1), max_rounds=1)
    reopened = Database(store.db_path)
    try:
        assert reopened.list_analyses('r')[0].fields
        assert reopened.get_report('r').document
    finally:
        reopened.close()
    store.trash_task('t', True)
    store.delete_trash(['t'])
    assert store.list_analyses('r') == [] and store.list_selections('r', 1) == []

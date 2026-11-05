"""有界论文分析；模型负责提取，代码负责来源范围、比较条件和覆盖口径。"""
import re
from difflib import SequenceMatcher
from itertools import combinations
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.models import (
    Assessment, Comparison, Evidence, Experiment, Extraction, MissingReason,
    PaperAnalysis, PaperSelection, ReadRange, ReportClaim, ReportSection, SourceType,
)

FIELD_LABELS = {
    "research_question": "研究问题", "method": "方法", "datasets": "数据集",
    "metrics": "指标", "results": "结果", "limitations": "局限",
}
ORIGIN_LABELS = {"author": "作者自述", "inference": "系统推断", "user": "用户要求"}
MISSING_LABELS = {
    "not_available": "来源不可用", "not_read": "尚未读取", "not_found": "所提供片段中未找到",
    "parse_failed": "解析失败", "not_applicable": "不适用",
}
CHUNK_SIZE = 3000
INPUT_CHARS = 18000


class AnalysisError(ValueError):
    """只使用代码生成的安全原因，不拼接模型原文、用户字段或服务响应。"""


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Quote(Output):
    # 引用与位置必须保持原样，不能继承普通字段的首尾空白裁剪。
    model_config = ConfigDict(str_strip_whitespace=False)
    source_text_id: str
    quote: str = Field(min_length=1, max_length=2000, description="复制本次提供片段中唯一出现的完整原文；字符位置由程序计算。")


class FieldOutput(Output):
    field_name: str = Field(min_length=1, max_length=200)
    value: Optional[str] = Field(default=None, max_length=2000)
    missing_reason: Optional[MissingReason] = None
    origin: Literal["author", "inference"] = "author"
    note: str = Field(default="", max_length=1000)
    citations: List[Quote] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def value_or_missing(self):
        if self.value:
            if self.missing_reason is not None or not self.citations:
                raise ValueError("非空字段必须有原文引用且不能同时缺失")
        elif self.value is not None or self.missing_reason is None or self.citations:
            raise ValueError("缺失字段使用null、缺失原因和空引用")
        return self


class ExperimentOutput(Output):
    dataset: Optional[str] = Field(default=None, max_length=200)
    dataset_version: Optional[str] = Field(default=None, max_length=200)
    split: Optional[str] = Field(default=None, max_length=500)
    metric: Optional[str] = Field(default=None, max_length=200)
    value: Optional[str] = Field(default=None, max_length=200)
    unit: Optional[str] = Field(default=None, max_length=100)
    direction: Optional[Literal["higher", "lower"]] = None
    protocol: Optional[str] = Field(default=None, max_length=1000)
    compute: Optional[str] = Field(default=None, max_length=500)
    citations: List[Quote] = Field(min_length=1, max_length=6)


class ExtractionOutput(Output):
    fields: List[FieldOutput] = Field(min_length=6, max_length=18)
    experiments: List[ExperimentOutput] = Field(default_factory=list, max_length=4)


class SelectionOutput(Output):
    paper_id: str
    relevant: bool
    reason: str = Field(min_length=1, max_length=1000)
    subproblems: List[str] = Field(default_factory=list, max_length=12)
    citations: List[Quote] = Field(default_factory=list, max_length=3)


class ScreeningOutput(Output):
    selections: List[SelectionOutput] = Field(min_length=1, max_length=12)


class ClaimOutput(Output):
    text: str = Field(min_length=1, max_length=1500)
    evidence_ids: List[str] = Field(min_length=1, max_length=8)
    origin: Literal["author", "inference"]


class SynthesisOutput(Output):
    background: List[ClaimOutput] = Field(min_length=1, max_length=4)
    taxonomy: List[ClaimOutput] = Field(min_length=1, max_length=6)
    conclusions: List[ClaimOutput] = Field(min_length=1, max_length=6)


def field_names(scope):
    return list(dict.fromkeys([*FIELD_LABELS, *scope.focus_dimensions]))


def source_inputs(sources, previous=(), focus=()):
    """仅发送未分析过的完整字符窗口；优先摘要及包含关注词/实验章节的窗口。"""
    seen = {(r.source_text_id, r.location_start, r.location_end) for r in previous}
    words = [w.casefold() for w in [*focus, "experiment", "evaluation", "limitation", "result"]]
    windows = []
    for source in sources:
        if source.status != "ok" or source.source_type == SourceType.METADATA:
            continue
        for start in range(0, len(source.content), CHUNK_SIZE):
            end = min(start + CHUNK_SIZE, len(source.content))
            if (source.id, start, end) in seen:
                continue
            text = source.content[start:end]
            priority = 100 if source.source_type == SourceType.ABSTRACT else sum(word in text.casefold() for word in words)
            windows.append((priority, {"source_text_id": source.id, "source_type": source.source_type.value,
                "page_number": source.page_number, "location_start": start, "location_end": end,
                "original_length": len(source.content), "content": text}))
    windows.sort(key=lambda item: -item[0])
    result, size = [], 0
    for _, window in windows:
        if size + len(window["content"]) > INPUT_CHARS:
            break
        result.append(window)
        size += len(window["content"])
    return result


def read_ranges(inputs):
    return [ReadRange.model_validate({k: v for k, v in item.items() if k != "content"}) for item in inputs]


def evidence_for(citations, inputs, paper_id):
    evidence = []
    for citation in citations:
        windows = [s for s in inputs if s["source_text_id"] == citation.source_text_id]
        if not windows:
            raise AnalysisError("引用不属于本次提供的来源范围")
        match = None
        for window in windows:
            offset = window["content"].find(citation.quote)
            if offset < 0:
                continue
            if match is not None or offset != window["content"].rfind(citation.quote):
                raise AnalysisError("引用在本次提供范围内出现多次，无法唯一定位")
            match = (window, offset)
        if match is None:
            raise AnalysisError("引用与原文不一致（本次提供片段中未找到完整摘录）")
        window, offset = match
        start = window["location_start"] + offset
        evidence.append(Evidence(id=uuid4().hex, source_text_id=citation.source_text_id, paper_id=paper_id,
            page_number=window["page_number"], quote=citation.quote,
            location_start=start, location_end=start + len(citation.quote)))
    return evidence


def extract_result(payload, run, paper, inputs, previous=None):
    output = ExtractionOutput.model_validate(payload)
    names = [field.field_name for field in output.fields]
    if len(set(names)) != len(names) or set(names) != set(field_names(run.current_input)):
        raise AnalysisError("提取结果必须逐项覆盖本次约定字段，不能重复或省略")
    evidence, fields, experiments = [], [], []
    for field in output.fields:
        refs = evidence_for(field.citations, inputs, paper.id)
        evidence.extend(refs)
        fields.append(Extraction(id=uuid4().hex, run_id=run.id, paper_id=paper.id,
            field_name=field.field_name, value=field.value, missing_reason=field.missing_reason,
            origin=field.origin, is_inference=field.origin == "inference", note=field.note,
            evidence_ids=[e.id for e in refs]))
    for experiment in output.experiments:
        refs = evidence_for(experiment.citations, inputs, paper.id)
        evidence.extend(refs)
        experiments.append(Experiment(id=uuid4().hex, paper_id=paper.id,
            **experiment.model_dump(exclude={"citations"}), evidence_ids=[e.id for e in refs]))
    ranges = read_ranges(inputs)
    if previous:
        # 不以新片段的缺失覆盖已找到的事实；不同值保留并列，留待语义复核。
        prior_facts = [f for f in previous.fields if f.value is not None]
        fields = prior_facts + [f for f in fields if f.value is not None or not any(p.field_name == f.field_name for p in prior_facts)]
        experiments = previous.experiments + experiments
        ranges = previous.ranges + ranges
    result = PaperAnalysis(id=uuid4().hex, run_id=run.id, paper_id=paper.id,
        analysis_revision=run.analysis_revision, round_number=run.current_round, status="completed",
        focus_dimensions=run.current_input.focus_dimensions, ranges=ranges, fields=fields,
        experiments=experiments, reused_from=previous.id if previous else None)
    return result, evidence


def screen_result(payload, run, papers, inputs_by_paper):
    """逐篇校验；单篇结果无效只让该篇记为未纳入，不作废同批其他论文。"""
    output = ScreeningOutput.model_validate(payload)
    by_id = {}
    for selection in output.selections:
        by_id.setdefault(selection.paper_id, selection)
    evidence, selections = [], []
    for paper in papers:
        selection = by_id.get(paper.id)
        try:
            if selection is None:
                raise AnalysisError("模型未返回该论文的筛选结果")
            if not set(selection.subproblems) <= set(run.subproblems):
                raise AnalysisError("筛选结果引用了未知子问题")
            if selection.relevant and (not selection.subproblems or not selection.citations):
                raise AnalysisError("相关论文必须关联子问题和实际依据")
            refs = evidence_for(selection.citations, inputs_by_paper[paper.id], paper.id)
        except AnalysisError as exc:
            selections.append(PaperSelection(paper_id=paper.id, analysis_revision=run.analysis_revision,
                relevant=False, reason="筛选结果无效：" + str(exc), reviewed=False, error=str(exc)))
            continue
        evidence.extend(refs)
        selections.append(PaperSelection(**selection.model_dump(exclude={"citations"}),
            analysis_revision=run.analysis_revision, evidence_ids=[e.id for e in refs]))
    return selections, evidence


def paper_groups(papers):
    parents = {p.id: p.id for p in papers}
    def root(pid):
        while parents[pid] != pid:
            pid = parents[pid]
        return pid
    candidates = []
    for left, right in combinations(papers, 2):
        doi = lambda p: re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (p.doi or "").strip().casefold())
        source = lambda p: (p.source, re.sub(r"v\d+$", "", p.source_id) if p.source == "arxiv" else p.source_id)
        if (doi(left) and doi(left) == doi(right)) or source(left) == source(right):
            a, b = sorted([root(left.id), root(right.id)])
            parents[b] = a
        elif set(a.casefold() for a in left.authors) & set(a.casefold() for a in right.authors) and SequenceMatcher(None, left.title.casefold(), right.title.casefold()).ratio() >= .92:
            candidates.append([left.id, right.id])
    return {pid: root(pid) for pid in parents}, candidates


def compare_experiments(analyses, groups):
    result = []
    conditions = {"dataset": "数据集", "dataset_version": "数据集版本", "split": "划分",
        "metric": "指标", "unit": "单位", "direction": "指标方向", "protocol": "评价协议", "compute": "计算条件"}
    experiments = [e for a in analyses for e in a.experiments]
    for left, right in combinations(experiments, 2):
        if groups[left.paper_id] == groups[right.paper_id]:
            continue
        if left.metric and right.metric and left.metric.casefold() != right.metric.casefold():
            continue  # 不同指标不是同一比较维度。
        different, missing = [], []
        for key, label in conditions.items():
            a, b = getattr(left, key), getattr(right, key)
            if not a or not b:
                missing.append(label + "缺失")
            elif a.strip().casefold() != b.strip().casefold():
                different.append(label + "不一致")
        if left.value is None or right.value is None:
            missing.append("实验值缺失")
        status = "not_comparable" if different else "insufficient" if missing else "comparable"
        result.append(Comparison(left_paper_id=left.paper_id, right_paper_id=right.paper_id,
            left_experiment_id=left.id, right_experiment_id=right.id, status=status,
            reasons=different + missing or ["已提取条件一致"],
            evidence_ids=list(dict.fromkeys(left.evidence_ids + right.evidence_ids)), metric=left.metric,
            left_value=left.value, right_value=right.value))
    return result


def evaluate(run, papers, analyses, selections):
    groups, candidates = paper_groups(papers)
    current = {a.paper_id: a for a in analyses if a.status == "completed" and a.paper_id in groups}
    support = {sub: [] for sub in run.subproblems}
    for selection in selections:
        analysis = current.get(selection.paper_id)
        if not selection.relevant or not analysis or not any(f.value and f.evidence_ids for f in analysis.fields):
            continue
        for sub in selection.subproblems:
            if sub in support and groups[selection.paper_id] not in support[sub]:
                support[sub].append(groups[selection.paper_id])
    expected = run.current_input.focus_dimensions or list(FIELD_LABELS)
    counts = {}
    for paper in papers:
        fields = current[paper.id].fields if paper.id in current else []
        counts[paper.id] = [len({f.field_name for f in fields if f.field_name in expected and f.value and f.evidence_ids}), len(expected)]
    # 同作版本在完整率中也只算一组，采用该组最低值以免挑选最佳版本抬高覆盖。
    rates = {group: min(counts[pid][0] / counts[pid][1] for pid in groups if groups[pid] == group) for group in set(groups.values())}
    completeness = sum(rates.values()) / len(rates) if rates else 0.0
    gaps, actions = [], []
    unreviewed = set(groups) - {s.paper_id for s in selections if s.reviewed}
    failed = [s for s in selections if s.error]
    if failed:
        gaps.append(f"{len(failed)}篇候选的筛选结果无效，未纳入")
        actions.append("重新筛选结果无效的候选论文")
    if unreviewed:
        gaps.append(f"{len(unreviewed)}篇候选尚未完成相关性筛选，不能视为已纳入")
        actions.append("完成候选论文的相关性筛选")
    if len(rates) < run.min_papers:
        label = "候选论文组（筛选未完成）" if unreviewed else "纳入论文组"
        gaps.append(f"{label} {len(rates)}/{run.min_papers}")
        actions.append("补充不同候选论文的检索")
    for sub, ids in support.items():
        if len(ids) < run.min_per_subproblem:
            gaps.append(f"子问题「{sub}」有依据的相关论文组 {len(ids)}/{run.min_per_subproblem}")
            actions.append(f"针对「{sub}」生成不同查询")
    if completeness < run.min_field_completeness:
        gaps.append(f"约定字段有证据完整率 {completeness:.0%}，低于操作性门槛 {run.min_field_completeness:.0%}")
        actions.append("补读尚未提供的来源片段；无法获得时保留缺失")
    if not support:
        gaps.append("尚无可评估子问题")
    for paper in papers:
        if paper.id not in current:
            gaps.append(f"{paper.id}：尚无成功的结构化分析")
    comparisons = compare_experiments(list(current.values()), groups)
    return Assessment(id=uuid4().hex, run_id=run.id, round_number=run.current_round,
        analysis_revision=run.analysis_revision, rule=run.assessment_rule,
        subproblem_coverage={s: min(1.0, len(ids) / run.min_per_subproblem) for s, ids in support.items()},
        field_completeness={pid: n / d for pid, (n, d) in counts.items()}, supporting_papers=support,
        field_counts=counts, paper_groups=groups, duplicate_candidates=candidates, comparisons=comparisons,
        gaps=gaps, next_actions=list(dict.fromkeys(actions)), sufficient=not gaps, decision="sufficient" if not gaps else "continue")


def synthesize_result(payload, evidence_ids):
    output = SynthesisOutput.model_validate(payload)
    sections = []
    for key, title in [("background", "背景"), ("taxonomy", "研究分类"), ("conclusions", "综合结论")]:
        claims = []
        for claim in getattr(output, key):
            if not set(claim.evidence_ids) <= evidence_ids:
                raise AnalysisError("报告引用了当前分析范围外的证据")
            claims.append(ReportClaim(**claim.model_dump()))
        sections.append(ReportSection(title=title, claims=claims))
    return sections

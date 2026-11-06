"""论文事实的结构与核对：引文定位、同作分组和实验条件比较由代码完成，不交给模型。"""
import re
import unicodedata
from difflib import SequenceMatcher
from itertools import combinations
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.models import Comparison, MissingReason

FIELD_LABELS = {
    "research_question": "研究问题", "method": "方法", "datasets": "数据集",
    "metrics": "指标", "results": "结果", "limitations": "局限",
}
ORIGIN_LABELS = {"author": "作者自述", "inference": "系统推断", "user": "用户要求"}
MISSING_LABELS = {
    "not_available": "来源不可用", "not_read": "尚未读取", "not_found": "已读内容中未找到",
    "parse_failed": "解析失败", "not_applicable": "不适用",
}


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Quote(Output):
    # 引用必须保持原样，不能继承普通字段的首尾空白裁剪。
    model_config = ConfigDict(str_strip_whitespace=False)
    source_text_id: str
    quote: str = Field(min_length=1, max_length=2000, description="从已读原文逐字复制；字符位置由程序计算。")


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
                raise ValueError("有内容的发现必须给原文引用，且不能同时标记缺失")
        elif self.value is not None or self.missing_reason is None or self.citations:
            raise ValueError("缺失的字段用 value=null、missing_reason 和空 citations")
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


QUOTE_MARKS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‐": "-", "‑": "-", "−": "-"})


def normalized(text):
    """比较时忽略空白和连字符（PDF 换行、断词、排版空格），并保留到原文位置的映射。"""
    chars, positions = [], []
    for index, char in enumerate(text):
        for part in unicodedata.normalize("NFKC", char).translate(QUOTE_MARKS):
            if part.isspace() or part == "-":
                continue
            chars.append(part)
            positions.append(index)
    return "".join(chars), positions


def locate(content, quote):
    """返回 quote 在 content 中的全部 (起, 止)；空白和 PDF 排版差异不影响定位。"""
    target = normalized(quote)[0]
    if not target:
        return []
    text, positions = normalized(content)
    found, start = [], text.find(target)
    while start >= 0:
        found.append((positions[start], positions[start + len(target) - 1] + 1))
        start = text.find(target, start + 1)
    return found


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

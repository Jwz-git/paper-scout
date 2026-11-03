"""人工标注的评价计数；不以模型自评分或引用定位代替语义支持标签。"""
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1)
    sample_kind: Literal["real_public", "artificial"] = Field(description="必须区分真实公开资料与人工样例")
    report_id: str
    reference_paper_ids: Optional[List[str]] = None
    retrieved_relevance: Dict[str, Optional[StrictBool]]
    field_correctness: Dict[str, Optional[StrictBool]]
    citation_support: Dict[str, Optional[StrictBool]]
    subproblem_coverage: Dict[str, Optional[StrictBool]]
    notes: str


def metric(labels):
    values = list(labels)
    denominator = sum(value is not None for value in values)
    numerator = sum(value is True for value in values)
    return {"numerator":numerator, "denominator":denominator,
        "unknown":sum(value is None for value in values), "value":numerator / denominator if denominator else None}


def evaluate_cases(cases):
    results = []
    for case in cases:
        if case.reference_paper_ids is None:
            recall = {"numerator":0, "denominator":0, "unknown":True, "value":None}
        else:
            reference = set(case.reference_paper_ids)
            found = reference & case.retrieved_relevance.keys()
            recall = {"numerator":len(found), "denominator":len(reference), "unknown":False,
                "value":len(found) / len(reference) if reference else None}
        results.append({"topic":case.topic, "sample_kind":case.sample_kind, "report_id":case.report_id,
            "retrieval_precision":metric(case.retrieved_relevance.values()), "sample_recall":recall,
            "field_accuracy":metric(case.field_correctness.values()), "citation_support":metric(case.citation_support.values()),
            "subproblem_coverage":metric(case.subproblem_coverage.values()), "notes":case.notes})
    return {"method":"manual-labels-v1", "boundary":"仅代表所标注样本；未知标签不计为正确或错误，未设置质量达标线。人工样例与真实结果分别呈现，不混合汇总。", "cases":results}

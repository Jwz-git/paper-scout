"""引文定位、缺失字段格式、同作分组和实验条件比较；人工样例只验证证据契约，不评估语义正确率。"""
import pytest
from pydantic import ValidationError

from backend.app.analysis import FieldOutput, compare_experiments, locate, paper_groups
from backend.app.domain.models import Experiment, Paper, PaperAnalysis


def test_quote_position_is_measured_on_the_original_text():
    text, quote = "前缀😀 unique fact. 后缀", "😀 unique fact."
    assert locate(text, quote) == [(2, 2 + len(quote))]


@pytest.mark.parametrize("text", [" Leading quote.", "Trailing quote. ", "\n😀 Exact quote.\t"])
def test_surrounding_whitespace_is_not_part_of_the_located_quote(text):
    (start, end), = locate(text, text)
    assert text[start:end] == text.strip()


@pytest.mark.parametrize("text, quote", [("same same", "same"), ("aaaa", "aaa")])
def test_repeated_quotes_report_every_position(text, quote):
    assert len(locate(text, quote)) == 2


def test_pdf_layout_differences_still_locate_the_quote():
    text = "Our coarse-to-\nfine pipeline   reaches\n “65%” recall on KITTI360Pose."
    (start, end), = locate(text, 'coarse-to-fine pipeline reaches "65%" recall')
    assert text[start:end].startswith("coarse") and text[start:end].endswith("recall")
    assert locate(text, "原文中没有的句子") == [] and locate(text, " - ") == []


@pytest.mark.parametrize("finding", [
    {"field_name": "datasets", "value": "Invented dataset"},
    {"field_name": "datasets", "value": "D", "missing_reason": "not_found", "citations": [{"source_text_id": "s", "quote": "D"}]},
    {"field_name": "datasets", "value": None},
    {"field_name": "datasets", "value": None, "missing_reason": "not_found", "citations": [{"source_text_id": "s", "quote": "D"}]},
])
def test_values_need_citations_and_missing_values_need_a_reason(finding):
    with pytest.raises(ValidationError):
        FieldOutput.model_validate(finding)


def papers(count):
    return [Paper(id=f"p{i}", source_id=f"fixture-{i}", title=f"人工样例 {i}", url=f"https://arxiv.org/abs/fixture-{i}")
            for i in range(count)]


def test_doi_and_versions_group_but_similar_titles_remain_candidates():
    group = papers(4)
    group[0].doi, group[1].doi = "https://doi.org/10.123/ABC", "10.123/abc"
    group[2].source_id, group[3].source_id = "1234.12345v1", "1234.12345v2"
    groups, _ = paper_groups(group)
    assert groups["p0"] == groups["p1"] and groups["p2"] == groups["p3"]
    group[3].source_id = "different"
    group[2].title = group[3].title = "Nearly identical paper title"
    group[2].authors = group[3].authors = ["Fixture Author"]
    groups, candidates = paper_groups(group)
    assert groups["p2"] != groups["p3"] and ["p2", "p3"] in candidates


@pytest.mark.parametrize("change, status", [({}, "comparable"), ({"split": "other test split"}, "not_comparable"),
                                            ({"compute": None}, "insufficient")])
def test_comparison_requires_all_experimental_conditions(change, status):
    values = dict(dataset="D", dataset_version="1", split="test", metric="accuracy", value="80", unit="percent",
                  direction="higher", protocol="one trial", compute="CPU", evidence_ids=["e"])
    left = Experiment(id="a", paper_id="p0", **values)
    right = Experiment(id="b", paper_id="p1", **{**values, **change})
    analyses = [PaperAnalysis(id=str(i), run_id="r", paper_id=f"p{i}", analysis_revision=1, round_number=1, status="completed",
                              experiments=[e]) for i, e in enumerate([left, right])]
    assert compare_experiments(analyses, {"p0": "p0", "p1": "p1"})[0].status == status
    assert compare_experiments(analyses, {"p0": "same", "p1": "same"}) == []

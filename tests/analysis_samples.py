"""明确的人工模型响应，仅用于离线行为验证，不代表科研答案。"""
from backend.app.analysis import FIELD_LABELS


def quote(source):
    text = source["content"][:min(80, len(source["content"]))]
    return {"source_text_id":source["source_text_id"], "quote":text}


def analysis_response(request, complete=False):
    operation = request.get("operation")
    if operation == "screen":
        return {"selections":[{"paper_id":paper["id"], "relevant":True,
            "reason":"人工样例：用于测试当前子问题", "subproblems":request["subproblems"],
            "citations":[quote(paper["sources"][0])]} for paper in request["papers"]]}
    if operation == "extract":
        source = request["sources"][0]
        fields = []
        for name in request["fields"]:
            found = complete or name in ("research_question", "method")
            fields.append({"field_name":name, "value":source["content"][:40] if found else None,
                "missing_reason":None if found else "not_found", "origin":"author",
                "citations":[quote(source)] if found else []})
        return {"fields":fields, "experiments":[]}
    if operation == "synthesize":
        evidence = request["evidence"][0]
        claim = {"text":"离线人工综合：" + evidence["quote"], "evidence_ids":[evidence["id"]], "origin":"inference"}
        return {"background":[claim], "taxonomy":[claim], "conclusions":[claim]}
    raise AssertionError("unexpected analysis operation")


def planned(value):
    return {**value, "query_targets":{q:value["subproblems"] for q in value["queries"]}}

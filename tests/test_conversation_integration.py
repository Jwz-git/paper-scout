"""真实应用寿命与 HTTP/worker 衔接，模型和文献来源均为离线人工替身。"""
from threading import Semaphore
from urllib.parse import quote

from fastapi.testclient import TestClient

from backend.app.agent.service import AgentService
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.storage.database import Database
from tests.agent_fakes import Model, Pdf, Search, finding, paper, reply, results, search_step


def test_conversation_http_worker_report_and_saved_source_followup(tmp_path):
    first = paper(0)
    evidence = []

    def note(messages):
        source = results(messages, "read")[0]["data"]["abstract"]["source_text_id"]
        return {"actions": [
            {"tool": "note", "paper_id": first.id,
             "findings": [finding("method", "规划器 M0", source, "We propose planner M0 for long-horizon tasks.")]},
            {"tool": "decide", "decisions": [{"paper_id": first.id, "include": True, "reason": "直接相关"}]}]}

    def report(messages):
        evidence.extend(results(messages, "note")[0]["evidence"])
        return {"actions": [{"tool": "report", "title": "离线报告", "question": "长程规划", "sections": [
            {"title": "方法", "claims": [{"text": "M0 是规划器。", "origin": "author", "evidence_ids": evidence}]}]}]}

    model = Model([search_step(1), {"actions": [{"tool": "read", "paper_id": first.id}]}, note, report,
                   reply("报告已保存。"), lambda messages: reply("摘要只说明它提出了规划器 M0。", evidence)])
    search = Search([first])
    db = Database(tmp_path / "isolated.db")
    service = AgentService(db, model, arxiv=search, pdf=Pdf())
    finished, process = Semaphore(0), service.process

    async def observe(turn):
        try:
            await process(turn)
        finally:
            finished.release()
    service.process = observe
    cfg = Settings(_env_file=None, llm_base_url="", llm_model="", llm_api_key="", data_dir=tmp_path)
    try:
        with TestClient(create_app(config=cfg, db=db, agent=service), base_url="http://127.0.0.1") as client:
            opening = {"content": "调研长程规划方法", "request_id": "integration-first"}
            response = client.post("/api/conversations", json=opening)
            assert response.status_code == 202
            task_id = response.json()["task"]["id"]
            assert finished.acquire(timeout=3), "排队的消息没有交给 worker 处理"
            view = client.get(f"/api/conversations/{task_id}").json()
            assert not view["busy"] and len(view["runs"]) == 1
            run_id, answer = view["runs"][0]["id"], view["messages"][-1]
            assert answer["content"] == "报告已保存。" and answer["work"]["report_id"]
            assert view["runs"][0]["total_calls"] == 6 and view["usage"]["model_calls"] == 5
            log = client.get(f"/api/runs/{run_id}/events", params={"turn_id": answer["id"]}).json()
            assert log and {e["turn_id"] for e in log} == {answer["id"]}
            report = client.get(f"/api/runs/{run_id}/report.md")
            assert report.status_code == 200 and first.title in report.text
            retried = client.post("/api/conversations", json=opening).json()
            assert retried["task"]["id"] == task_id and len(retried["messages"]) == len(view["messages"])
            assert len(model.requests) == 5 and len(search.queries) == 1

            question = {"content": "只根据已保存摘要说明资料", "mode": "ask", "request_id": "integration-ask"}
            assert client.post(f"/api/conversations/{task_id}/messages", json=question).status_code == 202
            assert finished.acquire(timeout=3), "追问没有在同一个 worker 中完成"
            followup = client.get(f"/api/conversations/{task_id}").json()
            answer = followup["messages"][-1]
            assert answer["status"] == "completed" and len(answer["citations"]) == 1
            reference = answer["citations"][0]
            detail = client.get(f"/api/runs/{reference['run_id']}/papers/{quote(reference['paper_id'], safe='')}").json()
            source = next(s for s in detail["sources"] if s["id"] == reference["source_text_id"])
            assert source["content"][reference["location_start"]:reference["location_end"]] == reference["quote"]
            assert reference["page_number"] is None and reference["source_type"] == "abstract"
            assert len(followup["runs"]) == 1 and followup["usage"]["model_calls"] == 6 and len(search.queries) == 1
            again = client.post(f"/api/conversations/{task_id}/messages", json=question).json()
            assert len(again["messages"]) == len(followup["messages"]) and not again["busy"]
    finally:
        db.close()

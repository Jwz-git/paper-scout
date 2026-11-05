"""真实应用寿命与 HTTP/worker 衔接，模型和文献来源均为离线人工替身。"""
import json
from threading import Event

from fastapi.testclient import TestClient

from backend.app.adapters.llm import LLMResponse, LLMUsage
from backend.app.config import Settings
from backend.app.domain.models import Paper
from backend.app.main import create_app
from backend.app.storage.database import Database
from tests.analysis_samples import analysis_response, planned
from backend.app.workflow.engine import WorkflowEngine


def test_conversation_http_worker_report_and_saved_source_followup(tmp_path):
    research_done = Event()
    answer_done = Event()

    class OfflineModel:
        def __init__(self):
            self.requests = []

        async def generate(self, messages, **kwargs):
            assert kwargs == {"response_format": "json_object"}
            request = json.loads(messages[-1].content)
            self.requests.append(request)
            if "operation" in request:
                result = analysis_response(request)
            elif "supplements" in request:
                result = planned({"queries": ["all:offline-fixture"], "subproblems": ["communication"]})
            elif request["mode"] == "ask":
                source = next(s for s in request["sources"] if s["source_type"] == "abstract")
                quote = "An artificial abstract for offline integration."
                result = {"action": "answer", "content": "离线示例只说明摘要原文，不作方法优劣判断。", "citations": [{
                    key: source[key] for key in ("run_id", "paper_id", "source_text_id", "source_type", "source_url", "page_number")
                } | {"quote": quote, "location_start": 0, "location_end": len(quote)}]}
            else:
                result = {"action": "research", "content": "开始收集资料。", "task_input": {"topic": "communication", "start_year": 2024}}
            return LLMResponse(content=json.dumps(result), parsed_json=result,
                               usage=LLMUsage(prompt_tokens=5, completion_tokens=7, total_tokens=12))

    class OfflineSearch:
        calls = 0

        async def search(self, query, **kwargs):
            await kwargs["on_request"]()
            self.calls += 1
            assert "submittedDate:[202401010000" in query
            return [Paper(id="offline-paper", source_id="offline-fixture", title="Artificial integration fixture",
                          year=2024, url="https://arxiv.org/abs/0000.00000",
                          abstract="An artificial abstract for offline integration.")]

    class OneRoundEngine(WorkflowEngine):
        async def execute_run(self, run_id):
            run = self.db.get_run(run_id)
            run.max_rounds = 1
            self.db.update_run(run)
            result = await super().execute_run(run_id)
            research_done.set()
            return result

    db = Database(tmp_path / "isolated.db")
    model, search = OfflineModel(), OfflineSearch()
    engine = OneRoundEngine(db, llm_adapter=model, arxiv_adapter=search)
    cfg = Settings(_env_file=None, llm_base_url="", llm_model="", llm_api_key="", data_dir=tmp_path)
    app = create_app(config=cfg, db=db, engine=engine)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            first = {"content": "查找2024年以来的通信文献", "request_id": "integration-first"}
            response = client.post("/api/conversations", json=first)
            assert response.status_code == 202
            task_id = response.json()["task"]["id"]
            assert research_done.wait(3), "queued dialogue did not reach the research worker"
            view = client.get(f"/api/conversations/{task_id}").json()
            assert not view["busy"] and len(view["runs"]) == 1
            run = view["runs"][0]
            assert run["status"] == "partial" and run["total_calls"] == 5
            assert view["usage"]["model_calls"] == 1
            assert search.calls == 1 and len(model.requests) == 5
            assert any("阶段性报告已保存" in m["content"] for m in view["messages"])
            report = client.get(f"/api/runs/{run['id']}/report.md")
            assert report.status_code == 200 and "Artificial integration fixture" in report.text
            retried = client.post("/api/conversations", json=first)
            assert retried.json()["task"]["id"] == task_id
            assert len(model.requests) == 5 and search.calls == 1

            original_process = app.state.dialogue.process

            async def observe_answer(turn):
                await original_process(turn)
                answer_done.set()

            app.state.dialogue.process = observe_answer
            question = {"content": "只根据已保存摘要说明资料", "mode": "ask", "request_id": "integration-ask"}
            assert client.post(f"/api/conversations/{task_id}/messages", json=question).status_code == 202
            assert answer_done.wait(3), "followup did not complete in the shared worker"
            followup = client.get(f"/api/conversations/{task_id}").json()
            answer = next(m for m in reversed(followup["messages"]) if m["action"] == "answer")
            assert answer["status"] == "completed" and len(answer["citations"]) == 1
            reference = answer["citations"][0]
            detail = client.get(f"/api/runs/{reference['run_id']}/papers/{reference['paper_id']}").json()
            source = next(s for s in detail["sources"] if s["id"] == reference["source_text_id"])
            assert source["content"][reference["location_start"]:reference["location_end"]] == reference["quote"]
            assert reference["page_number"] is None and reference["source_type"] == "abstract"
            assert len(followup["runs"]) == 1 and search.calls == 1 and len(model.requests) == 6
            assert followup["usage"]["model_calls"] == 2
            client.post(f"/api/conversations/{task_id}/messages", json=question)
            assert len(model.requests) == 6 and search.calls == 1
    finally:
        db.close()

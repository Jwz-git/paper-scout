import pytest


@pytest.mark.parametrize("payload", [{"topic":" "},{"topic":"a","start_year":2026,"end_year":2020},{"topic":"a","start_year":0},{"topic":"a","start_year":True},{"topic":"a","focus_dimensions":[" "]}])
def test_input_boundary(client,payload):
    assert client.post("/api/tasks",json=payload).status_code == 422


def test_missing_run_and_missing_report_are_distinct(client):
    task = client.post("/api/conversations",json={"content":"Agents","request_id":"report"}).json()["task"]
    run = client.app.state.db.agent_run(task["id"])
    assert client.get("/api/runs/missing/report").status_code == 404
    assert client.get(f"/api/runs/{run.id}/report").status_code == 409
    assert client.get("/api/tasks?limit=-1").status_code == 422
    assert client.get("/api/tasks?limit=10000").status_code == 422


def test_browser_cannot_start_paid_work_from_another_origin(client):
    assert client.post("/api/conversations",json={"content":"evil","request_id":"o"},headers={"Origin":"https://evil.example"}).status_code == 403
    assert client.post("/api/tasks",json={"topic":"evil"},headers={"Origin":"https://evil.example"}).status_code == 403
    assert client.post("/api/tasks",json={"topic":"allowed"},headers={"Origin":"http://127.0.0.1:5173"}).status_code == 201
    assert client.get("/api/health",headers={"Host":"evil.example"}).status_code == 400

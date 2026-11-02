import pytest
from backend.app.domain.models import RunStatus


def start(client):
    task = client.post("/api/tasks",json={"topic":"Agents","start_year":2022,"end_year":2026})
    assert task.status_code == 201
    response = client.post(f"/api/tasks/{task.json()['id']}/runs")
    assert response.status_code == 202
    return task.json(),response.json()


@pytest.mark.parametrize("payload", [{"topic":" "},{"topic":"a","start_year":2026,"end_year":2020},{"topic":"a","start_year":0},{"topic":"a","start_year":True},{"topic":"a","focus_dimensions":[" "]}])
def test_input_boundary(client,payload):
    assert client.post("/api/tasks",json=payload).status_code == 422


def test_control_states_history_and_duplicate_start(client):
    task,run=start(client)
    rid=run["id"]
    assert client.post(f"/api/tasks/{task['id']}/runs").status_code == 409
    assert client.post(f"/api/runs/{rid}/messages",json={"content":"more"}).status_code == 409
    assert client.post(f"/api/runs/{rid}/pause").json()["status"] == "paused"
    assert client.post(f"/api/runs/{rid}/messages",json={"content":" robotics "}).status_code == 201
    assert client.get(f"/api/runs/{rid}/messages").json()[0]["content"] == "robotics"
    assert client.post(f"/api/runs/{rid}/resume").json()["id"] == rid
    assert client.post(f"/api/runs/{rid}/resume").status_code == 409
    assert client.post(f"/api/runs/{rid}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 200
    assert client.post(f"/api/runs/{rid}/pause").status_code == 409
    assert client.post(f"/api/runs/{rid}/resume").status_code == 409
    assert len(client.get(f"/api/tasks/{task['id']}/runs").json()) == 1
    assert client.post(f"/api/tasks/{task['id']}/runs").status_code == 202


@pytest.mark.parametrize("status", [RunStatus.COMPLETED,RunStatus.PARTIAL,RunStatus.FAILED,RunStatus.INTERRUPTED])
def test_all_terminal_states_reject_control(client,status):
    _,run=start(client)
    db=client.app.state.db
    current=db.get_run(run["id"]); current.status=status; db.update_run(current)
    for path in ("pause","resume","cancel","messages"):
        kwargs={"json":{"content":"x"}} if path=="messages" else {}
        assert client.post(f"/api/runs/{run['id']}/{path}",**kwargs).status_code == 409


def test_missing_run_and_pending_report_are_distinct(client):
    _,run=start(client)
    assert client.get("/api/runs/missing/report").status_code == 404
    pending=client.get(f"/api/runs/{run['id']}/report")
    assert pending.status_code == 409 and pending.json()["detail"]["status"] == "queued"
    assert client.get("/api/tasks?limit=-1").status_code == 422
    assert client.get("/api/tasks?limit=10000").status_code == 422


def test_browser_cannot_start_paid_work_from_another_origin(client):
    assert client.post("/api/tasks",json={"topic":"evil"},headers={"Origin":"https://evil.example"}).status_code == 403
    assert client.post("/api/tasks",json={"topic":"allowed"},headers={"Origin":"http://127.0.0.1:5173"}).status_code == 201
    assert client.get("/api/health",headers={"Host":"evil.example"}).status_code == 400

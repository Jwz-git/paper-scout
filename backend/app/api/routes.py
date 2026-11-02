from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from backend.app.domain.models import Task, TaskInput, Run, RunMessage
from backend.app.services import RunService
from backend.app.storage.database import Database, StateConflict

router = APIRouter(prefix="/api", tags=["core"])


def get_db(request: Request) -> Database:
    return request.app.state.db


def require_task(db, task_id):
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


def require_run(db, run_id):
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    return run


def perform(operation):
    try:
        return operation()
    except StateConflict as exc:
        raise HTTPException(409, str(exc)) from exc


def signal(request):
    worker = getattr(request.app.state, "worker", None)
    if worker is not None:
        worker.notify()


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)


@router.post("/tasks", response_model=Task, status_code=201)
async def create_task(req: TaskInput, db=Depends(get_db)):
    task = Task(id="task_"+uuid4().hex, **req.model_dump())
    db.create_task(task)
    return task


@router.get("/tasks")
async def list_tasks(limit: int = Query(50, ge=1, le=100), db=Depends(get_db)):
    return db.list_tasks(limit)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, db=Depends(get_db)):
    return require_task(db, task_id)


@router.get("/tasks/{task_id}/runs")
async def task_runs(task_id: str, db=Depends(get_db)):
    require_task(db, task_id)
    return db.list_runs(task_id=task_id)


@router.post("/tasks/{task_id}/runs", response_model=Run, status_code=202)
async def create_run(task_id: str, request: Request, db=Depends(get_db)):
    task = require_task(db, task_id)
    run = perform(lambda: RunService(db).create(task))
    signal(request)
    return run


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db=Depends(get_db)):
    return require_run(db, run_id)


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, db=Depends(get_db)):
    run = require_run(db, run_id)
    return perform(lambda: RunService(db).pause(run))


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, request: Request, db=Depends(get_db)):
    run = perform(lambda: RunService(db).resume(require_run(db,run_id)))
    signal(request)
    return run


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, db=Depends(get_db)):
    return perform(lambda: RunService(db).cancel(require_run(db,run_id)))


@router.post("/runs/{run_id}/messages", response_model=RunMessage, status_code=201)
async def add_message(run_id: str, req: MessageCreateRequest, db=Depends(get_db)):
    return perform(lambda: RunService(db).add_message(require_run(db,run_id),req.content))


@router.get("/runs/{run_id}/messages")
async def messages(run_id: str, db=Depends(get_db)):
    require_run(db, run_id)
    return db.list_run_messages(run_id)


@router.get("/runs/{run_id}/events")
async def events(run_id: str, db=Depends(get_db)):
    require_run(db, run_id)
    return db.list_events(run_id)


@router.get("/runs/{run_id}/papers")
async def papers(run_id: str, db=Depends(get_db)):
    require_run(db, run_id)
    return db.get_papers_by_run(run_id, selected_only=True)


@router.get("/runs/{run_id}/papers/{paper_id}")
async def paper_detail(run_id: str, paper_id: str, db=Depends(get_db)):
    require_run(db, run_id)
    paper = next((p for p in db.get_papers_by_run(run_id) if p.id==paper_id), None)
    if paper is None:
        raise HTTPException(404, "本次运行中不存在该论文")
    return {"paper":paper,"sources":db.get_source_texts(paper_id,run_id),"evidence":db.get_evidence(paper_id,run_id)}


def require_report(db, run_id):
    run = require_run(db, run_id)
    report = db.get_report(run_id)
    if report is None:
        raise HTTPException(409, {"message":"本次运行尚无可交付报告", "status":run.status.value})
    return report


@router.get("/runs/{run_id}/report")
async def report(run_id: str, db=Depends(get_db)):
    return require_report(db, run_id)


@router.get("/runs/{run_id}/report.md")
async def report_markdown(run_id: str, db=Depends(get_db)):
    report = require_report(db, run_id)
    return Response(report.content_markdown,media_type="text/markdown; charset=utf-8",headers={"Content-Disposition":'attachment; filename="paper-scout-report.md"'})

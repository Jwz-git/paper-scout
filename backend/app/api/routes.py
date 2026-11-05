from uuid import uuid4
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from backend.app.domain.models import Task, TaskInput, Run, RunMessage
from backend.app.domain.conversation import ConversationCreateRequest, ConversationMessageRequest, ConversationView
from backend.app.storage.conversations import ConversationStore
from backend.app.services import RunService
from backend.app.storage.database import Database, StateConflict
from backend.app.model_settings import ModelSettings, ModelSettingsView, ProviderUpdate, ProviderSaveResult, ModelSelection, ModelCatalogRequest
from backend.app.adapters.llm import LLMError
from backend.app.adapters.model_catalog import ModelCatalogPage

router = APIRouter(prefix="/api", tags=["core"])


@router.get("/settings", response_model=ModelSettingsView)
async def get_settings(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    state = request.app.state
    return state.model_settings.view(state.db, state.worker)


@router.post("/settings", response_model=ModelSettingsView)
async def save_settings(req: ModelSettings, request: Request, response: Response):
    return settings_operation(request, response, lambda service, args: service.save(req, *args))


def settings_operation(request, response, operation):
    response.headers["Cache-Control"] = "no-store"
    state = request.app.state
    try:
        return operation(state.model_settings, (state.db, state.worker, state.engine, state.dialogue))
    except StateConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError:
        raise HTTPException(500, "无法保存本地设置，原有配置未更改") from None
    except KeyError:
        raise HTTPException(404, "供应商不存在") from None


@router.post("/settings/models", response_model=ModelCatalogPage)
async def available_models(req: ModelCatalogRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await request.app.state.model_settings.list_models(req)
    except KeyError:
        raise HTTPException(404, "供应商不存在") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except LLMError as exc:
        status = {"authentication_failed": 400, "rate_limited": 429, "timeout": 504}.get(exc.code, 502)
        raise HTTPException(status, str(exc)) from None


@router.post("/settings/providers", response_model=ProviderSaveResult)
async def create_provider(req: ProviderUpdate, request: Request, response: Response):
    return settings_operation(request, response, lambda service, args: service.save_provider(req, None, *args))


@router.post("/settings/providers/{provider_id}", response_model=ProviderSaveResult)
async def update_provider(provider_id: str, req: ProviderUpdate, request: Request, response: Response):
    return settings_operation(request, response, lambda service, args: service.save_provider(req, provider_id, *args))


@router.post("/settings/selection", response_model=ModelSettingsView)
async def select_model(req: ModelSelection, request: Request, response: Response):
    return settings_operation(request, response, lambda service, args: service.select_model(req, *args))


@router.post("/settings/providers/{provider_id}/delete", response_model=ModelSettingsView)
async def delete_provider(provider_id: str, request: Request, response: Response):
    return settings_operation(request, response, lambda service, args: service.delete_provider(provider_id, *args))


def get_db(request: Request) -> Database:
    return request.app.state.db


def require_task(db, task_id):
    task = db.get_task(task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(404, "任务不存在")
    return task


def require_run(db, run_id):
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    require_task(db, run.task_id)
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


@router.get("/runs/{run_id}/papers/{paper_id:path}")
async def paper_detail(run_id: str, paper_id: str, db=Depends(get_db)):
    run = require_run(db, run_id)
    paper = next((p for p in db.get_papers_by_run(run_id) if p.id==paper_id), None)
    if paper is None:
        raise HTTPException(404, "本次运行中不存在该论文")
    analysis = next((a for a in db.list_analyses(run_id, run.analysis_revision) if a.paper_id == paper_id), None)
    selection = next((s for s in db.list_selections(run_id, run.analysis_revision) if s.paper_id == paper_id), None)
    return {"paper":paper,"sources":db.get_source_texts(paper_id,run_id),"evidence":db.get_evidence(paper_id,run_id),
        "analysis":analysis,"selection":selection,"analysis_revision":run.analysis_revision,
        "selected":paper_id in {p.id for p in db.get_papers_by_run(run_id, selected_only=True)}}


@router.get("/runs/{run_id}/analysis")
async def run_analysis(run_id: str, revision: Optional[int] = Query(None, ge=1), db=Depends(get_db)):
    run = require_run(db, run_id)
    revision = revision or run.analysis_revision
    if revision != run.analysis_revision and revision not in run.scope_history:
        raise HTTPException(404, "分析修订不存在")
    assessments = db.list_assessments(run_id, revision)
    return {"analysis_revision":revision, "scope":run.scope_history.get(revision, run.current_input),
        "papers":db.get_papers_by_run(run_id), "selections":db.list_selections(run_id, revision),
        "analyses":db.list_analyses(run_id, revision), "assessment":assessments[-1] if assessments else None}


def require_report(db, run_id, report_id=None):
    run = require_run(db, run_id)
    report = db.get_report(run_id, report_id)
    if report is None:
        if report_id is not None:
            raise HTTPException(404, "本次运行中不存在该报告版本")
        raise HTTPException(409, {"message":"本次运行尚无可交付报告", "status":run.status.value})
    return report


@router.get("/runs/{run_id}/report")
async def report(run_id: str, report_id: Optional[str] = None, db=Depends(get_db)):
    return require_report(db, run_id, report_id)


@router.get("/runs/{run_id}/report.md")
async def report_markdown(run_id: str, report_id: Optional[str] = None, db=Depends(get_db)):
    report = require_report(db, run_id, report_id)
    return Response(report.content_markdown,media_type="text/markdown; charset=utf-8",headers={"Content-Disposition":'attachment; filename="paper-scout-report.md"'})


def rendered_report(db, run_id, report_id, format):
    from backend.app import reports
    report = require_report(db, run_id, report_id)
    if report.document is None:
        raise HTTPException(409, "历史报告只有Markdown；没有可供多格式导出的结构化快照")
    content = reports.word(report) if format == "docx" else reports.pdf(report)
    media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if format == "docx" else "application/pdf"
    return Response(content, media_type=media, headers={"Content-Disposition":f'attachment; filename="paper-scout-report.{format}"', "Cache-Control":"no-store"})


@router.get("/runs/{run_id}/report.docx")
def report_word(run_id: str, report_id: Optional[str] = None, db=Depends(get_db)):
    return rendered_report(db, run_id, report_id, "docx")


@router.get("/runs/{run_id}/report.pdf")
def report_pdf(run_id: str, report_id: Optional[str] = None, db=Depends(get_db)):
    return rendered_report(db, run_id, report_id, "pdf")


@router.get("/conversations", response_model=List[Task])
async def conversations(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                        query: str = Query("", max_length=2000), deleted: bool = False, db=Depends(get_db)):
    return db.list_tasks(limit, deleted=deleted, offset=offset, query=query.strip())


class ConversationRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)


class TrashSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # null 明确表示整个回收站；界面的全量操作不受列表分页限制。
    ids: Optional[List[str]] = Field(..., min_length=1, max_length=100)


@router.get("/conversations/trash")
async def trash_list(query: str = Query("", max_length=2000), sort: Literal["newest", "oldest", "title"] = "newest",
                     offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db=Depends(get_db)):
    return db.list_trash(query.strip(), sort, offset, limit)


@router.post("/conversations/trash/restore")
async def restore_trash(req: TrashSelection, db=Depends(get_db)):
    return {"tasks": perform(lambda: db.restore_trash(req.ids))}


@router.post("/conversations/trash/delete")
async def delete_trash(req: TrashSelection, request: Request, db=Depends(get_db)):
    worker = request.app.state.worker
    return {"ids": perform(lambda: db.delete_trash(req.ids, worker.active_task_id if worker else None))}


@router.post("/conversations/{task_id}/rename", response_model=Task)
async def rename_conversation(task_id: str, req: ConversationRenameRequest, db=Depends(get_db)):
    require_task(db, task_id)
    return db.rename_task(task_id, req.title)


@router.post("/conversations/{task_id}/trash", response_model=Task)
async def trash_conversation(task_id: str, request: Request, db=Depends(get_db)):
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(404, "对话不存在")
    if task.deleted_at is None:
        with db._get_connection():
            ConversationStore(db).stop(task_id)
            task = db.trash_task(task_id, True)
    signal(request)
    return task


@router.post("/conversations/{task_id}/restore", response_model=Task)
async def restore_conversation(task_id: str, db=Depends(get_db)):
    if db.get_task(task_id) is None:
        raise HTTPException(404, "对话不存在")
    return db.trash_task(task_id, False)


@router.post("/conversations", response_model=ConversationView, status_code=202)
async def create_conversation(req: ConversationCreateRequest, request: Request, db=Depends(get_db)):
    store = ConversationStore(db)
    task_id = perform(lambda: store.enqueue(req))
    signal(request)
    return store.view(task_id, request.app.state.dialogue.llm is not None)


@router.get("/conversations/{task_id}", response_model=ConversationView)
async def conversation(task_id: str, request: Request, db=Depends(get_db)):
    require_task(db, task_id)
    return ConversationStore(db).view(task_id, request.app.state.dialogue.llm is not None)


@router.post("/conversations/{task_id}/messages", response_model=ConversationView, status_code=202)
async def conversation_message(task_id: str, req: ConversationMessageRequest, request: Request, db=Depends(get_db)):
    require_task(db, task_id)
    store = ConversationStore(db)
    perform(lambda: store.enqueue(req, task_id))
    signal(request)
    return store.view(task_id, request.app.state.dialogue.llm is not None)


@router.post("/conversations/{task_id}/stop", response_model=ConversationView)
async def stop_conversation(task_id: str, request: Request, db=Depends(get_db)):
    require_task(db, task_id)
    store = ConversationStore(db)
    store.stop(task_id)
    signal(request)
    return store.view(task_id, request.app.state.dialogue.llm is not None)

import asyncio
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.routes import router
from backend.app.config import Settings
from backend.app.storage.database import Database
from backend.app.workflow.engine import WorkflowEngine
from backend.app.workflow.worker import SerialWorker

LOCAL_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000", "http://localhost:8000"}


def create_app(config=None, db=None, engine=None, run_worker=True):
    @asynccontextmanager
    async def lifespan(app):
        cfg = config if config is not None else Settings()
        store = db if db is not None else Database(cfg.data_dir / "paperscout.db")
        own_store = db is None
        app.state.db = store
        if engine is None:
            from backend.app.adapters.arxiv import ArXivAdapter
            from backend.app.adapters.llm import create_llm_adapter
            llm = None
            if cfg.llm_base_url or cfg.llm_model or cfg.llm_api_key.get_secret_value():
                if not cfg.llm_base_url or not cfg.llm_model:
                    raise ValueError("配置缺少 LLM_BASE_URL 或 LLM_MODEL")
                llm = create_llm_adapter(cfg.llm_protocol,cfg.llm_base_url,cfg.llm_model,cfg.llm_api_key.get_secret_value())
            runner = WorkflowEngine(store, arxiv_adapter=ArXivAdapter(user_agent=cfg.arxiv_user_agent,rate_limit_seconds=cfg.arxiv_rate_limit_seconds),llm_adapter=llm)
        else:
            runner = engine
        from backend.app.dialogue import DialogueService
        app.state.engine = runner
        app.state.dialogue = DialogueService(store, getattr(runner, "llm", None))
        app.state.worker = SerialWorker(store, runner, app.state.dialogue) if run_worker else None
        job = asyncio.create_task(app.state.worker.serve()) if run_worker else None
        try:
            yield
        finally:
            if job is not None:
                job.cancel()
                with suppress(asyncio.CancelledError):
                    await job
            if own_store:
                store.close()

    app = FastAPI(title="Paper Scout", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost","testserver"])
    app.add_middleware(CORSMiddleware,allow_origins=sorted(LOCAL_ORIGINS),allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["Content-Type"])

    @app.middleware("http")
    async def restrict_browser_mutations(request: Request, call_next):
        # CORS并不阻止恶意页面发出简单POST；本地付费任务也不能由其他站点启动。
        origin = request.headers.get("origin")
        if request.method not in ("GET","HEAD","OPTIONS") and origin is not None and origin not in LOCAL_ORIGINS:
            return JSONResponse({"detail":"不允许其他网站控制本地任务"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health",tags=["system"])
    async def health():
        return {"status":"ok","app":"Paper Scout","version":"0.1.0"}

    app.include_router(router)
    return app


app = create_app()

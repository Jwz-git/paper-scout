import asyncio
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from backend.app.agent.service import AgentService
from backend.app.agent.worker import SerialWorker
from backend.app.api.routes import router
from backend.app.config import Settings
from backend.app.model_settings import ModelSettingsService
from backend.app.storage.database import Database

LOCAL_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000", "http://localhost:8000"}


def create_app(config=None, db=None, agent=None, run_worker=True):
    @asynccontextmanager
    async def lifespan(app):
        cfg = config if config is not None else Settings()
        store = db if db is not None else Database(cfg.data_dir / "paperscout.db")
        own_store = db is None
        app.state.db = store
        app.state.model_settings = ModelSettingsService(cfg)
        if agent is None:
            from backend.app.adapters.arxiv import ArXivAdapter
            app.state.agent = AgentService(store, app.state.model_settings.adapter(),
                arxiv=ArXivAdapter(user_agent=cfg.arxiv_user_agent, rate_limit_seconds=cfg.arxiv_rate_limit_seconds))
        else:
            app.state.agent = agent
        app.state.worker = SerialWorker(store, app.state.agent) if run_worker else None
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

    @app.exception_handler(RequestValidationError)
    async def redact_settings_validation(request, exc):
        if request.url.path == "/api/settings" or request.url.path.startswith("/api/settings/"):
            # 默认 422 会包含 input；设置请求里的密钥不能随错误响应回显。
            errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
            return JSONResponse({"detail": errors}, status_code=422, headers={"Cache-Control": "no-store"})
        return await request_validation_exception_handler(request, exc)
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
    async def health(request: Request):
        return {"status":"ok","app":"Paper Scout","version":"0.1.0",
                "model_configured": request.app.state.agent.llm is not None}

    app.include_router(router)
    return app


app = create_app()

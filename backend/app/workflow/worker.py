"""本地单进程串行执行器：数据库保存队列，不用每请求 BackgroundTasks。"""
import asyncio
import logging
from backend.app.domain.models import RunStatus

logger = logging.getLogger(__name__)


class SerialWorker:
    def __init__(self, db, engine):
        self.db, self.engine = db, engine
        self.wake = asyncio.Event()

    def notify(self):
        self.wake.set()

    async def serve(self):
        self.db.interrupt_running()
        while True:
            self.wake.clear()
            queued = self.db.list_runs(status=RunStatus.QUEUED)
            if not queued:
                await self.wake.wait()
                continue
            for run in queued:
                try:
                    await self.engine.execute_run(run.id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # engine 已持久化程序错误；日志仅记类别，避免原文／凭据泄漏。
                    logger.error("运行 %s 程序错误：%s", run.id, type(exc).__name__)

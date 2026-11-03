"""本地单进程串行执行器：持久队列，不用每请求 BackgroundTasks。"""
import asyncio
import logging
from backend.app.domain.models import RunStatus
from backend.app.dialogue import DialogueService

logger = logging.getLogger(__name__)


class SerialWorker:
    def __init__(self, db, engine, dialogue=None):
        self.db, self.engine = db, engine
        self.dialogue = dialogue if dialogue is not None else DialogueService(db,getattr(engine,"llm",None))
        self.wake = asyncio.Event()

    def notify(self):
        self.wake.set()

    async def serve(self):
        self.db.interrupt_running()
        self.dialogue.store.interrupt_processing()
        while True:
            self.wake.clear()
            # 每轮重新读，不能让旧的待运行列表饿死刚收到的对话。
            turn = self.dialogue.store.next_turn()
            queued = self.db.list_runs(status=RunStatus.QUEUED) if turn is None else []
            if turn is None and not queued:
                await self.wake.wait()
                continue
            try:
                if turn is not None:
                    await self.dialogue.process(turn)
                else:
                    await self.engine.execute_run(queued[0].id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 服务已持久化程序错误；只记类别，不泄漏原文或凭据。
                logger.error("串行执行程序错误：%s", type(exc).__name__)

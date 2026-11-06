"""本地单进程串行执行器：持久队列，一次处理一轮对话；停止时取消正在执行的那一轮。"""
import asyncio
import logging

from backend.app.storage.conversations import ConversationStore

logger = logging.getLogger(__name__)


class SerialWorker:
    def __init__(self, db, agent):
        self.db, self.agent = db, agent
        self.store = ConversationStore(db)
        self.wake = asyncio.Event()
        self.busy = False
        self.active_task_id = None
        self.job = None

    def notify(self):
        self.wake.set()

    def cancel(self, task_id):
        if self.job is not None and self.active_task_id == task_id:
            self.job.cancel()

    async def serve(self):
        self.db.interrupt_running()
        self.store.interrupt_processing()
        while True:
            self.wake.clear()
            turn = self.store.next_turn()
            if turn is None:
                await self.wake.wait()
                continue
            self.busy, self.active_task_id = True, turn["task_id"]
            self.job = asyncio.ensure_future(self.agent.process(turn))
            try:
                # 用 wait 而不是直接 await：停止某一轮只取消该任务，不取消 worker 自己。
                await asyncio.wait({self.job})
            except asyncio.CancelledError:
                self.job.cancel()
                await asyncio.wait({self.job})
                raise
            finally:
                job, self.job = self.job, None
                self.busy, self.active_task_id = False, None
            if not job.cancelled() and job.exception() is not None:
                # 本轮已保存失败状态；日志只记类别，不记录原文或凭据。
                logger.error("对话处理程序错误：%s", type(job.exception()).__name__)

"""运行的业务状态规则。HTTP 层仅校验输入、调用服务、返回结果。"""
from uuid import uuid4
from backend.app.domain.models import Run, RunStatus, RunMessage, TaskInput
from backend.app.storage.database import StateConflict


class RunService:
    def __init__(self, db):
        self.db = db

    def create(self, task, dialogue=False):
        with self.db._get_connection():
            if not dialogue:
                self._require_no_dialogue(task.id)
            run = Run(id="run_"+uuid4().hex, task_id=task.id, initial_topic=task.topic,
                      initial_input=TaskInput.model_validate({k:getattr(task,k) for k in TaskInput.model_fields}))
            self.db.create_run(run)
            return run

    def pause(self, run):
        return self.db.pause_run(run.id)

    def _require_no_dialogue(self, task_id):
        from backend.app.storage.conversations import ConversationStore
        if ConversationStore(self.db).pending(task_id):
            raise StateConflict("对话正在处理，不能同时启动或继续研究")

    def resume(self, run, dialogue=False):
        with self.db._get_connection():
            if not dialogue:
                self._require_no_dialogue(run.task_id)
            return self.db.transition(run.id,[RunStatus.PAUSED,RunStatus.NEEDS_INPUT],RunStatus.QUEUED)

    def cancel(self, run):
        return self.db.cancel_run(run.id)

    def add_message(self, run, content):
        with self.db._get_connection():
            self._require_no_dialogue(run.task_id)
            msg = RunMessage(id="msg_"+uuid4().hex,run_id=run.id,content=content)
            self.db.add_message_if_paused(msg)
            return msg

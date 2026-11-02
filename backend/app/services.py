"""运行的业务状态规则。HTTP 层仅校验输入、调用服务、返回结果。"""
from uuid import uuid4
from backend.app.domain.models import Run, RunStatus, RunMessage, TaskInput
from backend.app.storage.database import StateConflict


class RunService:
    def __init__(self, db):
        self.db = db

    def create(self, task):
        run = Run(id="run_"+uuid4().hex, task_id=task.id, initial_topic=task.topic,
                  initial_input=TaskInput.model_validate({k:getattr(task,k) for k in TaskInput.model_fields}))
        self.db.create_run(run)
        return run

    def pause(self, run):
        return self.db.pause_run(run.id)

    def resume(self, run):
        return self.db.transition(run.id,[RunStatus.PAUSED,RunStatus.NEEDS_INPUT],RunStatus.QUEUED)

    def cancel(self, run):
        return self.db.cancel_run(run.id)

    def add_message(self, run, content):
        msg = RunMessage(id="msg_"+uuid4().hex,run_id=run.id,content=content)
        self.db.add_message_if_paused(msg)
        return msg

"""附加式对话持久化。所有状态改变使用现有数据库的同一短事务。"""
import json
from uuid import uuid4
from backend.app.domain.conversation import ChatMessage, ConversationUsage, ConversationView
from backend.app.domain.models import Task, TaskInput, RunStatus, utc_now
from backend.app.storage.database import StateConflict

ACTIVE = {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSE_REQUESTED,
          RunStatus.PAUSED, RunStatus.NEEDS_INPUT}
SUMMARY = {RunStatus.PAUSED, RunStatus.NEEDS_INPUT, RunStatus.COMPLETED,
           RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}


class ConversationStore:
    def __init__(self, db):
        self.db = db

    def ensure(self, task_id, legacy=True):
        with self.db._get_connection() as conn:
            if conn.execute("SELECT task_id FROM conversation_usage WHERE task_id=?", (task_id,)).fetchone():
                return
            task = self.db.get_task(task_id)
            if task is None:
                raise ValueError("任务不存在")
            self.save_usage(task_id, ConversationUsage())
            if legacy:
                runs = self.db.list_runs(task_id=task_id)
                first = runs[0] if runs else None
                if first:
                    scope = first.initial_input
                    content = scope.topic if scope else first.initial_topic
                    if scope and any((scope.start_year, scope.end_year, scope.focus_dimensions, scope.output_requirements)):
                        content += "\n原始范围：" + scope.model_dump_json(exclude={"topic"})
                    if scope is None:
                        content += "\n（历史运行缺少完整初始范围快照。）"
                else:
                    # 旧骨架允许空问题／非法年份。显示历史不能破坏保存的数据；
                    # 严格 TaskInput 校验只在发起新研究的边界执行。
                    content = "原始问题：" + json.dumps(task.topic,ensure_ascii=False)
                    raw_scope = {k:getattr(task,k) for k in TaskInput.model_fields if k != "topic"}
                    content += "\n原始范围：" + json.dumps(raw_scope,ensure_ascii=False)
                    content += "\n（历史任务输入原样展示，未按当前规则校验；启动研究时才校验范围。）"
                self.save_message(ChatMessage(id="chat_"+uuid4().hex, task_id=task_id,
                    role="user", content=content, status="completed", created_at=task.created_at))
                for run in runs:
                    self.record_run(run)

    def save_message(self, message):
        with self.db._get_connection() as conn:
            conn.execute("INSERT INTO chat_messages(id,task_id,role,status,data) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data",
                         (message.id,message.task_id,message.role,message.status,message.model_dump_json()))

    def messages(self, task_id):
        with self.db._get_connection() as conn:
            return [ChatMessage.model_validate_json(r[0]) for r in conn.execute(
                "SELECT data FROM chat_messages WHERE task_id=? ORDER BY rowid", (task_id,))]

    def message(self, message_id):
        with self.db._get_connection() as conn:
            row = conn.execute("SELECT data FROM chat_messages WHERE id=?", (message_id,)).fetchone()
            return ChatMessage.model_validate_json(row[0])

    def usage(self, task_id):
        with self.db._get_connection() as conn:
            return ConversationUsage.model_validate_json(conn.execute(
                "SELECT data FROM conversation_usage WHERE task_id=?", (task_id,)).fetchone()[0])

    def save_usage(self, task_id, usage):
        with self.db._get_connection() as conn:
            conn.execute("INSERT INTO conversation_usage VALUES(?,?) ON CONFLICT(task_id) DO UPDATE SET data=excluded.data", (task_id,usage.model_dump_json()))

    def pending(self, task_id):
        with self.db._get_connection() as conn:
            return conn.execute("SELECT 1 FROM conversation_turns WHERE task_id=? AND status IN ('queued','processing')", (task_id,)).fetchone() is not None

    def enqueue(self, req, task_id=None):
        scope = task_id or "create"
        payload = req.model_dump_json(exclude={"request_id"})
        with self.db._get_connection() as conn:
            prior = conn.execute("SELECT task_id,payload FROM conversation_turns WHERE request_scope=? AND request_id=?", (scope,req.request_id)).fetchone()
            if prior:
                if prior["payload"] != payload:
                    raise StateConflict("request_id 已被不同内容或模式使用")
                if self.db.get_task(prior["task_id"]).deleted_at is not None:
                    raise StateConflict("对话已移到回收站，请先恢复后再操作")
                return prior["task_id"]
            if task_id is None:
                task = Task(id="task_"+uuid4().hex,topic=req.content)
                task_id = task.id
                self.db.create_task(task)
                self.ensure(task_id, legacy=False)
            else:
                self.ensure(task_id)
            if self.pending(task_id):
                raise StateConflict("上一条对话仍在处理中，请等待后再发送")
            user = ChatMessage(id="chat_"+uuid4().hex,task_id=task_id,role="user",content=req.content,status="queued")
            assistant = ChatMessage(id="chat_"+uuid4().hex,task_id=task_id,role="assistant",content="",status="queued")
            self.save_message(user)
            self.save_message(assistant)
            runs = self.db.list_runs(task_id=task_id)
            active = next((r for r in reversed(runs) if r.status in ACTIVE),None)
            owned = bool(active and active.status in (RunStatus.QUEUED,RunStatus.RUNNING) and req.mode != "pause")
            conn.execute("INSERT INTO conversation_turns(request_scope,request_id,payload,task_id,user_id,assistant_id,status,mode,run_id,paused_by_dialogue) VALUES(?,?,?,?,?,?,'queued',?,?,?)",
                (scope,req.request_id,payload,task_id,user.id,assistant.id,req.mode,active.id if active else None,int(owned)))
            if active and active.status in (RunStatus.QUEUED,RunStatus.RUNNING):
                self.db.pause_run(active.id, dialogue=True)
            conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (utc_now().isoformat(),task_id))
            return task_id

    def next_turn(self):
        with self.db._get_connection() as conn:
            row = conn.execute("SELECT rowid,* FROM conversation_turns WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            return dict(row) if row else None

    def claim(self, turn):
        with self.db._get_connection() as conn:
            current = conn.execute("SELECT status FROM conversation_turns WHERE rowid=?", (turn["rowid"],)).fetchone()
            if current["status"] == "interrupted":
                return False
            if conn.execute("UPDATE conversation_turns SET status='processing' WHERE rowid=? AND status='queued'", (turn["rowid"],)).rowcount != 1:
                raise StateConflict("对话已被处理")
            for mid in (turn["user_id"],turn["assistant_id"]):
                message = self.message(mid)
                message.status = "processing"
                self.save_message(message)
            return True

    def processing(self, turn):
        with self.db._get_connection() as conn:
            return conn.execute("SELECT status FROM conversation_turns WHERE rowid=?", (turn["rowid"],)).fetchone()[0] == "processing"

    def finish(self, turn, decision=None, error=None, interrupted=False, diagnostic=None):
        with self.db._get_connection() as conn:
            current = conn.execute("SELECT status FROM conversation_turns WHERE rowid=?", (turn["rowid"],)).fetchone()
            if current["status"] == "interrupted":
                return
            status = "interrupted" if interrupted else ("failed" if error else "completed")
            conn.execute("UPDATE conversation_turns SET status=?,decision=? WHERE rowid=?", (status,decision.model_dump_json() if decision else None,turn["rowid"]))
            user = self.message(turn["user_id"])
            user.status = "completed"
            self.save_message(user)
            answer = self.message(turn["assistant_id"])
            answer.status = status
            answer.error_category = error
            if decision:
                answer.content, answer.action, answer.run_id = decision.content,decision.action,decision.run_id
                answer.citations = decision.citations
            elif error == "user_cancelled":
                answer.content = "用户已停止本轮对话。原始消息已保存，迟到的模型结果不会应用；已发出的调用仍可能完成并计入用量。"
            else:
                answer.content = ("对话处理已中断，不会自动重放可能付费的调用。" if interrupted else "对话处理失败："+error+"。原始消息已保存；暂停的研究不会自动继续。")
                if diagnostic and not interrupted:
                    answer.content += "\n" + diagnostic
            self.save_message(answer)

    def stop(self, task_id):
        with self.db._get_connection() as conn:
            self.ensure(task_id)
            turns = [dict(r) for r in conn.execute("SELECT rowid,* FROM conversation_turns WHERE task_id=? AND status IN ('queued','processing')", (task_id,))]
            for turn in turns:
                conn.execute("UPDATE conversation_turns SET paused_by_dialogue=0 WHERE rowid=?", (turn["rowid"],))
                self.finish(turn,error="user_cancelled",interrupted=True)
            active = [r for r in self.db.list_runs(task_id=task_id) if r.status in ACTIVE]
            for run in active:
                self.db.cancel_run(run.id)
            if turns or active:
                conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (utc_now().isoformat(),task_id))

    def interrupt_processing(self):
        with self.db._get_connection() as conn:
            turns = [dict(r) for r in conn.execute("SELECT rowid,* FROM conversation_turns WHERE status='processing'")]
            for turn in turns:
                self.finish(turn,error="process_interrupted",interrupted=True)

    def record_run(self, run):
        with self.db._get_connection() as conn:
            if not conn.execute("SELECT 1 FROM conversation_usage WHERE task_id=?", (run.task_id,)).fetchone():
                return
            report = self.db.get_report(run.id)
            signature = run.status.value + ":" + (report.id if report else "") + ":" + (run.stop_reason or "")
            prior = conn.execute("SELECT signature FROM conversation_run_states WHERE run_id=?", (run.id,)).fetchone()
            if prior and prior[0] == signature:
                return
            conn.execute("INSERT INTO conversation_run_states VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET signature=excluded.signature", (run.id,signature))
            if run.status not in SUMMARY:
                return
            content = f"系统运行摘要（非模型回答）：研究 {run.id} 状态为 {run.status.value}。"
            if run.stop_reason:
                content += "\n"+run.stop_reason
            if report:
                label = "研究报告" if run.status == RunStatus.COMPLETED else "阶段性来源报告"
                content += f"\n{label}已保存，可在研究资料中查看；原文定位可核验，语义支持仍未核验。"
            if run.status == RunStatus.PAUSED:
                content += "\n已保存检查点，可以在对话中继续补充或明确继续。"
            if run.gaps:
                content += "\n缺口：" + "；".join(run.gaps[:5])
            self.save_message(ChatMessage(id="chat_"+uuid4().hex,task_id=run.task_id,role="assistant",content=content,status="completed",run_id=run.id))

    def view(self, task_id, model_configured):
        with self.db._get_connection():
            self.ensure(task_id)
            runs = self.db.list_runs(task_id=task_id)
            for run in runs:
                self.record_run(run)
            return ConversationView(task=self.db.get_task(task_id),messages=self.messages(task_id),runs=runs,
                usage=self.usage(task_id),busy=self.pending(task_id),model_configured=model_configured)

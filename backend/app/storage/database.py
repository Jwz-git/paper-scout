import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from backend.app.config import settings
from backend.app.domain.models import (
    Evidence,
    Assessment,
    PaperAnalysis,
    PaperSelection,
    Paper,
    Report,
    Run,
    RunMessage,
    RunStage,
    RunStatus,
    SourceText,
    SourceType,
    Task,
    TaskInput,
    Event,
    SearchQuery,
    utc_now,
)


from contextlib import contextmanager
from threading import RLock


class StateConflict(ValueError):
    pass


class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(settings.data_dir / "paperscout.db")
        else:
            self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._depth = 0
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_tables()

    @contextmanager
    def _get_connection(self):
        # 互斥涵盖整笔事务；嵌套保存检查点和消息时不能提前提交。
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                if outer:
                    self._conn.rollback()
                raise
            else:
                if outer:
                    self._conn.commit()
            finally:
                self._depth -= 1

    def close(self):
        with self._lock:
            self._conn.close()

    def _init_tables(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    start_year INTEGER,
                    end_year INTEGER,
                    focus_dimensions TEXT,
                    output_requirements TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    initial_topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    current_round INTEGER NOT NULL DEFAULT 1,
                    max_rounds INTEGER NOT NULL DEFAULT 3,
                    max_calls INTEGER NOT NULL DEFAULT 20,
                    total_calls INTEGER NOT NULL DEFAULT 0,
                    total_execution_seconds REAL NOT NULL DEFAULT 0.0,
                    stop_reason TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS run_messages (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    impact_summary TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    authors TEXT,
                    year INTEGER,
                    doi TEXT,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    pdf_url TEXT,
                    abstract TEXT,
                    primary_category TEXT,
                    categories TEXT,
                    fetched_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS run_papers (
                    run_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    relevance_note TEXT,
                    is_selected INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (run_id, paper_id),
                    FOREIGN KEY (run_id) REFERENCES runs (id),
                    FOREIGN KEY (paper_id) REFERENCES papers (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS source_texts (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    page_number INTEGER,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    FOREIGN KEY (paper_id) REFERENCES papers (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    source_text_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    page_number INTEGER,
                    quote TEXT NOT NULL,
                    location_start INTEGER,
                    location_end INTEGER,
                    FOREIGN KEY (source_text_id) REFERENCES source_texts (id),
                    FOREIGN KEY (paper_id) REFERENCES papers (id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_markdown TEXT NOT NULL,
                    gaps TEXT,
                    stop_reason TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs (id)
                )
                """
            )
            # 已发布的初始骨架缺少运行快照。只对该已知 schema 做一次增量迁移。
            if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                conn.execute("ALTER TABLE runs ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")
                conn.execute("ALTER TABLE run_papers ADD COLUMN snapshot TEXT")
                conn.execute("PRAGMA user_version = 1")
            conn.execute("CREATE TABLE IF NOT EXISTS run_sources (run_id TEXT REFERENCES runs(id), source_text_id TEXT REFERENCES source_texts(id), PRIMARY KEY(run_id,source_text_id))")
            conn.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), data TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS search_queries (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), data TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS assessments (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), data TEXT NOT NULL)")
            if conn.execute("PRAGMA user_version").fetchone()[0] == 1:
                conn.execute("ALTER TABLE run_messages ADD COLUMN proposed_scope TEXT")
                conn.execute("PRAGMA user_version = 2")
            if conn.execute("PRAGMA user_version").fetchone()[0] == 2:
                conn.execute("ALTER TABLE tasks ADD COLUMN title TEXT")
                conn.execute("ALTER TABLE tasks ADD COLUMN deleted_at TEXT")
                conn.execute("PRAGMA user_version = 3")
            if conn.execute("PRAGMA user_version").fetchone()[0] == 3:
                conn.execute("ALTER TABLE reports ADD COLUMN document TEXT")
                conn.execute("CREATE TABLE paper_analyses (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), paper_id TEXT NOT NULL REFERENCES papers(id), revision INTEGER NOT NULL, data TEXT NOT NULL)")
                conn.execute("CREATE TABLE paper_selections (run_id TEXT NOT NULL REFERENCES runs(id), paper_id TEXT NOT NULL REFERENCES papers(id), revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,paper_id,revision))")
                conn.execute("PRAGMA user_version = 4")
            conn.execute("CREATE TABLE IF NOT EXISTS conversation_usage (task_id TEXT PRIMARY KEY REFERENCES tasks(id), data TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS chat_messages (id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),role TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS conversation_turns (request_scope TEXT NOT NULL,request_id TEXT NOT NULL,payload TEXT NOT NULL,task_id TEXT NOT NULL REFERENCES tasks(id),user_id TEXT NOT NULL REFERENCES chat_messages(id),assistant_id TEXT NOT NULL REFERENCES chat_messages(id),status TEXT NOT NULL,mode TEXT NOT NULL,run_id TEXT REFERENCES runs(id),paused_by_dialogue INTEGER NOT NULL DEFAULT 0,decision TEXT,PRIMARY KEY(request_scope,request_id))")
            conn.execute("CREATE TABLE IF NOT EXISTS conversation_run_states (run_id TEXT PRIMARY KEY REFERENCES runs(id),signature TEXT NOT NULL)")

    # --- Task 操作 ---
    def create_task(self, task: Task) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, topic, start_year, end_year, focus_dimensions, output_requirements, created_at, updated_at, title, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.topic,
                    task.start_year,
                    task.end_year,
                    json.dumps(task.focus_dimensions, ensure_ascii=False),
                    task.output_requirements,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.title,
                    task.deleted_at.isoformat() if task.deleted_at else None,
                ),
            )

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return Task(
                id=row["id"],
                topic=row["topic"],
                title=row["title"],
                deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
                start_year=row["start_year"],
                end_year=row["end_year"],
                focus_dimensions=json.loads(row["focus_dimensions"] or "[]"),
                output_requirements=row["output_requirements"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def list_tasks(self, limit: int = 50, deleted: bool = False, offset: int = 0, query: str = "") -> List[Task]:
        with self._get_connection() as conn:
            condition = "IS NOT NULL" if deleted else "IS NULL"
            rows = conn.execute(f"SELECT * FROM tasks WHERE deleted_at {condition} AND instr(lower(COALESCE(title, '') || ' ' || topic), lower(?)) > 0 "
                                "ORDER BY updated_at DESC, id LIMIT ? OFFSET ?", (query, limit, offset)).fetchall()
            return [
                Task(
                    id=row["id"],
                    topic=row["topic"],
                    title=row["title"],
                    deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
                    start_year=row["start_year"],
                    end_year=row["end_year"],
                    focus_dimensions=json.loads(row["focus_dimensions"] or "[]"),
                    output_requirements=row["output_requirements"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def rename_task(self, task_id, title):
        with self._get_connection() as conn:
            conn.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=?", (title, utc_now().isoformat(), task_id))
            return self.get_task(task_id)

    def trash_task(self, task_id, deleted):
        with self._get_connection() as conn:
            conn.execute("UPDATE tasks SET deleted_at=?, updated_at=? WHERE id=?",
                         (utc_now().isoformat() if deleted else None, utc_now().isoformat(), task_id))
            return self.get_task(task_id)

    def list_trash(self, query, sort, offset, limit):
        order = {"newest": "deleted_at DESC, id", "oldest": "deleted_at ASC, id",
                 "title": "COALESCE(title, topic) COLLATE NOCASE, id"}[sort]
        where = "deleted_at IS NOT NULL AND instr(lower(COALESCE(title, '') || ' ' || topic), lower(?)) > 0"
        with self._get_connection() as conn:
            total = conn.execute("SELECT count(*) FROM tasks WHERE deleted_at IS NOT NULL").fetchone()[0]
            matched = conn.execute(f"SELECT count(*) FROM tasks WHERE {where}", (query,)).fetchone()[0]
            rows = conn.execute(f"SELECT id FROM tasks WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                                (query, limit, offset)).fetchall()
            return {"items": [self.get_task(row[0]) for row in rows], "total": total, "matched": matched}

    def _trash_targets(self, conn, ids):
        if ids is None:
            return [row[0] for row in conn.execute("SELECT id FROM tasks WHERE deleted_at IS NOT NULL ORDER BY id")]
        unique = list(dict.fromkeys(ids))
        marks = ",".join("?" for _ in unique)
        found = {row[0] for row in conn.execute(f"SELECT id FROM tasks WHERE deleted_at IS NOT NULL AND id IN ({marks})", unique)}
        if found != set(unique):
            raise StateConflict("部分对话已被恢复或删除，请刷新回收站后重试")
        return unique

    def restore_trash(self, ids):
        with self._get_connection() as conn:
            return [self.trash_task(task_id, False) for task_id in self._trash_targets(conn, ids)]

    def delete_trash(self, ids, active_task_id=None):
        with self._get_connection() as conn:
            targets = self._trash_targets(conn, ids)
            if active_task_id in targets:
                raise StateConflict("对话的在途请求尚未结束，请稍后再彻底删除")
            for task_id in targets:
                # 先保存候选来源；只清理不再被其他运行引用的数据。
                sources = [row[0] for row in conn.execute("SELECT source_text_id FROM run_sources WHERE run_id IN (SELECT id FROM runs WHERE task_id=?)", (task_id,))]
                papers = [row[0] for row in conn.execute("SELECT paper_id FROM run_papers WHERE run_id IN (SELECT id FROM runs WHERE task_id=?)", (task_id,))]
                conn.execute("DELETE FROM conversation_turns WHERE task_id=?", (task_id,))
                conn.execute("DELETE FROM chat_messages WHERE task_id=?", (task_id,))
                conn.execute("DELETE FROM conversation_usage WHERE task_id=?", (task_id,))
                for table in ("paper_analyses", "paper_selections", "run_messages", "reports", "events", "search_queries", "assessments", "run_sources", "run_papers", "conversation_run_states"):
                    conn.execute(f"DELETE FROM {table} WHERE run_id IN (SELECT id FROM runs WHERE task_id=?)", (task_id,))
                conn.execute("DELETE FROM runs WHERE task_id=?", (task_id,))
                conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                for source_id in sources:
                    if not conn.execute("SELECT 1 FROM run_sources WHERE source_text_id=?", (source_id,)).fetchone():
                        conn.execute("DELETE FROM evidence WHERE source_text_id=?", (source_id,))
                        conn.execute("DELETE FROM source_texts WHERE id=?", (source_id,))
                for paper_id in papers:
                    conn.execute("DELETE FROM papers WHERE id=? AND NOT EXISTS (SELECT 1 FROM run_papers WHERE paper_id=?) AND NOT EXISTS (SELECT 1 FROM source_texts WHERE paper_id=?) AND NOT EXISTS (SELECT 1 FROM evidence WHERE paper_id=?)", (paper_id, paper_id, paper_id, paper_id))
            return targets

    # --- Run 与状态操作（只在短事务内执行，不跨网络请求） ---
    def create_run(self, run: Run) -> None:
        with self._get_connection() as conn:
            active = conn.execute("SELECT id FROM runs WHERE task_id=? AND status IN ('queued','running','pause_requested','paused','needs_input')", (run.task_id,)).fetchone()
            if active:
                raise StateConflict("该任务已有活动运行")
            if run.initial_input is None:
                task = self.get_task(run.task_id)
                if task is None:
                    raise ValueError("任务不存在")
                run.initial_input = TaskInput.model_validate({k: getattr(task,k) for k in TaskInput.model_fields})
            if run.current_input is None:
                run.current_input = run.initial_input.model_copy(deep=True)
            conn.execute("INSERT INTO runs(id,task_id,initial_topic,status,stage,created_at,details) VALUES(?,?,?,?,?,?,?)", (run.id,run.task_id,run.initial_topic,run.status.value,run.stage.value,run.created_at.isoformat(),run.model_dump_json()))
            self.update_run(run)

    def record_conversation_run(self, run):
        from backend.app.storage.conversations import ConversationStore
        ConversationStore(self).record_run(run)

    @staticmethod
    def _run_from_row(row):
        data = json.loads(row["details"])
        # 原始列是控制状态的单一事实来源；details 保存新增字段和检查点。
        data.update({k: row[k] for k in ("id","task_id","initial_topic","status","stage","current_round","max_rounds","max_calls","total_calls","total_execution_seconds","stop_reason","created_at","started_at","ended_at")})
        return Run.model_validate(data)

    def get_run(self, run_id: str) -> Optional[Run]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            return self._run_from_row(row) if row else None

    def list_runs(self, task_id=None, status=None):
        sql, values = "SELECT * FROM runs", []
        conditions = []
        if task_id is not None:
            conditions.append("task_id=?")
            values.append(task_id)
        if status is not None:
            conditions.append("status=?")
            values.append(status.value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        with self._get_connection() as conn:
            return [self._run_from_row(r) for r in conn.execute(sql + " ORDER BY created_at ASC,id ASC", values)]

    def update_run(self, run: Run) -> None:
        with self._get_connection() as conn:
            # API 控制请求可能发生在外部 await 中；旧 worker 快照不能覆盖暂停／取消。
            row = conn.execute("SELECT status,stop_reason,ended_at FROM runs WHERE id=?", (run.id,)).fetchone()
            if row is None:
                raise ValueError("运行不存在")
            if row["status"] == "cancelled":
                run.status = RunStatus.CANCELLED
                run.stop_reason = row["stop_reason"]
                run.ended_at = datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None
            elif row["status"] == "pause_requested" and run.status not in (RunStatus.PAUSED,RunStatus.INTERRUPTED,RunStatus.FAILED):
                run.status = RunStatus.PAUSE_REQUESTED
            conn.execute("UPDATE runs SET status=?,stage=?,current_round=?,max_rounds=?,max_calls=?,total_calls=?,total_execution_seconds=?,stop_reason=?,started_at=?,ended_at=?,details=? WHERE id=?", (run.status.value,run.stage.value,run.current_round,run.max_rounds,run.max_calls,run.total_calls,run.total_execution_seconds,run.stop_reason,run.started_at.isoformat() if run.started_at else None,run.ended_at.isoformat() if run.ended_at else None,run.model_dump_json(),run.id))
            self.record_conversation_run(run)

    def pause_run(self, run_id, dialogue=False):
        with self._get_connection() as conn:
            if not dialogue:
                conn.execute("UPDATE conversation_turns SET paused_by_dialogue=0 WHERE run_id=? AND status IN ('queued','processing')", (run_id,))
            run = self.get_run(run_id)
            if run is None:
                raise ValueError("运行不存在")
            if run.status in (RunStatus.PAUSED, RunStatus.PAUSE_REQUESTED):
                return run
            if run.status == RunStatus.QUEUED:
                return self.transition(run_id,[RunStatus.QUEUED],RunStatus.PAUSED)
            return self.transition(run_id,[RunStatus.RUNNING],RunStatus.PAUSE_REQUESTED)

    def cancel_run(self, run_id):
        with self._get_connection() as conn:
            run = self.get_run(run_id)
            if run is None:
                raise ValueError("运行不存在")
            if run.status == RunStatus.CANCELLED:
                return run
            conn.execute("UPDATE runs SET stop_reason='用户取消',ended_at=? WHERE id=?", (utc_now().isoformat(),run_id))
            self.transition(run_id,[RunStatus.QUEUED,RunStatus.RUNNING,RunStatus.PAUSE_REQUESTED,RunStatus.PAUSED,RunStatus.NEEDS_INPUT],RunStatus.CANCELLED)
            return self.get_run(run_id)

    def add_message_if_paused(self, msg):
        with self._get_connection():
            run = self.get_run(msg.run_id)
            if run is None or run.status not in (RunStatus.PAUSED,RunStatus.NEEDS_INPUT):
                raise StateConflict("只能在暂停或等待补充时添加信息")
            self.save_run_message(msg)

    def transition(self, run_id, expected, target):
        with self._get_connection() as conn:
            placeholders = ",".join("?" for _ in expected)
            changed = conn.execute(f"UPDATE runs SET status=? WHERE id=? AND status IN ({placeholders})", [target.value,run_id,*[s.value for s in expected]]).rowcount
            if not changed:
                raise StateConflict("当前运行状态不允许此操作")
            run = self.get_run(run_id)
            self.record_conversation_run(run)
            return run

    def interrupt_running(self):
        with self._get_connection() as conn:
            interrupted = [r.id for r in self.list_runs() if r.status in (RunStatus.RUNNING,RunStatus.PAUSE_REQUESTED)]
            conn.execute("UPDATE runs SET status='interrupted',stop_reason='执行进程中断；不会自动重复外部调用',ended_at=? WHERE status IN ('running','pause_requested')", (utc_now().isoformat(),))
            for run_id in interrupted:
                self.record_conversation_run(self.get_run(run_id))

    def save_run_message(self, msg: RunMessage) -> None:
        with self._get_connection() as conn:
            conn.execute("INSERT INTO run_messages(id,run_id,content,status,impact_summary,created_at,proposed_scope) VALUES(?,?,?,?,?,?,?)", (msg.id,msg.run_id,msg.content,msg.status,msg.impact_summary,msg.created_at.isoformat(),msg.proposed_scope.model_dump_json() if msg.proposed_scope else None))

    def list_run_messages(self, run_id: str) -> List[RunMessage]:
        with self._get_connection() as conn:
            messages = []
            for row in conn.execute("SELECT * FROM run_messages WHERE run_id=? ORDER BY created_at,id", (run_id,)):
                data = dict(row)
                data["proposed_scope"] = json.loads(data["proposed_scope"]) if data["proposed_scope"] else None
                messages.append(RunMessage.model_validate(data))
            return messages

    def apply_plan(self, run, messages, keep_paper_ids=None):
        with self._get_connection() as conn:
            if keep_paper_ids is not None:
                self.select_papers(run.id,keep_paper_ids)
            self.update_run(run)
            for msg in messages:
                conn.execute("UPDATE run_messages SET status='processed',impact_summary=? WHERE id=?", ("已重新规划并重新确定历史文献的纳入范围",msg.id))

    def save_papers(self, papers: List[Paper], run_id: Optional[str] = None) -> None:
        with self._get_connection() as conn:
            for p in papers:
                # 首次元数据不被下一次检索覆盖；各运行另外保存取得的独立快照。
                conn.execute("INSERT OR IGNORE INTO papers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (p.id,p.title,json.dumps(p.authors),p.year,p.doi,p.source,p.source_id,p.url,p.pdf_url,p.abstract,p.primary_category,json.dumps(p.categories),p.fetched_at.isoformat()))
                if run_id:
                    conn.execute("INSERT OR IGNORE INTO run_papers(run_id,paper_id,is_selected,snapshot) VALUES(?,?,1,?)", (run_id,p.id,p.model_dump_json()))

    def get_papers_by_run(self, run_id: str, selected_only=False) -> List[Paper]:
        with self._get_connection() as conn:
            sql = "SELECT p.*,rp.snapshot FROM papers p JOIN run_papers rp ON p.id=rp.paper_id WHERE rp.run_id=?"
            if selected_only:
                sql += " AND rp.is_selected=1"
            result = []
            for r in conn.execute(sql + " ORDER BY p.id", (run_id,)):
                if r["snapshot"] is not None:
                    result.append(Paper.model_validate_json(r["snapshot"]))
                else:
                    d = dict(r)
                    d.pop("snapshot")
                    d["authors"], d["categories"] = json.loads(d["authors"] or "[]"), json.loads(d["categories"] or "[]")
                    result.append(Paper.model_validate(d))
            return result

    def select_papers(self, run_id, paper_ids):
        with self._get_connection() as conn:
            conn.execute("UPDATE run_papers SET is_selected=0 WHERE run_id=?", (run_id,))
            for paper_id in paper_ids:
                if conn.execute("UPDATE run_papers SET is_selected=1 WHERE run_id=? AND paper_id=?", (run_id,paper_id)).rowcount != 1:
                    raise ValueError("计划引用了未知论文")

    def save_source_texts(self, texts: List[SourceText], run_id=None) -> None:
        with self._get_connection() as conn:
            for t in texts:
                # 快照一旦被引用，不能原地替换。
                conn.execute("INSERT INTO source_texts VALUES(?,?,?,?,?,?,?,?)", (t.id,t.paper_id,t.source_type.value,t.source_url,t.page_number,t.content,t.status,t.fetched_at.isoformat()))
                if run_id:
                    conn.execute("INSERT INTO run_sources VALUES(?,?)", (run_id,t.id))

    def get_source_texts(self, paper_id: str, run_id=None) -> List[SourceText]:
        with self._get_connection() as conn:
            sql, args = "SELECT s.* FROM source_texts s", []
            if run_id is not None:
                sql += " JOIN run_sources rs ON rs.source_text_id=s.id AND rs.run_id=?"
                args.append(run_id)
            sql += " WHERE s.paper_id=? ORDER BY s.fetched_at,s.page_number,s.id"
            args.append(paper_id)
            return [SourceText.model_validate(dict(r)) for r in conn.execute(sql, args)]

    def save_evidence(self, ev_list: List[Evidence]) -> None:
        with self._get_connection() as conn:
            for ev in ev_list:
                s = conn.execute("SELECT * FROM source_texts WHERE id=?", (ev.source_text_id,)).fetchone()
                start, end = ev.location_start, ev.location_end
                if s is None or s["status"] != "ok" or s["paper_id"] != ev.paper_id or s["page_number"] != ev.page_number or start is None or end is None or not (0 <= start < end <= len(s["content"])) or s["content"][start:end] != ev.quote:
                    raise ValueError("证据与实际读取的快照或定位不匹配")
                conn.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?)", (ev.id,ev.source_text_id,ev.paper_id,ev.page_number,ev.quote,start,end))

    def get_evidence(self, paper_id, run_id=None):
        with self._get_connection() as conn:
            sql, args = "SELECT e.* FROM evidence e", []
            if run_id is not None:
                sql += " JOIN run_sources rs ON rs.source_text_id=e.source_text_id AND rs.run_id=?"
                args.append(run_id)
            sql += " WHERE e.paper_id=? ORDER BY e.id"
            args.append(paper_id)
            return [Evidence.model_validate(dict(r)) for r in conn.execute(sql,args)]

    def save_report(self, report: Report) -> None:
        with self._get_connection() as conn:
            conn.execute("INSERT INTO reports(id,run_id,title,content_markdown,gaps,stop_reason,created_at,document) VALUES(?,?,?,?,?,?,?,?)", (report.id,report.run_id,report.title,report.content_markdown,json.dumps(report.gaps,ensure_ascii=False),report.stop_reason,report.created_at.isoformat(),report.document.model_dump_json() if report.document else None))
            self.record_conversation_run(self.get_run(report.run_id))

    def get_report(self, run_id: str, report_id: Optional[str] = None) -> Optional[Report]:
        with self._get_connection() as conn:
            if report_id is None:
                r = conn.execute("SELECT * FROM reports WHERE run_id=? ORDER BY rowid DESC LIMIT 1", (run_id,)).fetchone()
            else:
                r = conn.execute("SELECT * FROM reports WHERE run_id=? AND id=?", (run_id, report_id)).fetchone()
            if r is None:
                return None
            data = dict(r)
            data["gaps"] = json.loads(data["gaps"] or "[]")
            data["document"] = json.loads(data["document"]) if data["document"] else None
            return Report.model_validate(data)

    def save_event(self, event):
        with self._get_connection() as conn:
            conn.execute("INSERT INTO events VALUES(?,?,?)", (event.id,event.run_id,event.model_dump_json()))

    def list_events(self, run_id):
        with self._get_connection() as conn:
            return [Event.model_validate_json(r[0]) for r in conn.execute("SELECT data FROM events WHERE run_id=? ORDER BY rowid", (run_id,))]

    def save_query(self, query):
        with self._get_connection() as conn:
            conn.execute("INSERT INTO search_queries VALUES(?,?,?)", (query.id,query.run_id,query.model_dump_json()))

    def list_queries(self, run_id):
        with self._get_connection() as conn:
            return [SearchQuery.model_validate_json(r[0]) for r in conn.execute("SELECT data FROM search_queries WHERE run_id=? ORDER BY rowid", (run_id,))]

    def list_assessments(self, run_id, revision=None):
        with self._get_connection() as conn:
            rows = [Assessment.model_validate_json(r[0]) for r in conn.execute("SELECT data FROM assessments WHERE run_id=? ORDER BY rowid", (run_id,))]
            return [a for a in rows if revision is None or a.analysis_revision == revision]

    def save_analysis(self, analysis):
        with self._get_connection() as conn:
            conn.execute("INSERT INTO paper_analyses VALUES(?,?,?,?,?)", (analysis.id, analysis.run_id, analysis.paper_id, analysis.analysis_revision, analysis.model_dump_json()))

    def list_analyses(self, run_id, revision=None):
        with self._get_connection() as conn:
            sql, args = "SELECT data FROM paper_analyses WHERE run_id=?", [run_id]
            if revision is not None:
                sql += " AND revision=?"
                args.append(revision)
            latest = {}
            for row in conn.execute(sql + " ORDER BY rowid", args):
                analysis = PaperAnalysis.model_validate_json(row[0])
                latest[analysis.paper_id] = analysis
            return list(latest.values())

    def save_selections(self, run_id, selections):
        with self._get_connection() as conn:
            for selection in selections:
                conn.execute("INSERT INTO paper_selections VALUES(?,?,?,?)", (run_id, selection.paper_id, selection.analysis_revision, selection.model_dump_json()))
                conn.execute("UPDATE run_papers SET is_selected=?,relevance_note=? WHERE run_id=? AND paper_id=?", (int(selection.relevant), selection.reason, run_id, selection.paper_id))

    def list_selections(self, run_id, revision):
        with self._get_connection() as conn:
            return [PaperSelection.model_validate_json(r[0]) for r in conn.execute("SELECT data FROM paper_selections WHERE run_id=? AND revision=? ORDER BY rowid", (run_id, revision))]

    def save_assessment(self, assessment):
        with self._get_connection() as conn:
            conn.execute("INSERT INTO assessments VALUES(?,?,?)", (assessment.id,assessment.run_id,assessment.model_dump_json()))

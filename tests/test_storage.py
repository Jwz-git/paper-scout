from backend.app.domain.models import (
    Paper,
    Report,
    Run,
    RunMessage,
    RunStage,
    RunStatus,
    SourceText,
    SourceType,
    Task,
)
from backend.app.storage.database import Database


def test_database_crud():
    db = Database(db_path=":memory:")

    # 1. Task 测试
    task = Task(id="task-1", topic="LLM Agent Planning", start_year=2023, end_year=2026)
    db.create_task(task)
    fetched_task = db.get_task("task-1")
    assert fetched_task is not None
    assert fetched_task.topic == "LLM Agent Planning"
    assert fetched_task.start_year == 2023

    task_list = db.list_tasks()
    assert len(task_list) == 1

    # 2. Run 测试
    run = Run(id="run-1", task_id="task-1", initial_topic=task.topic)
    db.create_run(run)
    fetched_run = db.get_run("run-1")
    assert fetched_run is not None
    assert fetched_run.status == RunStatus.QUEUED
    assert fetched_run.stage == RunStage.UNDERSTANDING

    run.status = RunStatus.RUNNING
    run.stage = RunStage.SEARCHING
    db.update_run(run)
    updated_run = db.get_run("run-1")
    assert updated_run.status == RunStatus.RUNNING
    assert updated_run.stage == RunStage.SEARCHING

    # 3. Message 测试
    msg = RunMessage(id="msg-1", run_id="run-1", content="请补充关注机器人控制")
    db.save_run_message(msg)
    messages = db.list_run_messages("run-1")
    assert len(messages) == 1
    assert messages[0].content == "请补充关注机器人控制"

    # 4. Paper 与 SourceText 测试
    paper = Paper(
        id="arxiv:2203.08975",
        title="Test Paper",
        authors=["Author A"],
        source="arxiv",
        source_id="2203.08975",
        url="http://arxiv.org/abs/2203.08975",
        abstract="Test abstract",
    )
    db.save_papers([paper], run_id="run-1")
    papers = db.get_papers_by_run("run-1")
    assert len(papers) == 1
    assert papers[0].id == "arxiv:2203.08975"

    st = SourceText(
        id="arxiv:2203.08975:abstract",
        paper_id=paper.id,
        source_type=SourceType.ABSTRACT,
        content="Abstract content",
    )
    db.save_source_texts([st])
    st_list = db.get_source_texts(paper.id)
    assert len(st_list) == 1
    assert st_list[0].content == "Abstract content"

    # 5. Report 测试
    report = Report(
        id="report-1",
        run_id="run-1",
        title="Test Report",
        content_markdown="# Report content",
        gaps=["Gap 1"],
    )
    db.save_report(report)
    fetched_report = db.get_report("run-1")
    assert fetched_report is not None
    assert fetched_report.title == "Test Report"
    assert fetched_report.gaps == ["Gap 1"]
    db.close()


def test_snapshots_and_evidence_are_immutable(tmp_path):
    import sqlite3
    from backend.app.domain.models import Evidence
    db=Database(tmp_path/"data.db")
    for i in (1,2):
        db.create_task(Task(id=f"t{i}",topic="Agents"))
        db.create_run(Run(id=f"r{i}",task_id=f"t{i}",initial_topic="Agents"))
    p=Paper(id="p",source_id="p",title="Original",url="https://arxiv.org/abs/p",abstract="original")
    db.save_papers([p],"r1")
    newer=p.model_copy(update={"title":"Changed","abstract":"changed"})
    db.save_papers([newer],"r2")
    assert db.get_papers_by_run("r1")[0].title=="Original"
    assert db.get_papers_by_run("r2")[0].title=="Changed"
    s=SourceText(id="s",paper_id="p",source_type=SourceType.ABSTRACT,content="original")
    db.save_source_texts([s],"r1")
    e=Evidence(id="e",paper_id="p",source_text_id="s",quote="original",location_start=0,location_end=8)
    db.save_evidence([e])
    with __import__('pytest').raises(sqlite3.IntegrityError):
        db.save_source_texts([s.model_copy(update={"content":"changed"})],"r1")
    with __import__('pytest').raises(ValueError):
        db.save_evidence([e.model_copy(update={"id":"bad","quote":"invented"})])
    assert db.get_source_texts("p","r1")[0].content=="original"
    with __import__('pytest').raises(sqlite3.IntegrityError):
        db.save_papers([p],"missing_run")
    db.close()
    db=Database(tmp_path/"data.db")
    assert db.get_evidence("p","r1")[0].quote=="original"
    assert db.get_papers_by_run("r1")[0].title=="Original"
    db.close()


def test_old_schema_is_migrated_without_deleting_history(tmp_path):
    import sqlite3
    path=tmp_path/"legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE tasks(id TEXT PRIMARY KEY,topic TEXT NOT NULL,start_year INTEGER,end_year INTEGER,focus_dimensions TEXT,output_requirements TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE runs(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,initial_topic TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,current_round INTEGER NOT NULL DEFAULT 1,max_rounds INTEGER NOT NULL DEFAULT 3,max_calls INTEGER NOT NULL DEFAULT 20,total_calls INTEGER NOT NULL DEFAULT 0,total_execution_seconds REAL NOT NULL DEFAULT 0,stop_reason TEXT,created_at TEXT NOT NULL,started_at TEXT,ended_at TEXT);
            INSERT INTO tasks VALUES('old','Original',NULL,NULL,'[]',NULL,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00');
            INSERT INTO runs(id,task_id,initial_topic,status,stage,created_at) VALUES('oldrun','old','Original','running','searching','2026-01-01T00:00:00+00:00');
        """)
    db=Database(path)
    assert db.get_task("old").topic=="Original"
    assert db.get_run("oldrun").initial_input is None  # 不能编造已丢失的旧初始范围。
    db.interrupt_running()
    assert db.get_run("oldrun").status==RunStatus.INTERRUPTED
    db.close()


def test_shared_connection_rejects_duplicate_active_runs(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from backend.app.storage.database import StateConflict
    db=Database(tmp_path/"thread.db")
    db.create_task(Task(id="t",topic="Agents"))
    def create(i):
        try:
            db.create_run(Run(id=f"r{i}",task_id="t",initial_topic="Agents"))
            return True
        except StateConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(create,range(2)))==1
    assert len(db.list_runs())==1
    db.close()

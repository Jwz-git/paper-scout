"""对话 agent：每条用户消息交给同一个 agent，循环调用模型和工具，直到回复用户。

模型每一步输出 {thought, actions}；代码负责执行工具、计数、执行上限、引文核对、上下文压缩和状态保存。
执行中收到的新消息在下一次模型调用前并入；停止由 worker 取消协程。"""
import asyncio
import json
import time
from uuid import uuid4

from pydantic import ValidationError

from backend.app import prompts
from backend.app.adapters.arxiv import ArXivAdapter
from backend.app.adapters.llm import LLMError, LLMMessage
from backend.app.adapters.pdf import PDFAdapter
from backend.app.agent.actions import MainStep, ReaderStep
from backend.app.agent.workspace import ToolError, Workspace, pages_label, read_summary, short
from backend.app.domain.conversation import AgentWork
from backend.app.domain.models import Event, utc_now
from backend.app.storage.conversations import ConversationStore

# 每轮（一条用户消息及执行中并入的消息）的执行上限；阅读子 agent 共用同一份预算。
LIMITS = {"steps": 30, "calls": 150, "seconds": 1800, "fulltexts": 10, "readers": 3, "reader_steps": 8}
# 达到上限后留给收尾回复的额度。
FINAL_CALLS, FINAL_SECONDS = 2, 150
# 所用网关在多个模型请求同时进行时频繁返回 5xx，单个请求正常；子 agent 并行，但模型请求排队。
MODEL_CONCURRENCY = 1
RETRY_DELAYS = (2.0, 5.0)
# 所用网关的内容过滤实测不稳定（同一篇论文时拒时过），按暂时错误有限重试。
TRANSIENT = {"rate_limited", "timeout", "network_error", "server_error", "refusal"}
OUTPUT_ERRORS = {"invalid_json", "incomplete", "no_text"}
MAX_INVALID = 3
# 这些字段由代码回传给模型；长上下文里模型偶尔把它们续写进自己的输出，丢弃后再校验。
OBSERVATION_KEYS = {"results", "budget", "notices", "new_messages", "steps_left", "output_error", "final"}
# 一步内返回给模型的原文上限（字符）；整份上下文超过 cap 时压缩较早的步骤。
STEP_TEXT = 40000
HISTORY_MESSAGES, HISTORY_CHARS, MESSAGE_CHARS = 20, 24000, 4000
MODES = {"auto": "auto：由你判断直接回答、澄清还是开展调研",
         "research": "research：用户要求开展调研",
         "ask": "ask：只用工作区已有资料回答，不能检索或下载全文"}
READER_STATUS = {"done": "完成", "incomplete": "未完成", "failed": "失败"}


class LimitReached(Exception):
    """本轮执行上限；停止检索和阅读，进入收尾。"""


class AgentFailure(Exception):
    """本轮无法继续：模型服务失败。"""

    def __init__(self, code, detail=None):
        super().__init__(code)
        self.code, self.detail = code, detail


class InvalidOutput(Exception):
    def __init__(self, message, raw=None):
        super().__init__(message)
        self.raw = raw


def dumps(data):
    return json.dumps(data, ensure_ascii=False, default=str)


def output_text(exc):
    text = {"invalid_json": "输出不是有效的 JSON 对象", "no_text": "没有输出内容",
            "incomplete": "输出没有完成；不能当作完整结果，原因见诊断"}[exc.code]
    return text + (f"（{exc.diagnostic}）" if exc.diagnostic else "")


def validation_text(exc):
    parts = []
    for error in exc.errors()[:6]:
        location = ".".join(str(p) for p in error["loc"])
        parts.append(f"{location}：{error['msg']}" if location else error["msg"])
    return "输出不符合格式：" + "；".join(parts)


def describe(action):
    tool = action.tool
    if tool == "search":
        return "检索 arXiv：" + short(action.query, 60)
    if tool == "read":
        return f"阅读 {action.paper_id} " + ("摘要" if not action.pages else f"第 {pages_label(action.pages)} 页")
    if tool == "find":
        return f"在 {action.paper_id} 中查找「{short(action.text, 30)}」"
    if tool == "note":
        return f"记录 {action.paper_id} 的发现"
    if tool == "decide":
        return f"判断 {len(action.decisions)} 篇论文是否纳入"
    if tool == "delegate":
        return f"把 {len(action.tasks)} 篇论文分派给阅读子 agent"
    if tool == "todo":
        return "更新计划"
    if tool == "workspace":
        return "查看工作区" if action.paper_id is None else f"查看 {action.paper_id}"
    if tool == "report":
        return "撰写报告：" + short(action.title, 40)
    return tool


def brief_action(action):
    if action.tool == "note":
        return {"tool": "note", "paper_id": action.paper_id, "findings": len(action.findings), "experiments": len(action.experiments)}
    if action.tool == "report":
        return {"tool": "report", "title": action.title}
    if action.tool == "delegate":
        return {"tool": "delegate", "papers": [t.paper_id for t in action.tasks]}
    if action.tool == "todo":
        return {"tool": "todo", "items": len(action.items)}
    if action.tool in ("reply", "done"):
        return {"tool": action.tool}
    return action.model_dump(exclude_none=True)


def evidence_of(tool, data):
    if tool == "note":
        return [i for item in data["saved"] for i in item["evidence_ids"]]
    if tool == "delegate":
        return {r["paper_id"]: r["evidence"] for r in data["results"] if r["evidence"]}
    return None


class Tokens:
    """累计 token；任何一次调用缺少用量时总数记为未知，调用返回前也显示未知。"""

    def __init__(self, values, calls):
        self.values, self.started, self.inflight = dict(values), calls > 0, 0

    def begin(self):
        self.inflight += 1

    def end(self, usage):
        self.inflight -= 1
        values = usage.model_dump() if usage is not None else dict.fromkeys(self.values)
        for key, value in values.items():
            prior = self.values[key]
            self.values[key] = value if not self.started else (prior + value if prior is not None and value is not None else None)
        self.started = True

    def view(self):
        return dict.fromkeys(self.values) if self.inflight else dict(self.values)


class Transcript:
    """一个 agent 的上下文：开场消息加逐步的输出与结果。步骤过多或过长时，较早的步骤只保留动作和结果摘要。"""

    def __init__(self, system, opening, keep, slack, cap):
        self.system, self.opening = system, opening
        self.keep, self.slack, self.cap = keep, slack, cap
        self.steps, self.compacted = [], 0
        self.retry = None
        self.memo = {}

    def add(self, step, results, extra):
        self.steps.append({"step": step, "output": dumps(step.model_dump(mode="json", exclude_none=True)),
                           "observation": {"results": results, **extra}})

    def inbox(self):
        """模型还没看到的最后一条消息；执行中收到的新消息附在这里。"""
        return self.steps[-1]["observation"] if self.steps else self.opening

    def render(self, final):
        opening = dict(self.opening)
        if self.compacted:
            opening["earlier_steps"] = [{
                "thought": s["step"].thought, "actions": [brief_action(a) for a in s["step"].actions],
                "results": [{k: r[k] for k in ("tool", "ok", "summary", "error", "evidence") if k in r} for r in s["observation"]["results"]],
                **({"new_messages": s["observation"]["new_messages"]} if "new_messages" in s["observation"] else {}),
            } for s in self.steps[:self.compacted]]
            opening.update(self.memo)
        turns = [opening]
        for s in self.steps[self.compacted:]:
            turns += [s["output"], dict(s["observation"])]
        if self.retry is not None:
            raw, error = self.retry
            if raw:
                turns += [raw[:4000], {"output_error": error}]
            else:
                turns[-1]["output_error"] = error
        if final:
            turns[-1]["final"] = final
        return [LLMMessage(role="system", content=self.system)] + [
            LLMMessage(role="user", content=dumps(t)) if isinstance(t, dict) else LLMMessage(role="assistant", content=t)
            for t in turns]

    def messages(self, final=None):
        if len(self.steps) - self.compacted > self.keep + self.slack:
            self.compacted = len(self.steps) - self.keep
        messages = self.render(final)
        while sum(len(m.content) for m in messages) > self.cap and self.compacted < len(self.steps) - 1:
            self.compacted += 1
            messages = self.render(final)
        return messages


class Turn:
    """一轮 agent 工作：从一条用户消息开始，到回复、失败或停止为止。"""

    def __init__(self, service, row):
        self.db, self.store, self.llm = service.db, service.store, service.llm
        self.row = row
        self.clock = time.monotonic()
        self.wrapping, self.limited, self.invalid, self.reminded = False, None, 0, False
        self.fulltexts, self.max_fulltext = 0, LIMITS["fulltexts"]
        self.model_gate = asyncio.Semaphore(MODEL_CONCURRENCY)
        self.run = self.db.agent_run(row["task_id"])
        self.usage = self.store.usage(row["task_id"])
        self.base = (self.usage.model_calls, self.usage.total_execution_seconds,
                     self.run.total_calls, self.run.model_calls, self.run.total_execution_seconds)
        self.tokens = (Tokens(self.usage.token_usage, self.usage.model_calls), Tokens(self.run.token_usage, self.run.model_calls))
        self.work = AgentWork(run_id=self.run.id, limits={k: float(v) for k, v in LIMITS.items()})
        self.workspace = Workspace(self.db, self.run, service.arxiv, service.pdf, self, asyncio.Lock(), offline=row["mode"] == "ask")
        self.save()
        self.transcript = Transcript(prompts.AGENT, self.opening(), keep=6, slack=6, cap=120000)

    # --- 状态 ---
    def elapsed(self):
        return time.monotonic() - self.clock

    def limit(self, name):
        reserve = {"calls": FINAL_CALLS, "seconds": FINAL_SECONDS}.get(name, 0) if self.wrapping else 0
        return LIMITS[name] + reserve

    def save(self):
        elapsed = self.elapsed()
        calls, seconds, run_calls, run_model_calls, run_seconds = self.base
        self.work.seconds, self.work.progress_at = round(elapsed, 1), utc_now()
        self.usage.model_calls = calls + self.work.model_calls
        self.usage.total_execution_seconds = seconds + elapsed
        self.usage.token_usage = self.tokens[0].view()
        self.run.total_calls = run_calls + self.work.calls
        self.run.model_calls = run_model_calls + self.work.model_calls
        self.run.total_execution_seconds = run_seconds + elapsed
        self.run.token_usage = self.tokens[1].view()
        with self.db._get_connection():
            self.store.save_work(self.row, self.work)
            self.store.save_usage(self.row["task_id"], self.usage)
            self.db.update_run(self.run)

    def activity(self, text):
        self.work.activity = text
        self.save()

    def event(self, category, message, actor="agent"):
        self.db.save_event(Event(id=uuid4().hex, run_id=self.run.id, category=category, message=message,
                                 turn_id=self.row["assistant_id"], actor=actor))

    def budget(self):
        return {"steps_left": LIMITS["steps"] - self.work.steps, "calls_left": LIMITS["calls"] - self.work.calls,
                "seconds_left": max(0, int(LIMITS["seconds"] - self.elapsed())), "fulltexts_left": LIMITS["fulltexts"] - self.fulltexts}

    # --- 外部调用 ---
    async def external(self):
        """每次外部请求（模型、arXiv、PDF）发出前计数并检查上限；计数先保存，进程退出也不会少记。"""
        if self.work.calls >= self.limit("calls"):
            raise LimitReached("达到本轮外部调用上限")
        if self.elapsed() >= self.limit("seconds"):
            raise LimitReached("达到本轮执行时间上限")
        self.work.calls += 1
        self.save()

    async def generate(self, messages):
        # 排到之后才计数和计时：排队中被停止的请求没有发出。
        async with self.model_gate:
            await self.external()
            self.work.model_calls += 1
            usage = None
            for tokens in self.tokens:
                tokens.begin()
            try:
                response = await asyncio.wait_for(self.llm.generate(messages, response_format="json_object"),
                                                  timeout=max(1.0, self.limit("seconds") - self.elapsed()))
                usage = response.usage
                return response
            except asyncio.TimeoutError:
                raise LimitReached("达到本轮执行时间上限") from None
            except LLMError as exc:
                usage = exc.usage
                raise
            finally:
                for tokens in self.tokens:
                    tokens.end(usage)
                self.save()

    async def model(self, messages, schema, actor):
        """一次模型决策：暂时性服务错误有限重试；输出格式问题交回调用方，让模型改正。"""
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                response = await self.generate(messages)
                break
            except LLMError as exc:
                if exc.code in OUTPUT_ERRORS:
                    raise InvalidOutput(output_text(exc)) from None
                if exc.code not in TRANSIENT or attempt == len(RETRY_DELAYS):
                    raise AgentFailure(exc.code, exc.diagnostic) from None
                self.event("retry", f"模型调用失败（{exc.code}），{RETRY_DELAYS[attempt]:g} 秒后重试", actor)
                await asyncio.sleep(RETRY_DELAYS[attempt])
        data = {k: v for k, v in response.parsed_json.items() if k not in OBSERVATION_KEYS}
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            raise InvalidOutput(validation_text(exc), response.content) from None

    # --- 主循环 ---
    def opening(self):
        messages = self.store.messages(self.row["task_id"])
        index = next(i for i, m in enumerate(messages) if m.id == self.row["user_id"])
        history, remaining = [], HISTORY_CHARS
        for message in reversed(messages[:index]):
            if remaining <= 0 or len(history) >= HISTORY_MESSAGES:
                break
            if message.status != "completed" or not message.content:
                continue
            text = message.content[:min(MESSAGE_CHARS, remaining)]
            history.append({"role": message.role, "content": text, **({"truncated": True} if len(text) < len(message.content) else {})})
            remaining -= len(text)
        history.reverse()
        return {"date": utc_now().date().isoformat(), "mode": MODES[self.row["mode"]], "conversation": history,
                "workspace": self.workspace.overview(), "message": messages[index].content,
                "limits": {k: LIMITS[k] for k in ("steps", "calls", "seconds", "fulltexts")}}

    def absorb(self):
        """执行中收到的新消息并入本轮：工作转到最新消息下继续，模型在下一步看到这些消息。"""
        result = self.store.absorb(self.row)
        if result is None:
            return
        self.row, received = result
        self.workspace.offline = self.row["mode"] == "ask"
        self.transcript.inbox().setdefault("new_messages", []).extend(received)
        for message in received:
            self.event("message", "收到新消息：" + short(message["content"], 80), "user")

    def record(self, step, results):
        budget = self.budget()
        extra = {"budget": budget}
        if budget["steps_left"] <= 3 or budget["calls_left"] <= 12 or budget["seconds_left"] <= 300:
            extra["notices"] = ["预算即将用完：不要再开始新的检索或精读，用已有证据写报告（需要时）并 reply。"]
        self.transcript.add(step, results, extra)

    def unfinished_todos(self):
        """回复前提醒一次未完成的计划项；预算快用完时不提醒，避免把收尾挤掉。"""
        budget = self.budget()
        if self.reminded or budget["steps_left"] <= 3 or budget["calls_left"] <= 12 or budget["seconds_left"] <= 300:
            return []
        return [item.text for item in self.work.todos if item.status != "done"]

    async def loop(self):
        while True:
            self.absorb()
            if self.work.steps >= LIMITS["steps"]:
                return await self.wrap_up("达到本轮步数上限")
            self.work.steps += 1
            self.activity("思考下一步")
            try:
                step = await self.model(self.transcript.messages(), MainStep, "agent")
            except InvalidOutput as exc:
                self.invalid += 1
                self.event("error", f"模型输出无效（连续第 {self.invalid} 次）：{short(str(exc), 200)}")
                self.transcript.retry = (exc.raw, str(exc))
                if self.invalid >= MAX_INVALID:
                    return await self.wrap_up(f"模型连续 {MAX_INVALID} 次输出不符合格式")
                continue
            except LimitReached as exc:
                return await self.wrap_up(str(exc))
            self.transcript.retry, self.invalid = None, 0
            if step.thought:
                self.event("thought", step.thought)
            action = step.actions[-1]
            replying = action.tool == "reply"
            results = await self.execute(step.actions[:-1] if replying else step.actions)
            if self.limited:
                self.record(step, results)
                return await self.wrap_up(self.limited)
            if replying:
                try:
                    if any(not result["ok"] for result in results):
                        raise ToolError("前面的动作失败，reply 未执行；根据工具结果改正后再回复。")
                    unfinished = self.unfinished_todos()
                    if unfinished:
                        self.reminded = True
                        raise ToolError("计划清单还有未完成的项：" + "；".join(unfinished)
                                        + "。先完成它们；确实不做的项用 todo 标为 done，并在回复中说明没做的原因，然后再 reply。")
                    return action.content, self.workspace.citations(action.evidence_ids)
                except ToolError as exc:
                    self.event("tool_error", f"回复未执行：{exc}")
                    results.append({"tool": "reply", "ok": False, "error": str(exc)})
            self.record(step, results)

    async def execute(self, actions, actor="agent", allowed=None):
        results, room = [], STEP_TEXT
        for action in actions:
            if self.limited:
                results.append({"tool": action.tool, "ok": False, "error": "已达到执行上限，未执行"})
                continue
            if actor == "agent":
                self.activity(describe(action))
            try:
                summary, data = await self.tool(action, allowed, room)
            except ToolError as exc:
                results.append({"tool": action.tool, "ok": False, "error": str(exc)})
                self.event("tool_error", f"{describe(action)}：{exc}", actor)
                continue
            except LimitReached as exc:
                self.limited = str(exc)
                results.append({"tool": action.tool, "ok": False, "error": f"{exc}，未完成"})
                continue
            room -= len(dumps(data))
            result = {"tool": action.tool, "ok": True, "summary": summary, "data": data}
            evidence = evidence_of(action.tool, data)
            if evidence:
                result["evidence"] = evidence
            results.append(result)
            self.event("tool", summary, actor)
        return results

    async def tool(self, action, allowed, room):
        workspace = self.workspace
        if action.tool == "search":
            return await workspace.search(action)
        if action.tool == "read":
            return await workspace.read(action, allowed, room)
        if action.tool == "find":
            return await workspace.find(action, allowed)
        if action.tool == "note":
            return workspace.note(action, allowed)
        if action.tool == "decide":
            return workspace.decide(action)
        if action.tool == "workspace":
            return workspace.view(action)
        if action.tool == "report":
            summary, data = workspace.report(action, self.work.limits)
            self.work.report_id = data["report_id"]
            return summary, data
        if action.tool == "todo":
            self.work.todos = action.items
            self.transcript.memo["todos"] = [item.model_dump() for item in action.items]
            done = sum(item.status == "done" for item in action.items)
            return f"更新计划：{len(action.items)} 项，已完成 {done} 项", {"todos": self.transcript.memo["todos"]}
        return await self.delegate(action)

    async def delegate(self, action):
        """阅读子 agent 并行精读；共享本轮预算，随本轮一起停止。全部结束后才返回，不留下游离任务。"""
        papers = [self.workspace.paper(task.paper_id) for task in action.tasks]
        gate, finished = asyncio.Semaphore(LIMITS["readers"]), []
        self.work.subagents += len(papers)
        self.activity(f"{len(papers)} 篇论文交给阅读子 agent（同时最多 {LIMITS['readers']} 个）")

        async def one(task, paper):
            async with gate:
                result = await Reader(self, paper, task.instruction, action.context).run()
            finished.append(result)
            self.activity(f"阅读子 agent 已完成 {len(finished)}/{len(papers)} 篇")
            return result

        outcomes = await asyncio.gather(*(one(t, p) for t, p in zip(action.tasks, papers)), return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                raise outcome
        done = sum(o["status"] == "done" for o in outcomes)
        return f"阅读子 agent 完成 {done}/{len(outcomes)} 篇", {"results": outcomes}

    async def wrap_up(self, reason):
        """达到上限后用预留额度生成一次总结回复；仍然失败时由代码给出已保存资料的概况。"""
        self.wrapping, self.work.stop_reason = True, reason
        self.event("limit", f"{reason}，开始整理本轮结果")
        self.activity("整理本轮结果")
        final = (f"{reason}。不能再检索、阅读或记录。现在只输出一个 reply：说明完成了什么、有证据支持的发现"
                 "（列出 evidence_ids）、还缺什么，以及用户可以怎样继续。")
        for _ in range(FINAL_CALLS):
            try:
                step = await self.model(self.transcript.messages(final), MainStep, "agent")
            except InvalidOutput as exc:
                self.transcript.retry = (exc.raw, str(exc))
                continue
            except (LimitReached, AgentFailure):
                break
            action = step.actions[0]
            if action.tool == "reply":
                known = {e.id for e in self.db.run_evidence(self.run.id)}
                return action.content, self.workspace.citations([i for i in action.evidence_ids if i in known])
            self.transcript.retry = (dumps(step.model_dump(mode="json", exclude_none=True)), "收尾阶段只能输出 reply")
        return self.fallback(reason), []

    def fallback(self, reason):
        counts = self.workspace.overview()["counts"]
        text = (f"{reason}，没能生成本轮总结。工作区现有候选论文 {counts['candidates']} 篇、已纳入 {counts['included']} 篇、"
                f"已记录证据 {counts['evidence']} 条")
        if self.work.report_id:
            text += "；本轮写的报告已保存，可以在研究资料中查看"
        return text + "。发送“继续”可以在这些资料的基础上接着做。"

    async def perform(self):
        try:
            content, citations = await self.loop()
        except AgentFailure as exc:
            self.close()
            detail = (exc.detail + "\n") if exc.detail else ""
            if self.work.report_id:
                detail += "本轮报告已保存，可以在「资料与报告 → 研究报告」查看；回复失败不影响已保存的报告。\n"
            counts = self.workspace.overview()["counts"]
            if counts["candidates"] or counts["included"] or counts["excluded"] or counts["evidence"]:
                detail += "已保存的论文、阅读记录和发现仍在，可以稍后发送“继续”。"
            else:
                detail += "工作区还没有保存任何资料，可以稍后重新发送这条消息。"
            self.store.finish(self.row, error=exc.code, diagnostic=detail)
        except asyncio.CancelledError:
            self.close()
            self.store.finish(self.row, error="process_interrupted", interrupted=True)
            raise
        except Exception as exc:
            self.close()
            self.store.finish(self.row, error="internal_error", diagnostic=f"程序错误（{type(exc).__name__}），本轮已停止；已保存的资料仍在。")
            raise
        else:
            self.close()
            self.store.finish(self.row, content=content, citations=citations)

    def close(self):
        self.work.activity = None
        self.save()


class Reader:
    """阅读子 agent：只处理一篇论文，看不到对话；用主 agent 给的说明阅读、记录，最后汇报。"""

    def __init__(self, turn, paper, instruction, context):
        self.turn, self.paper = turn, paper
        self.actor = "reader:" + paper.id
        workspace = turn.workspace
        opening = {"paper": workspace.describe(paper), "fulltext": workspace.fulltext_status(paper),
                   "context": context, "instruction": instruction, "step_limit": LIMITS["reader_steps"]}
        self.transcript = Transcript(prompts.READER, opening, keep=3, slack=2, cap=60000)
        self.found = []

    async def run(self):
        turn, invalid = self.turn, 0
        turn.event("reader", f"开始阅读「{short(self.paper.title, 60)}」", self.actor)
        for number in range(1, LIMITS["reader_steps"] + 1):
            try:
                step = await turn.model(self.transcript.messages(), ReaderStep, self.actor)
            except InvalidOutput as exc:
                invalid += 1
                turn.event("error", f"模型输出无效（连续第 {invalid} 次）：{short(str(exc), 200)}", self.actor)
                if invalid >= MAX_INVALID:
                    return self.result("failed", f"模型连续 {MAX_INVALID} 次输出不符合格式")
                self.transcript.retry = (exc.raw, str(exc))
                continue
            except AgentFailure as exc:
                if exc.code not in TRANSIENT:
                    raise
                return self.result("failed", f"模型调用重试后仍失败（{exc.code}）" + (f"：{exc.detail}" if exc.detail else ""))
            except LimitReached as exc:
                turn.limited = turn.limited or str(exc)
                return self.result("incomplete", str(exc))
            self.transcript.retry, invalid = None, 0
            if step.thought:
                turn.event("thought", step.thought, self.actor)
            actions = [a for a in step.actions if a.tool != "done"]
            results = await turn.execute(actions, self.actor, self.paper.id) if actions else []
            self.found += [item for r in results if r["tool"] == "note" and r["ok"] for item in r["data"]["saved"]]
            finished = step.actions[-1].tool == "done"
            if finished and all(r["ok"] for r in results):
                return self.result("done", step.actions[-1].summary)
            if turn.limited:
                return self.result("incomplete", turn.limited)
            left = LIMITS["reader_steps"] - number
            extra = {"steps_left": left}
            if finished:
                extra["notices"] = ["这一步有动作失败，done 没有生效；改正后再 done。"]
            elif left <= 2:
                extra["notices"] = ["步数即将用完：立即 note 尚未记录的发现，然后 done。"]
            self.transcript.add(step, results, extra)
        return self.result("incomplete", "达到子任务步数上限")

    def result(self, status, summary):
        analysis = self.turn.workspace.analyses().get(self.paper.id)
        self.turn.event("reader", f"「{short(self.paper.title, 40)}」{READER_STATUS[status]}：{short(summary, 120)}", self.actor)
        return {"paper_id": self.paper.id, "title": self.paper.title, "status": status, "summary": summary,
                "read": read_summary(analysis), "findings": self.found,
                "evidence": [i for item in self.found for i in item["evidence_ids"]]}


class AgentService:
    def __init__(self, db, llm=None, arxiv=None, pdf=None):
        self.db, self.llm = db, llm
        self.arxiv = arxiv if arxiv is not None else ArXivAdapter()
        self.pdf = pdf if pdf is not None else PDFAdapter()
        self.store = ConversationStore(db)

    async def process(self, row):
        if not self.store.claim(row):
            return
        if self.llm is None:
            self.store.finish(row, error="model_not_configured", diagnostic="请先在设置中配置并启用模型，再重新发送。")
            return
        try:
            turn = Turn(self, row)
        except Exception as exc:
            self.store.finish(row, error="internal_error", diagnostic=f"程序错误（{type(exc).__name__}），本轮未开始。")
            raise
        await turn.perform()

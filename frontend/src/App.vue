<template>
  <main class="container">
    <header class="header">
      <h1>Paper Scout</h1>
      <p class="subtitle">科研文献资料收集原型</p>
      <div class="status-badge" :class="{ ok: backendStatus === 'ok', err: backendStatus === 'error' }">
        后端服务：{{ statusMessage }}
      </div>
      <button class="secondary-btn" :disabled="backendStatus === 'loading'" @click="checkHealth">重新检测</button>
      <p class="notice">当前仅提供阶段性资料报告；论文事实提取、跨文献自主分析及语义充分性判断尚未实现，运行结束不代表自主分析已完成。</p>
    </header>

    <section class="task-form card">
      <h2>新建调研任务</h2>
      <div class="field">
        <label for="topic">研究课题 / 问题：</label>
        <textarea id="topic" v-model="topic" placeholder="例如：Multi-Agent Reinforcement Learning with Communication" rows="2"></textarea>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="startYear">起始年份（可留空）：</label>
          <input id="startYear" v-model="startYear" type="number" min="1" max="9999" step="1" placeholder="2022" />
        </div>
        <div class="field">
          <label for="endYear">截止年份（可留空）：</label>
          <input id="endYear" v-model="endYear" type="number" min="1" max="9999" step="1" placeholder="2026" />
        </div>
      </div>
      <div class="field">
        <label for="dimensions">关注维度（逗号分隔）：</label>
        <input id="dimensions" v-model="dimensions" type="text" placeholder="研究问题, 核心方法, 评估基准, 主要局限" />
      </div>
      <p v-if="submitError" class="error-message" role="alert">{{ submitError }}</p>
      <div class="actions">
        <button class="primary-btn" :disabled="!topic.trim() || isWorking || selectedHasActiveRun" @click="handleStartWorkflow">
          {{ isSubmitting ? '正在创建…' : '开始资料检索' }}
        </button>
        <span v-if="selectedHasActiveRun" class="muted">当前任务有未结束运行，请先继续或取消。</span>
      </div>
    </section>

    <section class="card">
      <div class="card-header">
        <h2>任务记录</h2>
        <button class="secondary-btn" :disabled="isWorking" @click="refreshHistory">刷新记录</button>
      </div>
      <p v-if="historyError" class="error-message" role="alert">{{ historyError }}</p>
      <p v-if="isLoadingTasks || isLoadingRuns" class="muted">正在读取记录…</p>
      <div v-if="tasks.length" class="field">
        <label for="historyTask">任务：</label>
        <select id="historyTask" v-model="selectedTaskId" :disabled="isWorking" @change="handleSelectTask">
          <option v-for="task in tasks" :key="task.id" :value="task.id">{{ task.topic }} · {{ formatTime(task.created_at) }}</option>
        </select>
      </div>
      <p v-else-if="historyLoaded" class="muted">暂无任务记录。</p>
      <div v-if="taskRuns.length" class="field">
        <label for="historyRun">运行（重新运行会保留旧记录）：</label>
        <select id="historyRun" v-model="selectedRunId" :disabled="isWorking" @change="handleSelectRun">
          <option v-for="run in taskRuns" :key="run.id" :value="run.id">{{ statusLabels[run.status] }} · {{ formatTime(run.created_at) }} · {{ run.id }}</option>
        </select>
      </div>
      <p v-else-if="selectedTaskId && runsLoaded" class="muted">此任务尚无运行。</p>
      <button v-if="selectedTaskId" class="secondary-btn" :disabled="isWorking || !runsLoaded || selectedHasActiveRun" @click="handleRerun">为此任务新建运行</button>
    </section>

    <section v-if="currentRun || selectedRunId" class="card status-card">
      <div class="card-header">
        <h2>执行过程</h2>
        <span v-if="currentRun" class="run-badge" :class="currentRun.status">{{ statusLabels[currentRun.status] }}</span>
      </div>
      <p v-if="pollError" class="error-message" role="alert">{{ pollError }} 自动刷新已停止；已显示的数据可能不是最新，请重新获取。</p>
      <p v-if="actionError" class="error-message" role="alert">{{ actionError }}</p>
      <button class="secondary-btn" :disabled="pollLoading || isWorking" @click="retryPolling">{{ pollLoading ? '正在获取…' : '重新获取状态与资料' }}</button>
      <template v-if="currentRun">
        <p class="muted">{{ currentRun.initial_topic }}</p>
        <div class="run-metrics">
          <div class="metric"><span class="label">运行 ID：</span><code>{{ currentRun.id }}</code></div>
          <div class="metric"><span class="label">当前阶段：</span><strong>{{ stageLabels[currentRun.stage] }}</strong></div>
          <div class="metric"><span class="label">执行轮次：</span><span>{{ currentRun.current_round }} / {{ currentRun.max_rounds }}</span></div>
          <div class="metric"><span class="label">累计调用：</span><span>{{ currentRun.total_calls }} / {{ currentRun.max_calls }} 次</span></div>
          <div class="metric"><span class="label">累计执行：</span><span>{{ currentRun.total_execution_seconds.toFixed(1) }} / {{ currentRun.max_seconds }} 秒</span></div>
        </div>
        <div class="stage-stepper">
          <div v-for="stage in stages" :key="stage.key" class="step-item" :class="{ active: currentRun.stage === stage.key, done: isStageDone(stage.key) }">
            <div class="step-circle">{{ stage.label }}</div>
          </div>
        </div>
        <div class="run-actions">
          <button v-if="canPause" class="secondary-btn" :disabled="isWorking" @click="handleRunAction('pause')">请求暂停</button>
          <button v-if="canContinue" class="primary-btn" :disabled="isWorking" @click="handleRunAction('resume')">继续同次运行</button>
          <button v-if="!isTerminal(currentRun.status)" class="secondary-btn" :disabled="isWorking" @click="handleRunAction('cancel')">取消运行</button>
        </div>
        <p v-if="currentRun.status === 'pause_requested'" class="notice">正在暂停：等待在途请求结束或超时后保存检查点，不会立即中止该请求。</p>
        <div v-if="canContinue" class="field">
          <label for="runMessage">补充信息：</label>
          <textarea id="runMessage" v-model="messageDraft" rows="2" placeholder="补充范围、关键词或需要调整的要求"></textarea>
          <button class="secondary-btn" :disabled="!messageDraft.trim() || isWorking" @click="handleRunAction('message')">保存补充</button>
          <p class="muted">继续前会保存尚未提交的补充。继续保留同一运行 ID 和累计计数，暂停等待时间不计入执行时间。</p>
        </div>
        <div v-if="currentRun.stop_reason" class="stop-reason"><strong>停止 / 等待说明：</strong>{{ currentRun.stop_reason }}</div>
        <div v-if="currentRun.gaps.length" class="notice">
          <strong>已记录缺口：</strong>
          <ul><li v-for="gap in currentRun.gaps" :key="gap">{{ gap }}</li></ul>
        </div>
      </template>
      <details v-if="messages.length">
        <summary>补充记录（{{ messages.length }} 条）</summary>
        <ul class="record-list">
          <li v-for="message in messages" :key="message.id">
            <span class="muted">{{ formatTime(message.created_at) }} · {{ message.status === 'pending' ? '待处理' : '已处理' }}</span>
            <p>{{ message.content }}</p>
            <p v-if="message.impact_summary" class="muted">处理说明：{{ message.impact_summary }}</p>
          </li>
        </ul>
      </details>
      <details v-if="events.length">
        <summary>过程记录（{{ events.length }} 条）</summary>
        <ul class="record-list"><li v-for="event in events" :key="event.id"><span class="muted">{{ formatTime(event.created_at) }} · {{ stageLabels[event.stage] }}</span><p>{{ event.message }}</p></li></ul>
      </details>
    </section>

    <section v-if="currentRun && papersLoaded" class="card">
      <h2>检索文献（{{ papers.length }} 篇）</h2>
      <p class="muted">下列为论文元数据与可得摘要，不代表已经阅读全文或完成事实分析。</p>
      <p v-if="!papers.length" class="muted">本次成功读取的结果中暂无论文。</p>
      <ul class="paper-list">
        <li v-for="paper in papers" :key="paper.id" class="paper-item">
          <div class="paper-title"><a :href="paper.url" target="_blank" rel="noopener noreferrer">{{ paper.title }}</a><span v-if="paper.year" class="paper-year">（{{ paper.year }}）</span></div>
          <div class="paper-meta">作者：{{ paper.authors.join(', ') || '未知' }}</div>
          <p v-if="paper.abstract" class="paper-abstract">{{ paper.abstract }}</p>
          <p v-else class="muted">摘要缺失。</p>
        </li>
      </ul>
    </section>

    <section v-if="currentRun" class="card report-card">
      <div class="card-header">
        <h2>阶段性资料报告（Markdown）</h2>
        <button v-if="report" class="secondary-btn" :disabled="isDownloading || isWorking" @click="handleDownload">{{ isDownloading ? '正在下载…' : '下载 Markdown' }}</button>
      </div>
      <p class="notice">报告用于核查已收集资料，不是自主分析已完成的证明。事实与语义充分性仍需人工复核。</p>
      <p v-if="downloadError" class="error-message" role="alert">{{ downloadError }}</p>
      <template v-if="report">
        <div v-if="report.gaps.length" class="notice"><strong>报告缺口：</strong><ul><li v-for="gap in report.gaps" :key="gap">{{ gap }}</li></ul></div>
        <p v-if="report.stop_reason" class="muted">报告停止原因：{{ report.stop_reason }}</p>
        <pre class="markdown-preview">{{ report.content_markdown }}</pre>
      </template>
      <p v-else class="muted">{{ reportNotice }}</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from "vue";
import {
  ApiError, fetchHealth, getTasks, getTaskRuns, createTask, startRun, getRun,
  pauseRun, resumeRun, cancelRun, addRunMessage, getRunMessages, getRunEvents,
  getPapers, getReport, getMarkdownReport,
  type Task, type Run, type RunStatus, type RunStage, type RunMessage, type RunEvent, type Paper, type Report,
} from "./api/client.ts";

const topic = ref("Multi-Agent Reinforcement Learning with Communication");
const startYear = ref<string | number>("2022");
const endYear = ref<string | number>("2026");
const dimensions = ref("核心方法, 评估指标, 关键局限");
const backendStatus = ref<"loading" | "ok" | "error">("loading");
const statusMessage = ref("检测中…");
const tasks = ref<Task[]>([]);
const taskRuns = ref<Run[]>([]);
const selectedTaskId = ref("");
const selectedRunId = ref("");
const currentRun = ref<Run | null>(null);
const papers = ref<Paper[]>([]);
const messages = ref<RunMessage[]>([]);
const events = ref<RunEvent[]>([]);
const report = ref<Report | null>(null);
const messageDraft = ref("");
const reportNotice = ref("尚未获取报告。");
const submitError = ref("");
const historyError = ref("");
const pollError = ref("");
const actionError = ref("");
const downloadError = ref("");
const isSubmitting = ref(false);
const controlBusy = ref(false);
const isDownloading = ref(false);
const isLoadingTasks = ref(false);
const isLoadingRuns = ref(false);
const historyLoaded = ref(false);
const runsLoaded = ref(false);
const papersLoaded = ref(false);
const pollLoading = ref(false);

const statusLabels: Record<RunStatus, string> = {
  queued: "排队中", running: "执行中", pause_requested: "正在暂停", paused: "已暂停",
  needs_input: "等待补充", completed: "运行结束（请核查报告）", partial: "阶段性结果",
  failed: "执行失败", cancelled: "已取消", interrupted: "进程中断",
};
const stageLabels: Record<RunStage, string> = {
  understanding: "任务理解", planning: "检索规划", searching: "文献检索", extracting: "文本读取",
  assessing: "资料缺口检查", synthesizing: "资料整理", reporting: "资料报告生成",
};
const stages = (Object.keys(stageLabels) as RunStage[]).map((key) => ({ key, label: stageLabels[key] }));
const terminalStatuses = new Set<RunStatus>(["completed", "partial", "failed", "cancelled", "interrupted"]);
const pollingStatuses = new Set<RunStatus>(["queued", "running", "pause_requested"]);
const isTerminal = (status: RunStatus) => terminalStatuses.has(status);
const isWorking = computed(() => isSubmitting.value || controlBusy.value || isLoadingTasks.value || isLoadingRuns.value);
const selectedHasActiveRun = computed(() => taskRuns.value.some((run) => !isTerminal(run.status)));
const canPause = computed(() => currentRun.value && ["queued", "running"].includes(currentRun.value.status));
const canContinue = computed(() => currentRun.value && ["paused", "needs_input"].includes(currentRun.value.status));

let disposed = false;
let viewVersion = 0;
let pollVersion = 0;
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let pollController: AbortController | null = null;
let viewController = new AbortController();
const pageController = new AbortController();
const isCurrentView = (version: number) => !disposed && version === viewVersion;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "未知错误，请查看服务端记录";
const formatTime = (value: string) => new Date(value).toLocaleString();

function updateRun(run: Run) {
  currentRun.value = run;
  const index = taskRuns.value.findIndex((item) => item.id === run.id);
  if (index >= 0) taskRuns.value[index] = run;
  else taskRuns.value.unshift(run);
}

function stopPolling() {
  pollVersion++;
  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = null;
  pollController?.abort();
  pollController = null;
  pollLoading.value = false;
}

function beginView() {
  stopPolling();
  viewController.abort();
  viewController = new AbortController();
  viewVersion++;
  currentRun.value = null;
  papers.value = [];
  messages.value = [];
  events.value = [];
  report.value = null;
  papersLoaded.value = false;
  isDownloading.value = false;
  messageDraft.value = "";
  pollError.value = actionError.value = downloadError.value = "";
  reportNotice.value = "尚未获取报告。";
  return viewVersion;
}

function isStageDone(key: RunStage) {
  return currentRun.value ? stages.findIndex((item) => item.key === currentRun.value!.stage) > stages.findIndex((item) => item.key === key) : false;
}

async function checkHealth() {
  backendStatus.value = "loading";
  try {
    const data = await fetchHealth(pageController.signal);
    if (disposed) return;
    backendStatus.value = "ok";
    statusMessage.value = `正常（${data.app} v${data.version}）`;
  } catch (error) {
    if (disposed) return;
    backendStatus.value = "error";
    statusMessage.value = errorMessage(error);
  }
}

async function refreshHistory() {
  isLoadingTasks.value = true;
  historyError.value = "";
  try {
    const data = await getTasks(pageController.signal);
    if (disposed) return;
    tasks.value = data;
    historyLoaded.value = true;
    if (!selectedTaskId.value && data.length) selectedTaskId.value = data[0].id;
    if (selectedTaskId.value) await handleSelectTask();
  } catch (error) {
    if (!disposed) historyError.value = `读取任务记录失败：${errorMessage(error)}`;
  } finally {
    if (!disposed) isLoadingTasks.value = false;
  }
}

async function handleSelectTask() {
  const taskId = selectedTaskId.value;
  const version = beginView();
  selectedRunId.value = "";
  taskRuns.value = [];
  runsLoaded.value = false;
  historyError.value = "";
  isLoadingRuns.value = true;
  try {
    const data = await getTaskRuns(taskId, viewController.signal);
    if (!isCurrentView(version)) return;
    taskRuns.value = data;
    runsLoaded.value = true;
    isLoadingRuns.value = false;
    if (data.length) {
      selectedRunId.value = data[0].id;
      handleSelectRun();
    }
  } catch (error) {
    if (isCurrentView(version)) historyError.value = `读取运行记录失败：${errorMessage(error)}`;
  } finally {
    if (isCurrentView(version)) isLoadingRuns.value = false;
  }
}

function handleSelectRun() {
  beginView();
  const run = taskRuns.value.find((item) => item.id === selectedRunId.value);
  if (run) currentRun.value = run;
  if (selectedRunId.value) startPolling(selectedRunId.value);
}

function parseYear(value: string | number, label: string): number | null {
  if (String(value).trim() === "") return null;
  const year = Number(value);
  if (!Number.isInteger(year) || year < 1 || year > 9999) throw new Error(`${label}须为 1 至 9999 的整数或留空。`);
  return year;
}

async function handleStartWorkflow() {
  if (!topic.value.trim() || isWorking.value || selectedHasActiveRun.value) return;
  submitError.value = "";
  let payload;
  try {
    const firstYear = parseYear(startYear.value, "起始年份");
    const lastYear = parseYear(endYear.value, "截止年份");
    if (firstYear !== null && lastYear !== null && firstYear > lastYear) throw new Error("起始年份不能大于截止年份。");
    payload = { topic: topic.value.trim(), start_year: firstYear, end_year: lastYear, focus_dimensions: dimensions.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) };
  } catch (error) {
    submitError.value = errorMessage(error);
    return;
  }
  isSubmitting.value = true;
  const version = beginView();
  try {
    const task = await createTask(payload, viewController.signal);
    if (!isCurrentView(version)) return;
    tasks.value.unshift(task);
    selectedTaskId.value = task.id;
    selectedRunId.value = "";
    taskRuns.value = [];
    runsLoaded.value = true;
    const run = await startRun(task.id, viewController.signal);
    if (!isCurrentView(version)) return;
    selectedRunId.value = run.id;
    updateRun(run);
    startPolling(run.id);
  } catch (error) {
    if (isCurrentView(version)) submitError.value = `创建 / 启动失败：${errorMessage(error)}。已创建的任务可从记录中重新运行。`;
  } finally {
    if (isCurrentView(version)) isSubmitting.value = false;
  }
}

async function handleRerun() {
  if (!selectedTaskId.value || isWorking.value || !runsLoaded.value || selectedHasActiveRun.value) return;
  isSubmitting.value = true;
  submitError.value = "";
  const version = beginView();
  try {
    const run = await startRun(selectedTaskId.value, viewController.signal);
    if (!isCurrentView(version)) return;
    selectedRunId.value = run.id;
    updateRun(run);
    startPolling(run.id);
  } catch (error) {
    if (isCurrentView(version)) submitError.value = `新建运行失败：${errorMessage(error)}`;
  } finally {
    if (isCurrentView(version)) isSubmitting.value = false;
  }
}

function startPolling(runId: string) {
  stopPolling();
  const version = viewVersion;
  const cycleVersion = pollVersion;
  void pollRun(runId, version, cycleVersion);
}

async function pollRun(runId: string, version: number, cycleVersion: number) {
  const controller = new AbortController();
  pollController = controller;
  pollLoading.value = true;
  const active = () => isCurrentView(version) && cycleVersion === pollVersion && !controller.signal.aborted && selectedRunId.value === runId;
  let shouldContinue = false;
  try {
    const run = await getRun(runId, controller.signal);
    if (!active()) return;
    updateRun(run);
    const stopped = !pollingStatuses.has(run.status);
    const [paperResult, messageResult, eventResult, reportResult] = await Promise.allSettled([
      getPapers(runId, controller.signal), getRunMessages(runId, controller.signal), getRunEvents(runId, controller.signal),
      stopped ? getReport(runId, controller.signal) : Promise.resolve(null),
    ]);
    if (!active()) return;
    const errors: string[] = [];
    if (paperResult.status === "fulfilled") { papers.value = paperResult.value; papersLoaded.value = true; }
    else errors.push(`读取论文失败：${errorMessage(paperResult.reason)}`);
    if (messageResult.status === "fulfilled") messages.value = messageResult.value;
    else errors.push(`读取补充记录失败：${errorMessage(messageResult.reason)}`);
    if (eventResult.status === "fulfilled") events.value = eventResult.value;
    else errors.push(`读取过程记录失败：${errorMessage(eventResult.reason)}`);
    if (reportResult.status === "fulfilled") {
      report.value = reportResult.value;
      reportNotice.value = stopped ? "本次运行没有报告。" : "运行尚未生成阶段性资料报告。";
    } else if (reportResult.reason instanceof ApiError && reportResult.reason.status === 409) {
      report.value = null;
      reportNotice.value = `本次运行尚无报告（${statusLabels[run.status]}）。`;
    } else {
      reportNotice.value = "报告获取失败，请重新获取状态与资料。";
      errors.push(`读取报告失败：${errorMessage(reportResult.reason)}`);
    }
    pollError.value = errors.join("；");
    shouldContinue = !stopped && errors.length === 0;
  } catch (error) {
    if (active()) pollError.value = `刷新运行失败：${errorMessage(error)}`;
  } finally {
    if (active()) {
      pollController = null;
      pollLoading.value = false;
      // 本轮所有请求结束后才启动下一轮；任何失败都停下等待用户重试。
      if (shouldContinue) pollTimer = setTimeout(() => { pollTimer = null; void pollRun(runId, version, cycleVersion); }, 1500);
    }
  }
}

function retryPolling() {
  if (selectedRunId.value && !isWorking.value) startPolling(selectedRunId.value);
}

async function handleRunAction(action: "pause" | "resume" | "cancel" | "message") {
  if (!currentRun.value || isWorking.value) return;
  const runId = currentRun.value.id;
  const version = viewVersion;
  stopPolling();
  controlBusy.value = true;
  actionError.value = "";
  try {
    if ((action === "message" || action === "resume") && messageDraft.value.trim()) {
      const message = await addRunMessage(runId, messageDraft.value.trim(), viewController.signal);
      if (!isCurrentView(version)) return;
      messages.value.push(message);
      messageDraft.value = "";
    }
    if (action !== "message") {
      const run = await ({ pause: pauseRun, resume: resumeRun, cancel: cancelRun }[action])(runId, viewController.signal);
      if (!isCurrentView(version)) return;
      updateRun(run);
    }
  } catch (error) {
    if (isCurrentView(version)) actionError.value = `操作失败：${errorMessage(error)}`;
  } finally {
    if (isCurrentView(version)) {
      controlBusy.value = false;
      startPolling(runId);
    }
  }
}

async function handleDownload() {
  if (!currentRun.value || isDownloading.value) return;
  const runId = currentRun.value.id;
  const version = viewVersion;
  isDownloading.value = true;
  downloadError.value = "";
  try {
    const blob = await getMarkdownReport(runId, viewController.signal);
    if (!isCurrentView(version)) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `阶段性资料报告-${runId}.md`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    if (isCurrentView(version)) downloadError.value = `下载失败：${errorMessage(error)}`;
  } finally {
    if (isCurrentView(version)) isDownloading.value = false;
  }
}

onMounted(() => { void checkHealth(); void refreshHistory(); });
onUnmounted(() => {
  disposed = true;
  stopPolling();
  viewController.abort();
  pageController.abort();
});
</script>

<style scoped>
.container { max-width: 860px; margin: 0 auto; padding: 2rem 1rem; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1f2937; }
.header { margin-bottom: 1.5rem; border-bottom: 1px solid #e5e7eb; padding-bottom: 1rem; }
.header h1 { margin: 0; font-size: 1.8rem; color: #111827; }
.subtitle, .muted { color: #6b7280; font-size: 0.9rem; }
.subtitle { margin: 0.25rem 0 0.75rem; }
.status-badge { display: inline-block; padding: 0.25rem 0.75rem; margin-right: 0.5rem; border-radius: 9999px; font-size: 0.85rem; background-color: #f3f4f6; color: #4b5563; }
.status-badge.ok { background-color: #def7ec; color: #03543f; }
.status-badge.err, .error-message { background-color: #fde8e8; color: #9b1c1c; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); }
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
.card h2 { margin: 0 0 1rem; font-size: 1.25rem; }
.card-header h2 { margin: 0; }
.field { margin-bottom: 1rem; }
.field-row { display: flex; gap: 1rem; }
.field-row .field { flex: 1; min-width: 0; }
label { display: block; font-size: 0.9rem; font-weight: 500; margin-bottom: 0.35rem; color: #374151; }
input, textarea, select { width: 100%; box-sizing: border-box; padding: 0.5rem 0.75rem; border: 1px solid #d1d5db; border-radius: 6px; font-size: 0.95rem; }
input:focus, textarea:focus, select:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1); }
.actions, .run-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 0.75rem; margin: 1rem 0; }
.primary-btn { background-color: #2563eb; color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; font-size: 0.95rem; cursor: pointer; }
.secondary-btn { background-color: #f3f4f6; border: 1px solid #d1d5db; color: #374151; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: 0.55; cursor: not-allowed; }
.run-badge { padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; font-weight: bold; background: #f3f4f6; }
.run-badge.running, .run-badge.queued { background-color: #dbeafe; color: #1e40af; }
.run-badge.completed { background-color: #def7ec; color: #03543f; }
.run-badge.paused, .run-badge.pause_requested, .run-badge.needs_input, .run-badge.partial { background-color: #fef3c7; color: #92400e; }
.run-badge.failed, .run-badge.interrupted { background-color: #fde8e8; color: #9b1c1c; }
.run-metrics { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.25rem; background: #f9fafb; padding: 0.75rem 1rem; border-radius: 6px; }
.metric .label { color: #6b7280; font-size: 0.85rem; margin-right: 0.35rem; }
.metric code { overflow-wrap: anywhere; }
.stage-stepper { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 1.25rem 0; }
.step-item { flex: 1; text-align: center; }
.step-circle { display: inline-block; padding: 0.35rem 0.6rem; background: #f3f4f6; border-radius: 9999px; font-size: 0.85rem; color: #6b7280; white-space: nowrap; }
.step-item.active .step-circle { background: #2563eb; color: white; font-weight: 600; }
.step-item.done .step-circle { background: #def7ec; color: #03543f; }
.stop-reason, .notice, .error-message { margin-top: 1rem; padding: 0.75rem; border-radius: 4px; font-size: 0.9rem; line-height: 1.5; overflow-wrap: anywhere; }
.stop-reason { background: #f9fafb; border-left: 4px solid #9ca3af; }
.notice { background: #fffbeb; color: #92400e; }
.paper-list { list-style: none; padding: 0; margin: 0; }
.paper-item { padding: 1rem 0; border-bottom: 1px solid #f3f4f6; }
.paper-title a { color: #1d4ed8; font-weight: 600; text-decoration: none; }
.paper-title a:hover { text-decoration: underline; }
.paper-year { margin-left: 0.5rem; color: #6b7280; font-size: 0.9rem; }
.paper-meta { color: #6b7280; font-size: 0.85rem; margin: 0.25rem 0 0.5rem; }
.paper-abstract { font-size: 0.9rem; color: #4b5563; margin: 0; line-height: 1.4; }
details { margin-top: 1rem; }
summary { cursor: pointer; }
.record-list { padding-left: 1.25rem; }
.record-list p { margin: 0.35rem 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.markdown-preview { background: #f8fafc; padding: 1.25rem; border-radius: 6px; font-family: monospace; white-space: pre-wrap; word-break: break-word; font-size: 0.9rem; line-height: 1.5; border: 1px solid #e2e8f0; }
</style>

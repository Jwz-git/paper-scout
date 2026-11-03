<template>
  <main class="workspace" :class="{ 'panel-visible': panelOpen }">
    <button v-if="sidebarOpen" class="mobile-scrim" aria-label="关闭对话列表" @click="sidebarOpen = false"></button>
    <aside class="sidebar" :class="{ 'mobile-open': sidebarOpen }" aria-label="对话历史">
      <a class="brand" href="#" @click.prevent="newConversation"><span class="brand-mark">P↗</span><span>Paper Scout<small>LOCAL RESEARCH WORKSPACE</small></span></a>
      <button class="new-chat" aria-label="新建对话" @click="newConversation"><span>＋</span> 新建对话</button>
      <div class="sidebar-heading"><span>对话记录</span><button class="icon-button" aria-label="刷新对话记录" :disabled="historyLoading" @click="refreshHistory">↻</button></div>
      <p v-if="historyError" class="error-message" role="alert">{{ historyError }}</p><p v-if="historyLoading" class="muted" role="status">正在读取记录…</p>
      <nav class="history-list"><button v-for="task in tasks" :key="task.id" class="history-item" :class="{ selected: selectedKey === task.id }" @click="selectConversation(task.id)"><span class="history-title">{{ task.topic }}</span><small>{{ shortDate(task.updated_at) }}<span v-if="drafts[task.id]"> · 草稿</span><span v-if="pending[task.id]"> · 发送待确认</span></small></button></nav>
      <p v-if="historyLoaded && !tasks.length" class="muted">你的研究对话会保存在这里。</p><div class="sidebar-footer"><i></i><span>本地单用户工作区<small>资料保留在当前服务</small></span></div>
    </aside>
    <section class="chat-shell" aria-label="研究对话">
      <header class="chat-header"><div class="header-title"><button class="icon-button menu-toggle" aria-label="打开对话列表" @click="sidebarOpen = true">☰</button><div><span class="eyebrow">RESEARCH CHAT</span><h1>{{ conversation?.task.topic || (selectedKey === NEW_CHAT ? '新对话' : '读取对话') }}</h1></div></div><button class="artifact-toggle" aria-label="查看资料与报告" :disabled="!conversation?.runs.length" @click="togglePanel">▤ 资料与报告 <small v-if="conversation?.runs.length">{{ conversation.runs.length }}</small></button></header>
      <div ref="timelineElement" class="timeline-scroll" @scroll="trackScroll"><div class="timeline-content">
        <section v-if="selectedKey === NEW_CHAT" class="empty-state"><div class="empty-symbol">↗</div><p class="eyebrow">从一个问题开始</p><h2>把研究问题，<br />交给这段对话。</h2><p class="empty-description">一起检索文献、核查来源，逐步明确你的研究方向。<br />直接说出想研究什么，也可以先聊聊问题。</p><div class="example-prompts" aria-label="研究问题示例"><button v-for="example in examples" :key="example.title" @click="useExample(example.text)"><span>{{ example.icon }}</span><div><strong>{{ example.title }}</strong><small>{{ example.text }}</small></div><span>↗</span></button></div><p class="empty-note">没有预设任务。示例只填入草稿，发送后才会开始。</p></section>
        <p v-if="conversationLoading" class="muted" role="status">正在读取对话…</p><div v-if="conversationError" class="error-message" role="alert">{{ conversationError }} 已有记录保留，可能不是最新。<button class="text-button" :disabled="currentPending?.busy" @click="retryConversation">重新读取对话</button></div>
        <template v-if="conversation">
          <section v-if="legacyRuns.length || !conversation.messages.length" class="legacy-input"><span class="eyebrow">历史任务输入 · 原始记录</span><p>{{ conversation.task.topic }}</p><small v-if="conversation.task.start_year || conversation.task.end_year">年份范围：{{ conversation.task.start_year ?? '不限' }} — {{ conversation.task.end_year ?? '不限' }}</small><small v-if="conversation.task.focus_dimensions.length">关注：{{ conversation.task.focus_dimensions.join('、') }}</small></section>
          <template v-for="entry in timeline" :key="entry.id">
            <section v-if="entry.kind === 'run'" class="legacy-run"><div><strong>▤ 既有调研记录</strong><time>{{ formatTime(entry.run.created_at) }}</time></div><p>{{ entry.run.initial_topic }} · {{ runLabels[entry.run.status] }}</p><p v-if="entry.run.stop_reason" class="muted">{{ entry.run.stop_reason }}</p><button class="text-button" @click="openRun(entry.run.id)">查看这次运行的资料与报告 →</button></section>
            <article v-else class="message" :class="[entry.message.role, entry.message.status]" :aria-label="entry.message.role === 'user' ? '用户消息' : '助手消息'"><div class="message-avatar">{{ entry.message.role === 'user' ? '你' : '↗' }}</div><div class="message-body"><div class="message-heading"><strong>{{ entry.message.role === 'user' ? '你' : 'Paper Scout' }}</strong><time>{{ formatTime(entry.message.created_at) }}</time><span v-if="entry.message.role === 'assistant' || entry.message.status !== 'completed'" class="message-status" :class="entry.message.status">{{ messageLabels[entry.message.status] }}</span></div><p v-if="entry.message.content" class="message-text">{{ entry.message.content }}</p><p v-else class="muted">{{ messageLabels[entry.message.status] }}{{ entry.message.status === 'processing' ? '，完成后显示实际回复。' : '' }}</p><p v-if="entry.message.error_category" class="error-message" role="alert">错误类别：{{ entry.message.error_category }}</p><div v-if="entry.message.citations.length" class="citation-buttons" aria-label="回答引用"><button v-for="(citation, index) in entry.message.citations" :key="`${citation.source_text_id}-${index}`" :aria-label="`引用 ${index + 1}`" :title="citation.quote" @click="openCitation(citation)"><span>{{ index + 1 }}</span>{{ sourceLabels[citation.source_type] }}{{ citation.page_number != null ? ` · p${citation.page_number}` : '' }} ↗</button></div><button v-if="entry.message.run_id" class="message-artifact text-button" @click="openRun(entry.message.run_id!)">▤ 查看相关调研资料</button></div></article>
          </template>
          <p v-if="!conversation.messages.length && !conversation.runs.length" class="muted">这条记录还没有对话或调研。可以在下方直接继续。</p>
          <details v-if="latestRun" class="process-records" :open="processOpen" @toggle="onProcessToggle"><summary><span>过程记录</span><span class="muted">{{ processOpen ? '收起' : '按需查看实际执行记录' }} · {{ latestRun.current_round }}/{{ latestRun.max_rounds }} 轮</span></summary><div class="process-content"><p class="muted">这是后端执行记录，不是模型的思维过程。{{ runLabels[latestRun.status] }} · {{ stageLabels[latestRun.stage] }}</p><p v-if="processLoading" class="muted">正在读取过程记录…</p><p v-if="processError" class="error-message" role="alert">{{ processError }} <button class="text-button" @click="loadProcess">重试</button></p><ol v-if="processEvents.length" class="event-list"><li v-for="event in processEvents" :key="event.id"><time>{{ formatTime(event.created_at) }}</time><span>{{ stageLabels[event.stage] }} · {{ event.category }}</span><p>{{ event.message }}</p></li></ol><p v-else-if="!processLoading && !processError" class="muted">暂无已保存的执行记录。</p><ul v-if="latestRun.gaps.length" class="gap-list"><li v-for="gap in latestRun.gaps" :key="gap">{{ gap }}</li></ul></div></details>
        </template>
      </div></div><button v-if="!nearBottom && conversation" class="jump-bottom" @click="scrollToBottom">↓ 回到最新消息</button>
      <footer class="composer-dock">
        <div v-if="conversation" class="execution-strip" aria-label="执行状态与用量"><div class="execution-description"><i :class="{ running: isResearchRunning }"></i><strong>{{ conversation.busy ? '对话处理中' : latestRun ? runLabels[latestRun.status] : '可以继续对话' }}</strong><span v-if="latestRun && isResearchRunning">{{ stageLabels[latestRun.stage] }}</span><span>{{ conversation.usage.model_calls }} 次模型调用 · {{ Math.round(conversation.usage.total_execution_seconds) }} 秒</span></div><div class="execution-actions"><details class="usage-details"><summary>用量</summary><div><p>会话累计模型调用：{{ conversation.usage.model_calls }}</p><p>会话累计执行：{{ conversation.usage.total_execution_seconds.toFixed(1) }} 秒</p><p>Token：{{ tokenText(conversation.usage.token_usage.total_tokens) }}</p><p>输入 / 输出：{{ tokenText(conversation.usage.token_usage.prompt_tokens) }} / {{ tokenText(conversation.usage.token_usage.completion_tokens) }}</p><template v-if="latestRun"><p>当前运行外部调用：{{ latestRun.total_calls }} / {{ latestRun.max_calls }}</p><p>当前运行执行上限：{{ latestRun.max_seconds }} 秒</p><p>当前轮次：{{ latestRun.current_round }} / {{ latestRun.max_rounds }}</p></template><p>未知 token 不记为零；暂停等待不计执行时间。</p></div></details><button v-if="canPause" :disabled="controlsDisabled" @click="sendControl('pause')">暂停</button><button v-if="canResume" :disabled="controlsDisabled" @click="sendControl('resume')">继续</button><button v-if="activeRun || conversation.busy" :disabled="!!currentPending || stopBusy" @click="stopWork">{{ stopBusy ? '正在停止…' : '停止' }}</button></div></div><p v-if="latestRun?.stop_reason && !isResearchRunning" class="stop-note">{{ latestRun.stop_reason }}</p>
        <div v-if="currentPending" class="pending-notice" role="status"><div><strong>{{ currentPending.busy ? '正在发送…' : '发送未确认' }}</strong><p>{{ currentPending.error || '消息确认前保留草稿，不会重复提交。' }}</p><blockquote v-if="!currentPending.busy">{{ currentPending.content }}</blockquote></div><button v-if="!currentPending.busy" class="text-button" aria-label="重试发送" @click="retrySend">重试原消息</button></div><p v-if="sendErrors[selectedKey]" class="error-message" role="alert">{{ sendErrors[selectedKey] }}</p>
        <form class="composer" @submit.prevent="sendDraft"><label class="sr-only" for="chat-input">输入消息</label><textarea id="chat-input" ref="inputElement" v-model="draft" :maxlength="inputLimit" rows="3" placeholder="提出问题、补充方向，或追问已有资料…" aria-label="输入消息" @keydown="handleInputKey"></textarea><div class="composer-bottom"><div class="composer-options"><details ref="intentMenu" class="intent-menu"><summary aria-label="选择消息意图">{{ modeLabels[currentMode] }} ⌄</summary><div class="intent-options"><button v-for="mode in intentModes" :key="mode" type="button" :class="{ selected: currentMode === mode }" @click="chooseMode(mode)"><span>{{ modeLabels[mode] }}</span><small>{{ modeDescriptions[mode] }}</small></button></div></details><span class="input-hint">{{ conversation?.busy ? '等待当前回复完成再发送' : isResearchRunning ? '可直接补充，系统会保存检查点' : 'Enter 发送 · Shift + Enter 换行' }}</span></div><div class="send-group"><span v-if="draft.length" class="char-count">{{ draft.length }}/{{ inputLimit }}</span><button type="submit" class="send-button" aria-label="发送消息" :disabled="!canSend">↑</button></div></div></form><div class="composer-footnote"><span>来源可追溯，结论仍需核查。Markdown 回复以安全纯文本展示。</span><span class="model-status">{{ modelConfigured === true ? '● 模型已配置' : modelConfigured === false ? '● 未配置模型 · 能力受限' : healthError ? '连接状态未知' : '本地工作区' }}</span></div>
      </footer>
    </section>
    <aside v-if="panelOpen" class="artifact-panel" aria-label="资料与报告面板"><header class="panel-header"><div><span class="eyebrow">RESEARCH MATERIALS</span><h2>资料与报告</h2></div><button class="icon-button" aria-label="关闭资料面板" @click="closePanel">×</button></header><div class="panel-content"><details ref="runMenu" class="run-picker"><summary>{{ selectedRun ? `调研 ${runNumber(selectedRun.id)} · ${runLabels[selectedRun.status]}` : '选择一次调研' }} ⌄</summary><div><button v-for="run in sortedRuns" :key="run.id" :class="{ selected: selectedRunId === run.id }" @click="chooseRun(run.id)"><strong>调研 {{ runNumber(run.id) }} · {{ runLabels[run.status] }}</strong><small>{{ formatTime(run.created_at) }} · {{ run.initial_topic }}</small></button></div></details><p v-if="selectedRun" class="panel-note">{{ selectedRun.initial_input?.topic || selectedRun.initial_topic }}</p><div class="panel-tabs" aria-label="资料类型"><button :class="{ active: panelTab === 'papers' }" @click="panelTab = 'papers'">文献 <span v-if="artifact?.loaded">{{ artifact.papers.length }}</span></button><button :class="{ active: panelTab === 'report' }" @click="panelTab = 'report'; clearPaper()">Markdown 报告</button></div><div v-if="artifactError" class="error-message" role="alert">{{ artifactError }}<button class="text-button" @click="loadArtifacts">重新获取资料</button></div><p v-if="artifactLoading" class="muted" role="status">正在读取本次资料…</p>
      <template v-if="panelTab === 'papers'"><template v-if="paperSelection"><p v-if="paperLoading" class="muted">正在读取论文与来源快照…</p><div v-if="paperError" class="error-message" role="alert">{{ paperError }}<button class="text-button" @click="loadPaper">重试论文详情</button><button class="text-button" @click="clearPaper">返回列表</button></div><PaperDetailView v-if="paperDetail" :detail="paperDetail" :run-id="paperSelection.runId" :citation="selectedCitation" @back="clearPaper" @citation="selectedCitation = $event" /></template><template v-else><p class="panel-note">本次检索保存的论文。元数据、摘要与实际全文读取范围在详情中分开标记。</p><button v-for="(paper, index) in artifact?.papers || []" :key="paper.id" class="paper-card" @click="openPaper(paper.id)"><span class="paper-index">{{ String(index + 1).padStart(2, '0') }}</span><div><span class="paper-title">{{ paper.title }}</span><small>{{ paper.year ?? '年份缺失' }} · {{ paper.authors.slice(0, 2).join('、') || '作者缺失' }}{{ paper.authors.length > 2 ? ' 等' : '' }}</small><span class="paper-link">查看来源与读取状态 ↗</span></div></button><p v-if="artifact?.loaded && !artifact.papers.length" class="muted">本次成功读取的检索结果中暂无已选论文。</p></template></template>
      <template v-else><template v-if="artifact?.report"><div class="report-heading"><span>{{ artifact.report.title }}</span><button :disabled="downloadBusy" class="download-button" @click="downloadReport">{{ downloadBusy ? '下载中…' : '下载 .md ↓' }}</button></div><p v-if="downloadError" class="error-message" role="alert">{{ downloadError }}</p><p class="panel-note">Markdown 原文预览，未渲染 HTML。阶段性报告不代表自主分析已经完成。</p><ul v-if="artifact.report.gaps.length" class="gap-list"><li v-for="gap in artifact.report.gaps" :key="gap">{{ gap }}</li></ul><p v-if="artifact.report.stop_reason" class="muted">停止说明：{{ artifact.report.stop_reason }}</p><pre class="markdown-preview">{{ artifact.report.content_markdown }}</pre></template><p v-else-if="artifact?.loaded" class="muted">{{ artifact.reportNotice }}</p></template>
    </div></aside>
  </main>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue';
import PaperDetailView from './components/PaperDetail.vue';
import { ApiError, fetchHealth, getConversations, getConversation, sendConversationMessage, stopConversation, getPapers, getRunEvents, getReport, getPaperDetail, getMarkdownReport, type Task, type ConversationView, type ChatMode, type ChatMessage, type ChatCitation, type Run, type RunStatus, type RunStage, type ChatStatus, type SourceType, type Paper, type Report, type RunEvent, type PaperDetail } from './api/client.ts';

const NEW_CHAT = '__new__';
const selectedKey = ref(NEW_CHAT);
const tasks = ref<Task[]>([]);
const views = reactive<Record<string, ConversationView>>({});
const drafts = reactive<Record<string, string>>({ [NEW_CHAT]: '' });
const modes = reactive<Record<string, ChatMode>>({});
interface PendingSend { request_id: string; content: string; mode: ChatMode; snapshot: string; fromDraft: boolean; busy: boolean; error: string; }
const pending = reactive<Record<string, PendingSend | undefined>>({});
const sendErrors = reactive<Record<string, string>>({});
const selectedRuns = reactive<Record<string, string>>({});
const conversation = computed(() => views[selectedKey.value]);
const draft = computed({ get: () => drafts[selectedKey.value] || '', set: value => { drafts[selectedKey.value] = value; } });
const currentMode = computed(() => modes[selectedKey.value] || 'auto');
const currentPending = computed(() => pending[selectedKey.value]);
const inputLimit = computed(() => selectedKey.value === NEW_CHAT ? 2000 : 4000);
const stopBusy = ref(false);
const canSend = computed(() => !!draft.value.trim() && !stopBusy.value && !currentPending.value && !conversation.value?.busy && !conversationLoading.value && (selectedKey.value === NEW_CHAT || !!conversation.value));
const terminal = new Set<RunStatus>(['completed', 'partial', 'failed', 'cancelled', 'interrupted']);
const running = new Set<RunStatus>(['queued', 'running', 'pause_requested']);
const sortedRuns = computed(() => [...(conversation.value?.runs || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)));
const latestRun = computed(() => sortedRuns.value[0]);
const activeRun = computed(() => sortedRuns.value.find(run => !terminal.has(run.status)));
const isResearchRunning = computed(() => !!activeRun.value && running.has(activeRun.value.status));
const canPause = computed(() => !!activeRun.value && ['queued', 'running'].includes(activeRun.value.status));
const canResume = computed(() => !!activeRun.value && ['paused', 'needs_input'].includes(activeRun.value.status));
const controlsDisabled = computed(() => stopBusy.value || !!currentPending.value || !!conversation.value?.busy);
const selectedRunId = computed(() => selectedRuns[selectedKey.value] || latestRun.value?.id || '');
const selectedRun = computed(() => conversation.value?.runs.find(run => run.id === selectedRunId.value));
const legacyRuns = computed(() => (conversation.value?.runs || []).filter(run => !conversation.value?.messages.some(message => message.run_id === run.id)));
type TimelineEntry = { kind: 'message'; id: string; created_at: string; message: ChatMessage } | { kind: 'run'; id: string; created_at: string; run: Run };
const timeline = computed<TimelineEntry[]>(() => [...(conversation.value?.messages || []).map(message => ({ kind: 'message' as const, id: message.id, created_at: message.created_at, message })), ...legacyRuns.value.map(run => ({ kind: 'run' as const, id: run.id, created_at: run.created_at, run }))].sort((a, b) => a.created_at.localeCompare(b.created_at)));
const runLabels: Record<RunStatus, string> = { queued: '调研排队中', running: '正在调研', pause_requested: '正在保存检查点', paused: '调研已暂停', needs_input: '等待补充', completed: '调研已结束', partial: '已有阶段性资料', failed: '调研失败', cancelled: '调研已停止', interrupted: '调研已中断' };
const stageLabels: Record<RunStage, string> = { understanding: '理解需求', planning: '规划检索', searching: '检索文献', extracting: '读取文本', assessing: '检查资料缺口', synthesizing: '整理资料', reporting: '生成资料报告' };
const messageLabels: Record<ChatStatus, string> = { queued: '等待处理', processing: '正在处理', completed: '已完成', failed: '回复失败', interrupted: '回复已中断' };
const sourceLabels: Record<SourceType, string> = { metadata: '元数据', abstract: '摘要', fulltext: '全文' };
const modeLabels: Record<ChatMode, string> = { auto: '自动理解', research: '补充检索', ask: '只问已有资料', pause: '暂停', resume: '继续', cancel: '停止' };
const modeDescriptions: Record<string, string> = { auto: '根据对话理解问题、澄清或调研', research: '明确请求检索；终态后开启新运行并保留历史', ask: '根据已保存来源回答，不发起新检索' };
const intentModes: ChatMode[] = ['auto', 'research', 'ask'];
const examples = [{ icon: '⌕', title: '探索一个研究方向', text: '帮我梳理多智能体通信的研究方向，先看看有哪些值得关注的问题。' }, { icon: '≋', title: '带着边界找文献', text: '我想研究小样本条件下的检索增强生成，关注评估方法和局限。' }, { icon: '↗', title: '先讨论，再开始调研', text: '我对长上下文与 RAG 的关系还不太清楚，可以先帮我明确问题吗？' }];
const sidebarOpen = ref(false);
const panelOpen = ref(false);
const panelTab = ref<'papers' | 'report'>('papers');
const timelineElement = ref<HTMLElement | null>(null);
const inputElement = ref<HTMLTextAreaElement | null>(null);
const intentMenu = ref<HTMLDetailsElement | null>(null);
const runMenu = ref<HTMLDetailsElement | null>(null);
const nearBottom = ref(true);
const historyLoading = ref(false);
const historyLoaded = ref(false);
const historyError = ref('');
const conversationLoading = ref(false);
const conversationError = ref('');
const healthConfigured = ref<boolean | null>(null);
const healthError = ref('');
const modelConfigured = computed(() => conversation.value?.model_configured ?? healthConfigured.value);
interface ArtifactData { papers: Paper[]; report: Report | null; reportNotice: string; loaded: boolean; }
const artifacts = reactive<Record<string, ArtifactData>>({});
const artifact = computed(() => artifacts[selectedRunId.value]);
const artifactLoading = ref(false);
const artifactError = ref('');
const paperSelection = ref<{ runId: string; paperId: string } | null>(null);
const paperDetail = ref<PaperDetail | null>(null);
const selectedCitation = ref<ChatCitation | null>(null);
const paperLoading = ref(false);
const paperError = ref('');
const processOpen = ref(false);
const processEvents = ref<RunEvent[]>([]);
let processRunId = '';
const processLoading = ref(false);
const processError = ref('');
const downloadBusy = ref(false);
const downloadError = ref('');
let disposed = false;
let viewVersion = 0;
let pollVersion = 0;
let artifactVersion = 0;
let paperVersion = 0;
let processVersion = 0;
let historyVersion = 0;
let historyWriteVersion = 0;
const writeVersions: Record<string, number> = {};
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let pollController: AbortController | null = null;
let artifactController: AbortController | null = null;
let paperController: AbortController | null = null;
let processController: AbortController | null = null;
let historyController: AbortController | null = null;
let sendController: AbortController | null = null;
let stopController: AbortController | null = null;
let downloadController: AbortController | null = null;
const pageController = new AbortController();
const errorText = (error: unknown) => error instanceof Error ? error.message : '未知错误，请查看服务端记录';
const formatTime = (value: string) => new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const tokenText = (value: number | null) => value == null ? '未知' : value.toLocaleString();
function runNumber(id: string) { return [...sortedRuns.value].reverse().findIndex(run => run.id === id) + 1; }
function trackScroll() { const element = timelineElement.value; if (element) nearBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 110; }
function scrollToBottom() { const element = timelineElement.value; if (element) { element.scrollTop = element.scrollHeight; nearBottom.value = true; } }
async function scrollIfNeeded(shouldScroll: boolean) { if (!shouldScroll) return; const version = viewVersion; const key = selectedKey.value; await nextTick(); if (version === viewVersion && key === selectedKey.value && nearBottom.value) scrollToBottom(); }
function chooseMode(mode: ChatMode) { modes[selectedKey.value] = mode; if (intentMenu.value) intentMenu.value.open = false; }
function useExample(text: string) { if (!currentPending.value) draft.value = text; inputElement.value?.focus(); }
function handleInputKey(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void sendDraft(); } }
function upsertTask(task: Task) { const index = tasks.value.findIndex(item => item.id === task.id); if (index >= 0) tasks.value.splice(index, 1); tasks.value.unshift(task); historyWriteVersion++; }
function applyConversation(data: ConversationView, shouldScroll: boolean) { views[data.task.id] = data; upsertTask(data.task); if (selectedKey.value === data.task.id) void scrollIfNeeded(shouldScroll); }
function stopPolling() { pollVersion++; if (pollTimer !== null) clearTimeout(pollTimer); pollTimer = null; pollController?.abort(); pollController = null; }
function abortMaterials() { artifactVersion++; artifactController?.abort(); artifactLoading.value = false; processVersion++; processController?.abort(); processLoading.value = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); }
function beginView() { viewVersion++; stopPolling(); sendController?.abort(); stopController?.abort(); stopBusy.value = false; abortMaterials(); conversationLoading.value = false; conversationError.value = ''; artifactError.value = ''; processError.value = ''; downloadError.value = ''; processEvents.value = []; processOpen.value = false; panelOpen.value = false; sidebarOpen.value = false; }
function newConversation() { beginView(); selectedKey.value = NEW_CHAT; nearBottom.value = true; void nextTick(() => { scrollToBottom(); inputElement.value?.focus(); }); }
function selectConversation(taskId: string, acknowledged?: ConversationView) { beginView(); selectedKey.value = taskId; nearBottom.value = true; if (acknowledged) { applyConversation(acknowledged, true); schedulePolling(); } else void pollConversation(); void nextTick(scrollToBottom); }
function schedulePolling() { const data = conversation.value; if (!data || disposed || stopBusy.value || currentPending.value?.busy || conversationError.value) return; if (data.busy || data.runs.some(run => running.has(run.status))) { const version = pollVersion; if (pollTimer !== null) clearTimeout(pollTimer); pollTimer = setTimeout(() => { pollTimer = null; if (version === pollVersion) void pollConversation(); }, 1400); } }
async function pollConversation() {
  const key = selectedKey.value; if (key === NEW_CHAT || stopBusy.value || currentPending.value?.busy || pollController) return;
  const version = viewVersion; const cycle = pollVersion; const write = writeVersions[key] || 0;
  const controller = new AbortController(); pollController = controller; conversationLoading.value = !views[key];
  const active = () => !disposed && version === viewVersion && cycle === pollVersion && selectedKey.value === key && write === (writeVersions[key] || 0) && !controller.signal.aborted;
  try { const data = await getConversation(key, controller.signal); if (!active()) return; applyConversation(data, nearBottom.value); conversationError.value = ''; if (panelOpen.value) await loadArtifacts(); if (processOpen.value) await loadProcess(); }
  catch (error) { if (active()) conversationError.value = `读取对话失败：${errorText(error)}`; }
  finally { if (active()) { conversationLoading.value = false; pollController = null; schedulePolling(); } }
}
function retryConversation() { if (stopBusy.value || currentPending.value?.busy) return; stopPolling(); conversationError.value = ''; void pollConversation(); }
async function refreshHistory() {
  historyController?.abort(); const controller = new AbortController(); historyController = controller;
  const version = ++historyVersion; const write = historyWriteVersion; historyLoading.value = true; historyError.value = '';
  try { const data = await getConversations(controller.signal); if (disposed || version !== historyVersion) return; if (write === historyWriteVersion) tasks.value = data; else { const byId = new Map(data.map(task => [task.id, task])); for (const task of tasks.value) { const item = byId.get(task.id); if (!item || item.updated_at <= task.updated_at) byId.set(task.id, task); } tasks.value = [...byId.values()].sort((a,b) => b.updated_at.localeCompare(a.updated_at)); } historyLoaded.value = true; }
  catch (error) { if (!disposed && version === historyVersion && !controller.signal.aborted) historyError.value = `读取记录失败：${errorText(error)}。现有历史仍保留。`; }
  finally { if (!disposed && version === historyVersion) historyLoading.value = false; }
}
async function sendDraft() {
  if (!canSend.value) return; const key = selectedKey.value; const content = draft.value.trim();
  if (Array.from(content).length > inputLimit.value) { sendErrors[key] = `消息不能超过 ${inputLimit.value} 字符。`; return; }
  pending[key] = { request_id: crypto.randomUUID(), content, mode: currentMode.value, snapshot: draft.value, fromDraft: true, busy: false, error: '' }; await transmit(key);
}
async function sendControl(mode: 'pause' | 'resume' | 'cancel') {
  if (controlsDisabled.value || !conversation.value) return; const key = selectedKey.value;
  const content = { pause: '暂停当前调研', resume: '继续当前调研', cancel: '停止当前调研' }[mode];
  pending[key] = { request_id: crypto.randomUUID(), content, mode, snapshot: '', fromDraft: false, busy: false, error: '' }; await transmit(key);
}
async function stopWork() {
  const key = selectedKey.value;
  if (!conversation.value || currentPending.value || stopBusy.value) return;
  const view = viewVersion; stopPolling();
  const write = (writeVersions[key] || 0) + 1; writeVersions[key] = write;
  const controller = new AbortController(); stopController = controller; stopBusy.value = true; sendErrors[key] = '';
  const active = () => !disposed && view === viewVersion && key === selectedKey.value && write === writeVersions[key] && !controller.signal.aborted;
  try { const data = await stopConversation(key, controller.signal); if (active()) { applyConversation(data, nearBottom.value); conversationError.value = ''; if (panelOpen.value) void loadArtifacts(); } }
  catch (error) { if (active()) sendErrors[key] = `停止请求未确认：${errorText(error)}。已有消息与草稿保留，可重新停止。`; }
  finally { if (active()) { stopBusy.value = false; stopController = null; schedulePolling(); } }
}
async function retrySend() { if (currentPending.value && !currentPending.value.busy) await transmit(selectedKey.value); }
async function transmit(key: string) {
  const request = pending[key]; if (!request || request.busy) return;
  const version = viewVersion; stopPolling(); const write = (writeVersions[key] || 0) + 1; writeVersions[key] = write;
  const controller = new AbortController(); sendController = controller; request.busy = true; request.error = ''; sendErrors[key] = '';
  try {
    const data = await sendConversationMessage(key === NEW_CHAT ? null : key, { content: request.content, mode: request.mode, request_id: request.request_id }, controller.signal);
    if (disposed || write !== writeVersions[key]) return;
    if (request.fromDraft && drafts[key] === request.snapshot) drafts[key] = '';
    if (key === NEW_CHAT) { drafts[data.task.id] = drafts[key] || ''; drafts[key] = ''; modes[data.task.id] = modes[key] || 'auto'; }
    delete pending[key]; applyConversation(data, nearBottom.value);
    if (version === viewVersion && selectedKey.value === key) { if (key === NEW_CHAT) selectConversation(data.task.id, data); else { conversationError.value = ''; if (panelOpen.value) void loadArtifacts(); } }
  } catch (error) {
    if (disposed) return;
    if (error instanceof ApiError && error.status >= 400 && error.status < 500) { sendErrors[key] = `消息未被接受：${errorText(error)}。草稿仍保留。`; delete pending[key]; }
    else request.error = controller.signal.aborted ? '已切换对话，请求结果未确认。返回后重试原消息，沿用同一请求标识。' : `${errorText(error)}。服务可能已接收；重试原消息不会新建重复请求。`;
  } finally { request.busy = false; if (sendController === controller) sendController = null; if (!disposed && version === viewVersion && selectedKey.value === key) schedulePolling(); }
}
function clearPaper() { paperVersion++; paperController?.abort(); paperSelection.value = null; paperDetail.value = null; selectedCitation.value = null; paperError.value = ''; paperLoading.value = false; }
function closePanel() { panelOpen.value = false; artifactVersion++; artifactController?.abort(); artifactLoading.value = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); }
function togglePanel() { if (panelOpen.value) closePanel(); else { if (!selectedRuns[selectedKey.value] && latestRun.value) selectedRuns[selectedKey.value] = latestRun.value.id; panelOpen.value = true; void loadArtifacts(); } }
function chooseRun(runId: string) { selectedRuns[selectedKey.value] = runId; if (runMenu.value) runMenu.value.open = false; downloadController?.abort(); downloadBusy.value = false; clearPaper(); artifactError.value = ''; downloadError.value = ''; void loadArtifacts(); }
function openRun(runId: string) { panelOpen.value = true; panelTab.value = 'papers'; chooseRun(runId); }
function openPaper(paperId: string) { clearPaper(); paperSelection.value = { runId: selectedRunId.value, paperId }; void loadPaper(); }
function openCitation(citation: ChatCitation) { downloadController?.abort(); downloadBusy.value = false; downloadError.value = ''; panelOpen.value = true; panelTab.value = 'papers'; selectedRuns[selectedKey.value] = citation.run_id; clearPaper(); selectedCitation.value = citation; paperSelection.value = { runId: citation.run_id, paperId: citation.paper_id }; void loadArtifacts(); void loadPaper(); }
async function loadArtifacts() {
  if (!panelOpen.value || !selectedRunId.value) return;
  artifactController?.abort(); const controller = new AbortController(); artifactController = controller;
  const version = ++artifactVersion; const view = viewVersion; const runId = selectedRunId.value;
  const active = () => !disposed && view === viewVersion && version === artifactVersion && panelOpen.value && runId === selectedRunId.value && !controller.signal.aborted;
  artifactLoading.value = true;
  try {
    const [paperResult, reportResult] = await Promise.allSettled([getPapers(runId, controller.signal), getReport(runId, controller.signal)]); if (!active()) return;
    const data = artifacts[runId] || { papers: [], report: null, reportNotice: '', loaded: false }; const errors: string[] = [];
    if (paperResult.status === 'fulfilled') { data.papers = paperResult.value; data.loaded = true; } else errors.push(`读取文献失败：${errorText(paperResult.reason)}`);
    if (reportResult.status === 'fulfilled') data.report = reportResult.value;
    else if (reportResult.reason instanceof ApiError && reportResult.reason.status === 409) { data.report = null; data.reportNotice = `本次运行尚无可交付报告（${selectedRun.value ? runLabels[selectedRun.value.status] : '当前状态未知'}）。`; }
    else errors.push(`读取报告失败：${errorText(reportResult.reason)}`);
    artifacts[runId] = data; artifactError.value = errors.join('；');
  } finally { if (active()) artifactLoading.value = false; }
}
async function loadPaper() {
  const selection = paperSelection.value; if (!selection) return;
  paperController?.abort(); const controller = new AbortController(); paperController = controller;
  const version = ++paperVersion; const view = viewVersion;
  const active = () => !disposed && view === viewVersion && version === paperVersion && !controller.signal.aborted;
  paperLoading.value = true; paperError.value = '';
  try { const data = await getPaperDetail(selection.runId, selection.paperId, controller.signal); if (active()) paperDetail.value = data; }
  catch (error) { if (active()) paperError.value = `读取论文详情失败：${errorText(error)}`; }
  finally { if (active()) paperLoading.value = false; }
}
function onProcessToggle(event: Event) { processOpen.value = (event.target as HTMLDetailsElement).open; if (processOpen.value) void loadProcess(); else { processVersion++; processController?.abort(); processLoading.value = false; } }
async function loadProcess() {
  if (!processOpen.value || !latestRun.value) return;
  processController?.abort(); const controller = new AbortController(); processController = controller;
  const version = ++processVersion; const view = viewVersion; const runId = latestRun.value.id;
  if (processRunId !== runId) { processRunId = runId; processEvents.value = []; processError.value = ''; }
  const active = () => !disposed && view === viewVersion && version === processVersion && !controller.signal.aborted;
  processLoading.value = true;
  try { const data = await getRunEvents(runId, controller.signal); if (active()) { processEvents.value = data; processError.value = ''; } }
  catch (error) { if (active()) processError.value = `读取过程失败：${errorText(error)}`; }
  finally { if (active()) processLoading.value = false; }
}
async function downloadReport() {
  if (downloadBusy.value || !selectedRunId.value) return;
  const runId = selectedRunId.value; const view = viewVersion;
  const controller = new AbortController(); downloadController = controller; downloadBusy.value = true; downloadError.value = '';
  const active = () => !disposed && view === viewVersion && runId === selectedRunId.value && !controller.signal.aborted;
  try { const blob = await getMarkdownReport(runId, controller.signal); if (!active()) return; const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `paper-scout-${runId}.md`; link.click(); URL.revokeObjectURL(url); }
  catch (error) { if (active()) downloadError.value = `下载失败：${errorText(error)}`; }
  finally { if (active()) downloadBusy.value = false; }
}
onMounted(() => { void refreshHistory(); void fetchHealth(pageController.signal).then(data => { if (!disposed) healthConfigured.value = data.model_configured ?? null; }).catch(error => { if (!disposed) healthError.value = errorText(error); }); });
onUnmounted(() => { disposed = true; stopPolling(); abortMaterials(); sendController?.abort(); stopController?.abort(); historyController?.abort(); pageController.abort(); });
</script>
<style src="./workspace.css"></style>

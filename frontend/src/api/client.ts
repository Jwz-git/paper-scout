export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  model_configured?: boolean;
}

export type ModelProtocol = 'openai_chat' | 'openai_responses' | 'anthropic_messages';

export interface ModelSettings {
  enabled: boolean;
  protocol: ModelProtocol;
  base_url: string;
  model: string;
  api_key_set: boolean;
  source: 'environment' | 'local';
  busy: boolean;
  active_provider_id: string | null;
  active_model: string | null;
  providers: AiProvider[];
  limits: {
    research: { max_rounds: number; max_calls: number; max_seconds: number };
    conversation: { calls_per_turn: number; seconds_per_turn: number };
  };
}

export interface AiProvider {
  id: string;
  name: string;
  protocol: ModelProtocol;
  base_url: string;
  models: string[];
  api_key_set: boolean;
}

export interface ProviderUpdate {
  name: string;
  protocol: ModelProtocol;
  base_url: string;
  models: string[];
  api_key: string | null;
  clear_api_key: boolean;
}

export interface AvailableModel { id: string; name: string; }
export interface ModelCatalogRequest {
  protocol: ModelProtocol;
  base_url: string;
  api_key: string | null;
  clear_api_key: boolean;
  provider_id: string | null;
  cursor?: string | null;
}

export interface ModelSettingsUpdate {
  enabled: boolean;
  protocol: ModelProtocol;
  base_url: string;
  model: string;
  api_key: string | null;
  clear_api_key: boolean;
}

export interface TokenUsage {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
}

export type ChatMode = "auto" | "research" | "ask" | "pause" | "resume" | "cancel";
export type ChatStatus = "queued" | "processing" | "completed" | "failed" | "interrupted";
export type SourceType = "metadata" | "abstract" | "fulltext";

export interface ChatCitation {
  source_text_id: string;
  paper_id: string;
  run_id: string;
  source_type: SourceType;
  source_url?: string | null;
  page_number?: number | null;
  quote: string;
  location_start: number | null;
  location_end: number | null;
}

export interface ChatMessage {
  id: string;
  task_id: string;
  role: "user" | "assistant";
  content: string;
  status: ChatStatus;
  action?: "research" | "answer" | "clarify" | "pause" | "resume" | "cancel" | null;
  run_id?: string | null;
  citations: ChatCitation[];
  created_at: string;
  error_category?: string | null;
}

export interface ConversationView {
  task: Task;
  messages: ChatMessage[];
  runs: Run[];
  usage: {
    model_calls: number;
    total_execution_seconds: number;
    token_usage: TokenUsage;
  };
  busy: boolean;
  model_configured: boolean;
}

export interface ChatRequest {
  content: string;
  mode: ChatMode;
  request_id: string;
}

export interface Task {
  id: string;
  topic: string;
  title?: string | null;
  deleted_at?: string | null;
  start_year?: number | null;
  end_year?: number | null;
  focus_dimensions: string[];
  output_requirements?: string | null;
  created_at: string;
  updated_at: string;
}

export type RunStatus = "queued" | "running" | "pause_requested" | "paused" | "needs_input" | "completed" | "partial" | "failed" | "cancelled" | "interrupted";
export type RunStage = "understanding" | "planning" | "searching" | "screening" | "extracting" | "analyzing" | "assessing" | "synthesizing" | "reporting";

export interface Run {
  id: string;
  task_id: string;
  initial_topic: string;
  initial_input?: Omit<Task, "id" | "created_at" | "updated_at"> | null;
  current_input?: Omit<Task, "id" | "created_at" | "updated_at"> | null;
  model_calls?: number;
  token_usage?: TokenUsage;
  status: RunStatus;
  stage: RunStage;
  analysis_revision?: number;
  current_round: number;
  max_rounds: number;
  max_calls: number;
  max_seconds: number;
  total_calls: number;
  total_execution_seconds: number;
  gaps: string[];
  stop_reason?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface RunMessage {
  id: string;
  run_id: string;
  content: string;
  status: string;
  impact_summary?: string | null;
  created_at: string;
}

export interface RunEvent {
  id: string;
  run_id: string;
  stage: RunStage;
  analysis_revision?: number;
  category: string;
  message: string;
  created_at: string;
}

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  year?: number | null;
  url: string;
  pdf_url?: string | null;
  abstract?: string | null;
  doi?: string | null;
  source?: string;
  source_id?: string;
  primary_category?: string | null;
  categories?: string[];
  fetched_at?: string;
}

export interface SourceText {
  id: string;
  paper_id: string;
  source_type: SourceType;
  source_url?: string | null;
  page_number?: number | null;
  content: string;
  status: string;
  fetched_at: string;
}

export interface Evidence {
  id: string;
  source_text_id: string;
  paper_id: string;
  page_number?: number | null;
  quote: string;
  location_start: number | null;
  location_end: number | null;
}

export interface Extraction {
  id: string; field_name: string; value: string | null; missing_reason: string | null;
  evidence_ids: string[]; origin: 'author' | 'inference' | 'user'; note: string;
}
export interface ReadRange {
  source_text_id: string; source_type: SourceType; page_number: number | null;
  location_start: number; location_end: number; original_length: number;
}
export interface PaperAnalysis {
  id: string; paper_id: string; analysis_revision: number; status: 'completed' | 'failed' | 'unavailable';
  fields: Extraction[]; ranges: ReadRange[]; error: string | null; reused_from: string | null;
}
export interface PaperSelection {
  paper_id: string; relevant: boolean; reviewed: boolean; reason: string; subproblems: string[]; evidence_ids: string[];
}
export interface Comparison {
  left_paper_id: string; right_paper_id: string; status: 'comparable' | 'not_comparable' | 'insufficient';
  metric: string | null; left_value: string | null; right_value: string | null; reasons: string[]; evidence_ids: string[];
}
export interface Assessment {
  sufficient: boolean; rule: string; supporting_papers: Record<string, string[]>; field_counts: Record<string, [number, number]>;
  paper_groups: Record<string, string>; duplicate_candidates: string[][]; comparisons: Comparison[]; gaps: string[]; next_actions: string[];
}
export interface ResearchAnalysis {
  analysis_revision: number; papers: Paper[]; analyses: PaperAnalysis[]; selections: PaperSelection[]; assessment: Assessment | null;
}
export interface ReportClaim { text: string; origin: 'author' | 'inference' | 'user'; evidence_ids: string[]; }
export interface ReportDocument {
  analysis_revision: number; sections: { title: string; claims: ReportClaim[] }[];
  evidence: Evidence[]; excluded_papers: Paper[];
}
export interface PaperDetail {
  paper: Paper;
  sources: SourceText[];
  evidence: Evidence[];
  analysis?: PaperAnalysis | null;
  selection?: PaperSelection | null;
  selected?: boolean;
  analysis_revision?: number;
}

export interface Report {
  id: string;
  run_id: string;
  title: string;
  content_markdown: string;
  document?: ReportDocument | null;
  gaps: string[];
  stop_reason?: string | null;
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => `${item.loc?.join(".") || "输入"}：${item.msg}`).join("；");
  }
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  return "服务未返回可读的错误说明";
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`请求失败（HTTP ${status}）：${detailMessage(detail)}`);
    this.name = "ApiError";
  }
}

async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    // HTTP 错误在客户端边界解析，不用空数据掩盖服务失败。
    let detail: unknown = response.statusText;
    if (response.headers.get("content-type")?.includes("application/json")) {
      try {
        const body = await response.json();
        detail = body.detail ?? body;
      } catch {
        detail = "服务错误响应不是有效的 JSON";
      }
    }
    throw new ApiError(response.status, detail);
  }
  return response;
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return (await request("/health", { signal })).json();
}

export async function getModelSettings(signal?: AbortSignal): Promise<ModelSettings> {
  return (await request('/settings', { signal, cache: 'no-store' })).json();
}

export async function saveModelSettings(payload: ModelSettingsUpdate, signal?: AbortSignal): Promise<ModelSettings> {
  return (await request('/settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload), signal,
  })).json();
}

export async function getConversations(page: { query: string; offset: number; limit: number }, signal?: AbortSignal): Promise<Task[]> {
  const params = new URLSearchParams({ query: page.query, offset: String(page.offset), limit: String(page.limit) });
  return (await request(`/conversations?${params}`, { signal })).json();
}

export async function renameConversation(id: string, title: string, signal?: AbortSignal): Promise<Task> {
  return (await request(`/conversations/${encodeURIComponent(id)}/rename`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }), signal })).json();
}

export async function trashConversation(id: string, signal?: AbortSignal): Promise<Task> {
  return (await request(`/conversations/${encodeURIComponent(id)}/trash`, { method: 'POST', signal })).json();
}

export async function restoreConversation(id: string, signal?: AbortSignal): Promise<Task> {
  return (await request(`/conversations/${encodeURIComponent(id)}/restore`, { method: 'POST', signal })).json();
}

export interface TrashPage { items: Task[]; total: number; matched: number; }
export async function getTrash(query: string, sort: string, offset: number, limit: number, signal?: AbortSignal): Promise<TrashPage> {
  const params = new URLSearchParams({ query, sort, offset: String(offset), limit: String(limit) });
  return (await request(`/conversations/trash?${params}`, { signal })).json();
}
export async function restoreTrash(ids: string[] | null): Promise<{ tasks: Task[] }> {
  return (await request('/conversations/trash/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) })).json();
}
export async function deleteTrash(ids: string[] | null): Promise<{ ids: string[] }> {
  return (await request('/conversations/trash/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) })).json();
}

export async function saveProvider(id: string | null, payload: ProviderUpdate, signal?: AbortSignal): Promise<{ provider_id: string; settings: ModelSettings }> {
  const path = id ? `/settings/providers/${encodeURIComponent(id)}` : '/settings/providers';
  return (await request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal })).json();
}

export async function fetchAvailableModels(payload: ModelCatalogRequest, signal?: AbortSignal): Promise<{ models: AvailableModel[]; next_cursor: string | null }> {
  return (await request('/settings/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal, cache: 'no-store' })).json();
}

export async function selectProviderModel(providerId: string, model: string, signal?: AbortSignal): Promise<ModelSettings> {
  return (await request('/settings/selection', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider_id: providerId, model }), signal })).json();
}

export async function deleteProvider(id: string, signal?: AbortSignal): Promise<ModelSettings> {
  return (await request(`/settings/providers/${encodeURIComponent(id)}/delete`, { method: 'POST', signal })).json();
}

export async function getConversation(taskId: string, signal?: AbortSignal): Promise<ConversationView> {
  return (await request(`/conversations/${encodeURIComponent(taskId)}`, { signal })).json();
}

export async function sendConversationMessage(taskId: string | null, payload: ChatRequest, signal?: AbortSignal): Promise<ConversationView> {
  const path = taskId ? `/conversations/${encodeURIComponent(taskId)}/messages` : "/conversations";
  return (await request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  })).json();
}

export async function stopConversation(taskId: string, signal?: AbortSignal): Promise<ConversationView> {
  return (await request(`/conversations/${encodeURIComponent(taskId)}/stop`, { method: "POST", signal })).json();
}

export async function getPaperDetail(runId: string, paperId: string, signal?: AbortSignal): Promise<PaperDetail> {
  return (await request(`/runs/${encodeURIComponent(runId)}/papers/${encodeURIComponent(paperId)}`, { signal })).json();
}

// 论文链接是外部输入，只允许浏览器打开 HTTP(S)，避免 javascript: 等可执行地址。
export function sourceLink(value?: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export async function getTasks(signal?: AbortSignal): Promise<Task[]> {
  return (await request("/tasks", { signal })).json();
}

export async function getTaskRuns(taskId: string, signal?: AbortSignal): Promise<Run[]> {
  return (await request(`/tasks/${taskId}/runs`, { signal })).json();
}

export async function createTask(payload: {
  topic: string;
  start_year?: number | null;
  end_year?: number | null;
  focus_dimensions?: string[];
}, signal?: AbortSignal): Promise<Task> {
  return (await request("/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  })).json();
}

export async function startRun(taskId: string, signal?: AbortSignal): Promise<Run> {
  return (await request(`/tasks/${taskId}/runs`, { method: "POST", signal })).json();
}

export async function getRun(runId: string, signal?: AbortSignal): Promise<Run> {
  return (await request(`/runs/${runId}`, { signal })).json();
}

export async function pauseRun(runId: string, signal?: AbortSignal): Promise<Run> {
  return (await request(`/runs/${runId}/pause`, { method: "POST", signal })).json();
}

export async function resumeRun(runId: string, signal?: AbortSignal): Promise<Run> {
  return (await request(`/runs/${runId}/resume`, { method: "POST", signal })).json();
}

export async function cancelRun(runId: string, signal?: AbortSignal): Promise<Run> {
  return (await request(`/runs/${runId}/cancel`, { method: "POST", signal })).json();
}

export async function addRunMessage(runId: string, content: string, signal?: AbortSignal): Promise<RunMessage> {
  return (await request(`/runs/${runId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
    signal,
  })).json();
}

export async function getRunMessages(runId: string, signal?: AbortSignal): Promise<RunMessage[]> {
  return (await request(`/runs/${runId}/messages`, { signal })).json();
}

export async function getRunEvents(runId: string, signal?: AbortSignal): Promise<RunEvent[]> {
  return (await request(`/runs/${runId}/events`, { signal })).json();
}

export async function getPapers(runId: string, signal?: AbortSignal): Promise<Paper[]> {
  return (await request(`/runs/${runId}/papers`, { signal })).json();
}

export async function getReport(runId: string, signal?: AbortSignal): Promise<Report> {
  // 404 是运行不存在；409 是已有运行尚无报告，由界面分别展示。
  return (await request(`/runs/${runId}/report`, { signal })).json();
}

export async function getResearchAnalysis(runId: string, signal?: AbortSignal): Promise<ResearchAnalysis> {
  return (await request(`/runs/${runId}/analysis`, { signal })).json();
}

export async function getReportFile(runId: string, reportId: string, format: 'md' | 'docx' | 'pdf', signal?: AbortSignal): Promise<Blob> {
  return (await request(`/runs/${runId}/report.${format}?report_id=${encodeURIComponent(reportId)}`, { signal })).blob();
}

export async function getMarkdownReport(runId: string, signal?: AbortSignal): Promise<Blob> {
  return (await request(`/runs/${runId}/report.md`, { signal })).blob();
}

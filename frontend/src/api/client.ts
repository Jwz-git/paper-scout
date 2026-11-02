export interface HealthResponse {
  status: string;
  app: string;
  version: string;
}

export interface Task {
  id: string;
  topic: string;
  start_year?: number | null;
  end_year?: number | null;
  focus_dimensions: string[];
  output_requirements?: string | null;
  created_at: string;
  updated_at: string;
}

export type RunStatus = "queued" | "running" | "pause_requested" | "paused" | "needs_input" | "completed" | "partial" | "failed" | "cancelled" | "interrupted";
export type RunStage = "understanding" | "planning" | "searching" | "extracting" | "assessing" | "synthesizing" | "reporting";

export interface Run {
  id: string;
  task_id: string;
  initial_topic: string;
  status: RunStatus;
  stage: RunStage;
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
}

export interface Report {
  id: string;
  run_id: string;
  title: string;
  content_markdown: string;
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

export async function getMarkdownReport(runId: string, signal?: AbortSignal): Promise<Blob> {
  return (await request(`/runs/${runId}/report.md`, { signal })).blob();
}

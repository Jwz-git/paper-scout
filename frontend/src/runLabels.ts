import type { RunStatus, TodoItem } from './api/client';

export const runLabels: Record<RunStatus, string> = { queued: '调研排队中', running: '正在调研', pause_requested: '正在保存检查点', paused: '调研已暂停', needs_input: '等待补充', completed: '调研已结束', partial: '已有阶段性资料', failed: '调研失败', cancelled: '调研已停止', interrupted: '调研已中断' };
export const eventLabels: Record<string, string> = { thought: '思考', tool: '操作', tool_error: '操作失败', retry: '重试', limit: '达到上限', message: '新消息', reader: '阅读', error: '出错' };
export const todoLabels: Record<TodoItem['status'], string> = { pending: '待做', in_progress: '进行中', done: '已完成' };

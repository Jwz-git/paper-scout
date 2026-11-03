import type { RunStage, RunStatus } from './api/client';

export const runLabels: Record<RunStatus, string> = { queued: '调研排队中', running: '正在调研', pause_requested: '正在保存检查点', paused: '调研已暂停', needs_input: '等待补充', completed: '调研已结束', partial: '已有阶段性资料', failed: '调研失败', cancelled: '调研已停止', interrupted: '调研已中断' };
export const stageLabels: Record<RunStage, string> = { understanding: '理解需求', planning: '规划检索', searching: '检索文献', screening: '筛选相关文献', extracting: '读取文本', analyzing: '提取论文事实', assessing: '检查证据缺口', synthesizing: '综合研究结论', reporting: '保存研究报告' };

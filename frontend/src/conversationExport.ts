import type { ConversationView } from './api/client';

const statusLabels = { queued: '等待处理', processing: '正在处理', completed: '已完成', failed: '回复失败', interrupted: '已中断' };
const sourceLabels = { metadata: '元数据', abstract: '摘要', fulltext: '全文' };

export function exportConversation(view: ConversationView, format: 'markdown' | 'json') {
  const exportedAt = new Date().toISOString();
  let content: string;
  if (format === 'json') {
    // 只导出已加载的会话，模型配置和未发送草稿不属于会话数据。
    content = JSON.stringify({ format: 'paper-scout-conversation', version: 1, exported_at: exportedAt, task: view.task, messages: view.messages, runs: view.runs, usage: view.usage }, null, 2);
  } else {
    const lines = [`# ${view.task.title || view.task.topic}`, '', `会话 ID：${view.task.id}`, `导出时间：${exportedAt}`, '', '## 研究问题', '', view.task.topic, '', '## 对话记录', ''];
    if (!view.messages.length) lines.push('尚无对话消息。', '');
    for (const message of view.messages) {
      lines.push(`### ${message.role === 'user' ? '你' : 'Paper Scout'} · ${message.created_at}`, '', `状态：${statusLabels[message.status]}`, '', message.content || '（尚无回复内容）', '');
      if (message.error_category) lines.push(`错误类别：${message.error_category}`, '');
      for (const [index, citation] of message.citations.entries()) {
        lines.push(`引用 ${index + 1}：${sourceLabels[citation.source_type]}${citation.page_number != null ? ` · 第 ${citation.page_number} 页` : ''}`, `运行：${citation.run_id}；论文：${citation.paper_id}；来源快照：${citation.source_text_id}`, `字符范围：${citation.location_start ?? '未知'}—${citation.location_end ?? '未知'}`, ...(citation.source_url ? [`来源：${citation.source_url}`] : []), '', ...citation.quote.split('\n').map(line => `> ${line}`), '');
      }
    }
    lines.push('---', '本文件仅包含已加载的对话与引用摘录，不包含论文全文或阶段性报告。运行中的内容是导出时的快照。', '');
    content = lines.join('\n');
  }
  const url = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `paper-scout-${view.task.id}.${format === 'json' ? 'json' : 'md'}`;
  link.click();
  // 给浏览器下载一次事件循环以读取 Blob。
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

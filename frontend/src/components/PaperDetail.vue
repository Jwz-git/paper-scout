<template>
  <article class="paper-detail">
    <button class="text-button back-link" @click="$emit('back')">← 返回文献列表</button>
    <h2>文献详情</h2>
    <p class="detail-context">论文 · 本次运行快照</p>
    <p class="paper-detail-title">{{ detail.paper.title }}</p>
    <p class="paper-authors">{{ detail.paper.authors.join('、') || '作者信息缺失' }}</p>
    <dl class="metadata-grid">
      <div><dt>年份</dt><dd>{{ detail.paper.year ?? '缺失' }}</dd></div>
      <div><dt>来源</dt><dd>{{ detail.paper.source || '未提供' }}</dd></div>
      <div><dt>来源 ID</dt><dd>{{ detail.paper.source_id || '缺失' }}</dd></div>
      <div><dt>DOI</dt><dd>{{ detail.paper.doi || '缺失' }}</dd></div>
      <div v-if="detail.paper.fetched_at" class="wide"><dt>元数据获取时间</dt><dd>{{ formatTime(detail.paper.fetched_at) }}</dd></div>
    </dl>
    <div class="external-links">
      <a v-if="sourceLink(detail.paper.url)" :href="sourceLink(detail.paper.url)" target="_blank" rel="noopener noreferrer">论文来源 ↗</a>
      <a v-if="sourceLink(detail.paper.pdf_url)" :href="sourceLink(detail.paper.pdf_url)" target="_blank" rel="noopener noreferrer">原始 PDF ↗</a>
    </div>

    <section v-if="citation" class="citation-focus">
      <div class="section-heading"><h3>引用原文</h3><span>{{ sourceLabels[citation.source_type] }}</span></div>
      <p class="muted">{{ citation.page_number == null ? '未提供 PDF 页码' : `PDF 第 ${citation.page_number} 页` }} · 字符区间 {{ formatRange(citation.location_start, citation.location_end) }}</p>
      <blockquote>{{ citation.quote }}</blockquote>
      <code class="source-id">来源快照 {{ citation.source_text_id }}</code>
      <a v-if="sourceLink(citation.source_url)" :href="sourceLink(citation.source_url)" target="_blank" rel="noopener noreferrer">打开引用来源 ↗</a>
      <p v-if="!citedSource" class="error-message" role="alert">本次详情未返回这条引用的来源快照；不能核对原文。</p>
      <p v-else-if="!citationMatches" class="error-message" role="alert">引用范围或摘录与已保存快照不一致，需人工核查；未将不匹配的内容标为已验证。</p>
      <p v-else class="muted">下方高亮来自已保存快照。定位一致不代表原文一定支持回答中的主张。</p>
    </section>

    <section class="reading-summary">
      <h3>实际读取范围</h3>
      <dl class="reading-tags">
        <div><dt>元数据</dt><dd>{{ countReadable('metadata') ? '已保存' : '未读取' }}</dd></div>
        <div><dt>摘要</dt><dd>{{ countReadable('abstract') ? '已保存' : '未读取 / 缺失' }}</dd></div>
        <div><dt>全文</dt><dd>{{ countReadable('fulltext') }} 个可读页快照</dd></div>
      </dl>
      <p class="muted">仅代表保存的来源与页，不表示阅读全文。下载失败、扫描页、截断与解析状态按原记录展示；不提供 OCR。</p>
    </section>

    <section v-if="detail.sources.length" class="saved-sources">
      <h3>来源快照</h3>
      <div class="source-tabs" aria-label="选择来源快照">
        <button v-for="source in detail.sources" :key="source.id" :class="{ active: selectedSourceId === source.id }" :aria-pressed="selectedSourceId === source.id" @click="selectedSourceId = source.id">
          {{ sourceLabels[source.source_type] }}{{ source.page_number != null ? ` · p${source.page_number}` : '' }}
          <span v-if="source.status !== 'ok'"> · {{ statusLabel(source.status) }}</span>
        </button>
      </div>
      <template v-if="selectedSource">
        <div class="source-meta">
          <span>{{ statusLabel(selectedSource.status) }}</span>
          <span>{{ formatTime(selectedSource.fetched_at) }}</span>
          <span v-if="selectedSource.page_number != null">PDF 第 {{ selectedSource.page_number }} 页</span>
        </div>
        <p v-if="sourceLink(selectedSource.source_url)" class="source-url"><a :href="sourceLink(selectedSource.source_url)" target="_blank" rel="noopener noreferrer">{{ selectedSource.source_url }} ↗</a></p>
        <pre v-if="selectedSource.content" class="source-preview" tabindex="0" role="region" aria-label="已保存的来源原文"><template v-if="highlight"><span>{{ highlight.before }}</span><mark>{{ highlight.quote }}</mark><span>{{ highlight.after }}</span></template><template v-else>{{ selectedSource.content }}</template></pre>
        <p v-else class="muted">此快照没有可读文本（{{ statusLabel(selectedSource.status) }}）。</p>
        <code class="source-id">{{ selectedSource.id }}</code>
      </template>
    </section>
    <p v-else class="muted">本次运行未保存来源文本，不能根据外部链接推断已经读取。</p>

    <details v-if="detail.evidence.length" class="evidence-records">
      <summary>已保存证据片段 · {{ detail.evidence.length }}</summary>
      <button v-for="evidence in detail.evidence" :key="evidence.id" class="evidence-card" @click="openEvidence(evidence)">
        <span>{{ evidence.page_number == null ? '未提供页码' : `PDF 第 ${evidence.page_number} 页` }} · {{ formatRange(evidence.location_start, evidence.location_end) }}</span>
        <q>{{ evidence.quote }}</q>
        <small>查看原文定位 →</small>
      </button>
    </details>
  </article>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { sourceLink, type ChatCitation, type Evidence, type PaperDetail, type SourceType } from '../api/client.ts';

const props = defineProps<{ detail: PaperDetail; runId: string; citation: ChatCitation | null }>();
const emit = defineEmits<{ back: []; citation: [citation: ChatCitation] }>();
const sourceLabels: Record<SourceType, string> = { metadata: '元数据', abstract: '摘要', fulltext: '全文' };
const selectedSourceId = ref('');
watch(() => [props.detail, props.citation] as const, () => {
  selectedSourceId.value = props.citation?.source_text_id || props.detail.sources[0]?.id || '';
}, { immediate: true });
const selectedSource = computed(() => props.detail.sources.find(source => source.id === selectedSourceId.value));
const citedSource = computed(() => props.detail.sources.find(source => source.id === props.citation?.source_text_id));
const citationMatches = computed(() => {
  const citation = props.citation;
  if (!citation || !citedSource.value || citation.location_start == null || citation.location_end == null) return false;
  const characters = Array.from(citedSource.value.content);
  return citation.location_start >= 0 && citation.location_end >= citation.location_start && citation.location_end <= characters.length
    && characters.slice(citation.location_start, citation.location_end).join('') === citation.quote;
});
const highlight = computed(() => {
  const citation = props.citation;
  if (!citation || !citationMatches.value || selectedSource.value?.id !== citation.source_text_id) return null;
  // API 的定位按 Python Unicode 字符计数，不按 JavaScript UTF-16 单元计数。
  const characters = Array.from(selectedSource.value.content);
  return {
    before: characters.slice(0, citation.location_start!).join(''),
    quote: characters.slice(citation.location_start!, citation.location_end!).join(''),
    after: characters.slice(citation.location_end!).join(''),
  };
});
function countReadable(type: SourceType) {
  return props.detail.sources.filter(source => source.source_type === type && source.status === 'ok' && source.content).length;
}
function statusLabel(status: string) {
  const labels: Record<string, string> = { ok: '可读文本已保存', empty: '没有可读文本', not_read: '未读取', not_available: '不可获取', parse_failed: '解析失败', download_failed: '下载失败', truncated: '内容截断', page_limit: '已达读取页数上限，后续页未读取', scanned: '扫描页 / 不可读', failed: '读取失败' };
  return labels[status] || status;
}
function formatTime(value: string) { return new Date(value).toLocaleString(); }
function formatRange(start: number | null, end: number | null) {
  return start == null || end == null ? '未提供' : `[${start}, ${end})`;
}
function openEvidence(evidence: Evidence) {
  const source = props.detail.sources.find(item => item.id === evidence.source_text_id);
  if (!source) return;
  emit('citation', { ...evidence, run_id: props.runId, source_type: source.source_type, source_url: source.source_url });
}
</script>

<style scoped>
.paper-detail { min-width: 0; color: var(--text); }
h2 { margin: 20px 0 0; font-size: 18px; font-weight: 500; line-height: 1.4; }
h3 { margin: 0 0 12px; font-size: var(--fs-section); font-weight: 500; line-height: 1.5; }
.detail-context { margin: 6px 0 20px; color: var(--muted); font-size: var(--fs-small); line-height: 1.6; }
.paper-detail-title { margin: 0 0 12px; font-size: 18px; font-weight: 500; line-height: 1.7; overflow-wrap: anywhere; }
.paper-authors { color: var(--muted); font-size: var(--fs-body); line-height: 1.8; }
.metadata-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 24px 0; }
.metadata-grid .wide { grid-column: 1 / -1; }
dt { margin-bottom: 6px; color: var(--muted); font-size: var(--fs-small); }
dd { margin: 0; color: var(--text); font-size: var(--fs-body); line-height: 1.65; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.external-links { display: flex; flex-wrap: wrap; gap: 12px 18px; font-size: var(--fs-small); }
a { color: var(--accent); text-decoration: none; overflow-wrap: anywhere; }
a:hover { text-decoration: underline; text-underline-offset: 3px; }
.back-link { margin: 0; }
.text-button { display: inline-flex; align-items: center; min-height: 32px; padding: 2px 0; border: 0; background: none; color: var(--text); cursor: pointer; font: inherit; font-size: var(--fs-small); }
.text-button:hover { text-decoration: underline; text-underline-offset: 3px; }
.citation-focus, .reading-summary, .saved-sources { margin-top: 28px; }
.citation-focus { padding: 16px; border-radius: var(--radius-card); background: var(--accent-soft); }
.section-heading { display: flex; justify-content: space-between; align-items: center; gap: 10px; color: var(--accent); font-size: var(--fs-small); }
.section-heading h3 { margin-bottom: 0; color: var(--text); }
blockquote { margin: 12px 0; padding-left: 12px; border-left: 2px solid var(--accent); color: var(--text); font-size: var(--fs-body); line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.muted { color: var(--muted); font-size: var(--fs-small); line-height: 1.8; }
.source-id { display: block; margin: 12px 0; color: var(--muted); font-family: var(--font); font-size: var(--fs-small); line-height: 1.65; overflow-wrap: anywhere; }
.reading-tags { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0 0 12px; padding: 16px; border-radius: var(--radius-card); background: var(--raised); }
.reading-tags > div:last-child { grid-column: 1 / -1; }
.source-tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.source-tabs button { min-height: 36px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--surface); color: var(--muted); cursor: pointer; font: inherit; font-size: var(--fs-small); }
.source-tabs button.active { border-color: var(--control); background: var(--active); color: var(--text); }
.source-tabs button:hover { border-color: var(--control); }
.source-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 16px; color: var(--muted); font-size: var(--fs-small); line-height: 1.7; }
.source-url { margin: 12px 0; font-size: var(--fs-small); line-height: 1.7; }
.source-preview { max-height: 520px; padding: 16px; overflow-y: auto; border-radius: var(--radius-card); background: var(--raised); color: var(--text); font: var(--fs-body)/1.9 var(--font); white-space: pre-wrap; overflow-wrap: anywhere; }
mark { border-radius: 2px; background: var(--active); color: var(--text); }
.error-message { padding: 12px; border-radius: var(--radius-control); background: var(--negative-soft); color: var(--negative-ink); font-size: var(--fs-small); line-height: 1.8; }
.evidence-records { margin-top: 24px; font-size: var(--fs-body); }
summary { min-height: 36px; padding: 8px 0; color: var(--text); cursor: pointer; }
.evidence-card { display: block; width: 100%; margin-top: 12px; padding: 14px; text-align: left; border: 1px solid var(--border); border-radius: var(--radius-card); background: var(--surface); color: var(--text); cursor: pointer; font: inherit; }
.evidence-card:hover { border-color: var(--control); }
.evidence-card span, .evidence-card small { display: block; color: var(--muted); font-size: var(--fs-small); line-height: 1.7; }
.evidence-card q { display: block; margin: 10px 0; font-size: var(--fs-body); line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 640px) {
  .text-button, .source-tabs button, summary { min-height: 44px; }
  .external-links a { display: inline-flex; align-items: center; min-height: 44px; }
  .paper-detail-title { font-size: var(--fs-reading); }
}
</style>

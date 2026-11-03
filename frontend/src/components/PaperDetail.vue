<template>
  <article class="paper-detail">
    <button class="text-button back-link" @click="$emit('back')">← 返回文献列表</button>
    <div class="eyebrow">论文 · 本次运行快照</div>
    <h2>{{ detail.paper.title }}</h2>
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
      <div class="reading-tags">
        <span>元数据 {{ countReadable('metadata') ? '已保存' : '未读取' }}</span>
        <span>摘要 {{ countReadable('abstract') ? '已保存' : '未读取 / 缺失' }}</span>
        <span>全文 {{ countReadable('fulltext') }} 个可读页快照</span>
      </div>
      <p class="muted">仅代表保存的来源与页，不表示阅读全文。下载失败、扫描页、截断与解析状态按原记录展示；不提供 OCR。</p>
    </section>

    <section v-if="detail.sources.length" class="saved-sources">
      <h3>来源快照</h3>
      <div class="source-tabs" aria-label="选择来源快照">
        <button v-for="source in detail.sources" :key="source.id" :class="{ active: selectedSourceId === source.id }" @click="selectedSourceId = source.id">
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
        <pre v-if="selectedSource.content" class="source-preview"><template v-if="highlight"><span>{{ highlight.before }}</span><mark>{{ highlight.quote }}</mark><span>{{ highlight.after }}</span></template><template v-else>{{ selectedSource.content }}</template></pre>
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
.paper-detail { min-width: 0; }
h2 { margin: 10px 0; font-size: 19px; letter-spacing: -.025em; line-height: 1.45; }
h3 { font-size: 13px; margin: 0 0 12px; }
.eyebrow { color: #697873; font-size: 10px; letter-spacing: .08em; margin-top: 24px; }
.paper-authors { font-size: 12px; color: #687570; line-height: 1.7; }
.metadata-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 22px 0; }
.metadata-grid .wide { grid-column: 1 / -1; }
dt { color: #79857e; font-size: 10px; margin-bottom: 5px; }
dd { margin: 0; font-size: 12px; overflow-wrap: anywhere; }
.external-links { display: flex; gap: 18px; font-size: 12px; }
a { color: #256650; text-decoration: none; overflow-wrap: anywhere; } a:hover { text-decoration: underline; }
.back-link { margin: 0 0 5px; }
.text-button { background: none; padding: 0; border: 0; color: #65776e; cursor: pointer; font: inherit; font-size: 12px; }
.citation-focus, .reading-summary, .saved-sources { margin-top: 28px; }
.citation-focus { background: #f1f6ef; padding: 17px; border: 1px solid #dfe9dc; border-radius: 12px; }
.section-heading { display: flex; justify-content: space-between; gap: 10px; font-size: 11px; color: #61785f; }
blockquote { margin: 12px 0; padding-left: 13px; border-left: 2px solid #8fa989; font-size: 13px; line-height: 1.85; white-space: pre-wrap; overflow-wrap: anywhere; }
.muted { color: #78847d; font-size: 11px; line-height: 1.8; }
.source-id { display: block; color: #7e8983; font-size: 10px; overflow-wrap: anywhere; margin: 12px 0; }
.reading-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.reading-tags span { font-size: 10px; padding: 6px 8px; border: 1px solid #e0e6df; border-radius: 6px; }
.source-tabs { display: flex; flex-wrap: wrap; gap: 5px; }
.source-tabs button { cursor: pointer; background: #f3f5f1; border: 1px solid transparent; color: #69766f; border-radius: 7px; padding: 7px 9px; font-size: 11px; }
.source-tabs button.active { border-color: #a7b9a0; background: #eaf0e7; color: #355a3d; }
.source-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 15px; font-size: 10px; color: #748178; }
.source-url { font-size: 10px; line-height: 1.7; }
.source-preview { padding: 14px; background: #f7f8f4; border: 1px solid #e7eae2; border-radius: 9px; font: 11px/1.9 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 520px; overflow-y: auto; }
mark { background: #dceabe; color: inherit; border-radius: 2px; }
.error-message { color: #a04434; background: #fff0ea; font-size: 11px; line-height: 1.7; padding: 10px; border-radius: 8px; }
.evidence-records { margin-top: 25px; font-size: 12px; } summary { cursor: pointer; color: #66776c; }
.evidence-card { display: block; width: 100%; text-align: left; padding: 14px; margin-top: 10px; border: 1px solid #e3e9df; background: #fff; border-radius: 9px; cursor: pointer; font: inherit; }
.evidence-card span, .evidence-card small { display: block; font-size: 10px; color: #76856e; }
.evidence-card q { display: block; margin: 9px 0; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>

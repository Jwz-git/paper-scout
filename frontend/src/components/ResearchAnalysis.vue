<template>
  <section class="research-analysis" aria-label="研究分析">
    <div class="analysis-heading"><h3>分析与比较</h3><button type="button" @click="load">刷新分析</button></div>
    <p v-if="loading && !data" role="status">正在读取分析…</p>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <template v-if="data">
      <p class="analysis-note">范围修订 {{ data.analysis_revision }}</p>
      <section>
        <h4>子问题覆盖</h4>
        <template v-if="data.assessment">
          <p class="analysis-note">{{ data.assessment.sufficient ? '达到本次操作性门槛' : '仍有证据缺口' }}；规则 {{ data.assessment.rule }}</p>
          <dl><div v-for="(ids, subproblem) in data.assessment.supporting_papers" :key="subproblem"><dt>{{ subproblem }}</dt><dd>{{ ids.length }} 个有依据的论文组</dd></div></dl>
          <details><summary>约定字段的有证据数量</summary><dl><div v-for="(count, id) in data.assessment.field_counts" :key="id"><dt><button class="paper-link" @click="$emit('paper', id)">{{ title(id) }}</button></dt><dd>{{ count[0] }} / {{ count[1] }}</dd></div></dl></details>
          <ul class="analysis-list"><li v-for="gap in data.assessment.gaps" :key="gap">{{ gap }}</li></ul>
          <details v-if="data.assessment.next_actions.length"><summary>缺口对应的后续动作</summary><ul class="analysis-list"><li v-for="action in data.assessment.next_actions" :key="action">{{ action }}</li></ul></details>
        </template>
        <p v-else class="analysis-note">尚未完成本轮评估。</p>
      </section>
      <section>
        <h4>筛选记录</h4>
        <p v-if="!data.selections.length" class="analysis-note">尚无筛选记录。</p>
        <details v-for="selection in data.selections" :key="selection.paper_id" class="selection-row">
          <summary><span>{{ selection.reviewed ? selection.relevant ? '纳入' : '排除' : '未审阅' }}</span>{{ title(selection.paper_id) }}</summary>
          <p>{{ selection.reason }}</p><p class="analysis-note">对应子问题：{{ selection.subproblems.join('、') || '无' }}</p>
          <button class="paper-link" @click="$emit('paper', selection.paper_id)">查看论文与筛选依据</button>
        </details>
      </section>
      <section>
        <h4>实验条件比较</h4>
        <div v-if="data.assessment?.comparisons.length" class="comparison-scroll" tabindex="0" role="region" aria-label="实验比较表">
          <table><thead><tr><th>论文与指标值</th><th>可比性与依据</th></tr></thead><tbody>
            <tr v-for="(comparison, index) in data.assessment.comparisons" :key="index">
              <td><p><button class="paper-link" @click="$emit('paper', comparison.left_paper_id)">{{ title(comparison.left_paper_id) }}</button><br>{{ comparison.left_value ?? '缺失' }}</p><p><button class="paper-link" @click="$emit('paper', comparison.right_paper_id)">{{ title(comparison.right_paper_id) }}</button><br>{{ comparison.right_value ?? '缺失' }}</p><small>{{ comparison.metric || '指标缺失' }}</small></td>
              <td><strong>{{ comparisonLabels[comparison.status] }}</strong><ul><li v-for="reason in comparison.reasons" :key="reason">{{ reason }}</li></ul><button class="paper-link" @click="$emit('paper', comparison.left_paper_id, comparison.evidence_ids[0])">打开原文依据</button></td>
            </tr>
          </tbody></table>
        </div>
        <p v-else class="analysis-note">暂无同指标的跨论文实验对。</p>
        <details v-if="data.assessment?.duplicate_candidates.length"><summary>疑似重复，尚未合并</summary><p v-for="(pair, index) in data.assessment.duplicate_candidates" :key="index">{{ pair.map(title).join(' / ') }}</p></details>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue';
import { getResearchAnalysis, type ResearchAnalysis, type Run } from '../api/client';
import { comparisonLabels } from '../analysisLabels';
const props = defineProps<{ run: Run }>();
defineEmits<{ paper: [paperId: string, evidenceId?: string] }>();
const data = ref<ResearchAnalysis | null>(null);
const loading = ref(false);
const error = ref('');
let controller: AbortController | null = null;
let key = '';
const title = (id: string) => data.value?.papers.find(paper => paper.id === id)?.title || id;
async function load() {
  controller?.abort();
  const current = new AbortController(); controller = current;
  const nextKey = `${props.run.id}:${props.run.analysis_revision}`;
  if (key !== nextKey) data.value = null;
  key = nextKey; loading.value = true; error.value = '';
  try { const result = await getResearchAnalysis(props.run.id, current.signal); if (!current.signal.aborted) data.value = result; }
  catch (cause) { if (!current.signal.aborted) error.value = cause instanceof Error ? cause.message : '未能读取分析，请重试。'; }
  finally { if (!current.signal.aborted) loading.value = false; }
}
// 分析只在阶段、轮次或状态变化时产生；轮询中的调用计数变化不重新读取。
watch(() => [props.run.id, props.run.analysis_revision, props.run.stage, props.run.current_round, props.run.status], load, { immediate: true });
onUnmounted(() => controller?.abort());
</script>

<style scoped>
.research-analysis { color: var(--text); font-size: var(--fs-body); line-height: 1.75; overflow-wrap: anywhere; }
.analysis-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
h3 { font-size: 18px; font-weight: 500; margin: 18px 0; } h4 { font-size: 16px; font-weight: 500; margin: 0 0 12px; }
section section { padding: 24px 0; border-top: 1px solid var(--border); }
button { font: inherit; color: var(--text); cursor: pointer; background: none; border: 0; min-height: 36px; padding: 4px 0; text-align: left; }
button:hover { text-decoration: underline; } button:focus-visible, summary:focus-visible, .comparison-scroll:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.analysis-note, small { color: var(--muted); font-size: var(--fs-small); }
dl { margin: 14px 0; } dl > div { display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; } dd { margin: 0; flex-shrink: 0; font-variant-numeric: tabular-nums; }
.analysis-list { padding-left: 20px; } li { margin: 5px 0; }
summary { padding: 8px 0; cursor: pointer; } .selection-row { padding: 8px 0; border-bottom: 1px solid var(--border); } summary span { margin-right: 12px; color: var(--muted); font-size: var(--fs-small); }
.comparison-scroll { overflow-x: auto; } table { border-collapse: collapse; width: 100%; min-width: 360px; text-align: left; font-size: var(--fs-small); } th { font-weight: 500; } th, td { padding: 12px 8px; border-bottom: 1px solid var(--border); vertical-align: top; } td { width: 50%; } td p { margin: 0 0 12px; } td ul { padding-left: 16px; }
@media(max-width: 640px) { button, summary { min-height: 44px; } dl > div { display: block; } table { min-width: 0; table-layout: fixed; } th, td { padding: 10px 4px; } }
</style>

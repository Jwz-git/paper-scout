<template>
  <section class="research-usage">
    <div class="settings-section-heading"><div><h3>研究与用量</h3><p>查看对话消耗，了解每次调研的执行范围。</p></div></div>
    <nav class="usage-view-switch" aria-label="用量视图"><button type="button" :aria-pressed="view === 'usage'" @click="view = 'usage'">用量概览</button><button type="button" :aria-pressed="view === 'limits'" @click="view = 'limits'">执行上限</button></nav>

    <div v-if="view === 'usage'" class="usage-overview">
      <div v-if="!conversation" class="usage-empty"><span><UiIcon name="chart" /></span><h4>选择对话后查看用量</h4><p>从侧栏打开已保存的对话，<br />即可查看对话和各次调研的消耗。</p><button type="button" class="settings-secondary" @click="emit('close')">返回对话<UiIcon name="arrowRight" /></button></div>
      <template v-else>
        <div class="usage-context"><UiIcon name="chat" /><div><span>当前对话</span><h4 :title="conversation.task.title || conversation.task.topic">{{ conversation.task.title || conversation.task.topic }}</h4></div><span v-if="conversation.busy" class="usage-live"><i></i>处理中</span></div>

        <section class="usage-section" aria-labelledby="conversation-usage-title">
          <div class="usage-section-heading"><h4 id="conversation-usage-title">对话消耗</h4><span>本会话累计</span></div>
          <p class="usage-description">意图理解、需求澄清和资料问答的模型用量。</p>
          <div class="usage-meters" aria-label="对话用量">
            <div v-for="metric in conversationMetrics" :key="metric.label" class="usage-meter">
              <div class="usage-meter-title"><span>{{ metric.label }}</span><span :class="{ 'usage-reached': metric.used >= metric.limit }">{{ metric.used >= metric.limit ? '已达上限' : `剩余 ${formatMetric(metric.limit - metric.used, metric.time)}` }}</span></div>
              <div class="usage-meter-value"><strong>{{ formatMetric(metric.used, metric.time) }}</strong><span>/ {{ formatMetric(metric.limit, metric.time) }}</span></div>
              <div class="usage-track" role="progressbar" :aria-label="`对话${metric.label}`" aria-valuemin="0" :aria-valuemax="metric.limit" :aria-valuenow="Math.min(metric.used, metric.limit)" :aria-valuetext="`${formatMetric(metric.used, metric.time)}，上限 ${formatMetric(metric.limit, metric.time)}`"><span :style="{ width: percent(metric.used, metric.limit) }" :class="{ 'usage-reached': metric.used >= metric.limit }"></span></div>
            </div>
          </div>
          <dl class="usage-token-row" aria-label="对话 Token"><div><dt>Token 总量</dt><dd>{{ token(conversation.usage.token_usage.total_tokens) }}</dd></div><div><dt>输入 Token</dt><dd>{{ token(conversation.usage.token_usage.prompt_tokens) }}</dd></div><div><dt>输出 Token</dt><dd>{{ token(conversation.usage.token_usage.completion_tokens) }}</dd></div></dl>
        </section>

        <section class="usage-section usage-research" aria-labelledby="research-usage-title">
          <div class="usage-section-heading"><h4 id="research-usage-title">调研消耗</h4><span>{{ runs.length }} 次调研</span></div>
          <p v-if="!runs.length" class="usage-no-runs">此对话尚未发起调研，后续记录会显示在这里。</p>
          <template v-else-if="selectedRun">
            <label class="usage-run-label" for="usage-run-select">查看调研</label>
            <select id="usage-run-select" v-model="selectedRunId" class="usage-run-select"><option v-for="(run, index) in runs" :key="run.id" :value="run.id">第 {{ runs.length - index }} 次调研 · {{ date(run.created_at) }} · {{ runLabels[run.status] }}</option></select>
            <div class="usage-run-status"><span>{{ runLabels[selectedRun.status] }}</span><span v-if="['queued', 'running', 'pause_requested'].includes(selectedRun.status)">{{ stageLabels[selectedRun.stage] }}</span><span>当前第 {{ selectedRun.current_round }} / {{ selectedRun.max_rounds }} 轮</span></div>
            <div class="usage-meters" aria-label="调研用量">
              <div v-for="metric in researchMetrics" :key="metric.label" class="usage-meter">
                <div class="usage-meter-title"><span>{{ metric.label }}</span><span :class="{ 'usage-reached': metric.used >= metric.limit }">{{ metric.used >= metric.limit ? '已达上限' : `剩余 ${formatMetric(metric.limit - metric.used, metric.time)}` }}</span></div>
                <div class="usage-meter-value"><strong>{{ formatMetric(metric.used, metric.time) }}</strong><span>/ {{ formatMetric(metric.limit, metric.time) }}</span></div>
                <div class="usage-track" role="progressbar" :aria-label="`调研${metric.label}`" aria-valuemin="0" :aria-valuemax="metric.limit" :aria-valuenow="Math.min(metric.used, metric.limit)" :aria-valuetext="`${formatMetric(metric.used, metric.time)}，上限 ${formatMetric(metric.limit, metric.time)}`"><span :style="{ width: percent(metric.used, metric.limit) }" :class="{ 'usage-reached': metric.used >= metric.limit }"></span></div>
              </div>
            </div>
            <div class="usage-run-note"><span>其中模型调用 <strong>{{ token(selectedRun.model_calls) }} 次</strong></span><span>外部调用包含模型、检索及全文请求。</span></div>
            <dl class="usage-token-row" aria-label="调研 Token"><div><dt>Token 总量</dt><dd>{{ token(selectedRun.token_usage?.total_tokens) }}</dd></div><div><dt>输入 Token</dt><dd>{{ token(selectedRun.token_usage?.prompt_tokens) }}</dd></div><div><dt>输出 Token</dt><dd>{{ token(selectedRun.token_usage?.completion_tokens) }}</dd></div></dl>
            <p v-if="selectedRun.stop_reason" class="usage-stop-reason"><UiIcon name="info" /><span>{{ selectedRun.stop_reason }}</span></p>
          </template>
        </section>
        <p class="usage-scope-note">仅统计当前对话，对话与调研分开计量。数值随已保存的执行记录更新。</p>
      </template>
    </div>

    <div v-else class="usage-limits">
      <p class="usage-limits-intro">服务端提供的执行上限，当前仅供查看。已有对话和调研的实际上限可在用量概览中查看。</p>
      <section v-for="scope in limitScopes" :key="scope.title" class="usage-limit-section">
        <div class="usage-limit-heading"><span><UiIcon :name="scope.icon" /></span><div><h4>{{ scope.title }}</h4><p>{{ scope.description }}</p></div></div>
        <dl class="usage-limit-rows"><div v-for="item in scope.items" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl>
      </section>
    </div>

    <details class="usage-accounting"><summary><UiIcon name="info" /><span>用量如何计算</span><UiIcon name="chevronDown" /></summary><ul><li>暂停等待不计入实际执行时间；已发出的失败请求仍计入调用次数。</li><li>Token 显示“未知”表示未取得完整统计，不会按 0 计入。</li><li>切换模型、暂停或继续研究，都不会重置累计用量。</li><li>执行上限用于控制资源消耗，不代表研究质量；这里不估算费用。</li></ul></details>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { ConversationView, ModelSettings } from '../api/client';
import { runLabels, stageLabels } from '../runLabels';
import UiIcon from './UiIcon.vue';

const props = defineProps<{ conversation?: ConversationView; limits: ModelSettings['limits'] }>();
const emit = defineEmits<{ close: [] }>();
const view = ref<'usage' | 'limits'>(props.conversation ? 'usage' : 'limits');
const runs = computed(() => [...(props.conversation?.runs || [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id)));
const selectedRunId = ref('');
const selectedRun = computed(() => runs.value.find(run => run.id === selectedRunId.value));
watch(() => [props.conversation?.task.id, ...runs.value.map(run => run.id)], () => {
  if (!runs.value.some(run => run.id === selectedRunId.value)) selectedRunId.value = runs.value[0]?.id || '';
}, { immediate: true });

const token = (value?: number | null) => value == null ? '未知' : value.toLocaleString();
const date = (value: string) => new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
function duration(seconds: number) {
  const rounded = Math.round(seconds * 10) / 10;
  if (rounded < 60) return `${rounded} 秒`;
  const minutes = Math.floor(rounded / 60), rest = Math.round((rounded % 60) * 10) / 10;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`;
}
const formatMetric = (value: number, time: boolean) => time ? duration(value) : `${value.toLocaleString()} 次`;
const percent = (used: number, limit: number) => `${Math.min(100, used / limit * 100)}%`;
const conversationMetrics = computed(() => props.conversation ? [
  { label: '模型调用', used: props.conversation.usage.model_calls, limit: props.conversation.usage.max_calls, time: false },
  { label: '执行时间', used: props.conversation.usage.total_execution_seconds, limit: props.conversation.usage.max_seconds, time: true },
] : []);
const researchMetrics = computed(() => selectedRun.value ? [
  { label: '外部调用', used: selectedRun.value.total_calls, limit: selectedRun.value.max_calls, time: false },
  { label: '执行时间', used: selectedRun.value.total_execution_seconds, limit: selectedRun.value.max_seconds, time: true },
] : []);
const limitScopes = computed(() => [
  { title: '每个对话', icon: 'chat' as const, description: '意图理解、澄清与问答累计计算。', items: [
    { label: '模型调用', value: `${props.limits.conversation.max_calls} 次` },
    { label: '实际执行时间', value: duration(props.limits.conversation.max_seconds) },
  ] },
  { title: '每次调研', icon: 'book' as const, description: '每次新调研独立计量，同次继续保留累计消耗。', items: [
    { label: '迭代轮次', value: `${props.limits.research.max_rounds} 轮` },
    { label: '外部调用', value: `${props.limits.research.max_calls} 次` },
    { label: '实际执行时间', value: duration(props.limits.research.max_seconds) },
  ] },
]);
</script>
<style src="./research-usage.css"></style>

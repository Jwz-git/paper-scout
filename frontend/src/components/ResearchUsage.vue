<template>
  <section class="research-usage">
    <div class="settings-section-heading"><div><h3>研究与用量</h3><p>查看对话消耗和每轮执行上限。</p></div></div>
    <nav class="usage-view-switch" aria-label="用量视图"><button type="button" :aria-pressed="view === 'usage'" @click="view = 'usage'">用量概览</button><button type="button" :aria-pressed="view === 'limits'" @click="view = 'limits'">执行上限</button></nav>

    <div v-if="view === 'usage'" class="usage-overview">
      <div v-if="!conversation" class="usage-empty"><span><UiIcon name="chart" /></span><h4>选择对话后查看用量</h4><p>从侧栏打开已保存的对话，<br />即可查看对话和各次调研的消耗。</p><button type="button" class="settings-secondary" @click="emit('close')">返回对话<UiIcon name="arrowRight" /></button></div>
      <template v-else>
        <div class="usage-context"><UiIcon name="chat" /><div><span>当前对话</span><h4 :title="conversation.task.title || conversation.task.topic">{{ conversation.task.title || conversation.task.topic }}</h4></div><span v-if="conversation.busy" class="usage-live"><i></i>处理中</span></div>

        <section class="usage-section" aria-labelledby="conversation-usage-title">
          <div class="usage-section-heading"><h4 id="conversation-usage-title">对话消耗</h4><span>本会话累计</span></div>
          <p class="usage-description">本对话各轮工作的模型用量，含阅读子 agent。</p>
          <dl class="usage-token-row usage-totals" aria-label="对话用量"><div><dt>模型调用</dt><dd>{{ formatMetric(conversation.usage.model_calls, false) }}</dd></div><div><dt>执行时间</dt><dd>{{ duration(conversation.usage.total_execution_seconds) }}</dd></div></dl>
          <dl class="usage-token-row" aria-label="对话 Token"><div><dt>Token 总量</dt><dd>{{ token(conversation.usage.token_usage.total_tokens) }}</dd></div><div><dt>输入 Token</dt><dd>{{ token(conversation.usage.token_usage.prompt_tokens) }}</dd></div><div><dt>输出 Token</dt><dd>{{ token(conversation.usage.token_usage.completion_tokens) }}</dd></div></dl>
        </section>

        <section class="usage-section usage-research" aria-labelledby="research-usage-title">
          <div class="usage-section-heading"><h4 id="research-usage-title">调研消耗</h4><span v-if="runs.length > 1">{{ runs.length }} 份记录</span></div>
          <p v-if="!runs.length" class="usage-no-runs">此对话尚未发起调研，后续记录会显示在这里。</p>
          <template v-else-if="selectedRun">
            <template v-if="runs.length > 1">
              <label class="usage-run-label" for="usage-run-select">查看调研</label>
              <select id="usage-run-select" v-model="selectedRunId" class="usage-run-select"><option v-for="run in runs" :key="run.id" :value="run.id">{{ run.agent ? '对话 agent · 累计' : `第 ${legacyNumber(run.id)} 次调研 · ${date(run.created_at)} · ${runLabels[run.status]}` }}</option></select>
            </template>
            <template v-if="selectedRun.agent">
              <dl class="usage-token-row usage-totals usage-agent-totals" aria-label="调研用量"><div><dt>外部调用</dt><dd>{{ formatMetric(selectedRun.total_calls, false) }}</dd></div><div><dt>模型调用</dt><dd>{{ formatMetric(selectedRun.model_calls, false) }}</dd></div><div><dt>执行时间</dt><dd>{{ duration(selectedRun.total_execution_seconds) }}</dd></div></dl>
              <div class="usage-run-note"><span>外部调用包含模型、检索及全文请求。</span></div>
            </template>
            <template v-else>
              <div class="usage-run-status"><span>{{ runLabels[selectedRun.status] }}</span><span>当前第 {{ selectedRun.current_round }} / {{ selectedRun.max_rounds }} 轮</span></div>
              <div class="usage-meters" aria-label="调研用量">
                <div v-for="metric in researchMetrics" :key="metric.label" class="usage-meter">
                  <div class="usage-meter-title"><span>{{ metric.label }}</span><span :class="{ 'usage-reached': metric.used >= metric.limit }">{{ metric.used >= metric.limit ? '已达上限' : `剩余 ${formatMetric(metric.limit - metric.used, metric.time)}` }}</span></div>
                  <div class="usage-meter-value"><strong>{{ formatMetric(metric.used, metric.time) }}</strong><span>/ {{ formatMetric(metric.limit, metric.time) }}</span></div>
                  <div class="usage-track" role="progressbar" :aria-label="`调研${metric.label}`" aria-valuemin="0" :aria-valuemax="metric.limit" :aria-valuenow="Math.min(metric.used, metric.limit)" :aria-valuetext="`${formatMetric(metric.used, metric.time)}，上限 ${formatMetric(metric.limit, metric.time)}`"><span :style="{ width: percent(metric.used, metric.limit) }" :class="{ 'usage-reached': metric.used >= metric.limit }"></span></div>
                </div>
              </div>
              <div class="usage-run-note"><span>其中模型调用 <strong>{{ token(selectedRun.model_calls) }} 次</strong></span><span>外部调用包含模型、检索及全文请求。</span></div>
            </template>
            <dl class="usage-token-row" aria-label="调研 Token"><div><dt>Token 总量</dt><dd>{{ token(selectedRun.token_usage?.total_tokens) }}</dd></div><div><dt>输入 Token</dt><dd>{{ token(selectedRun.token_usage?.prompt_tokens) }}</dd></div><div><dt>输出 Token</dt><dd>{{ token(selectedRun.token_usage?.completion_tokens) }}</dd></div></dl>
            <p v-if="selectedRun.stop_reason" class="usage-stop-reason"><UiIcon name="info" /><span>{{ selectedRun.stop_reason }}</span></p>
          </template>
        </section>
        <p class="usage-scope-note">仅统计当前对话。数值随已保存的执行记录更新。</p>
      </template>
    </div>

    <div v-else class="usage-limits">
      <p class="usage-limits-intro">执行上限由服务端设置，此处只读。</p>
      <section v-for="scope in limitScopes" :key="scope.title" class="usage-limit-section">
        <div class="usage-limit-heading"><span><UiIcon :name="scope.icon" /></span><div><h4>{{ scope.title }}</h4><p>{{ scope.description }}</p></div></div>
        <dl class="usage-limit-rows"><div v-for="item in scope.items" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl>
      </section>
    </div>

    <details class="usage-accounting"><summary><UiIcon name="info" /><span>用量如何计算</span><UiIcon name="chevronDown" /></summary><ul><li>已发出的失败请求仍计入调用次数。</li><li>Token 显示“未知”表示服务未返回完整统计。</li><li>切换模型或停止回合都不会重置累计用量。</li></ul></details>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { ConversationView, ModelSettings } from '../api/client';
import { runLabels } from '../runLabels';
import UiIcon from './UiIcon.vue';

const props = defineProps<{ conversation?: ConversationView; limits: ModelSettings['limits'] }>();
const emit = defineEmits<{ close: [] }>();
const view = ref<'usage' | 'limits'>(props.conversation ? 'usage' : 'limits');
const runs = computed(() => [...(props.conversation?.runs || [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id)));
const legacyRuns = computed(() => runs.value.filter(run => !run.agent));
const legacyNumber = (id: string) => legacyRuns.value.length - legacyRuns.value.findIndex(run => run.id === id);
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
const researchMetrics = computed(() => selectedRun.value ? [
  { label: '外部调用', used: selectedRun.value.total_calls, limit: selectedRun.value.max_calls, time: false },
  { label: '执行时间', used: selectedRun.value.total_execution_seconds, limit: selectedRun.value.max_seconds, time: true },
] : []);
const limitScopes = computed(() => {
  const limits = props.limits.agent;
  return [
    { title: '每轮工作', icon: 'chat' as const, description: '从一条消息开始到回复为止；执行中补充的消息并入同一轮，阅读子 agent 共用本轮额度。', items: [
      { label: '步数', value: `${limits.steps} 步` },
      { label: '外部调用', value: `${limits.calls} 次` },
      { label: '执行时间', value: duration(limits.seconds) },
      { label: '全文下载', value: `${limits.fulltexts} 篇` },
      { label: '同时阅读的子 agent', value: `${limits.readers} 个` },
      { label: '每个子 agent 步数', value: `${limits.reader_steps} 步` },
    ] },
  ];
});
</script>
<style src="./research-usage.css"></style>

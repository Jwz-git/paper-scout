<template>
  <Teleport to="body">
    <div v-if="open" class="settings-overlay" @click.self="close">
      <section ref="dialog" class="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <aside class="settings-nav">
          <div class="settings-brand"><UiIcon name="settings" /><h2 id="settings-title">设置</h2></div>
          <nav aria-label="设置分类">
            <button type="button" :class="{ active: tab === 'general' }" :aria-current="tab === 'general' ? 'page' : undefined" @click="tab = 'general'"><UiIcon name="layout" />通用<UiIcon name="chevronRight" /></button>
            <button type="button" :disabled="saving" :class="{ active: tab === 'model' }" :aria-current="tab === 'model' ? 'page' : undefined" @click="tab = 'model'"><UiIcon name="model" />AI服务<UiIcon name="chevronRight" /></button>
            <button type="button" :class="{ active: tab === 'appearance' }" :aria-current="tab === 'appearance' ? 'page' : undefined" @click="tab = 'appearance'"><UiIcon name="sun" />外观<UiIcon name="chevronRight" /></button>
            <button type="button" :class="{ active: tab === 'data' }" :aria-current="tab === 'data' ? 'page' : undefined" @click="tab = 'data'"><UiIcon name="database" />数据管理<UiIcon name="chevronRight" /></button>
            <button type="button" :disabled="saving" :class="{ active: tab === 'limits' }" :aria-current="tab === 'limits' ? 'page' : undefined" @click="tab = 'limits'"><UiIcon name="chart" />研究与用量<UiIcon name="chevronRight" /></button>
          </nav>
        </aside>
        <div class="settings-main">
          <header class="settings-header">
            <button ref="closeButton" class="icon-button" type="button" aria-label="关闭设置" @click="close"><UiIcon name="close" /></button>
          </header>
          <div class="settings-scroll">
            <section v-if="tab === 'general'" class="general-settings">
              <div class="settings-section-heading"><div><h3>通用</h3><p>调整对话习惯，选择后即时生效。</p></div></div>
              <div class="preference-row"><label for="send-shortcut"><strong>发送快捷键</strong><small>{{ preferences.sendShortcut === 'enter' ? 'Enter 发送，Shift + Enter 换行。' : 'Ctrl / ⌘ + Enter 发送，Enter 换行。' }}</small></label><select id="send-shortcut" v-model="preferences.sendShortcut"><option value="enter">Enter</option><option value="modifier-enter">Ctrl / ⌘ + Enter</option></select></div>
              <div class="preference-row"><label for="default-message-mode"><strong>默认消息模式</strong><small>用于尚未手动选择模式的对话。输入区仍可单独切换。</small></label><select id="default-message-mode" v-model="preferences.defaultMode"><option value="auto">自动理解</option><option value="research">补充检索</option><option value="ask">只问已有资料</option></select></div>
              <label class="preference-row preference-toggle"><span><strong>自动跟随最新消息</strong><small>在底部阅读时跟随更新；向上查看历史时不会打断。</small></span><input v-model="preferences.autoScroll" type="checkbox" role="switch" aria-label="自动跟随最新消息" /><span class="settings-switch" aria-hidden="true"></span></label>
              <div class="settings-inline-note"><UiIcon name="info" /><p>“只问已有资料”不会发起新检索；新对话还没有来源时，请先使用自动理解或补充检索。</p></div>
            </section>
            <section v-else-if="tab === 'appearance'" class="appearance-settings">
              <div class="settings-section-heading"><div><h3>外观</h3><p>选择适合你的阅读方式。</p></div></div>
              <fieldset class="theme-options"><legend>主题模式</legend>
                <label v-for="option in themeOptions" :key="option.value" class="theme-option" :class="{ selected: theme === option.value }"><UiIcon :name="option.icon" /><span><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span><input v-model="theme" type="radio" name="appearance-theme" :value="option.value" :aria-label="option.label" /></label>
              </fieldset>
              <p class="appearance-status">{{ theme === 'system' ? `当前系统为${systemDark ? '暗色' : '亮色'}，界面会自动同步。` : `当前使用${resolvedTheme === 'dark' ? '暗色' : '亮色'}主题。` }}</p>
              <div class="preference-row"><label for="reading-text-size"><strong>对话字号</strong><small>调整消息正文和输入框的文字大小。</small></label><select id="reading-text-size" v-model="preferences.textSize"><option value="small">小 · 14px</option><option value="standard">标准 · 15px</option><option value="large">大 · 17px</option></select></div>
              <div class="preference-row"><label for="reading-width"><strong>对话宽度</strong><small>宽屏下的最大阅读区域，窄屏自动适应。</small></label><select id="reading-width" v-model="preferences.readingWidth"><option value="standard">标准</option><option value="wide">宽松</option></select></div>
              <div class="reading-preview"><span>阅读预览</span><p>从一个问题开始，让讨论逐渐清晰。</p><small>研究资料和引用仍可按需打开。</small></div>
            </section>
            <section v-else-if="tab === 'data'" class="data-settings">
              <div class="settings-section-heading"><div><h3>数据管理</h3><p>导出当前对话，管理已删除记录与界面偏好。</p></div></div>
              <div class="settings-data-block"><h4>导出当前对话</h4><p class="export-conversation-title">{{ conversation ? conversation.task.title || conversation.task.topic : '尚未选择已保存的对话' }}</p><p>{{ conversation ? `${conversation.messages.length} 条消息 · ${conversation.runs.length} 次研究运行` : '在侧栏选择一个对话后，即可导出。' }}</p><div class="settings-data-actions"><button type="button" :disabled="!conversation" @click="downloadConversation('markdown')"><UiIcon name="download" />导出 Markdown</button><button type="button" :disabled="!conversation" @click="downloadConversation('json')"><UiIcon name="download" />导出 JSON</button></div><p class="field-help">包含已加载的消息与引用。JSON 另含运行信息和用量；不含论文全文、报告文件、模型配置或未发送草稿。研究报告可在资料区单独下载。</p><p v-if="exportMessage" class="data-export-status" role="status">{{ exportMessage }}</p><p v-if="exportError" class="settings-error" role="alert">{{ exportError }}</p></div>
              <div class="preference-row"><div><strong>对话回收站</strong><small>集中查看、批量恢复或彻底删除已删除的对话。</small></div><button type="button" class="settings-secondary" @click="emit('openTrash')">打开回收站<UiIcon name="chevronRight" /></button></div>
              <div class="preference-row"><div><strong>恢复默认偏好</strong><small>重置主题、阅读和对话选项；对话、模型配置与密钥保留。</small></div><button type="button" class="settings-secondary" @click="resetOpen = true">恢复默认</button></div>
              <div class="settings-inline-note"><UiIcon name="shield" /><p>对话和模型配置保存在运行服务的本机；浏览器仅保存界面偏好。使用模型时，问题和相关来源片段会发送至你填写的服务地址。</p></div>
            </section>
            <template v-else>
            <div v-if="loading" class="settings-loading" role="status"><UiIcon name="refresh" />正在读取本机设置…</div>
            <div v-if="loadError" class="settings-error" role="alert"><UiIcon name="info" /><div><strong>暂时无法读取设置</strong><p>{{ loadError }}</p><button type="button" class="text-button" @click="load">重新读取</button></div></div>
            <template v-if="settings && !loading">
              <section v-if="tab === 'model'" class="model-services">
                <div class="settings-section-heading"><div><h3>AI服务</h3><p>连接供应商，管理可用于对话与研究的模型。</p></div></div>
                <p v-if="message" class="model-operation-success" role="status"><UiIcon name="check" />{{ message }}</p>
                <template v-if="!editorOpen">
                  <div v-if="providers.length" class="model-list-heading"><span>{{ providers.length }} 家供应商</span><button type="button" ref="addModelButton" class="settings-secondary" :disabled="saving" @click="addProvider"><UiIcon name="plus" />添加供应商</button></div>
                  <div v-if="!providers.length" class="model-empty-state"><span class="model-empty-icon"><UiIcon name="network" /></span><h4>添加AI供应商</h4><p>填写供应商的连接信息，<br />获取并选择你要使用的模型。</p><button type="button" ref="addModelButton" class="settings-save" :disabled="saving" @click="addProvider"><UiIcon name="plus" />添加供应商</button></div>
                  <div v-else class="model-list" aria-label="已添加的供应商">
                    <article v-for="provider in providers" :key="provider.id" class="model-list-item provider-list-item" :aria-label="provider.name">
                      <div class="model-item-heading"><span class="model-item-icon"><UiIcon name="network" /></span><div><h4>{{ provider.name }}</h4><p>{{ provider.models.length }} 个模型</p></div></div>
                      <div class="model-item-details"><span>{{ protocolName(provider.protocol) }}</span><span class="model-service-address" :title="provider.base_url">{{ serviceAddress(provider.base_url) }}</span></div>
                      <div class="provider-models-preview"><span v-for="model in provider.models.slice(0, 3)" :key="model" :title="model">{{ model }}</span><small v-if="provider.models.length > 3">另 {{ provider.models.length - 3 }} 个</small></div>
                      <div class="model-item-footer"><span class="model-key-status"><UiIcon name="key" />{{ provider.api_key_set ? '密钥已保存' : '未设置密钥' }}</span><div class="model-item-actions"><button type="button" class="model-edit-button" :aria-label="`编辑供应商：${provider.name}`" :disabled="saving || (settings.busy && isActive(provider))" @click="editProvider(provider)"><UiIcon name="edit" />配置</button><button type="button" class="icon-button model-delete-button" :aria-label="`删除供应商：${provider.name}`" :disabled="saving || (settings.busy && isActive(provider))" @click="removeTarget = provider"><UiIcon name="trash" /></button></div></div>
                    </article>
                  </div>
                </template>
                <form v-else id="model-settings-form" class="model-editor" @submit.prevent="save">
                  <div class="model-editor-heading"><button type="button" class="text-button model-back" :disabled="saving" @click="requestEditorClose"><UiIcon name="arrowLeft" />供应商列表</button><h4>{{ editorKind === 'add' ? '添加供应商' : '配置供应商' }}</h4></div>
                  <fieldset class="model-fields" :disabled="saving">
                    <legend class="sr-only">供应商连接信息</legend>
                    <div class="settings-field"><label for="provider-name">供应商名称 <span>可选</span></label><div class="settings-input-wrap"><input id="provider-name" v-model="form.name" maxlength="80" placeholder="例如：我的 OpenAI 服务" autocomplete="off" /></div></div>
                    <div class="settings-field"><label for="model-protocol">接口类型</label><select id="model-protocol" v-model="form.protocol" class="model-protocol-select"><option v-for="protocol in protocols" :key="protocol.value" :value="protocol.value">{{ protocol.label }}</option></select></div>
                    <div class="settings-field"><label for="model-base-url">服务地址 <span>Base URL</span></label><div class="settings-input-wrap"><input id="model-base-url" v-model="form.base_url" type="url" required maxlength="2000" placeholder="https://your-provider.example/v1" autocomplete="off" spellcheck="false" /></div><p class="field-help">填写服务商提供的 API 根地址，不含具体请求端点。</p></div>
                    <div class="settings-field"><label for="model-api-key">API Key <span v-if="editingProfile?.api_key_set" class="key-saved"><UiIcon name="key" />已保存</span></label><div class="settings-input-wrap"><input id="model-api-key" v-model="form.api_key" :type="showKey ? 'text' : 'password'" :disabled="form.clear_api_key" maxlength="4096" :placeholder="form.clear_api_key ? '保存后清除原密钥' : editingProfile?.api_key_set ? '留空保留原密钥，输入新值可替换' : '服务无需密钥时可留空'" autocomplete="new-password" spellcheck="false" /><button type="button" class="icon-button" :disabled="!form.api_key || form.clear_api_key" :aria-label="showKey ? '隐藏新密钥' : '显示新密钥'" :aria-pressed="showKey" @click="showKey = !showKey"><UiIcon :name="showKey ? 'eyeOff' : 'eye'" /></button></div><div class="key-options"><p class="field-help">密钥仅保存于本机服务端，不会回显。</p><label v-if="editingProfile?.api_key_set" class="clear-key"><input v-model="form.clear_api_key" type="checkbox" @change="form.api_key = ''; showKey = false" />清除原密钥</label></div></div>
                    <div class="settings-field"><div class="model-selection-label"><label for="model-picker-trigger">模型<span>可多选</span></label><button type="button" class="model-fetch-button" :disabled="catalogLoading || !form.base_url.trim() || (addressChanged && editingProfile?.api_key_set && !form.api_key && !form.clear_api_key)" @click="fetchModels(false)"><UiIcon :name="catalogLoading ? 'clock' : 'refresh'" />{{ catalogLoading ? '获取中…' : '获取模型' }}</button></div><ModelPicker v-model="selectedModels" :options="catalogModels" :disabled="saving" :loading="catalogLoading" :has-more="!!catalogCursor" @more="fetchModels(true)" /><p v-if="catalogError" class="model-catalog-status model-catalog-error" role="alert">{{ catalogError }}</p><p v-else-if="catalogLoaded" class="model-catalog-status" role="status">{{ catalogModels.length ? `已获取 ${catalogModels.length} 个模型${catalogCursor ? '，可加载更多' : ''}。` : '服务未返回模型，可手动添加模型 ID。' }}</p></div>
                  </fieldset>
                  <div v-if="addressChanged && editingProfile?.api_key_set" class="settings-notice"><UiIcon name="info" /><p>地址已更改，请重新输入密钥或勾选清除原密钥。</p></div>
                  <p class="model-save-explainer">{{ saveExplainer }}</p>
                  <div class="model-editor-actions"><button type="button" class="settings-secondary" :disabled="saving" @click="requestEditorClose">取消</button><button type="submit" class="settings-save" :disabled="!canSave"><UiIcon :name="saving ? 'refresh' : 'check'" />{{ saving ? '正在保存…' : '保存供应商' }}</button></div>
                </form>
                <div v-if="settings.busy" class="settings-notice"><UiIcon name="clock" /><p>对话执行中，当前这一轮结束或停止后才能修改或删除当前供应商。</p><button type="button" class="text-button" :disabled="saving" @click="refreshBusy">刷新状态</button></div>
                <div v-if="saveError" class="settings-error model-operation-error" role="alert"><UiIcon name="info" /><p>{{ saveError }}</p></div>
                <p v-if="!editorOpen && providers.length" class="settings-privacy"><UiIcon name="shield" />对话内容与相关来源会发送至所选供应商。</p>
              </section>
              <ResearchUsage v-else :conversation="conversation" :limits="settings.limits" @close="close" />
            </template>
            </template>
            <p v-if="localSettingsTab && !localStorageAvailable" class="settings-storage-notice" role="status">浏览器未允许保存，此次选择仅在当前页面生效</p>
          </div>
        </div>
      </section>
    </div>
    <ActionDialog v-if="discardOpen && open" title="放弃本次编辑？" description="尚未保存的修改将被丢弃。" confirm-label="放弃修改" @close="cancelDiscard" @confirm="finishEditing" />
    <ActionDialog v-if="removeTarget && open" title="删除这个供应商？" :description="`将删除“${removeTarget.name}”的连接信息、密钥和 ${removeTarget.models.length} 个已选模型。历史对话和资料保留。${isActive(removeTarget) ? '删除后需要重新选择供应商和模型。' : ''}`" confirm-label="删除供应商" danger :busy="saving" @close="removeTarget = null" @confirm="removeProvider" />
    <ActionDialog v-if="resetOpen && open" title="恢复默认偏好？" description="主题将恢复跟随系统；发送快捷键、默认消息模式、自动滚动、字号和宽度将恢复默认。已保存的对话、模型配置和密钥不受影响。" confirm-label="恢复默认" @close="resetOpen = false" @confirm="restorePreferences" />
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { ApiError, getModelSettings, saveProvider, deleteProvider, type ModelSettings, type AiProvider, type ModelProtocol, type AvailableModel, fetchAvailableModels } from '../api/client';
import UiIcon from './UiIcon.vue';
import ActionDialog from './ActionDialog.vue';
import ResearchUsage from './ResearchUsage.vue';
import ModelPicker from './ModelPicker.vue';
import { useTheme, type ThemePreference } from '../composables/useTheme';
import { usePreferences } from '../composables/usePreferences';
import { exportConversation } from '../conversationExport';
import type { ConversationView } from '../api/client';

const props = defineProps<{ open: boolean; initialTab?: 'general' | 'model'; conversation?: ConversationView }>();
const emit = defineEmits<{ close: []; openTrash: []; saved: [settings: ModelSettings]; busy: [value: boolean]; notice: [message: string, error: boolean] }>();
const tab = ref<'general' | 'model' | 'limits' | 'appearance' | 'data'>('general');
const { theme, resolvedTheme, systemDark, storageAvailable } = useTheme();
const { preferences, preferencesStorageAvailable, resetPreferences } = usePreferences();
const localSettingsTab = computed(() => ['general', 'appearance', 'data'].includes(tab.value));
const localStorageAvailable = computed(() => storageAvailable.value && preferencesStorageAvailable.value);
const resetOpen = ref(false);
const exportMessage = ref('');
const exportError = ref('');
function downloadConversation(format: 'markdown' | 'json') {
  if (!props.conversation) return;
  exportMessage.value = ''; exportError.value = '';
  try { exportConversation(props.conversation, format); exportMessage.value = '已发起下载，请在浏览器下载列表中查看。'; }
  catch { exportError.value = '未能生成导出文件，请重试。'; }
}
function restorePreferences() {
  theme.value = 'system'; resetPreferences(); resetOpen.value = false;
  emit('notice', '界面偏好已恢复默认', false);
}
const themeOptions: { value: ThemePreference; label: string; description: string; icon: 'desktop' | 'sun' | 'moon' }[] = [
  { value: 'system', label: '跟随系统', description: '随设备的外观自动切换', icon: 'desktop' },
  { value: 'light', label: '亮色', description: '明亮纸面，柔和边界', icon: 'sun' },
  { value: 'dark', label: '暗色', description: '低亮度背景，清晰文字', icon: 'moon' },
];
const dialog = ref<HTMLElement | null>(null);
const closeButton = ref<HTMLButtonElement | null>(null);
const settings = ref<ModelSettings | null>(null);
const providers = computed(() => [...(settings.value?.providers || [])].sort((a, b) => Number(isActive(b)) - Number(isActive(a))));
const isActive = (provider?: AiProvider) => !!settings.value?.enabled && provider?.id === settings.value.active_provider_id;
const editorOpen = ref(false);
const editorKind = ref<'add' | 'edit'>('add');
const editingId = ref<string | null>(null);
const editingProfile = computed(() => settings.value?.providers.find(profile => profile.id === editingId.value));
const discardOpen = ref(false);
const removeTarget = ref<AiProvider | null>(null);
const addModelButton = ref<HTMLButtonElement | null>(null);
const loading = ref(false);
const saving = ref(false);
const loadError = ref('');
const saveError = ref('');
const message = ref('');
const showKey = ref(false);
let loadController: AbortController | null = null;
const operationController = new AbortController();
const form = reactive({ name: '', protocol: 'openai_chat' as ModelProtocol, base_url: '', api_key: '', clear_api_key: false });
const selectedModels = ref<string[]>([]);
const catalogModels = ref<AvailableModel[]>([]);
const catalogLoading = ref(false);
const catalogLoaded = ref(false);
const catalogError = ref('');
const catalogCursor = ref<string | null>(null);
let catalogController: AbortController | null = null;
function clearCatalog() { catalogController?.abort(); catalogModels.value = []; catalogCursor.value = null; catalogError.value = ''; catalogLoaded.value = false; catalogLoading.value = false; }
watch(() => [form.protocol, form.base_url, form.api_key, form.clear_api_key], clearCatalog);
async function fetchModels(more: boolean) {
  if (catalogLoading.value || !form.base_url.trim()) return;
  catalogController?.abort(); const controller = new AbortController(); catalogController = controller;
  const payload = { protocol: form.protocol, base_url: form.base_url, api_key: form.api_key || null, clear_api_key: form.clear_api_key, provider_id: editingId.value, cursor: more ? catalogCursor.value : null };
  catalogLoading.value = true; catalogError.value = '';
  if (!more) { catalogModels.value = []; catalogCursor.value = null; catalogLoaded.value = false; }
  try {
    const result = await fetchAvailableModels(payload, controller.signal);
    if (controller.signal.aborted) return;
    catalogModels.value = [...new Map([...(more ? catalogModels.value : []), ...result.models].map(model => [model.id, model])).values()];
    catalogCursor.value = result.next_cursor; catalogLoaded.value = true;
  } catch (cause) { if (!controller.signal.aborted) catalogError.value = cause instanceof Error ? cause.message : '获取模型失败，请重试。'; }
  finally { if (!controller.signal.aborted) catalogLoading.value = false; }
}
const protocols: { value: ModelProtocol; label: string }[] = [
  { value: 'openai_chat', label: 'OpenAI 兼容 · Chat Completions' },
  { value: 'openai_responses', label: 'OpenAI · Responses' },
  { value: 'anthropic_messages', label: 'Anthropic · Messages' },
];
const protocolName = (protocol: ModelProtocol) => protocols.find(item => item.value === protocol)!.label;
const serviceAddress = (value: string) => value.replace(/^https?:\/\//, '').replace(/\/$/, '');
const addressChanged = computed(() => !!editingProfile.value && form.base_url.trim().replace(/\/+$/, '') !== editingProfile.value.base_url);
const affectsCurrent = computed(() => !!(editingProfile.value && isActive(editingProfile.value)));
const dirty = computed(() => {
  const profile = editorKind.value === 'edit' ? editingProfile.value : undefined;
  return !profile ? !!(form.name || form.base_url || selectedModels.value.length || form.api_key) : form.name.trim() !== profile.name || form.protocol !== profile.protocol || addressChanged.value || JSON.stringify(selectedModels.value) !== JSON.stringify(profile.models) || !!form.api_key || form.clear_api_key;
});
const canSave = computed(() => !!settings.value && !loading.value && !saving.value && dirty.value && !!form.base_url.trim() && selectedModels.value.length > 0 && !(settings.value.busy && affectsCurrent.value));
watch([form, selectedModels], () => { message.value = ''; saveError.value = ''; });
const saveExplainer = computed(() => isActive(editingProfile.value) && !selectedModels.value.includes(settings.value!.active_model || '') ? '当前使用的型号已移出。保存后请在对话中重新选择模型。' : `所选 ${selectedModels.value.length} 个模型将显示在对话的模型菜单中。保存供应商不会切换当前模型。`);
function closeEditor() {
  editorOpen.value = false; discardOpen.value = false; editingId.value = null;
  clearCatalog(); selectedModels.value = [];
  Object.assign(form, { name: '', protocol: 'openai_chat', base_url: '', api_key: '', clear_api_key: false });
  showKey.value = false;
}
// 关闭设置时若有未保存的编辑，先确认放弃，确认后再关闭面板。
let closeAfterDiscard = false;
function finishEditing() {
  closeEditor();
  if (closeAfterDiscard) { closeAfterDiscard = false; emit('close'); return; }
  void nextTick(() => addModelButton.value?.focus());
}
function cancelDiscard() { discardOpen.value = false; closeAfterDiscard = false; }
function requestEditorClose() { closeAfterDiscard = false; if (dirty.value) discardOpen.value = true; else finishEditing(); }
function openEditor(profile?: AiProvider) {
  editorKind.value = profile ? 'edit' : 'add';
  // 初始环境中的空占位项在首个模型保存时直接补全，不显示成一个假模型。
  editingId.value = profile?.id ?? null;
  clearCatalog(); selectedModels.value = profile ? [...profile.models] : [];
  Object.assign(form, { name: profile?.name || '', protocol: profile?.protocol || 'openai_chat', base_url: profile?.base_url || '', api_key: '', clear_api_key: false });
  showKey.value = false; message.value = ''; saveError.value = ''; editorOpen.value = true;
  void nextTick(() => {
    const scroll = dialog.value?.querySelector('.settings-scroll'); if (scroll) scroll.scrollTop = 0;
    dialog.value?.querySelector<HTMLInputElement>('#provider-name')?.focus({ preventScroll: true });
  });
}
function addProvider() { openEditor(); }
function editProvider(profile: AiProvider) { openEditor(profile); }
async function load() {
  loadController?.abort(); const controller = new AbortController(); loadController = controller;
  loading.value = true; loadError.value = ''; saveError.value = ''; message.value = ''; closeEditor();
  try { const value = await getModelSettings(controller.signal); if (!controller.signal.aborted) settings.value = value; }
  catch (error) { if (!controller.signal.aborted) loadError.value = error instanceof Error ? error.message : '无法连接本地服务'; }
  finally { if (!controller.signal.aborted) loading.value = false; }
}
async function refreshBusy() {
  try { const value = await getModelSettings(operationController.signal); if (settings.value) settings.value.busy = value.busy; }
  catch (error) { saveError.value = error instanceof Error ? error.message : '无法读取执行状态'; }
}
async function perform(operation: () => Promise<ModelSettings>, success: string) {
  if (saving.value) return;
  let completed = false;
  saving.value = true; emit('busy', true); saveError.value = ''; message.value = '';
  try {
    const value = await operation();
    if (operationController.signal.aborted) return;
    settings.value = value; closeEditor(); removeTarget.value = null; completed = true;
    await nextTick(); message.value = success; emit('saved', value);
    if (!props.open) emit('notice', success, false);
  } catch (error) {
    if (!operationController.signal.aborted) {
      saveError.value = error instanceof Error ? error.message : '操作未确认，请重新读取设置确认当前状态';
      if (error instanceof ApiError && error.status === 409 && settings.value) settings.value.busy = true;
      if (!props.open) emit('notice', saveError.value, true);
      else if (tab.value === 'model') { await nextTick(); dialog.value?.querySelector('.model-operation-error')?.scrollIntoView({ block: 'nearest' }); }
    }
  } finally {
    saving.value = false; emit('busy', false);
    if (completed && props.open && tab.value === 'model') { await nextTick(); addModelButton.value?.focus(); }
  }
}
async function save() {
  if (!canSave.value) return;
  const id = editingId.value;
  const payload = { ...form, models: [...selectedModels.value], api_key: form.api_key || null };
  const success = editorKind.value === 'edit' ? '供应商已更新' : '供应商已添加';
  await perform(async () => (await saveProvider(id, payload, operationController.signal)).settings, success);
}
async function removeProvider() {
  const id = removeTarget.value!.id;
  await perform(() => deleteProvider(id, operationController.signal), '供应商已删除');
  removeTarget.value = null;
}
function close() {
  if (editorOpen.value && dirty.value && !saving.value) { closeAfterDiscard = true; discardOpen.value = true; return; }
  emit('close');
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    const picker = dialog.value?.querySelector<HTMLDetailsElement>('details.model-picker[open]');
    if (picker) { picker.open = false; picker.querySelector('summary')?.focus(); }
    else close();
    event.preventDefault(); event.stopImmediatePropagation(); return;
  }
  if (event.key !== 'Tab') return;
  const controls = [...dialog.value!.querySelectorAll<HTMLElement>('button, input, select, summary, [tabindex="0"]')].filter(element => !element.matches(':disabled') && element.getClientRects().length);
  const first = controls[0], last = controls[controls.length - 1];
  if (!dialog.value!.contains(document.activeElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); return; }
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}
watch(() => props.open, async open => {
  if (open) { tab.value = props.initialTab || 'general'; exportMessage.value = ''; exportError.value = ''; if (!saving.value) void load(); await nextTick(); closeButton.value?.focus(); }
  else { loadController?.abort(); clearCatalog(); loading.value = false; form.api_key = ''; showKey.value = false; discardOpen.value = false; removeTarget.value = null; resetOpen.value = false; }
}, { immediate: true });
function documentKeydown(event: KeyboardEvent) {
  if (props.open && !document.querySelector('dialog[open]')) onKeydown(event);
}
onMounted(() => document.addEventListener('keydown', documentKeydown, true));
onUnmounted(() => { document.removeEventListener('keydown', documentKeydown, true); loadController?.abort(); catalogController?.abort(); operationController.abort(); form.api_key = ''; });
</script>
<style src="./settings.css"></style>

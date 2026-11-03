<template>
  <Teleport to="body">
    <dialog ref="dialog" class="trash-dialog" aria-labelledby="trash-title" @cancel.prevent="emit('close')" @click="outside">
      <header class="trash-header">
        <div class="trash-heading"><span class="trash-heading-icon"><UiIcon name="trash" /></span><div><h2 id="trash-title">回收站 <span>{{ page.total }}</span></h2><p>恢复需要的对话，清理不再保留的记录。</p></div></div>
        <button class="icon-button" type="button" aria-label="关闭回收站" @click="emit('close')"><UiIcon name="close" /></button>
      </header>

      <div class="trash-tools">
        <label class="trash-search"><UiIcon name="search" /><input ref="searchInput" v-model="query" type="search" maxlength="2000" placeholder="搜索已删除的对话" aria-label="搜索已删除的对话" :disabled="busy" /></label>
        <select v-model="sort" aria-label="回收站排序" :disabled="busy"><option value="newest">最近删除</option><option value="oldest">最早删除</option><option value="title">按名称</option></select>
        <button class="icon-button" type="button" aria-label="刷新回收站" :disabled="loading || busy" @click="load"><UiIcon name="refresh" /></button>
      </div>

      <div class="trash-actions">
        <div class="trash-selection"><label><input type="checkbox" :checked="allSelected" :indeterminate="selected.length > 0 && !allSelected" :disabled="unavailable || !page.items.length" aria-label="选择本页对话" @change="togglePage" /><span>{{ selected.length ? `已选择 ${selected.length} 项` : '选择本页' }}</span></label><button v-if="selected.length" type="button" class="text-button" :disabled="busy" @click="selected = []">取消选择</button></div>
        <div v-if="selected.length" class="trash-action-buttons"><button type="button" :disabled="unavailable" @click="restore(selected)"><UiIcon name="restore" />恢复所选</button><button type="button" class="trash-danger" :disabled="unavailable" @click="askDelete(selected)"><UiIcon name="trash" />删除所选</button></div>
        <div v-else class="trash-action-buttons"><button type="button" :disabled="unavailable || !page.total" @click="askRestoreAll"><UiIcon name="restore" />全部恢复</button><button type="button" class="trash-danger" :disabled="unavailable || !page.total" @click="askDelete(null)"><UiIcon name="trash" />清空回收站</button></div>
      </div>

      <div v-if="error" class="trash-feedback trash-error" role="alert"><UiIcon name="info" /><span>{{ error }}</span><button v-if="loadFailed" type="button" class="text-button" @click="load">重试</button></div>
      <p v-if="message || busy" class="trash-feedback" role="status"><UiIcon :name="busy ? 'clock' : 'check'" />{{ busy ? '正在处理，请稍候…' : message }}</p>

      <div class="trash-content" :aria-busy="loading">
        <div v-if="loading" class="trash-empty" role="status"><UiIcon name="refresh" /><p>正在读取回收站…</p></div>
        <div v-else-if="loadFailed" class="trash-empty"><UiIcon name="info" /><h3>暂时无法读取回收站</h3><p>请重新加载后再管理对话。</p></div>
        <div v-else-if="!page.items.length" class="trash-empty"><span class="trash-empty-icon"><UiIcon :name="query.trim() ? 'search' : 'trash'" /></span><h3>{{ query.trim() ? '没有找到相关对话' : '回收站是空的' }}</h3><p>{{ query.trim() ? '换个关键词，或清除搜索查看全部记录。' : '删除的对话会出现在这里，可随时恢复。' }}</p><button v-if="query.trim()" type="button" class="text-button" @click="query = ''">清除搜索</button></div>
        <template v-else>
          <div class="trash-list-head" aria-hidden="true"><span>对话</span><span>删除时间</span><span>操作</span></div>
          <ul class="trash-list" aria-label="已删除的对话">
            <li v-for="task in page.items" :key="task.id" class="trash-row" :class="{ 'is-selected': selected.includes(task.id) }">
              <label class="trash-row-main"><input v-model="selected" type="checkbox" :value="task.id" :aria-label="`选择对话：${title(task)}`" :disabled="busy" /><span class="trash-row-icon"><UiIcon name="chat" /></span><span class="trash-row-copy"><strong :title="title(task)">{{ title(task) }}</strong><small v-if="task.title && task.title !== task.topic" :title="task.topic">{{ task.topic }}</small><time class="trash-mobile-time" :datetime="task.deleted_at!">{{ date(task.deleted_at!) }}</time></span></label>
              <time class="trash-row-date" :datetime="task.deleted_at!">{{ date(task.deleted_at!) }}</time>
              <div class="trash-row-actions"><button type="button" :aria-label="`恢复对话：${title(task)}`" :disabled="busy" @click="restore([task.id])"><UiIcon name="restore" /><span>恢复</span></button><button type="button" class="icon-button trash-danger" :aria-label="`彻底删除对话：${title(task)}`" :disabled="busy" @click="askDelete([task.id])"><UiIcon name="trash" /></button></div>
            </li>
          </ul>
        </template>
      </div>

      <div class="trash-bottom"><p><UiIcon name="info" />恢复不会自动执行研究；彻底删除后无法找回。</p><div v-if="page.matched" class="trash-pagination"><span>{{ offset + 1 }}–{{ Math.min(offset + PAGE_SIZE, page.matched) }} / {{ page.matched }}</span><button type="button" class="icon-button" aria-label="回收站上一页" :disabled="unavailable || offset === 0" @click="offset -= PAGE_SIZE"><UiIcon name="chevronRight" class="trash-previous" /></button><button type="button" class="icon-button" aria-label="回收站下一页" :disabled="unavailable || offset + PAGE_SIZE >= page.matched" @click="offset += PAGE_SIZE"><UiIcon name="chevronRight" /></button></div></div>
    </dialog>
    <ActionDialog v-if="confirmation && open" :title="confirmation.kind === 'restore' ? '恢复全部对话？' : confirmation.ids === null ? '清空回收站？' : `彻底删除 ${confirmation.count} 个对话？`" :description="confirmation.kind === 'restore' ? `将恢复回收站中的全部 ${confirmation.count} 个对话。已停止的研究不会自动重启。` : `${confirmation.ids === null ? `将永久删除回收站中的全部 ${confirmation.count} 个对话` : `将永久删除所选 ${confirmation.count} 个对话`}及其消息、研究记录和报告。此操作无法撤销。`" :confirm-label="confirmation.kind === 'restore' ? '全部恢复' : confirmation.ids === null ? '确认清空' : '彻底删除'" :danger="confirmation.kind === 'delete'" :busy="busy" :error="error" @close="confirmation = null" @confirm="confirmAction" />
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue';
import { deleteTrash, getTrash, restoreTrash, type Task, type TrashPage } from '../api/client';
import ActionDialog from './ActionDialog.vue';
import UiIcon from './UiIcon.vue';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; restored: [tasks: Task[]]; deleted: [ids: string[]]; notice: [message: string, error: boolean] }>();
const PAGE_SIZE = 50;
const dialog = ref<HTMLDialogElement | null>(null);
const searchInput = ref<HTMLInputElement | null>(null);
const page = ref<TrashPage>({ items: [], total: 0, matched: 0 });
const query = ref('');
const sort = ref('newest');
const offset = ref(0);
const selected = ref<string[]>([]);
const loading = ref(false);
const loadFailed = ref(false);
const busy = ref(false);
const error = ref('');
const message = ref('');
const confirmation = ref<{ kind: 'restore' | 'delete'; ids: string[] | null; count: number } | null>(null);
const allSelected = computed(() => page.value.items.length > 0 && selected.value.length === page.value.items.length);
const unavailable = computed(() => loading.value || busy.value || loadFailed.value);
const title = (task: Task) => task.title || task.topic;
const date = (value: string) => new Date(value).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
let readController: AbortController | null = null;
let disposed = false;

async function load() {
  readController?.abort();
  const controller = new AbortController(); readController = controller;
  loading.value = true; loadFailed.value = false; error.value = ''; selected.value = [];
  try {
    const result = await getTrash(query.value, sort.value, offset.value, PAGE_SIZE, controller.signal);
    if (controller.signal.aborted || disposed) return;
    page.value = result;
    if (offset.value && offset.value >= result.matched) offset.value = Math.max(0, Math.floor((result.matched - 1) / PAGE_SIZE) * PAGE_SIZE);
  } catch (cause) {
    if (!controller.signal.aborted && !disposed) { loadFailed.value = true; error.value = `读取失败：${cause instanceof Error ? cause.message : '未知错误'}`; }
  } finally { if (!controller.signal.aborted && !disposed) loading.value = false; }
}
function togglePage() { selected.value = allSelected.value ? [] : page.value.items.map(task => task.id); }
function askDelete(ids: string[] | null) { error.value = ''; confirmation.value = { kind: 'delete', ids: ids ? [...ids] : null, count: ids?.length ?? page.value.total }; }
function askRestoreAll() { error.value = ''; confirmation.value = { kind: 'restore', ids: null, count: page.value.total }; }
async function restore(ids: string[] | null) { await perform('restore', ids ? [...ids] : null); }
async function confirmAction() { if (confirmation.value) await perform(confirmation.value.kind, confirmation.value.ids); }
async function perform(kind: 'restore' | 'delete', ids: string[] | null) {
  if (busy.value) return;
  busy.value = true; error.value = ''; message.value = '';
  try {
    let count: number;
    if (kind === 'restore') { const result = await restoreTrash(ids); count = result.tasks.length; emit('restored', result.tasks); }
    else { const result = await deleteTrash(ids); count = result.ids.length; emit('deleted', result.ids); }
    const resultMessage = kind === 'restore' ? `已恢复 ${count} 个对话；研究不会自动重启` : `已彻底删除 ${count} 个对话`;
    confirmation.value = null;
    if (props.open) { message.value = resultMessage; await load(); }
    else emit('notice', resultMessage, false);
  } catch (cause) {
    const resultMessage = `${kind === 'restore' ? '恢复' : '删除'}失败：${cause instanceof Error ? cause.message : '未知错误'}`;
    error.value = resultMessage;
    if (!props.open) emit('notice', resultMessage, true);
  } finally { busy.value = false; if (props.open && !confirmation.value) { await nextTick(); searchInput.value?.focus({ preventScroll: true }); } }
}
function outside(event: MouseEvent) {
  if (event.target !== dialog.value) return;
  const rect = dialog.value!.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) emit('close');
}
watch([query, sort, offset], (values, previous) => {
  if (!props.open) return;
  if ((values[0] !== previous[0] || values[1] !== previous[1]) && offset.value) { offset.value = 0; return; }
  void load();
});
watch(() => props.open, async open => {
  if (open) {
    query.value = ''; sort.value = 'newest'; offset.value = 0; message.value = ''; confirmation.value = null;
    await nextTick(); dialog.value?.showModal(); searchInput.value?.focus(); void load();
  } else { dialog.value?.close(); confirmation.value = null; readController?.abort(); }
});
onUnmounted(() => { disposed = true; readController?.abort(); });
</script>
<style src="./trash.css"></style>

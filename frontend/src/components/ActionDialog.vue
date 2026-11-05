<template>
  <Teleport to="body">
    <dialog ref="element" class="action-dialog" aria-labelledby="action-dialog-title" @cancel.prevent="emit('close')" @click="outside">
      <form @submit.prevent="emit('confirm', value)">
        <header><h2 id="action-dialog-title">{{ title }}</h2><button type="button" class="icon-button" aria-label="关闭对话操作" @click="emit('close')"><UiIcon name="close" /></button></header>
        <p v-if="description">{{ description }}</p>
        <label v-if="editable" class="action-input-label">对话名称<input v-model="value" required maxlength="120" aria-label="对话名称" /></label>
        <p v-if="error" class="error-message" role="alert">{{ error }}</p>
        <footer><button type="button" @click="emit('close')">取消</button><button type="submit" :class="{ danger }" :disabled="busy || (editable && !value.trim())">{{ busy ? '处理中…' : confirmLabel }}</button></footer>
      </form>
    </dialog>
  </Teleport>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue';
import UiIcon from './UiIcon.vue';
const props = defineProps<{ title: string; description: string; confirmLabel: string; initialValue?: string; editable?: boolean; danger?: boolean; busy?: boolean; error?: string }>();
const emit = defineEmits<{ close: []; confirm: [value: string] }>();
const element = ref<HTMLDialogElement | null>(null);
const value = ref(props.initialValue || '');
function outside(event: MouseEvent) {
  if (event.target !== element.value) return;
  const bounds = element.value!.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) emit('close');
}
onMounted(() => { element.value!.showModal(); if (props.editable) { const input = element.value!.querySelector('input')!; input.focus(); input.select(); } });
</script>
<style>
.action-dialog { width: min(430px, calc(100vw - 32px)); margin: auto; padding: 24px; border: 1px solid var(--border); border-radius: 15px; background: var(--paper); color: var(--text); box-shadow: var(--overlay-shadow); }
.action-dialog::backdrop { background: var(--scrim); backdrop-filter: blur(3px); }
.action-dialog header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.action-dialog h2 { margin: 0; font-size: 18px; font-weight: 500; }
.action-dialog p { color: var(--muted); font-size: 13px; line-height: 1.9; overflow-wrap: anywhere; }
.action-input-label { display: block; margin: 22px 0; font-size: 12px; color: var(--muted); }
.action-input-label input { display: block; width: 100%; margin-top: 8px; padding: 11px 12px; border: 1px solid var(--control); border-radius: 7px; background: var(--surface); color: var(--text); }
.action-dialog footer { display: flex; justify-content: flex-end; gap: 9px; margin-top: 24px; }
.action-dialog footer button { min-height: 37px; padding: 8px 15px; border: 1px solid var(--control); border-radius: 7px; background: none; color: var(--text); font-size: 12px; }
.action-dialog footer button[type='submit'] { border-color: var(--primary); background: var(--primary); color: var(--on-primary); }
.action-dialog footer button.danger { border-color: var(--negative); background: var(--negative); }
.action-dialog footer button:disabled { opacity: .5; }
</style>

<template>
  <div class="model-picker-field">
    <details ref="element" class="model-picker">
      <summary id="model-picker-trigger" :aria-disabled="disabled" :tabindex="disabled ? -1 : 0" aria-label="选择模型" @click="disabled && $event.preventDefault()"><UiIcon name="model" /><span>{{ modelValue.length ? modelValue.length === 1 ? modelValue[0] : `已选择 ${modelValue.length} 个模型` : '选择模型，可多选' }}</span><UiIcon name="chevronDown" /></summary>
      <div class="model-picker-panel">
        <label class="model-picker-search"><UiIcon name="search" /><input id="model-name" v-model="query" maxlength="200" placeholder="搜索模型，或输入模型 ID" aria-label="搜索或输入模型 ID" autocomplete="off" spellcheck="false" :disabled="disabled" @keydown.enter.prevent.stop="addManual" /></label>
        <div class="model-picker-options" role="group" aria-label="可用模型">
          <label v-for="model in filteredModels" :key="model.id" class="model-picker-option" :class="{ chosen: modelValue.includes(model.id) }"><input type="checkbox" :checked="modelValue.includes(model.id)" :aria-label="`选择模型：${model.id}`" :disabled="disabled || (!modelValue.includes(model.id) && modelValue.length >= 100)" @change="toggle(model.id)" /><span><strong>{{ model.name }}</strong><small v-if="model.name !== model.id">{{ model.id }}</small></span><UiIcon v-if="modelValue.includes(model.id)" name="check" /></label>
          <p v-if="loading" class="model-picker-empty" role="status">正在获取模型…</p>
          <p v-else-if="!filteredModels.length" class="model-picker-empty">{{ query.trim() ? '没有匹配的模型，可按 ID 手动添加。' : '点击“获取模型”读取列表，或在上方输入模型 ID。' }}</p>
        </div>
        <button v-if="canAddManual" type="button" class="model-picker-manual" :disabled="disabled" @click="addManual"><UiIcon name="plus" /><span>添加此模型 <strong>{{ query.trim() }}</strong></span></button>
        <div class="model-picker-bottom"><span>{{ modelValue.length }} / 100 个已选</span><button v-if="hasMore" type="button" class="text-button" :disabled="disabled || loading" @click="emit('more')">{{ loading ? '加载中…' : '加载更多' }}</button><button type="button" class="text-button" :disabled="disabled || !modelValue.length" @click="emit('update:modelValue', [])">清除选择</button></div>
      </div>
    </details>
    <div v-if="modelValue.length" class="model-picker-chips" aria-label="已选模型"><span v-for="id in modelValue" :key="id"><span :title="id">{{ id }}</span><button type="button" :aria-label="`移除模型：${id}`" :disabled="disabled" @click="toggle(id)"><UiIcon name="close" /></button></span></div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import type { AvailableModel } from '../api/client';
import UiIcon from './UiIcon.vue';
const props = defineProps<{ modelValue: string[]; options: AvailableModel[]; disabled?: boolean; loading?: boolean; hasMore?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: string[]]; more: [] }>();
const element = ref<HTMLDetailsElement | null>(null);
const query = ref('');
const filteredModels = computed(() => {
  const models = new Map(props.options.map(model => [model.id, model]));
  for (const id of props.modelValue) if (!models.has(id)) models.set(id, { id, name: id });
  const search = query.value.trim().toLocaleLowerCase();
  return [...models.values()].filter(model => `${model.id} ${model.name}`.toLocaleLowerCase().includes(search));
});
const canAddManual = computed(() => !!query.value.trim() && props.modelValue.length < 100 && !props.modelValue.includes(query.value.trim()) && !props.options.some(model => model.id === query.value.trim()));
function toggle(id: string) { emit('update:modelValue', props.modelValue.includes(id) ? props.modelValue.filter(item => item !== id) : [...props.modelValue, id]); }
function addManual() { if (!props.disabled && canAddManual.value) { emit('update:modelValue', [...props.modelValue, query.value.trim()]); query.value = ''; } }
function outside(event: Event) { if (element.value?.open && !element.value.contains(event.target as Node)) element.value.open = false; }
onMounted(() => { document.addEventListener('pointerdown', outside, true); document.addEventListener('focusin', outside); });
onUnmounted(() => { document.removeEventListener('pointerdown', outside, true); document.removeEventListener('focusin', outside); });
</script>
<style>
.model-selection-label { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.model-selection-label > label { color: var(--text); font-size: 12px; font-weight: 500; }
.model-selection-label > label > span { margin-left: 7px; color: var(--faint); font-size: 10px; font-weight: 400; }
.model-fetch-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 32px; padding: 6px 9px; border: 1px solid var(--border); border-radius: 6px; background: var(--ground); color: var(--text); font: 11px var(--font); }
.model-fetch-button .ui-icon { width: 13px; height: 13px; }
.model-fetch-button:disabled { opacity: .45; }
.model-picker { overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: var(--paper); }
.model-picker > summary { display: flex; align-items: center; gap: 9px; min-height: 43px; padding: 11px 12px; color: var(--muted); font-size: 12px; cursor: pointer; list-style: none; }
.model-picker > summary::-webkit-details-marker { display: none; }
.model-picker > summary > span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-picker > summary > .ui-icon { width: 14px; height: 14px; color: var(--faint); }
.model-picker[open] > summary > .ui-icon:last-child { transform: rotate(180deg); }
.model-picker-panel { padding: 8px; border-top: 1px solid var(--border); }
.model-picker-search { display: flex; align-items: center; gap: 7px; margin-bottom: 7px; padding: 0 9px; border: 1px solid var(--border); border-radius: 6px; background: var(--ground); }
.model-picker-search > .ui-icon { width: 14px; height: 14px; color: var(--faint); }
.model-picker-search input { min-width: 0; width: 100%; padding: 10px 0; border: 0; outline: none; background: none; color: var(--text); font: 12px var(--font); }
.model-picker-search input:focus-visible { outline: none; }
.model-picker-search:focus-within { border-color: var(--accent-border); }
.model-picker-options { max-height: 210px; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: var(--control) transparent; }
.model-picker-option { display: flex; align-items: center; gap: 9px; min-height: 40px; padding: 9px; border-radius: 5px; cursor: pointer; }
.model-picker-option:hover, .model-picker-option.chosen { background: var(--active); }
.model-picker-option > input { width: 14px; height: 14px; flex: none; margin: 0; accent-color: var(--primary); }
.model-picker-option > span { flex: 1; min-width: 0; }
.model-picker-option strong { display: block; overflow-wrap: anywhere; color: var(--text); font-size: 11px; font-weight: 400; line-height: 1.7; }
.model-picker-option small { display: block; margin-top: 3px; overflow-wrap: anywhere; color: var(--faint); font-size: 10px; }
.model-picker-option > .ui-icon { width: 13px; height: 13px; color: var(--muted); }
.model-picker-empty { margin: 0; padding: 17px 9px; color: var(--faint); font-size: 11px; line-height: 1.8; }
.model-picker-manual { display: flex; align-items: flex-start; gap: 7px; width: 100%; padding: 11px 9px; border: 0; border-radius: 6px; background: var(--ground); color: var(--muted); text-align: left; font: 11px var(--font); line-height: 1.8; }
.model-picker-manual > .ui-icon { width: 14px; height: 14px; margin-top: 3px; }
.model-picker-manual > span { min-width: 0; overflow-wrap: anywhere; }
.model-picker-manual strong { margin-left: 5px; color: var(--text); font-weight: 400; }
.model-picker-bottom { display: flex; align-items: center; gap: 13px; padding: 11px 9px 4px; border-top: 1px solid var(--rule); color: var(--faint); font-size: 10px; }
.model-picker-bottom > span { flex: 1; }
.model-picker-bottom .text-button { font-size: 10px; }
.model-picker-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }
.model-picker-chips > span { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: 100%; padding: 4px 5px 4px 8px; border: 1px solid var(--border); border-radius: 5px; background: var(--ground); color: var(--muted); font-size: 10px; }
.model-picker-chips > span > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-picker-chips button { display: grid; place-items: center; width: 21px; height: 21px; flex: none; padding: 0; border: 0; border-radius: 3px; background: none; color: var(--faint); }
.model-picker-chips button:hover { background: var(--active); }
.model-picker-chips .ui-icon { width: 12px; height: 12px; }
.model-catalog-status { margin: 9px 0 0; color: var(--faint); font-size: 10px; line-height: 1.8; }
.model-catalog-error { color: var(--negative-ink); }
@media (max-width: 640px) {
  .model-picker > summary { min-height: 46px; }
  .model-picker-search input { font-size: 16px; }
  .model-picker-search input::placeholder { font-size: 11px; }
  .model-picker-option { min-height: 44px; }
  .model-fetch-button { min-height: 36px; }
  .model-picker-chips button { width: 25px; height: 25px; }
}
</style>

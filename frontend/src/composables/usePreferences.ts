import { reactive, ref, watch } from 'vue';

export interface InterfacePreferences {
  sendShortcut: 'enter' | 'modifier-enter';
  defaultMode: 'auto' | 'research' | 'ask';
  autoScroll: boolean;
  textSize: 'small' | 'standard' | 'large';
  readingWidth: 'standard' | 'wide';
}

const key = 'paper-scout.preferences';
const defaults: InterfacePreferences = { sendShortcut: 'enter', defaultMode: 'auto', autoScroll: true, textSize: 'standard', readingWidth: 'standard' };
const preferences = reactive({ ...defaults });
const storageAvailable = ref(true);

// 浏览器存储是输入边界：只接收已知选项，研究内容和密钥不进入这里。
let saved: Partial<InterfacePreferences> = {};
let stored: string | null = null;
try { stored = localStorage.getItem(key); }
catch { storageAvailable.value = false; }
if (stored) {
  try { saved = JSON.parse(stored) || {}; }
  catch { saved = {}; }
}
if (saved.sendShortcut === 'modifier-enter') preferences.sendShortcut = saved.sendShortcut;
if (saved.defaultMode === 'research' || saved.defaultMode === 'ask') preferences.defaultMode = saved.defaultMode;
if (typeof saved.autoScroll === 'boolean') preferences.autoScroll = saved.autoScroll;
if (saved.textSize === 'small' || saved.textSize === 'large') preferences.textSize = saved.textSize;
if (saved.readingWidth === 'wide') preferences.readingWidth = saved.readingWidth;

function applyReadingPreferences() {
  document.documentElement.dataset.textSize = preferences.textSize;
  document.documentElement.dataset.readingWidth = preferences.readingWidth;
}
applyReadingPreferences();
watch(preferences, () => {
  applyReadingPreferences();
  try { localStorage.setItem(key, JSON.stringify(preferences)); storageAvailable.value = true; }
  catch { storageAvailable.value = false; }
});

export function usePreferences() {
  return { preferences, preferencesStorageAvailable: storageAvailable, resetPreferences: () => Object.assign(preferences, defaults) };
}

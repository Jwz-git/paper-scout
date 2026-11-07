import { reactive, ref, watch } from 'vue';

export interface InterfacePreferences {
  sendShortcut: 'enter' | 'modifier-enter';
  defaultMode: 'auto' | 'research' | 'ask';
  autoScroll: boolean;
  textSize: 'small' | 'standard' | 'large';
  readingWidth: 'standard' | 'wide';
  sidebarWidth: number | null;
  materialsWidth: number | null;
}

export const PANE_LIMITS = { sidebar: [200, 420], materials: [320, 960] } as const;

const key = 'paper-scout.preferences';
const defaults: InterfacePreferences = { sendShortcut: 'enter', defaultMode: 'auto', autoScroll: true, textSize: 'standard', readingWidth: 'standard', sidebarWidth: null, materialsWidth: null };
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
const paneWidth = (value: unknown, [min, max]: readonly [number, number]) =>
  typeof value === 'number' && value >= min && value <= max ? Math.round(value) : null;
preferences.sidebarWidth = paneWidth(saved.sidebarWidth, PANE_LIMITS.sidebar);
preferences.materialsWidth = paneWidth(saved.materialsWidth, PANE_LIMITS.materials);

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

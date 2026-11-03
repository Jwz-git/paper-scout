import { computed, onUnmounted, shallowRef } from 'vue';

export type ThemePreference = 'system' | 'light' | 'dark';
interface ThemeState {
  preference: ThemePreference;
  resolved: 'light' | 'dark';
  systemDark: boolean;
  storageAvailable: boolean;
}
declare global {
  interface Window {
    paperScoutTheme: {
      getState(): ThemeState;
      setPreference(value: ThemePreference): void;
      subscribe(listener: (value: ThemeState) => void): () => void;
    };
  }
}

export function useTheme() {
  const state = shallowRef(window.paperScoutTheme.getState());
  const unsubscribe = window.paperScoutTheme.subscribe(value => { state.value = value; });
  onUnmounted(unsubscribe);
  return {
    theme: computed({ get: () => state.value.preference, set: (value: ThemePreference) => window.paperScoutTheme.setPreference(value) }),
    resolvedTheme: computed(() => state.value.resolved),
    systemDark: computed(() => state.value.systemDark),
    storageAvailable: computed(() => state.value.storageAvailable),
  };
}

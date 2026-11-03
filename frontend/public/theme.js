// 在首屏绘制前应用外观。这里只保存非敏感的主题偏好。
(() => {
  const key = 'paper-scout.theme';
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  let storageAvailable = true;
  const listeners = new Set();
  function readPreference(value) {
    return value === 'light' || value === 'dark' ? value : 'system';
  }
  try { preference = readPreference(localStorage.getItem(key)); }
  catch { storageAvailable = false; }
  function state() {
    return { preference, resolved: preference === 'system' ? (media.matches ? 'dark' : 'light') : preference, systemDark: media.matches, storageAvailable };
  }
  function apply() {
    const value = state();
    document.documentElement.dataset.theme = value.resolved;
    document.documentElement.dataset.themePreference = value.preference;
    document.documentElement.style.colorScheme = value.resolved;
    document.querySelector('meta[name="theme-color"]').content = value.resolved === 'dark' ? '#1b1b1b' : '#ffffff';
    listeners.forEach(listener => listener(value));
  }
  window.paperScoutTheme = {
    getState: state,
    setPreference(value) {
      preference = value;
      try {
        if (value === 'system') localStorage.removeItem(key);
        else localStorage.setItem(key, value);
        storageAvailable = true;
      } catch { storageAvailable = false; }
      apply();
    },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
  media.addEventListener('change', apply);
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = readPreference(event.newValue); apply(); }
  });
  apply();
})();

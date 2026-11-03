import { onMounted, onUnmounted } from 'vue';

export function closeMenus() {
  document.querySelectorAll<HTMLDetailsElement>('details[data-menu][open]').forEach(menu => { menu.open = false; });
}

// 只接管浮层菜单，研究过程等可展开内容不受影响。
export function useDismissableMenus() {
  function outside(event: Event) {
    const target = event.target as Node;
    document.querySelectorAll<HTMLDetailsElement>('details[data-menu][open]').forEach(menu => {
      if (!menu.contains(target)) menu.open = false;
    });
  }
  function toggle(event: Event) {
    const opened = event.target as HTMLDetailsElement;
    if (!opened.matches('details[data-menu]') || !opened.open) return;
    document.querySelectorAll<HTMLDetailsElement>('details[data-menu][open]').forEach(menu => {
      if (menu !== opened) menu.open = false;
    });
    if (opened.classList.contains('history-menu')) {
      const trigger = opened.getBoundingClientRect();
      const panel = opened.querySelector<HTMLElement>('div')!;
      panel.style.left = `${Math.max(8, trigger.right - 146)}px`;
      panel.style.top = `${Math.min(trigger.bottom + 4, window.innerHeight - panel.offsetHeight - 8)}px`;
    }
  }
  function escape(event: KeyboardEvent) {
    if (event.key !== 'Escape') return;
    const menus = [...document.querySelectorAll<HTMLDetailsElement>('details[data-menu][open]')];
    const menu = menus.find(item => item.contains(document.activeElement)) || menus[menus.length - 1];
    if (!menu) return;
    menu.open = false;
    menu.querySelector<HTMLElement>('summary')?.focus();
    event.preventDefault();
    event.stopImmediatePropagation();
  }
  onMounted(() => {
    document.addEventListener('pointerdown', outside, true);
    document.addEventListener('focusin', outside);
    document.addEventListener('toggle', toggle, true);
    document.addEventListener('scroll', outside, true);
    window.addEventListener('resize', closeMenus);
    document.addEventListener('keydown', escape, true);
  });
  onUnmounted(() => {
    document.removeEventListener('pointerdown', outside, true);
    document.removeEventListener('focusin', outside);
    document.removeEventListener('toggle', toggle, true);
    document.removeEventListener('scroll', outside, true);
    window.removeEventListener('resize', closeMenus);
    document.removeEventListener('keydown', escape, true);
  });
}

(function () {
  let current = 'light';
  let picked = false;
  let switchFrame = 0;

  function mark(theme: string): void {
    document.querySelectorAll<HTMLElement>('#settingsOverlay .theme-card').forEach((card) =>
      card.classList.toggle('on', card.dataset.card === theme));
  }

  function applyTheme(theme: string): void {
    const next = theme || 'light';
    current = next;
    mark(next);
    const root = document.documentElement;
    if (root.dataset.theme === next) return;
    root.classList.add('theme-switch');
    root.dataset.theme = next;
    void root.offsetHeight;
    const frame = ++switchFrame;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (frame === switchFrame) root.classList.remove('theme-switch');
    }));
  }

  function beginLoad(): void {
    picked = false;
  }

  function applyLoaded(theme: string): void {
    if (picked) return;
    applyTheme(theme);
  }

  function initTheme(theme: string): void {
    if (picked) return;
    applyTheme(theme);
  }

  function pickTheme(theme: string): void {
    picked = true;
    applyTheme(theme);
    if (bridge) bridge.setTheme(theme);
  }

  function currentTheme(): string {
    return current;
  }

  const kit = window.SettingsKit || (window.SettingsKit = {} as SettingsKitApi);
  kit.theme = { beginLoad, applyLoaded, initTheme, pickTheme, applyTheme, current: currentTheme };
})();

(function () {
  type HotkeyKey = keyof SettingsHotkeyValues;

  const IDS: Record<HotkeyKey, string> = {
    emergency_hide: 'setHkHide',
    fullscreen_toggle: 'setHkFull',
    mute_toggle: 'setHkMute',
    screenshot: 'setHkShot',
  };

  const model = window.SettingsKit.model;

  let capture: {
    el: HTMLInputElement;
    prev: string;
    handler: (e: KeyboardEvent) => void;
    timer: ReturnType<typeof setTimeout> | null;
  } | null = null;

  function input(key: HotkeyKey): HTMLInputElement | null {
    return document.getElementById(IDS[key]) as HTMLInputElement | null;
  }

  function renderHotkey(el: HTMLInputElement): void {
    const card = el.closest('.hotkey-card') as HTMLElement | null;
    const host = card?.querySelector<HTMLElement>(`[data-hotkey-keys="${el.id}"]`);
    if (!card || !host) return;
    const hint = el.classList.contains('hint');
    const conflict = el.classList.contains('conflict');
    card.classList.toggle('is-capturing', hint);
    card.classList.toggle('is-conflict', conflict);
    const edit = card.querySelector<HTMLElement>('.hk-edit');
    if (edit) edit.textContent = hint ? '录制中…' : conflict ? '快捷键冲突' : '点击修改';
    host.replaceChildren();
    if (hint) {
      host.textContent = '请按下组合键…';
      return;
    }
    if (conflict) {
      host.textContent = '冲突，请换一个';
      return;
    }
    const text = el.value.trim();
    if (!text) {
      host.textContent = '未设置';
      return;
    }
    text.split('+').map((part) => part.trim()).filter(Boolean).forEach((part, index) => {
      if (index > 0) {
        const plus = document.createElement('span');
        plus.className = 'hk-plus';
        plus.textContent = '+';
        host.appendChild(plus);
      }
      const key = document.createElement('span');
      key.className = 'hk-key';
      key.textContent = part;
      host.appendChild(key);
    });
  }

  function renderAll(): void {
    (Object.keys(IDS) as HotkeyKey[]).forEach((key) => {
      const el = input(key);
      if (el) renderHotkey(el);
    });
  }

  function read(): SettingsHotkeyValues {
    const values = {} as SettingsHotkeyValues;
    (Object.keys(IDS) as HotkeyKey[]).forEach((key) => {
      values[key] = String(input(key)?.value || '');
    });
    return values;
  }

  function load(values: SettingsHotkeyValues): void {
    (Object.keys(IDS) as HotkeyKey[]).forEach((key) => {
      const el = input(key);
      if (!el) return;
      el.value = values[key] || model.defaults[key] || '';
    });
    renderAll();
  }

  function takenHotkeys(exceptId: string): Set<string> {
    const values = read();
    const taken = new Set<string>();
    (Object.keys(IDS) as HotkeyKey[]).forEach((key) => {
      if (IDS[key] === exceptId) return;
      const value = values[key].trim();
      if (value && value !== '请按下组合键…' && value !== '冲突，请换一个') taken.add(value);
    });
    return taken;
  }

  function stop(restore: boolean): void {
    const cap = capture;
    if (!cap) return;
    capture = null;
    document.removeEventListener('keydown', cap.handler);
    if (cap.timer !== null) clearTimeout(cap.timer);
    if (restore && (cap.el.value === '请按下组合键…' || cap.el.classList.contains('conflict'))) {
      cap.el.value = cap.prev;
    }
    cap.el.classList.remove('hint', 'conflict');
    renderHotkey(cap.el);
  }

  function bindHotkey(el: HTMLInputElement): void {
    if (el.dataset.hotkeyBound === '1') return;
    el.dataset.hotkeyBound = '1';
    el.addEventListener('blur', function () {
      if (capture && capture.el === el) stop(true);
    });
    el.addEventListener('focus', function () {
      stop(true);
      const prev = el.value;
      el.classList.add('hint');
      el.value = '请按下组合键…';
      renderHotkey(el);
      const cap = {
        el,
        prev,
        timer: null as ReturnType<typeof setTimeout> | null,
        handler: function (e: KeyboardEvent): void {
          e.preventDefault();
          e.stopPropagation();
          const mods: string[] = [];
          if (e.ctrlKey) mods.push('Ctrl');
          if (e.altKey) mods.push('Alt');
          if (e.shiftKey) mods.push('Shift');
          if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return;
          const keyName = e.key.length === 1 ? e.key.toUpperCase() : e.key;
          const combo = mods.concat([keyName]).join(' + ');
          if (takenHotkeys(el.id).has(combo)) {
            el.value = '冲突，请换一个';
            el.classList.remove('hint');
            el.classList.add('conflict');
            renderHotkey(el);
            if (cap.timer !== null) clearTimeout(cap.timer);
            cap.timer = setTimeout(() => {
              cap.timer = null;
              if (capture === cap) {
                el.value = '请按下组合键…';
                el.classList.add('hint');
                el.classList.remove('conflict');
                renderHotkey(el);
              }
            }, 1200);
            return;
          }
          el.value = combo;
          el.classList.remove('hint');
          renderHotkey(el);
          document.removeEventListener('keydown', cap.handler);
          capture = null;
        },
      };
      capture = cap;
      document.addEventListener('keydown', cap.handler);
    });
  }

  function bindAll(): void {
    (Object.keys(IDS) as HotkeyKey[]).forEach((key) => {
      const el = input(key);
      if (el) bindHotkey(el);
    });
    renderAll();
  }

  const kit = window.SettingsKit || (window.SettingsKit = {} as SettingsKitApi);
  kit.hotkeys = { bindAll, load, read, stop };
})();

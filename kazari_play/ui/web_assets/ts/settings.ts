/* settings.ts — 设置窗口逻辑（对齐《设置窗口设计计划书》）
 * - 打开/关闭、导航切换
 * - 加载 config 填充表单、主题即时预览、保存/取消/恢复默认
 * - 热键捕获
 */
(function () {
  const $ = (id: string): HTMLElement => document.getElementById(id)!;
  let savedTheme = 'light';
  let pendingTheme: string | null = null;

  function applyTheme(t: string): void {
    const root = document.documentElement;
    root.classList.add('theme-switch');   // 全局禁 transition，避免重排痕迹
    root.dataset.theme = t;
    void root.offsetHeight;               // 强制同步重排：主题立即生效
    requestAnimationFrame(() => root.classList.remove('theme-switch'));  // 布局稳定后恢复
  }

  function markThemeCard(t: string): void {
    document.querySelectorAll<HTMLElement>('.theme-card').forEach((c) =>
      c.classList.toggle('on', c.dataset.card === t));
  }

  function fmtKey(k: unknown): string {
    if (!k) return '';
    return String(k).split('+').map((s) => s.trim())
      .map((s) => s.charAt(0).toUpperCase() + s.slice(1)).join(' + ');
  }

  function open(): void {
    loadConfig();
    $('settingsOverlay').classList.add('show');
    // 恢复上次停留的 tab（阶段 E：tab 记忆）
    let lastTab = 'general';
    try { lastTab = localStorage.getItem('settings_tab') || 'general'; } catch (e) { }
    if (!document.getElementById('set-' + lastTab)) lastTab = 'general';
    document.querySelectorAll<HTMLElement>('#setNav .nav-item').forEach((x) =>
      x.classList.toggle('active', x.dataset.tab === lastTab));
    document.querySelectorAll<HTMLElement>('#settingsOverlay .page').forEach((p) =>
      p.style.display = p.id === 'set-' + lastTab ? 'block' : 'none');
  }

  function close(): void {
    if (pendingTheme !== null && pendingTheme !== savedTheme) applyTheme(savedTheme);
    closeSheet('settingsOverlay');
  }

  function loadConfig(): void {
    if (!bridge) return;
    bridge.getConfig(function (s: unknown) {
      const cfg = JSON.parse(String(s || '{}')) as Record<string, unknown> & {
        hotkeys?: Record<string, string>;
      };
      ($('setCoverSize') as HTMLSelectElement).value = (cfg.cover_size as string) || 'medium';
      ($('setLogLevel') as HTMLSelectElement).value = String(cfg.log_level || 'INFO').toUpperCase();
      ($('setDisguise') as HTMLSelectElement).value = (cfg.disguise_scene as string) || 'excel';
      ($('setShowConsole') as HTMLInputElement).checked = !!cfg.show_console;
      const cd = (cfg.cover_download || {}) as { timeout?: number; max_concurrent?: number };
      ($('setCoverTimeout') as HTMLSelectElement).value = String(cd.timeout ?? 90);
      ($('setCoverConcurrent') as HTMLSelectElement).value = String(cd.max_concurrent ?? 4);
      const hk = cfg.hotkeys || {};
      ($('setHkHide') as HTMLInputElement).value = fmtKey(hk.emergency_hide) || 'Ctrl + F12';
      ($('setHkFull') as HTMLInputElement).value = fmtKey(hk.fullscreen_toggle) || 'F11';
      ($('setHkMute') as HTMLInputElement).value = fmtKey(hk.mute_toggle) || 'Ctrl + M';
      ($('setHkShot') as HTMLInputElement).value = fmtKey(hk.screenshot) || 'F12';
      ($('setCfgPath')).textContent = '配置目录：' + ((cfg.path as string) || '%APPDATA%\\KazariPlay');
      savedTheme = (cfg.theme as string) || 'light';
      pendingTheme = savedTheme;
      applyTheme(savedTheme);
      markThemeCard(savedTheme);
    });
    loadMetaSources();
  }

  // 元数据源列表（favicon + 名称 + 状态，勾选参与混合检索）
  function loadMetaSources(): void {
    const box = $('setSrcList');
    if (!bridge || !box) return;
    bridge.getMetadataSources(function (s: unknown) {
      let sources: MetadataSource[] = [];
      try { sources = JSON.parse(String(s || '[]')) as MetadataSource[]; } catch (e) { }
      box.innerHTML = '';
      sources.forEach(src => {
        const usable = src.status === 'ready' || src.status === 'experimental';
        const statusText: Record<string, string> = { ready: '可用', experimental: '实验性', pending: '未接入' };
        const st = (statusText[src.status!] || src.status || '') as string;
        const row = document.createElement('label');
        row.className = 'src-opt' + (usable ? '' : ' disabled');
        row.innerHTML = `
          <input type="checkbox" class="src-check" data-id="${esc(src.id)}" ${src.enabled && usable ? 'checked' : ''} ${usable ? '' : 'disabled'}>
          <span class="src-box"></span>
          <img class="src-fav" src="${esc(src.icon || '')}" onerror="this.style.display='none'" alt="">
          <span class="src-name">${esc(src.name)}</span>
          <span class="src-status">${st}</span>`;
        box.appendChild(row);
      });
    });
  }

  function pickTheme(t: string): void {
    pendingTheme = t;
    applyTheme(t);
    markThemeCard(t);
    // 主题即时持久化：无需点「保存」，也避免关闭设置页时被还原
    savedTheme = t;
    if (bridge) bridge.setTheme(t);
  }

  function save(): void {
    if (!bridge) return;
    const data: Record<string, unknown> = {
      cover_size: ($('setCoverSize') as HTMLSelectElement).value,
      log_level: ($('setLogLevel') as HTMLSelectElement).value,
      disguise_scene: ($('setDisguise') as HTMLSelectElement).value,
      show_console: ($('setShowConsole') as HTMLInputElement).checked,
      cover_download: {
        timeout: parseInt(($('setCoverTimeout') as HTMLSelectElement).value, 10) || 90,
        max_concurrent: parseInt(($('setCoverConcurrent') as HTMLSelectElement).value, 10) || 4,
      },
      theme: pendingTheme || savedTheme,
      hotkeys: {
        emergency_hide: ($('setHkHide') as HTMLInputElement).value,
        fullscreen_toggle: ($('setHkFull') as HTMLInputElement).value,
        mute_toggle: ($('setHkMute') as HTMLInputElement).value,
        screenshot: ($('setHkShot') as HTMLInputElement).value,
      },
    };
    bridge.saveConfigs(JSON.stringify(data));
    // 元数据源勾选（独立保存，即时生效）
    const checkedSrc = [...document.querySelectorAll<HTMLElement>('#setSrcList .src-check:checked')]
      .map(x => x.dataset.id);
    bridge.saveMetadataSources(JSON.stringify(checkedSrc));
    // 截图热键立即重注册（先写配置再重注册；注册失败静默，配置仍已保存）
    bridge.updateScreenshotHotkey(($('setHkShot') as HTMLInputElement).value);
    if (window.applyCoverSize) window.applyCoverSize(data.cover_size as string);
    savedTheme = pendingTheme || savedTheme;
    toast('设置已保存');
    close();
  }

  // 热键占用检查（阶段 E）：已配置的其它热键集合（不含当前输入框）
  function takenHotkeys(exceptId: string): Set<string> {
    const ids = ['setHkHide', 'setHkFull', 'setHkMute', 'setHkShot'].filter((id) => id !== exceptId);
    const taken = new Set<string>();
    ids.forEach((id) => { const v = ($(id) as HTMLInputElement).value; if (v && v !== '请按下组合键…') taken.add(v); });
    return taken;
  }

  function bindHotkey(el: HTMLInputElement): void {
    el.addEventListener('focus', function () {
      el.classList.add('hint');
      el.value = '请按下组合键…';
      const handler = function (e: KeyboardEvent): void {
        e.preventDefault();
        e.stopPropagation();
        const mods: string[] = [];
        if (e.ctrlKey) mods.push('Ctrl');
        if (e.altKey) mods.push('Alt');
        if (e.shiftKey) mods.push('Shift');
        if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return;
        const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
        const combo = mods.concat([key]).join(' + ');
        // 冲突检测：与其它已配置热键重复 → 拒绝并提示
        if (takenHotkeys(el.id).has(combo)) {
          el.value = '冲突，请换一个';
          el.classList.remove('hint');
          el.classList.add('conflict');
          setTimeout(() => { el.value = '请按下组合键…'; el.classList.add('hint'); el.classList.remove('conflict'); }, 1200);
          return;
        }
        el.value = combo;
        el.classList.remove('hint');
        document.removeEventListener('keydown', handler);
      };
      document.addEventListener('keydown', handler);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('setNav').addEventListener('click', function (e: MouseEvent) {
      const item = (e.target as HTMLElement).closest('.nav-item') as HTMLElement | null;
      if (!item) return;
      document.querySelectorAll<HTMLElement>('#setNav .nav-item').forEach((x) => x.classList.remove('active'));
      item.classList.add('active');
      document.querySelectorAll<HTMLElement>('#settingsOverlay .page').forEach((p) =>
        p.style.display = 'none');
      $('set-' + item.dataset.tab).style.display = 'block';
      // 记录当前 tab（阶段 E：下次打开停留在上次位置）
      try { localStorage.setItem('settings_tab', item.dataset.tab!); } catch (err) { }
    });

    $('setClose').onclick = close;
    $('setCancel').onclick = close;
    $('setSave').onclick = save;
    ($('setReset')).onclick = function () {
      if (!bridge) return;
      bridge.resetConfig();
      loadConfig();
      toast('已恢复默认设置');
    };
    ['setHkHide', 'setHkFull', 'setHkMute', 'setHkShot'].forEach((id) => bindHotkey($(id) as HTMLInputElement));

    document.addEventListener('keydown', function (e: KeyboardEvent) {
      if (e.key === 'Escape' && $('settingsOverlay').classList.contains('show')) close();
    });
  });

  window.Settings = { open: open, close: close, pickTheme: pickTheme, applyTheme: applyTheme };
})();

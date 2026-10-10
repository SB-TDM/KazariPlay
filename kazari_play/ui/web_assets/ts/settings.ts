/* settings.ts — 设置窗口逻辑（对齐《设置窗口设计计划书》）
 * - 打开/关闭、导航切换
 * - 加载 config 填充表单、主题即时预览、保存/取消/恢复默认
 * - 热键捕获
 */
(function () {
  const $ = (id: string): HTMLElement => document.getElementById(id)!;
  let savedTheme = 'light';
  let pendingTheme: string | null = null;
  let themePicked = false;        // 用户已显式选择主题：迟到配置不得覆盖
  let configRequest = 0;          // 配置加载代际：只接受最新请求的回包
  let settingsSession = 0;        // 打开会话代际：关闭/重开使旧保存回包失效
  let saveSeq = 0;                // 保存请求代际：重复提交时只有最新一次生效

  function applyTheme(t: string): void {
    const root = document.documentElement;
    root.classList.add('theme-switch');   // 全局禁 transition，避免重排痕迹
    root.dataset.theme = t;
    void root.offsetHeight;               // 强制同步重排：主题立即生效
    requestAnimationFrame(() => root.classList.remove('theme-switch'));  // 布局稳定后恢复
  }

  // 启动时的初始主题：用户已自行选择（或初始化期间点击过主题）则不再覆盖
  function initTheme(t: string): void {
    if (themePicked) return;
    savedTheme = t;
    pendingTheme = t;
    applyTheme(t);
    markThemeCard(t);
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
    settingsSession++;
    stopHotkeyCapture(true);
    ($('setSave') as HTMLButtonElement).disabled = false;
    loadConfig();
    $('settingsOverlay').classList.add('show');
    // 恢复上次停留的 tab（阶段 E：tab 记忆）
    let lastTab = 'general';
    try { lastTab = localStorage.getItem('settings_tab') || 'general'; } catch (e) { }
    if (!document.getElementById('set-' + lastTab)) lastTab = 'general';
    document.querySelectorAll<HTMLElement>('#setNav .nav-item').forEach((x) => {
      const on = x.dataset.tab === lastTab;
      x.classList.toggle('active', on);
      x.setAttribute('aria-selected', on ? 'true' : 'false');
      x.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll<HTMLElement>('#settingsOverlay .page').forEach((p) =>
      p.style.display = p.id === 'set-' + lastTab ? 'block' : 'none');
  }

  function close(): void {
    settingsSession++;   // 使在途保存回包失效，不再关闭/干扰后续会话
    stopHotkeyCapture(true);
    if (pendingTheme !== null && pendingTheme !== savedTheme) applyTheme(savedTheme);
    closeSheet('settingsOverlay');
  }

  function loadConfig(): void {
    if (!bridge) return;
    themePicked = false;   // 本次加载允许回填主题；期间用户选择后由 themePicked 拦下
    const request = ++configRequest;
    bridge.getConfig(function (s: unknown, failed?: boolean) {
      if (failed || request !== configRequest) return;
      let cfg: Record<string, unknown> & { hotkeys?: Record<string, string> };
      try { cfg = JSON.parse(String(s || '{}')); } catch (e) { return; }
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
      if (!themePicked) {   // 用户在等待期间已自行选择主题时不覆盖
        savedTheme = (cfg.theme as string) || 'light';
        pendingTheme = savedTheme;
        applyTheme(savedTheme);
        markThemeCard(savedTheme);
      }
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
    themePicked = true;   // 显式选择后，迟到的配置回包不再改写主题
    pendingTheme = t;
    applyTheme(t);
    markThemeCard(t);
    // 主题即时持久化：无需点「保存」，也避免关闭设置页时被还原
    savedTheme = t;
    if (bridge) bridge.setTheme(t);
  }

  function save(): void {
    if (!bridge) return;
    const session = settingsSession;
    const seq = ++saveSeq;
    stopHotkeyCapture(true);
    const hotkeyShot = ($('setHkShot') as HTMLInputElement).value;
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
        screenshot: hotkeyShot,
      },
    };
    // 元数据源勾选与热键在点击时定格：成功回调不再读取当时的表单状态
    const checkedSrc = [...document.querySelectorAll<HTMLElement>('#setSrcList .src-check:checked')]
      .map(x => x.dataset.id);
    const saveBtn = $('setSave') as HTMLButtonElement;
    saveBtn.disabled = true;
    bridge.saveConfigs(JSON.stringify(data), function (s: unknown, failed?: boolean) {
      // 旧会话 / 被后续保存超越的回包：不干扰当前窗口与输入
      if (session !== settingsSession || seq !== saveSeq) return;
      if (failed) { saveBtn.disabled = false; toast('设置保存失败'); return; }
      let r: { ok?: boolean; msg?: string } = {};
      try { r = JSON.parse(String(s || '{}')) as { ok?: boolean; msg?: string }; } catch (e) { }
      if (!r || r.ok !== true) { saveBtn.disabled = false; toast(r.msg || '设置保存失败'); return; }   // 失败保留窗口与输入
      // 元数据源勾选（独立保存，即时生效）
      bridge.saveMetadataSources(JSON.stringify(checkedSrc));
      // 截图热键立即重注册（配置已保存；注册失败仅提示，不谎报）
      bridge.updateScreenshotHotkey(hotkeyShot, function (ok: unknown, hkFailed?: boolean) {
        toast(!hkFailed && ok === true ? '设置已保存' : '设置已保存（截图热键注册失败）');
      });
      if (window.applyCoverSize) window.applyCoverSize(data.cover_size as string);
      savedTheme = pendingTheme || savedTheme;
      close();
    });
  }

  // 热键占用检查（阶段 E）：已配置的其它热键集合（不含当前输入框）
  function takenHotkeys(exceptId: string): Set<string> {
    const ids = ['setHkHide', 'setHkFull', 'setHkMute', 'setHkShot'].filter((id) => id !== exceptId);
    const taken = new Set<string>();
    ids.forEach((id) => { const v = ($(id) as HTMLInputElement).value; if (v && v !== '请按下组合键…') taken.add(v); });
    return taken;
  }

  // 当前热键捕获状态：同一时刻只允许一个字段在捕获，失焦/关闭/保存统一清理
  let hotkeyCapture: {
    el: HTMLInputElement;
    prev: string;
    handler: (e: KeyboardEvent) => void;
    timer: ReturnType<typeof setTimeout> | null;
  } | null = null;

  // 结束当前捕获：移除监听与冲突计时器；restore=true 时恢复捕获前的值
  function stopHotkeyCapture(restore: boolean): void {
    const cap = hotkeyCapture;
    if (!cap) return;
    hotkeyCapture = null;
    document.removeEventListener('keydown', cap.handler);
    if (cap.timer !== null) clearTimeout(cap.timer);
    if (restore && (cap.el.value === '请按下组合键…' || cap.el.classList.contains('conflict'))) {
      cap.el.value = cap.prev;
    }
    cap.el.classList.remove('hint', 'conflict');
  }

  function bindHotkey(el: HTMLInputElement): void {
    el.addEventListener('blur', function () {
      if (hotkeyCapture && hotkeyCapture.el === el) stopHotkeyCapture(true);
    });
    el.addEventListener('focus', function () {
      stopHotkeyCapture(true);   // 切换字段时先结束上一个捕获
      const prev = el.value;
      el.classList.add('hint');
      el.value = '请按下组合键…';
      const cap = {
        el: el,
        prev: prev,
        timer: null as ReturnType<typeof setTimeout> | null,
        handler: function (e: KeyboardEvent): void {
          e.preventDefault();
          e.stopPropagation();
          const mods: string[] = [];
          if (e.ctrlKey) mods.push('Ctrl');
          if (e.altKey) mods.push('Alt');
          if (e.shiftKey) mods.push('Shift');
          if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return;
          const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
          const combo = mods.concat([key]).join(' + ');
          // 冲突检测：与其它已配置热键重复 → 拒绝并提示（计时器属于本次捕获）
          if (takenHotkeys(el.id).has(combo)) {
            el.value = '冲突，请换一个';
            el.classList.remove('hint');
            el.classList.add('conflict');
            if (cap.timer !== null) clearTimeout(cap.timer);
            cap.timer = setTimeout(() => {
              cap.timer = null;
              if (hotkeyCapture === cap) { el.value = '请按下组合键…'; el.classList.add('hint'); el.classList.remove('conflict'); }
            }, 1200);
            return;
          }
          el.value = combo;
          el.classList.remove('hint');
          document.removeEventListener('keydown', cap.handler);
          hotkeyCapture = null;
        },
      };
      hotkeyCapture = cap;
      document.addEventListener('keydown', cap.handler);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    const setTabs = [...document.querySelectorAll<HTMLElement>('#setNav .nav-item')];
    setTabs.forEach((t) => {
      t.setAttribute('role', 'tab');
      t.setAttribute('aria-controls', 'set-' + t.dataset.tab);
      const on = t.classList.contains('active');
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    function activateTab(item: HTMLElement): void {
      setTabs.forEach((x) => { x.classList.remove('active'); x.setAttribute('aria-selected', 'false'); x.tabIndex = -1; });
      item.classList.add('active');
      item.setAttribute('aria-selected', 'true');
      item.tabIndex = 0;
      document.querySelectorAll<HTMLElement>('#settingsOverlay .page').forEach((p) =>
        p.style.display = 'none');
      $('set-' + item.dataset.tab).style.display = 'block';
      // 记录当前 tab（阶段 E：下次打开停留在上次位置）
      try { localStorage.setItem('settings_tab', item.dataset.tab!); } catch (err) { }
    }
    $('setNav').setAttribute('role', 'tablist');
    $('setNav').addEventListener('click', function (e: MouseEvent) {
      const item = (e.target as HTMLElement).closest('.nav-item') as HTMLElement | null;
      if (!item) return;
      activateTab(item);
    });
    // 方向键在 tab 间移动（WAI-ARIA tab 键盘路径）
    $('setNav').addEventListener('keydown', function (e: KeyboardEvent) {
      const keys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'];
      if (!keys.includes(e.key)) return;
      const cur = (e.target as HTMLElement).closest('.nav-item') as HTMLElement | null;
      if (!cur) return;
      e.preventDefault();
      let i = setTabs.indexOf(cur);
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') i = (i - 1 + setTabs.length) % setTabs.length;
      else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') i = (i + 1) % setTabs.length;
      else if (e.key === 'Home') i = 0;
      else i = setTabs.length - 1;
      activateTab(setTabs[i]);
      setTabs[i].focus();
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
  });

  // Esc 关闭最上层统一由 ui.closeTopSheet 处理（含本窗口），不再单独注册监听
  window.Settings = { open: open, close: close, pickTheme: pickTheme, applyTheme: applyTheme, initTheme: initTheme };
})();

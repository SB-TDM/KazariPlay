/* 设置窗口逻辑（对齐《设置窗口设计计划书》）
 * - 打开/关闭、导航切换
 * - 加载 config 填充表单、主题即时预览、保存/取消/恢复默认
 * - 热键捕获
 */
(function () {
  const $ = (id) => document.getElementById(id);
  let savedTheme = 'light';
  let pendingTheme = null;

  function applyTheme(t) {
    const root = document.documentElement;
    root.classList.add('theme-switch');   // 全局禁 transition，避免重排痕迹
    root.dataset.theme = t;
    void root.offsetHeight;               // 强制同步重排：主题立即生效
    requestAnimationFrame(() => root.classList.remove('theme-switch'));  // 布局稳定后恢复
  }

  function markThemeCard(t) {
    document.querySelectorAll('.theme-card').forEach((c) =>
      c.classList.toggle('on', c.dataset.card === t));
  }

  function fmtKey(k) {
    if (!k) return '';
    return String(k).split('+').map((s) => s.trim())
      .map((s) => s.charAt(0).toUpperCase() + s.slice(1)).join(' + ');
  }

  function open() {
    loadConfig();
    $('settingsOverlay').classList.add('show');
    document.querySelectorAll('#setNav .nav-item').forEach((x) =>
      x.classList.toggle('active', x.dataset.tab === 'general'));
    document.querySelectorAll('#settingsOverlay .page').forEach((p) =>
      p.style.display = p.id === 'set-general' ? 'block' : 'none');
  }

  function close() {
    if (pendingTheme !== null && pendingTheme !== savedTheme) applyTheme(savedTheme);
    closeSheet('settingsOverlay');
  }

  function loadConfig() {
    if (!bridge) return;
    bridge.getConfig(function (s) {
      const cfg = JSON.parse(s || '{}');
      $('setAutoScan').checked = !!cfg.auto_scan_on_startup;
      $('setCoverSize').value = cfg.cover_size || 'medium';
      $('setLogLevel').value = (cfg.log_level || 'INFO').toUpperCase();
      $('setDisguise').value = cfg.disguise_scene || 'excel';
      $('setShowConsole').checked = !!cfg.show_console;
      const hk = cfg.hotkeys || {};
      $('setHkHide').value = fmtKey(hk.emergency_hide) || 'Ctrl + F12';
      $('setHkFull').value = fmtKey(hk.fullscreen_toggle) || 'F11';
      $('setHkMute').value = fmtKey(hk.mute_toggle) || 'Ctrl + M';
      $('setHkShot').value = fmtKey(hk.screenshot) || 'F12';
      $('setCfgPath').textContent = '配置目录：' + (cfg.path || '%APPDATA%\\KazariPlay');
      savedTheme = cfg.theme || 'light';
      pendingTheme = savedTheme;
      applyTheme(savedTheme);
      markThemeCard(savedTheme);
    });
    loadMetaSources();
  }

  // 元数据源列表（favicon + 名称 + 状态，勾选参与混合检索）
  function loadMetaSources() {
    const box = $('setSrcList');
    if (!bridge || !box) return;
    bridge.getMetadataSources(function (s) {
      let sources = [];
      try { sources = JSON.parse(s || '[]'); } catch (e) { }
      box.innerHTML = '';
      sources.forEach(src => {
        const usable = src.status === 'ready' || src.status === 'experimental';
        const statusText = { ready: '可用', experimental: '实验性', pending: '未接入' }[src.status] || src.status;
        const row = document.createElement('label');
        row.className = 'src-opt' + (usable ? '' : ' disabled');
        row.innerHTML = `
          <input type="checkbox" class="src-check" data-id="${esc(src.id)}" ${src.enabled && usable ? 'checked' : ''} ${usable ? '' : 'disabled'}>
          <span class="src-box"></span>
          <img class="src-fav" src="${esc(src.icon)}" onerror="this.style.display='none'" alt="">
          <span class="src-name">${esc(src.name)}</span>
          <span class="src-status">${statusText}</span>`;
        box.appendChild(row);
      });
    });
  }

  function pickTheme(t) {
    pendingTheme = t;
    applyTheme(t);
    markThemeCard(t);
  }

  function save() {
    if (!bridge) return;
    const data = {
      auto_scan_on_startup: $('setAutoScan').checked,
      cover_size: $('setCoverSize').value,
      log_level: $('setLogLevel').value,
      disguise_scene: $('setDisguise').value,
      show_console: $('setShowConsole').checked,
      theme: pendingTheme || savedTheme,
      hotkeys: {
        emergency_hide: $('setHkHide').value,
        fullscreen_toggle: $('setHkFull').value,
        mute_toggle: $('setHkMute').value,
        screenshot: $('setHkShot').value,
      },
    };
    bridge.saveConfigs(JSON.stringify(data));
    // 元数据源勾选（独立保存，即时生效）
    const checkedSrc = [...document.querySelectorAll('#setSrcList .src-check:checked')]
      .map(x => x.dataset.id);
    bridge.saveMetadataSources(JSON.stringify(checkedSrc));
    // 截图热键立即重注册（先写配置再重注册；注册失败静默，配置仍已保存）
    bridge.updateScreenshotHotkey($('setHkShot').value);
    if (window.applyCoverSize) window.applyCoverSize(data.cover_size);
    savedTheme = pendingTheme || savedTheme;
    toast('设置已保存');
    close();
  }

  function bindHotkey(el) {
    el.addEventListener('focus', function () {
      el.classList.add('hint');
      el.value = '请按下组合键…';
      const handler = function (e) {
        e.preventDefault();
        e.stopPropagation();
        const mods = [];
        if (e.ctrlKey) mods.push('Ctrl');
        if (e.altKey) mods.push('Alt');
        if (e.shiftKey) mods.push('Shift');
        if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return;
        const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
        el.value = mods.concat([key]).join(' + ');
        el.classList.remove('hint');
        document.removeEventListener('keydown', handler);
      };
      document.addEventListener('keydown', handler);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('setNav').addEventListener('click', function (e) {
      const item = e.target.closest('.nav-item');
      if (!item) return;
      document.querySelectorAll('#setNav .nav-item').forEach((x) => x.classList.remove('active'));
      item.classList.add('active');
      document.querySelectorAll('#settingsOverlay .page').forEach((p) =>
        p.style.display = 'none');
      $('set-' + item.dataset.tab).style.display = 'block';
    });

    $('setClose').onclick = close;
    $('setCancel').onclick = close;
    $('setSave').onclick = save;
    $('setReset').onclick = function () {
      if (!bridge) return;
      bridge.resetConfig();
      loadConfig();
      toast('已恢复默认设置');
    };
    ['setHkHide', 'setHkFull', 'setHkMute', 'setHkShot'].forEach((id) => bindHotkey($(id)));

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && $('settingsOverlay').classList.contains('show')) close();
    });
  });

  window.Settings = { open: open, close: close, pickTheme: pickTheme, applyTheme: applyTheme };
})();

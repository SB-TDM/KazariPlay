(function () {
  const $ = (id: string): HTMLElement => document.getElementById(id)!;
  const kit = window.SettingsKit;

  let settingsSession = 0;
  let configRequest = 0;
  let saveSeq = 0;

  function isOpen(): boolean {
    return $('settingsOverlay').classList.contains('show');
  }

  function lastTab(): string {
    try {
      return localStorage.getItem('settings_tab') || 'general';
    } catch (e) {
      return 'general';
    }
  }

  function activateTab(name: string, persist: boolean): void {
    const tabs = [...document.querySelectorAll<HTMLElement>('#setNav .nav-item')];
    const target = tabs.find((tab) => tab.dataset.tab === name) ? name : 'general';
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === target;
      tab.classList.toggle('active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll<HTMLElement>('#settingsOverlay .page').forEach((page) =>
      page.style.display = page.id === 'set-' + target ? 'block' : 'none');
    if (persist) {
      try { localStorage.setItem('settings_tab', target); } catch (e) { }
    }
  }

  function loadConfig(session: number): void {
    if (!bridge) return;
    const request = ++configRequest;
    bridge.getConfig(function (s: unknown, failed?: boolean) {
      if (request !== configRequest || session !== settingsSession) return;
      if (failed) {
        toast('读取设置失败');
        return;
      }
      const cfg = kit.model.parse(s);
      if (!cfg) {
        toast('读取设置失败');
        return;
      }
      kit.fields.load(cfg);
      kit.hotkeys.load(kit.model.hotkeys(cfg));
      kit.theme.applyLoaded(cfg.theme || 'light');
      $('setCfgPath').textContent = '配置目录：' + (cfg.path || '%APPDATA%\\KazariPlay');
      kit.sources.load(() => session === settingsSession);
    });
  }

  function open(): void {
    settingsSession++;
    kit.theme.beginLoad();
    kit.hotkeys.stop(true);
    ($('setSave') as HTMLButtonElement).disabled = false;
    const proxyTest = document.getElementById('setProxyTest') as HTMLButtonElement | null;
    if (proxyTest) proxyTest.disabled = false;
    loadConfig(settingsSession);
    activateTab(lastTab(), false);
    showSheet('settingsOverlay');
  }

  function close(): void {
    settingsSession++;
    kit.hotkeys.stop(true);
    closeSheet('settingsOverlay');
  }

  function finishSave(session: number, seq: number, warnings: string[], coverSize: string): void {
    if (session !== settingsSession || seq !== saveSeq) return;
    if (warnings.length) toast('设置已保存（' + warnings.join('，') + '）');
    else toast('设置已保存');
    if (window.applyCoverSize) window.applyCoverSize(coverSize);
    close();
  }

  function save(): void {
    if (!bridge) return;
    const session = settingsSession;
    const seq = ++saveSeq;
    kit.hotkeys.stop(true);
    const fields = kit.fields.read();
    const hotkeys = kit.hotkeys.read();
    const data = {
      ...fields,
      theme: kit.theme.current(),
      hotkeys,
    };
    const checkedSources = kit.sources.readChecked();
    const saveBtn = $('setSave') as HTMLButtonElement;
    const saveSources = (done: (warning: string | null) => void): void => {
      if (checkedSources === null) {
        done('数据源未加载');
        return;
      }
      bridge.saveMetadataSources(JSON.stringify(checkedSources), function (_s: unknown, metaFailed?: boolean) {
        done(metaFailed ? '数据源保存失败' : null);
      });
    };
    saveBtn.disabled = true;

    bridge.saveConfigs(JSON.stringify(data), function (s: unknown, failed?: boolean) {
      if (session !== settingsSession || seq !== saveSeq) return;
      if (failed) {
        saveBtn.disabled = false;
        toast('设置保存失败');
        return;
      }
      let result: { ok?: boolean; msg?: string } = {};
      try { result = JSON.parse(String(s || '{}')); } catch (e) { }
      if (!result || result.ok !== true) {
        saveBtn.disabled = false;
        toast(result.msg || '设置保存失败');
        return;
      }

      saveSources(function (metaWarning) {
        if (session !== settingsSession || seq !== saveSeq) return;
        bridge.updateScreenshotHotkey(hotkeys.screenshot, function (ok: unknown, hotkeyFailed?: boolean) {
          if (session !== settingsSession || seq !== saveSeq) return;
          const warnings: string[] = [];
          if (metaWarning) warnings.push(metaWarning);
          if (hotkeyFailed || ok !== true) warnings.push('截图热键注册失败');
          finishSave(session, seq, warnings, fields.cover_size);
        });
      });
    });
  }

  function reset(): void {
    if (!bridge) return;
    const session = settingsSession;
    showConfirmDialog({
      title: '恢复默认设置',
      message: '将重置主题、热键、封面尺寸、日志级别与元数据源等设置，是否继续？',
      danger: true,
      okText: '恢复默认',
      cb: function () {
        bridge.resetConfig(function () {
          if (session !== settingsSession) return;
          loadConfig(settingsSession);
          toast('已恢复默认设置');
        });
      },
    });
  }

  function bindTabs(): void {
    const tabs = [...document.querySelectorAll<HTMLElement>('#setNav .nav-item')];
    tabs.forEach((tab) => {
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', 'set-' + tab.dataset.tab);
      const on = tab.classList.contains('active');
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
    });
    const nav = $('setNav');
    nav.setAttribute('role', 'tablist');
    nav.addEventListener('click', function (e: MouseEvent) {
      const item = (e.target as HTMLElement).closest('.nav-item') as HTMLElement | null;
      if (item?.dataset.tab) activateTab(item.dataset.tab, true);
    });
    nav.addEventListener('keydown', function (e: KeyboardEvent) {
      const keys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'];
      if (!keys.includes(e.key)) return;
      const current = (e.target as HTMLElement).closest('.nav-item') as HTMLElement | null;
      if (!current) return;
      e.preventDefault();
      let index = tabs.indexOf(current);
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') index = (index - 1 + tabs.length) % tabs.length;
      else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') index = (index + 1) % tabs.length;
      else if (e.key === 'Home') index = 0;
      else index = tabs.length - 1;
      const next = tabs[index];
      if (next?.dataset.tab) activateTab(next.dataset.tab, true);
      next?.focus();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindTabs();
    kit.fields.bind(isOpen);
    kit.hotkeys.bindAll();
    document.querySelectorAll<HTMLElement>('#settingsOverlay .theme-card').forEach((card) => {
      card.addEventListener('click', () => {
        if (card.dataset.card) kit.theme.pickTheme(card.dataset.card);
      });
    });
    ($('setClose')).onclick = close;
    ($('setCancel')).onclick = close;
    ($('setSave')).onclick = save;
    ($('setReset')).onclick = reset;
  });

  window.Settings = {
    open,
    close,
    pickTheme: (theme) => kit.theme.pickTheme(theme),
    applyTheme: (theme) => kit.theme.applyTheme(theme),
    initTheme: (theme) => kit.theme.initTheme(theme),
  };
})();

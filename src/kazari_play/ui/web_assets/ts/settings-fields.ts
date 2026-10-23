(function () {
  let isCurrent = (): boolean => true;

  function control<T extends HTMLElement>(id: string): T | null {
    return document.getElementById(id) as T | null;
  }

  function selectValue(id: string): string {
    return (control<HTMLSelectElement>(id)?.value || '');
  }

  function inputValue(id: string): string {
    return (control<HTMLInputElement>(id)?.value || '');
  }

  function updateProxyMode(): void {
    const mode = selectValue('setProxyMode');
    const input = control<HTMLInputElement>('setProxyUrl');
    if (input) input.disabled = mode !== 'custom';
  }

  function testProxy(): void {
    if (!bridge) return;
    const btn = control<HTMLButtonElement>('setProxyTest');
    const out = control<HTMLElement>('setProxyTestResult');
    if (!btn || !out) return;
    const mode = selectValue('setProxyMode');
    const url = inputValue('setProxyUrl').trim();
    if (mode === 'custom' && !url) {
      out.textContent = '请填写代理地址';
      return;
    }
    btn.disabled = true;
    out.textContent = '测试中…';
    bridge.testMetadataConnection(JSON.stringify({ mode, proxy_url: url }), function (s: unknown, failed?: boolean) {
      if (!isCurrent()) return;
      btn.disabled = false;
      if (failed) {
        out.textContent = '测试失败：后端无响应';
        return;
      }
      let result: {
        msg?: string;
        results?: Array<{ name?: string; ok?: boolean; ms?: number; msg?: string }>;
      } = {};
      try { result = JSON.parse(String(s || '{}')); } catch (e) { }
      const results = result.results || [];
      if (result.msg && results.length === 0) {
        out.textContent = '代理配置错误：' + result.msg;
        return;
      }
      out.textContent = results.length
        ? results.map((item) =>
          `${item.name || ''} ${item.ok ? '可用' : '失败'}${item.ok ? ` (${item.ms || 0}ms)` : `（${item.msg || ''}）`}`)
          .join('  ·  ')
        : '没有测试结果';
    });
  }

  function load(cfg: SettingsConfig): void {
    const cover = cfg.cover_download || {};
    const meta = cfg.metadata_sources || {};
    const net = cfg.network || {};

    const coverSize = control<HTMLSelectElement>('setCoverSize');
    if (coverSize) coverSize.value = cfg.cover_size || 'medium';
    const logLevel = control<HTMLSelectElement>('setLogLevel');
    if (logLevel) logLevel.value = String(cfg.log_level || 'INFO').toUpperCase();
    const disguise = control<HTMLSelectElement>('setDisguise');
    if (disguise) disguise.value = cfg.disguise_scene || 'excel';
    const showConsole = control<HTMLInputElement>('setShowConsole');
    if (showConsole) showConsole.checked = !!cfg.show_console;

    const coverSource = control<HTMLSelectElement>('setCoverSource');
    if (coverSource) coverSource.value = String(cover.preferred_source || 'auto');
    const coverTimeout = control<HTMLSelectElement>('setCoverTimeout');
    if (coverTimeout) coverTimeout.value = String(cover.timeout ?? 90);
    const coverConcurrent = control<HTMLSelectElement>('setCoverConcurrent');
    if (coverConcurrent) coverConcurrent.value = String(cover.max_concurrent ?? 4);

    const shionlibKey = control<HTMLInputElement>('setShionlibKey');
    if (shionlibKey) shionlibKey.value = String(meta.shionlib_api_key || '');
    const kungalConcurrent = control<HTMLSelectElement>('setKungalConcurrent');
    if (kungalConcurrent) kungalConcurrent.value = String(meta.kungal_concurrency ?? 4);

    const proxyMode = control<HTMLSelectElement>('setProxyMode');
    if (proxyMode) proxyMode.value = String(net.proxy_mode || 'direct');
    const proxyUrl = control<HTMLInputElement>('setProxyUrl');
    if (proxyUrl) proxyUrl.value = String(net.proxy_url || '');
    updateProxyMode();
  }

  function read(): SettingsFormValues {
    return {
      cover_size: selectValue('setCoverSize'),
      log_level: selectValue('setLogLevel'),
      disguise_scene: selectValue('setDisguise'),
      show_console: control<HTMLInputElement>('setShowConsole')?.checked === true,
      cover_download: {
        preferred_source: selectValue('setCoverSource'),
        timeout: parseInt(selectValue('setCoverTimeout'), 10) || 90,
        max_concurrent: parseInt(selectValue('setCoverConcurrent'), 10) || 4,
      },
      metadata_sources: {
        shionlib_api_key: inputValue('setShionlibKey').trim(),
        kungal_concurrency: parseInt(selectValue('setKungalConcurrent'), 10) || 4,
      },
      network: {
        proxy_mode: selectValue('setProxyMode'),
        proxy_url: inputValue('setProxyUrl').trim(),
      },
    };
  }

  function bind(current: () => boolean): void {
    isCurrent = current;
    const proxyMode = control<HTMLSelectElement>('setProxyMode');
    if (proxyMode) proxyMode.addEventListener('change', updateProxyMode);
    const proxyTest = control<HTMLButtonElement>('setProxyTest');
    if (proxyTest) proxyTest.onclick = testProxy;
  }

  const kit = window.SettingsKit || (window.SettingsKit = {} as SettingsKitApi);
  kit.fields = { bind, load, read };
})();

/* settings.ts — 设置窗口逻辑（对齐《设置窗口设计计划书》）
 * - 打开/关闭、导航切换
 * - 加载 config 填充表单、主题即时预览、保存/取消/恢复默认
 * - 热键捕获
 */
(function () {
  const $ = (id: string): HTMLElement => document.getElementById(id)!;
  let savedTheme = 'light';
  let pendingTheme: string | null = null;
  let savedOverlay: Record<string, unknown> = {};   // 保留 overlay 其他配置（合并保存用）

  // 清洗过滤器清单（与 C++ overlay/src/filter_chain.cpp 注册保持一致）
  // agg=true 为"激进"过滤器：默认关闭，误伤正常字幕风险高（叠词/短重复/ABAB），需手动开启
  const FILTER_DEFS: CleanFilterDef[] = [
    { id: 'dedup_chars', name: '重复字符去重', desc: 'AAAABBBB→AB' },
    { id: 'dedup_lines', name: '整句重复去重', desc: 'ABCDABCD→ABCD' },
    { id: 'dedup_mixed_lines', name: '混合重复行去重', desc: 'S1S1S2S2→S1S2', agg: true },
    { id: 'incremental_dedup', name: '递增拼接去重', desc: '「マ「マジ…→「マジ', agg: true },
    { id: 'furigana', name: '注音清理', desc: '{漢字/かな}→漢字' },
    { id: 'html_tag', name: 'HTML 标签清理', desc: '<div>x</div>→x' },
    { id: 'control_char', name: '控制字符过滤', desc: '丢弃 ASCII 控制符' },
    { id: 'shift_jis', name: '非日文字符过滤', desc: '乱码清除', agg: true },
    { id: 'english_symbol', name: '英文标点过滤', desc: '丢弃 ASCII 标点', agg: true },
    { id: 'quote_only', name: '仅保留「」内容', desc: '会丢旁白', agg: true },
    { id: 'unicode_normalize', name: '全角转半角', desc: 'Unicode 正规化' },
    { id: 'line_trimmer', name: '行截取', desc: '只留前/后 N 行', agg: true },
    { id: 'regex_replace', name: '正则替换', desc: '用户自定义规则', agg: true },
  ];
  window.CLEAN_FILTER_DEFS = FILTER_DEFS;   // 供游戏详情页清洗配置共用

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
    if (window.SubtitleStyle) window.SubtitleStyle.load();
    $('settingsOverlay').classList.add('show');
    // 恢复上次停留的 tab（阶段 E：tab 记忆）
    let lastTab = 'general';
    try { lastTab = localStorage.getItem('settings_tab') || 'general'; } catch (e) { }
    document.querySelectorAll<HTMLElement>('#setNav .nav-item').forEach((x) =>
      x.classList.toggle('active', x.dataset.tab === lastTab));
    document.querySelectorAll<HTMLElement>('#settingsOverlay .page').forEach((p) =>
      p.style.display = p.id === 'set-' + lastTab ? 'block' : 'none');
    if (lastTab === 'subtitle' && window.SubtitleStyle) window.SubtitleStyle.load();
  }

  function close(): void {
    if (pendingTheme !== null && pendingTheme !== savedTheme) applyTheme(savedTheme);
    // 关闭设置页时隐藏预览字幕（预览应随字幕界面关闭而消失）
    if (bridge && bridge.hideSubtitle) bridge.hideSubtitle();
    closeSheet('settingsOverlay');
  }

  function loadConfig(): void {
    if (!bridge) return;
    bridge.getConfig(function (s: unknown) {
      const cfg = JSON.parse(String(s || '{}')) as Record<string, unknown> & {
        hotkeys?: Record<string, string>; overlay?: Record<string, unknown>;
        translate?: Record<string, unknown>; textractor?: Record<string, unknown>;
        clean?: Record<string, unknown>; subtitle?: { enabled?: boolean };
      };
      ($('setAutoScan') as HTMLInputElement).checked = !!cfg.auto_scan_on_startup;
      ($('setCoverSize') as HTMLSelectElement).value = (cfg.cover_size as string) || 'medium';
      ($('setLogLevel') as HTMLSelectElement).value = String(cfg.log_level || 'INFO').toUpperCase();
      ($('setDisguise') as HTMLSelectElement).value = (cfg.disguise_scene as string) || 'excel';
      ($('setShowConsole') as HTMLInputElement).checked = !!cfg.show_console;
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
      // Hook 实时翻译配置
      savedOverlay = cfg.overlay || {};
      const tr = cfg.translate || {};
      const tx = cfg.textractor || {};
      const ai = (tr.ai || {}) as Record<string, string>;
      ($('setAiBaseUrl') as HTMLInputElement).value = ai.base_url || 'https://api.deepseek.com';
      ($('setAiApiKey') as HTMLInputElement).value = ai.api_key || '';
      ($('setAiModel') as HTMLInputElement).value = ai.model || 'deepseek-chat';
      ($('setSrcLang') as HTMLSelectElement).value = (tr.source_lang as string) || 'ja';
      ($('setDstLang') as HTMLSelectElement).value = (tr.target_lang as string) || 'zh';
      ($('setHostDir') as HTMLInputElement).value = (tx.host_dir as string) || '';
      ($('setTextCodepage') as HTMLInputElement).value = String(tx.codepage || 0);
      ($('setSubtitleEnabled') as HTMLInputElement).checked = (savedOverlay.subtitle_enabled !== false);
      // 字幕总开关以 subtitle.enabled 为准（控制面板并入后由该键持久化），缺省开
      const subEnabled = cfg.subtitle && cfg.subtitle.enabled;
      if (typeof subEnabled === 'boolean') ($('setSubtitleEnabled') as HTMLInputElement).checked = subEnabled;
      const cln = cfg.clean || {};
      ($('setAiClean') as HTMLInputElement).checked = !!cln.ai_assist_enabled;
      ($('setAiCleanTh') as HTMLSelectElement).value = (cln.ai_assist_threshold as string) === 'always' ? 'always' : 'dirty';
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
  }

  function save(): void {
    if (!bridge) return;
    const data: Record<string, unknown> = {
      auto_scan_on_startup: ($('setAutoScan') as HTMLInputElement).checked,
      cover_size: ($('setCoverSize') as HTMLSelectElement).value,
      log_level: ($('setLogLevel') as HTMLSelectElement).value,
      disguise_scene: ($('setDisguise') as HTMLSelectElement).value,
      show_console: ($('setShowConsole') as HTMLInputElement).checked,
      theme: pendingTheme || savedTheme,
      hotkeys: {
        emergency_hide: ($('setHkHide') as HTMLInputElement).value,
        fullscreen_toggle: ($('setHkFull') as HTMLInputElement).value,
        mute_toggle: ($('setHkMute') as HTMLInputElement).value,
        screenshot: ($('setHkShot') as HTMLInputElement).value,
      },
      overlay: Object.assign({}, savedOverlay, { subtitle_enabled: ($('setSubtitleEnabled') as HTMLInputElement).checked }),
      textractor: {
        host_dir: ($('setHostDir') as HTMLInputElement).value.trim(),
        codepage: parseInt(($('setTextCodepage') as HTMLInputElement).value, 10) || 0,
      },
      translate: {
        engine: 'ai',
        ai: {
          base_url: ($('setAiBaseUrl') as HTMLInputElement).value.trim(),
          api_key: ($('setAiApiKey') as HTMLInputElement).value.trim(),
          model: ($('setAiModel') as HTMLInputElement).value.trim() || 'deepseek-chat',
        },
        source_lang: ($('setSrcLang') as HTMLSelectElement).value,
        target_lang: ($('setDstLang') as HTMLSelectElement).value,
      },
      clean: {
        ai_assist_enabled: ($('setAiClean') as HTMLInputElement).checked,
        ai_assist_threshold: ($('setAiCleanTh') as HTMLSelectElement).value,
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
      // 离开字幕 tab 时隐藏预览字幕（预览随字幕界面切换而消失）
      if (item.dataset.tab !== 'subtitle' && bridge && bridge.hideSubtitle) bridge.hideSubtitle();
      // 字幕 tab 激活时加载样式（实时生效区，无需点保存）
      if (item.dataset.tab === 'subtitle' && window.SubtitleStyle) window.SubtitleStyle.load();
    });

    $('setClose').onclick = close;
    $('setCancel').onclick = close;
    $('setSave').onclick = save;
    // 「显示字幕」开关：实时下发 C++ overlay（游戏运行中立即生效），并持久化
    ($('setSubtitleEnabled') as HTMLInputElement).addEventListener('change', function () {
      if (bridge.setSubtitleEnabled) bridge.setSubtitleEnabled(($('setSubtitleEnabled') as HTMLInputElement).checked);
    });
    // 翻译测试（用已保存配置；未保存时先点保存）
    ($('setTransTest')).onclick = function () {
      const resEl = $('setTransTestRes');
      resEl.textContent = '测试中…（使用已保存配置）';
      bridge.testTranslation('こんにちは、世界', function (s: unknown) {
        try {
          const r = JSON.parse(String(s || '{}')) as { ok?: boolean; msg?: string };
          resEl.textContent = r.ok ? ('✓ ' + r.msg) : ('✗ ' + r.msg);
        } catch (e) { resEl.textContent = '✗ 测试失败'; }
      });
    };
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
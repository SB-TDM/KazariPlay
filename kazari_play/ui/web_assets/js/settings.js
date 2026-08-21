"use strict";
/* settings.ts — 设置窗口逻辑（对齐《设置窗口设计计划书》）
 * - 打开/关闭、导航切换
 * - 加载 config 填充表单、主题即时预览、保存/取消/恢复默认
 * - 热键捕获
 */
(function () {
    const $ = (id) => document.getElementById(id);
    let savedTheme = 'light';
    let pendingTheme = null;
    let savedOverlay = {}; // 保留 overlay 其他配置（合并保存用）
    // 清洗过滤器清单（与 C++ overlay/src/filter_chain.cpp 注册保持一致）
    // agg=true 为"激进"过滤器：默认关闭，误伤正常字幕风险高（叠词/短重复/ABAB），需手动开启
    const FILTER_DEFS = [
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
    window.CLEAN_FILTER_DEFS = FILTER_DEFS; // 供游戏详情页清洗配置共用
    function applyTheme(t) {
        const root = document.documentElement;
        root.classList.add('theme-switch'); // 全局禁 transition，避免重排痕迹
        root.dataset.theme = t;
        void root.offsetHeight; // 强制同步重排：主题立即生效
        requestAnimationFrame(() => root.classList.remove('theme-switch')); // 布局稳定后恢复
    }
    function markThemeCard(t) {
        document.querySelectorAll('.theme-card').forEach((c) => c.classList.toggle('on', c.dataset.card === t));
    }
    function fmtKey(k) {
        if (!k)
            return '';
        return String(k).split('+').map((s) => s.trim())
            .map((s) => s.charAt(0).toUpperCase() + s.slice(1)).join(' + ');
    }
    function open() {
        loadConfig();
        if (window.SubtitleStyle)
            window.SubtitleStyle.load();
        $('settingsOverlay').classList.add('show');
        // 恢复上次停留的 tab（阶段 E：tab 记忆）
        let lastTab = 'general';
        try {
            lastTab = localStorage.getItem('settings_tab') || 'general';
        }
        catch (e) { }
        document.querySelectorAll('#setNav .nav-item').forEach((x) => x.classList.toggle('active', x.dataset.tab === lastTab));
        document.querySelectorAll('#settingsOverlay .page').forEach((p) => p.style.display = p.id === 'set-' + lastTab ? 'block' : 'none');
        if (lastTab === 'subtitle' && window.SubtitleStyle)
            window.SubtitleStyle.load();
    }
    function close() {
        if (pendingTheme !== null && pendingTheme !== savedTheme)
            applyTheme(savedTheme);
        // 关闭设置页时隐藏预览字幕（预览应随字幕界面关闭而消失）
        if (bridge && bridge.hideSubtitle)
            bridge.hideSubtitle();
        closeSheet('settingsOverlay');
    }
    function loadConfig() {
        if (!bridge)
            return;
        bridge.getConfig(function (s) {
            const cfg = JSON.parse(String(s || '{}'));
            $('setAutoScan').checked = !!cfg.auto_scan_on_startup;
            $('setCoverSize').value = cfg.cover_size || 'medium';
            $('setLogLevel').value = String(cfg.log_level || 'INFO').toUpperCase();
            $('setDisguise').value = cfg.disguise_scene || 'excel';
            $('setShowConsole').checked = !!cfg.show_console;
            const hk = cfg.hotkeys || {};
            $('setHkHide').value = fmtKey(hk.emergency_hide) || 'Ctrl + F12';
            $('setHkFull').value = fmtKey(hk.fullscreen_toggle) || 'F11';
            $('setHkMute').value = fmtKey(hk.mute_toggle) || 'Ctrl + M';
            $('setHkShot').value = fmtKey(hk.screenshot) || 'F12';
            ($('setCfgPath')).textContent = '配置目录：' + (cfg.path || '%APPDATA%\\KazariPlay');
            savedTheme = cfg.theme || 'light';
            pendingTheme = savedTheme;
            applyTheme(savedTheme);
            markThemeCard(savedTheme);
            // Hook 实时翻译配置
            savedOverlay = cfg.overlay || {};
            const tr = cfg.translate || {};
            const tx = cfg.textractor || {};
            const ai = (tr.ai || {});
            $('setAiBaseUrl').value = ai.base_url || 'https://api.deepseek.com';
            $('setAiApiKey').value = ai.api_key || '';
            $('setAiModel').value = ai.model || 'deepseek-chat';
            $('setSrcLang').value = tr.source_lang || 'ja';
            $('setDstLang').value = tr.target_lang || 'zh';
            $('setHostDir').value = tx.host_dir || '';
            $('setTextCodepage').value = String(tx.codepage || 0);
            $('setSubtitleEnabled').checked = (savedOverlay.subtitle_enabled !== false);
            // 字幕总开关以 subtitle.enabled 为准（控制面板并入后由该键持久化），缺省开
            const subEnabled = cfg.subtitle && cfg.subtitle.enabled;
            if (typeof subEnabled === 'boolean')
                $('setSubtitleEnabled').checked = subEnabled;
            const cln = cfg.clean || {};
            $('setAiClean').checked = !!cln.ai_assist_enabled;
            $('setAiCleanTh').value = cln.ai_assist_threshold === 'always' ? 'always' : 'dirty';
        });
        loadMetaSources();
    }
    // 元数据源列表（favicon + 名称 + 状态，勾选参与混合检索）
    function loadMetaSources() {
        const box = $('setSrcList');
        if (!bridge || !box)
            return;
        bridge.getMetadataSources(function (s) {
            let sources = [];
            try {
                sources = JSON.parse(String(s || '[]'));
            }
            catch (e) { }
            box.innerHTML = '';
            sources.forEach(src => {
                const usable = src.status === 'ready' || src.status === 'experimental';
                const statusText = { ready: '可用', experimental: '实验性', pending: '未接入' };
                const st = (statusText[src.status] || src.status || '');
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
    function pickTheme(t) {
        pendingTheme = t;
        applyTheme(t);
        markThemeCard(t);
    }
    function save() {
        if (!bridge)
            return;
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
            overlay: Object.assign({}, savedOverlay, { subtitle_enabled: $('setSubtitleEnabled').checked }),
            textractor: {
                host_dir: $('setHostDir').value.trim(),
                codepage: parseInt($('setTextCodepage').value, 10) || 0,
            },
            translate: {
                engine: 'ai',
                ai: {
                    base_url: $('setAiBaseUrl').value.trim(),
                    api_key: $('setAiApiKey').value.trim(),
                    model: $('setAiModel').value.trim() || 'deepseek-chat',
                },
                source_lang: $('setSrcLang').value,
                target_lang: $('setDstLang').value,
            },
            clean: {
                ai_assist_enabled: $('setAiClean').checked,
                ai_assist_threshold: $('setAiCleanTh').value,
            },
        };
        bridge.saveConfigs(JSON.stringify(data));
        // 元数据源勾选（独立保存，即时生效）
        const checkedSrc = [...document.querySelectorAll('#setSrcList .src-check:checked')]
            .map(x => x.dataset.id);
        bridge.saveMetadataSources(JSON.stringify(checkedSrc));
        // 截图热键立即重注册（先写配置再重注册；注册失败静默，配置仍已保存）
        bridge.updateScreenshotHotkey($('setHkShot').value);
        if (window.applyCoverSize)
            window.applyCoverSize(data.cover_size);
        savedTheme = pendingTheme || savedTheme;
        toast('设置已保存');
        close();
    }
    // 热键占用检查（阶段 E）：已配置的其它热键集合（不含当前输入框）
    function takenHotkeys(exceptId) {
        const ids = ['setHkHide', 'setHkFull', 'setHkMute', 'setHkShot'].filter((id) => id !== exceptId);
        const taken = new Set();
        ids.forEach((id) => { const v = $(id).value; if (v && v !== '请按下组合键…')
            taken.add(v); });
        return taken;
    }
    function bindHotkey(el) {
        el.addEventListener('focus', function () {
            el.classList.add('hint');
            el.value = '请按下组合键…';
            const handler = function (e) {
                e.preventDefault();
                e.stopPropagation();
                const mods = [];
                if (e.ctrlKey)
                    mods.push('Ctrl');
                if (e.altKey)
                    mods.push('Alt');
                if (e.shiftKey)
                    mods.push('Shift');
                if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key))
                    return;
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
        $('setNav').addEventListener('click', function (e) {
            const item = e.target.closest('.nav-item');
            if (!item)
                return;
            document.querySelectorAll('#setNav .nav-item').forEach((x) => x.classList.remove('active'));
            item.classList.add('active');
            document.querySelectorAll('#settingsOverlay .page').forEach((p) => p.style.display = 'none');
            $('set-' + item.dataset.tab).style.display = 'block';
            // 记录当前 tab（阶段 E：下次打开停留在上次位置）
            try {
                localStorage.setItem('settings_tab', item.dataset.tab);
            }
            catch (err) { }
            // 离开字幕 tab 时隐藏预览字幕（预览随字幕界面切换而消失）
            if (item.dataset.tab !== 'subtitle' && bridge && bridge.hideSubtitle)
                bridge.hideSubtitle();
            // 字幕 tab 激活时加载样式（实时生效区，无需点保存）
            if (item.dataset.tab === 'subtitle' && window.SubtitleStyle)
                window.SubtitleStyle.load();
        });
        $('setClose').onclick = close;
        $('setCancel').onclick = close;
        $('setSave').onclick = save;
        // 「显示字幕」开关：实时下发 C++ overlay（游戏运行中立即生效），并持久化
        $('setSubtitleEnabled').addEventListener('change', function () {
            if (bridge.setSubtitleEnabled)
                bridge.setSubtitleEnabled($('setSubtitleEnabled').checked);
        });
        // 翻译测试（用已保存配置；未保存时先点保存）
        ($('setTransTest')).onclick = function () {
            const resEl = $('setTransTestRes');
            resEl.textContent = '测试中…（使用已保存配置）';
            bridge.testTranslation('こんにちは、世界', function (s) {
                try {
                    const r = JSON.parse(String(s || '{}'));
                    resEl.textContent = r.ok ? ('✓ ' + r.msg) : ('✗ ' + r.msg);
                }
                catch (e) {
                    resEl.textContent = '✗ 测试失败';
                }
            });
        };
        ($('setReset')).onclick = function () {
            if (!bridge)
                return;
            bridge.resetConfig();
            loadConfig();
            toast('已恢复默认设置');
        };
        ['setHkHide', 'setHkFull', 'setHkMute', 'setHkShot'].forEach((id) => bindHotkey($(id)));
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && $('settingsOverlay').classList.contains('show'))
                close();
        });
    });
    window.Settings = { open: open, close: close, pickTheme: pickTheme, applyTheme: applyTheme };
})();

"use strict";
// ============================================================
// detail_translate.ts — 详情内 Hook 实时翻译行 + 每游戏文本清洗配置
// 依赖：state.ts / core.ts（toast）/ ui.ts / hook_select.ts（HookSelect）
// 定义：renderTransRow / loadCleanCfg / collectCleanCfg / saveCleanCfg / resetCleanCfg
// 被依赖：detail.ts（refreshDetail 调用 renderTransRow）
// 注意：window.CLEAN_FILTER_DEFS 由 settings.ts 提供（FILTER_DEFS 全局暴露）
// ============================================================
function renderTransRow() {
    const row = document.getElementById('dlgTransRow');
    if (!row)
        return;
    const g = App.data.currentGame;
    row.style.display = 'block';
    const sw = document.getElementById('dlgTrans');
    sw.checked = !!g.translate_enabled;
    const badge = document.getElementById('dlgHookBadge');
    const rehook = document.getElementById('dlgRehook');
    if (g.has_hook_code) {
        badge.textContent = '已配置 Hook 点';
        badge.classList.add('on');
        rehook.textContent = '重新选择';
        rehook.onclick = () => {
            bridge.clearHookCode(String(g.id));
            g.has_hook_code = false;
            renderTransRow();
            toast('已清除 Hook 点，可重新选择');
        };
    }
    else {
        badge.textContent = '未配置 Hook 点';
        badge.classList.remove('on');
        rehook.textContent = '选择 Hook';
        rehook.onclick = () => {
            bridge.getRunning(function (rid) {
                if (rid && rid === g.id && window.HookSelect) {
                    window.HookSelect.open(g.id);
                }
                else {
                    toast('请先启动游戏，再选择 Hook 点');
                }
            });
        };
    }
    sw.onchange = () => {
        bridge.toggleGameTranslation(String(g.id), sw.checked);
        g.translate_enabled = sw.checked;
        toast(sw.checked ? '已启用实时翻译' : '已关闭实时翻译');
    };
    // 折叠：点击标题栏展开/收起配置区（默认收起，避免打断详情阅读流）
    const head = document.getElementById('dlgTransHead');
    const body = document.getElementById('dlgTransBody');
    const arrow = document.getElementById('dlgTransArrow');
    if (head && body) {
        const toggle = () => {
            const show = body.style.display !== 'none';
            body.style.display = show ? 'none' : 'block';
            if (arrow)
                arrow.textContent = show ? '▸' : '▾';
        };
        head.onclick = (e) => {
            // 点击开关本身不折叠
            if (e.target.closest('.switch'))
                return;
            toggle();
        };
        // 已配置 Hook 且本游戏启用翻译时自动展开（否则保持折叠）
        if (g.has_hook_code && g.translate_enabled) {
            body.style.display = 'block';
            if (arrow)
                arrow.textContent = '▾';
        }
    }
    // 文本清洗配置（每游戏）
    const cleanBtn = document.getElementById('dlgCleanCfg');
    const cleanPanel = document.getElementById('dlgCleanPanel');
    if (cleanBtn && cleanPanel) {
        cleanBtn.onclick = (e) => {
            e.stopPropagation();
            const show = cleanPanel.style.display === 'none';
            cleanPanel.style.display = show ? 'block' : 'none';
            if (show)
                loadCleanCfg(g.id);
        };
    }
    const cleanSave = document.getElementById('dlgCleanSave');
    if (cleanSave)
        cleanSave.onclick = () => saveCleanCfg();
    const cleanReset = document.getElementById('dlgCleanReset');
    if (cleanReset)
        cleanReset.onclick = resetCleanCfg;
}
// 清洗配置：加载某游戏当前过滤器状态并渲染勾选
function loadCleanCfg(gameId) {
    const box = document.getElementById('dlgCleanFilters');
    const defs = window.CLEAN_FILTER_DEFS || [];
    if (!box || !defs.length || !bridge)
        return;
    bridge.getCleanFilterConfig(String(gameId), function (s) {
        let data = {};
        try {
            data = JSON.parse(String(s || '{}'));
        }
        catch (e) { }
        let list = data.filters || [];
        const srcEl = document.getElementById('dlgCleanSrc');
        if (srcEl) {
            srcEl.textContent = data.source === 'runtime' ? '（当前运行中生效配置）'
                : data.source === 'override' ? '（自定义配置）'
                    : '（引擎默认策略，保存后转为自定义）';
        }
        const byId = {};
        list.forEach((f) => { if (f && f.id)
            byId[f.id] = f; });
        const merged = defs.map((d) => {
            const cur = byId[d.id] || {};
            return Object.assign({}, d, {
                enabled: cur.enabled === undefined ? false : !!cur.enabled,
                order: cur.order === undefined ? 999 : cur.order,
            });
        });
        merged.sort((a, b) => (a.enabled === b.enabled ? a.order - b.order : (b.enabled ? 1 : 0) - (a.enabled ? 1 : 0)));
        box.innerHTML = '';
        merged.forEach((f) => {
            const row = document.createElement('label');
            row.className = 'clean-fil';
            row.innerHTML = `
        <input type="checkbox" class="clean-check" data-id="${esc(f.id)}" ${f.enabled ? 'checked' : ''}>
        <span class="clean-box"></span>
        <span class="clean-name">${esc(f.name)}${f.agg ? ' <em class="clean-agg">激进</em>' : ''}</span>
        <span class="clean-desc">${esc(f.desc || '')}</span>`;
            // 勾选即保存并实时下发（游戏运行中立即生效）
            row.querySelector('.clean-check').addEventListener('change', () => saveCleanCfg(true));
            box.appendChild(row);
        });
    });
}
function collectCleanCfg() {
    const defs = window.CLEAN_FILTER_DEFS || [];
    const checks = {};
    [...document.querySelectorAll('#dlgCleanFilters .clean-check')]
        .forEach((c) => { checks[c.dataset.id] = c.checked; });
    return defs.map((d, i) => ({ id: d.id, enabled: !!checks[d.id], order: i }));
}
function saveCleanCfg(silent) {
    if (!App.data.currentGame || !bridge)
        return;
    bridge.setCleanFilterConfig(String(App.data.currentGame.id), JSON.stringify(collectCleanCfg()));
    if (!silent) {
        const res = document.getElementById('dlgCleanRes');
        if (res) {
            res.textContent = '已保存';
            setTimeout(() => { res.textContent = ''; }, 2000);
        }
    }
}
function resetCleanCfg() {
    if (!App.data.currentGame || !bridge)
        return;
    bridge.setCleanFilterConfig(String(App.data.currentGame.id), '[]');
    const res = document.getElementById('dlgCleanRes');
    if (res) {
        res.textContent = '已恢复引擎默认';
        setTimeout(() => { res.textContent = ''; }, 2000);
    }
    loadCleanCfg(App.data.currentGame.id);
}

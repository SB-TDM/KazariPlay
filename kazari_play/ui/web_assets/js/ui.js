"use strict";
// ============================================================
// ui.ts — Sheet / 通用对话框 / 右键菜单基础设施
// 依赖：core.ts（esc）
// 定义：showSheet / closeSheet / closeTopSheet / formOverlayVisible /
//       showConfirmDialog / confirmOk / showInputDialog / inputOk /
//       openPicker / showContextMenu
// 被依赖：games.ts（卡片右键菜单）、collections.ts（收藏夹右键菜单）、
//         batch.ts（openPicker）、detail.ts / screenshots.ts（对话框）
// ============================================================
// ---------- Sheet（底部抽屉 / 居中弹层）----------
function showSheet(id) {
    const o = document.getElementById(id);
    if (!o)
        return;
    o.classList.remove('hiding');
    o.classList.add('show');
}
function closeSheet(id, instant) {
    const o = document.getElementById(id);
    if (!o)
        return;
    if (instant) {
        o.classList.remove('show', 'hiding');
        if (id === 'detailOverlay')
            setActiveCard(null);
        return;
    }
    o.classList.remove('show');
    o.classList.add('hiding');
    setTimeout(() => o.classList.remove('hiding'), 280);
    if (id === 'detailOverlay')
        setActiveCard(null);
}
// 点击遮罩关闭（Hook 选择弹窗除外：误关后只能重启游戏才能再选）
document.querySelectorAll('.overlay').forEach(o => {
    if (o.id === 'hookSelectOverlay')
        return;
    o.addEventListener('click', e => { if (e.target === o)
        closeSheet(o.id); });
});
// Esc 关闭最上层（顺序：表单 > 截图预览 > 管理游戏 > 收藏夹 > 选择器 > 详情）
function closeTopSheet() {
    if (formOverlayVisible())
        return closeSheet('formOverlay');
    if (document.getElementById('shotPreviewOverlay').classList.contains('show'))
        return closeSheet('shotPreviewOverlay');
    if (document.getElementById('manageGamesOverlay').classList.contains('show'))
        return closeSheet('manageGamesOverlay');
    if (document.getElementById('collectionOverlay').classList.contains('show'))
        return closeSheet('collectionOverlay');
    if (document.getElementById('pickerOverlay').classList.contains('show'))
        return closeSheet('pickerOverlay');
    if (document.getElementById('detailOverlay').classList.contains('show'))
        closeSheet('detailOverlay');
}
function formOverlayVisible() {
    return document.getElementById('formOverlay').classList.contains('show');
}
// ---------- 通用确认对话框（替代原生 confirm）----------
let confirmCb = null;
function showConfirmDialog(opts) {
    document.getElementById('confirmTitle').textContent = opts.title || '确认';
    document.getElementById('confirmMsg').textContent = opts.message || '确定执行此操作？';
    confirmCb = opts.cb || null;
    const ok = document.getElementById('confirmOk');
    ok.textContent = opts.okText || '确定';
    showSheet('confirmOverlay');
}
function confirmOk() {
    const cb = confirmCb;
    confirmCb = null;
    closeSheet('confirmOverlay');
    if (cb)
        cb();
}
// ---------- 通用输入对话框（替代原生 prompt）----------
let inputCb = null;
function showInputDialog(opts) {
    document.getElementById('inputTitle').textContent = opts.title || '输入';
    document.getElementById('inputLabel').textContent = opts.label || '名称';
    document.getElementById('inputValue').value = opts.value || '';
    inputCb = opts.cb || null;
    showSheet('inputOverlay');
    setTimeout(() => document.getElementById('inputValue').focus(), 50);
}
function inputOk() {
    const v = document.getElementById('inputValue');
    closeSheet('inputOverlay');
    if (inputCb) {
        inputCb(v.value);
        inputCb = null;
    }
}
// ---------- 通用对话框按钮绑定（input/confirm 的打开与关闭由本模块负责）----------
document.getElementById('inputClose').onclick = () => { inputCb = null; closeSheet('inputOverlay'); };
document.getElementById('inputCancel').onclick = () => { inputCb = null; closeSheet('inputOverlay'); };
document.getElementById('inputOk').onclick = inputOk;
document.getElementById('inputValue').addEventListener('keydown', e => { if (e.key === 'Enter')
    inputOk(); });
document.getElementById('confirmClose').onclick = () => { confirmCb = null; closeSheet('confirmOverlay'); };
document.getElementById('confirmCancel').onclick = () => { confirmCb = null; closeSheet('confirmOverlay'); };
document.getElementById('confirmOk').onclick = confirmOk;
// ---------- 通用选择器（批量收藏夹选择等）----------
function openPicker(title, items, onPick) {
    document.getElementById('pickerTitle').textContent = title;
    const list = document.getElementById('pickerList');
    list.innerHTML = '';
    items.forEach(it => {
        const d = document.createElement('div');
        d.className = 'p-item';
        d.textContent = it.label;
        d.onclick = () => { closeSheet('pickerOverlay'); onPick(it.value); };
        list.appendChild(d);
    });
    showSheet('pickerOverlay');
}
// ---------- 通用右键菜单（卡片 / 收藏夹共用）----------
// entries: {icon, text, danger?, action} | 'sep'（分隔线）
// 样式与定位逻辑统一在此维护，避免各调用方重复实现。
function showContextMenu(entries, x, y, width) {
    document.querySelectorAll('.ctx-menu').forEach(mm => mm.remove());
    const m = document.createElement('div');
    m.className = 'more-menu ctx-menu';
    const w = width || 170;
    // 固定定位：clamp 到视口内，避免超出屏幕右侧/底部
    const vw = window.innerWidth, vh = window.innerHeight;
    const mh = entries.length * 34 + 20;
    let px = x, py = y;
    if (px + w > vw - 8)
        px = vw - w - 8;
    if (py + mh > vh - 8)
        py = vh - mh - 8;
    px = Math.max(8, px);
    py = Math.max(8, py);
    m.style.cssText = `position:fixed;left:${px}px;top:${py}px;display:block;z-index:90;background:var(--bg-panel);border:1.5px solid var(--border-soft);border-radius:12px;padding:5px;width:${w}px;box-shadow:0 10px 24px var(--glow-med);`;
    m.innerHTML = entries.map(e => e === 'sep'
        ? '<div class="menu-sep"></div>'
        : `<button type="button" class="item ${e.danger ? 'danger' : ''}"><span class="mi">${e.icon || ''}</span>${esc(e.text || '')}</button>`).join('');
    [...m.children].forEach((d, i) => {
        if (d.classList.contains('menu-sep'))
            return;
        d.onclick = () => {
            m.remove();
            const a = (entries[i] !== 'sep' && entries[i].action) || undefined;
            if (a)
                a();
        };
    });
    document.body.appendChild(m);
    setTimeout(() => document.addEventListener('click', function h() { m.remove(); document.removeEventListener('click', h); }), 0);
    return m;
}

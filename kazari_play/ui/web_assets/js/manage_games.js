"use strict";
// ============================================================
// manage_games.ts — 管理游戏对话框（批量勾选收藏夹内游戏）
// 依赖：state.ts / core.ts（esc/toast）/ ui.ts（showSheet/closeSheet）
// 定义：openManageGames / renderManageGames / updateManageCount / saveManageGames
//       + manageGames* 模块状态与事件绑定
// 被依赖：collections.ts（showCollectionCtx 调用 openManageGames）
// ============================================================
// ---------- 管理游戏对话框（批量勾选收藏夹内游戏）----------
let manageGamesId = null; // 当前管理的收藏夹 id
let manageGamesIsGroup = false; // 是否分组（分组时聚合子分类保存）
let manageGamesSel = new Set(); // 已勾选游戏 id
let manageGamesData = []; // 全部游戏（title/id 缓存）
function openManageGames(node) {
    manageGamesId = node.id;
    manageGamesIsGroup = node.parent_id == null;
    document.getElementById('manageGamesTitle').textContent = '管理游戏：' + node.name;
    document.getElementById('manageGamesKw').value = '';
    showSheet('manageGamesOverlay');
    // 分组：聚合其全部子分类的游戏；分类：仅自身
    const idsToFetch = manageGamesIsGroup
        ? [node.id].concat((node.children || []).map(c => c.id))
        : [node.id];
    const allSel = new Set();
    let pending = idsToFetch.length;
    if (!pending) {
        manageGamesSel = new Set();
        manageGamesData = App.data.games.slice();
        renderManageGames();
        return;
    }
    idsToFetch.forEach(cid => {
        bridge.getGamesInCollection(cid, function (idsStr) {
            let ids = [];
            try {
                ids = JSON.parse(String(idsStr || '[]'));
            }
            catch (e) { }
            ids.forEach(i => allSel.add(i));
            if (--pending === 0) {
                manageGamesSel = allSel;
                manageGamesData = App.data.games.slice();
                renderManageGames();
            }
        });
    });
}
function renderManageGames() {
    const kw = document.getElementById('manageGamesKw').value.trim().toLowerCase();
    const list = manageGamesData.filter(g => !kw || g.title.toLowerCase().includes(kw));
    const t = document.getElementById('manageGamesList');
    t.innerHTML = '';
    if (!list.length) {
        t.innerHTML = '<div class="cand-empty">没有符合条件的游戏</div>';
    }
    list.forEach(g => {
        const checked = manageGamesSel.has(g.id);
        const d = document.createElement('div');
        d.className = 'mg-item' + (checked ? ' on' : '');
        // 行整体作为可聚焦复选框（role=checkbox）；内部 checkbox 仅作视觉展示
        d.setAttribute('role', 'checkbox');
        d.setAttribute('aria-checked', checked ? 'true' : 'false');
        d.setAttribute('aria-label', g.title || '游戏');
        d.tabIndex = 0;
        d.innerHTML = `<input type="checkbox" tabindex="-1" aria-hidden="true" ${checked ? 'checked' : ''}><span class="mg-title">${esc(g.title)}</span>`;
        d.onclick = () => {
            toggleManageGame(d, g.id);
        };
        d.onkeydown = (e) => {
            if (e.key === ' ' || e.key === 'Enter') {
                e.preventDefault();
                toggleManageGame(d, g.id);
            }
        };
        t.appendChild(d);
    });
    updateManageCount();
}
// 勾选/取消勾选一个管理游戏行（行整体点击 + 键盘 Enter/空格 共用）
function toggleManageGame(d, gid) {
    if (manageGamesSel.has(gid))
        manageGamesSel.delete(gid);
    else
        manageGamesSel.add(gid);
    d.setAttribute('aria-checked', manageGamesSel.has(gid) ? 'true' : 'false');
    d.classList.toggle('on', manageGamesSel.has(gid));
    const cb = d.querySelector('input');
    if (cb)
        cb.checked = manageGamesSel.has(gid);
    updateManageCount();
}
function updateManageCount() {
    document.getElementById('manageGamesCount').textContent = `已选 ${manageGamesSel.size} 个`;
}
function saveManageGames() {
    if (manageGamesId == null)
        return;
    const ids = [...manageGamesSel];
    if (manageGamesIsGroup) {
        // 分组：整体替换分组本身 + 每个子分类（保证分组筛选含全部勾选）
        const group = findCollectionNode(manageGamesId);
        const targets = [manageGamesId].concat((group && group.children || []).map(c => c.id));
        targets.forEach(cid => bridge.setCollectionGames(cid, JSON.stringify(ids)));
        toast('收藏夹已更新');
    }
    else {
        bridge.setCollectionGames(manageGamesId, JSON.stringify(ids));
        toast('收藏夹已更新');
    }
    closeSheet('manageGamesOverlay');
}
document.getElementById('manageGamesClose').onclick = () => closeSheet('manageGamesOverlay');
let mgKwTimer = null;
document.getElementById('manageGamesKw').addEventListener('input', () => {
    clearTimeout(mgKwTimer);
    mgKwTimer = setTimeout(renderManageGames, 200); // 防抖：连续输入只过滤一次
});
document.getElementById('manageGamesSelAll').onclick = () => {
    manageGamesData.forEach(g => manageGamesSel.add(g.id));
    renderManageGames();
};
document.getElementById('manageGamesClear').onclick = () => {
    manageGamesSel.clear();
    renderManageGames();
};
document.getElementById('manageGamesSave').onclick = saveManageGames;

// ============================================================
// collections.js — 收藏夹树 / 收藏夹管理 / 管理游戏对话框
// 依赖：state.js / core.js（esc/toast/chipColor）/ ui.js（showSheet/closeSheet/
//       showInputDialog/showConfirmDialog/showContextMenu）
// 定义：renderCollectionTree / renderCollectionGroup / renderCollectionCategory /
//       toggleExpand / bindCollectionItems / findCollectionNode / selectCollection /
//       findParentGroupId / clearCollectionFilter / showCollectionCtx / newCollection /
//       renameCollection / delCollection / openCollectionManager / renderGameCollections /
//       openManageGames / renderManageGames / updateManageCount / saveManageGames
//       + 收藏夹事件绑定
// ============================================================

// ---------- 侧边栏树形收藏夹 ----------
function renderCollectionTree() {
  const cl = document.getElementById('collectionTree');
  cl.innerHTML = '';
  state.collectionTree.forEach(group => cl.appendChild(renderCollectionGroup(group)));
  bindCollectionItems();
}

function renderCollectionGroup(group) {
  const el = document.createElement('div');
  el.className = 'collection-group';
  const open = state.openGroupId === group.id;
  const hasChildren = (group.children || []).length > 0;
  el.innerHTML = `
    <div class="collection-group-header ${state.collectionId === group.id ? 'active' : ''}" data-id="${group.id}">
      ${hasChildren ? `<button class="toggle ${open ? 'open' : ''}" title="${open ? '收起' : '展开'}">${open ? '▾' : '▸'}</button>` : ''}
      <span class="name">${esc(group.name)}</span>
      <span class="count">${group.game_count || 0}</span>
    </div>
    ${hasChildren && open ? `<div class="collection-children">${(group.children || []).map(renderCollectionCategory).join('')}</div>` : ''}`;
  const hdr = el.querySelector('.collection-group-header');
  // 点击分组名 → 直接筛选该分组（含子分类），不展开
  hdr.addEventListener('click', () => selectCollection(group.id, group));
  hdr.addEventListener('contextmenu', (e) => { e.preventDefault(); showCollectionCtx(e.clientX, e.clientY, group); });
  // 小按钮 → 仅展开/收起子分类（手风琴），不筛选
  const tgl = el.querySelector('.toggle');
  if (tgl) tgl.addEventListener('click', (e) => { e.stopPropagation(); toggleExpand(group); });
  return el;
}

// 手风琴：仅切换分组展开/收起（不改变筛选）
function toggleExpand(group) {
  state.openGroupId = state.openGroupId === group.id ? null : group.id;
  renderCollectionTree();
}

function renderCollectionCategory(cat) {
  return `
    <div class="collection-item ${state.collectionId === cat.id ? 'active' : ''}" data-id="${cat.id}">
      <span class="name">${esc(cat.name)}</span>
      <span class="count">${cat.game_count || 0}</span>
    </div>`;
}

function bindCollectionItems() {
  document.querySelectorAll('#collectionTree .collection-item').forEach(it => {
    const cid = +it.dataset.id;
    it.onclick = () => selectCollection(cid, findCollectionNode(cid));
    it.oncontextmenu = (e) => {
      e.preventDefault();
      const node = findCollectionNode(cid);
      if (node) showCollectionCtx(e.clientX, e.clientY, node);
    };
  });
}

function findCollectionNode(id) {
  for (const g of state.collectionTree) {
    if (g.id === id) return g;
    const c = (g.children || []).find(x => x.id === id);
    if (c) return c;
  }
  return null;
}

// 收藏夹选择：分组显示其全部（含子分类），分类仅显示自身
function selectCollection(id, node) {
  const isGroup = node && node.parent_id == null;
  state.collectionId = id;
  state.collectionGroupId = isGroup ? id : (node ? findParentGroupId(id) : null);
  state.nav = 'collection';
  // 选子分类时确保其父分组展开
  if (node && !isGroup) {
    const pg = findParentGroupId(id);
    if (pg) state.openGroupId = pg;
  }
  // 拉取收藏夹内 sort_order 顺序（拖拽排序用）
  state.collectionOrder = [];
  bridge.getGamesInCollection(id, function (idsStr) {
    try { state.collectionOrder = JSON.parse(idsStr || '[]'); } catch (e) { }
    renderAll();
  });
  renderCollectionTree();
  renderAll();
}

function findParentGroupId(id) {
  for (const g of state.collectionTree) {
    if ((g.children || []).some(c => c.id === id)) return g.id;
  }
  return null;
}

// 清除收藏夹筛选，回到「全部作品」
function clearCollectionFilter() {
  state.collectionId = null; state.collectionGroupId = null; state.openGroupId = null;
  state.collectionOrder = []; state.nav = '全部作品'; state.kw = '';
  renderCollectionTree();
  document.querySelectorAll('#sidebar .side-item').forEach(x => {
    x.classList.toggle('active', x.dataset.nav === '全部作品');
  });
  renderAll();
}

// 收藏夹右键菜单（复用通用右键菜单，带图标）
function showCollectionCtx(x, y, node) {
  showContextMenu([
    { icon: '🎮', text: '管理游戏', action: () => openManageGames(node) },
    { icon: '✏️', text: '重命名', action: () => renameCollection(node) },
    { icon: '🗑️', text: '删除', action: () => delCollection(node), danger: true },
  ], x, y, 180);
}

function newCollection(parentId) {
  showInputDialog({
    title: parentId ? '新建分类' : '新建分组',
    label: parentId ? '分类名称' : '分组名称',
    cb: function (name) {
      if (name && name.trim()) { bridge.createCollection(name.trim(), parentId || 0, '', ''); toast('已创建'); }
    }
  });
}

function renameCollection(node) {
  showInputDialog({
    title: '重命名收藏夹', label: '名称', value: node.name,
    cb: function (name) {
      if (name && name.trim() && name.trim() !== node.name) {
        bridge.updateCollection(node.id, JSON.stringify({ name: name.trim() })); toast('已重命名');
      }
    }
  });
}

function delCollection(node) {
  const kids = (node.children || []).length;
  showConfirmDialog({
    title: '删除收藏夹',
    message: `删除「${node.name}」？${kids ? `其 ${kids} 个子分类一并删除，` : ''}关联游戏将不再属于该收藏夹。`,
    danger: true, okText: '删除', cb: () => { bridge.deleteCollection(node.id); toast('已删除'); }
  });
}

// ---------- 收藏夹管理抽屉：当前游戏加入/退出收藏夹 ----------
function openCollectionManager() {
  if (!currentGame) return;
  // 异步拉取最新数据（右键进入时 currentGame 可能是快照），再渲染
  bridge.getGame(currentGame.id, function (s) {
    try {
      const fresh = JSON.parse(s || '{}');
      if (fresh && fresh.id) {
        currentGame = fresh;
        const gi = GAMES.findIndex(x => x.id === fresh.id);
        if (gi >= 0) GAMES[gi] = fresh;
      }
    } catch (e) { }
    renderGameCollections();
  });
  showSheet('collectionOverlay');
}

function renderGameCollections() {
  const sec = document.getElementById('gameCollectionSection');
  if (!currentGame) { sec.style.display = 'none'; return; }
  sec.style.display = 'block';
  document.getElementById('gameCollectionTitle').textContent = '当前游戏：' + currentGame.title;
  const curIds = new Set((currentGame.collections || []).map(c => c.id));
  const t = document.getElementById('gameCollectionList');
  t.innerHTML = '';
  // 全部分组 + 子分类（带完整路径），均可勾选
  const all = [];
  state.collectionTree.forEach(g => {
    all.push({ id: g.id, label: g.name, color: g.color, icon: g.icon });
    (g.children || []).forEach(c => all.push({ id: c.id, label: (g.name + ' / ' + c.name), color: c.color, icon: c.icon }));
  });
  all.forEach(col => {
    const selected = curIds.has(col.id);
    const c = document.createElement('span');
    c.className = 'chip' + (selected ? ' on' : '');
    c.style.color = selected ? '' : '#4a4358';
    c.style.background = selected ? '' : (col.color || chipColor(col.label));
    c.textContent = (col.icon || '') + ' ' + col.label;
    c.onclick = () => {
      const next = new Set(curIds);
      if (next.has(col.id)) next.delete(col.id); else next.add(col.id);
      bridge.setGameCollections(currentGame.id, JSON.stringify([...next]));
      // 本地同步 currentGame.collections，立即反映选中态（后端 refresh 也会回写）
      const had = curIds.has(col.id);
      if (had) { currentGame.collections = currentGame.collections.filter(x => x.id !== col.id); }
      else { currentGame.collections = currentGame.collections.concat([{ id: col.id, name: col.label, color: col.color, icon: col.icon || '' }]); }
      toast(had ? '已移除收藏夹' : '已加入收藏夹');
      renderGameCollections();
    };
    t.appendChild(c);
  });
}

// ---------- 管理游戏对话框（批量勾选收藏夹内游戏）----------
let manageGamesId = null;        // 当前管理的收藏夹 id
let manageGamesIsGroup = false;  // 是否分组（分组时聚合子分类保存）
let manageGamesSel = new Set();  // 已勾选游戏 id
let manageGamesData = [];        // 全部游戏（title/id 缓存）

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
  if (!pending) { manageGamesSel = new Set(); manageGamesData = GAMES.slice(); renderManageGames(); return; }
  idsToFetch.forEach(cid => {
    bridge.getGamesInCollection(cid, function (idsStr) {
      let ids = [];
      try { ids = JSON.parse(idsStr || '[]'); } catch (e) { }
      ids.forEach(i => allSel.add(i));
      if (--pending === 0) {
        manageGamesSel = allSel;
        manageGamesData = GAMES.slice();
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
  if (!list.length) { t.innerHTML = '<div class="cand-empty">没有符合条件的游戏</div>'; }
  list.forEach(g => {
    const checked = manageGamesSel.has(g.id);
    const d = document.createElement('div');
    d.className = 'mg-item' + (checked ? ' on' : '');
    d.innerHTML = `<input type="checkbox" ${checked ? 'checked' : ''}><span class="mg-title">${esc(g.title)}</span>`;
    d.onclick = () => {
      if (manageGamesSel.has(g.id)) manageGamesSel.delete(g.id); else manageGamesSel.add(g.id);
      d.classList.toggle('on', manageGamesSel.has(g.id));
      const cb = d.querySelector('input'); if (cb) cb.checked = manageGamesSel.has(g.id);
      updateManageCount();
    };
    t.appendChild(d);
  });
  updateManageCount();
}

function updateManageCount() {
  document.getElementById('manageGamesCount').textContent = `已选 ${manageGamesSel.size} 个`;
}

function saveManageGames() {
  if (manageGamesId == null) return;
  const ids = [...manageGamesSel];
  if (manageGamesIsGroup) {
    // 分组：整体替换分组本身 + 每个子分类（保证分组筛选含全部勾选）
    const group = findCollectionNode(manageGamesId);
    const targets = [manageGamesId].concat((group && group.children || []).map(c => c.id));
    targets.forEach(cid => bridge.setCollectionGames(cid, JSON.stringify(ids)));
    toast('收藏夹已更新');
  } else {
    bridge.setCollectionGames(manageGamesId, JSON.stringify(ids));
    toast('收藏夹已更新');
  }
  closeSheet('manageGamesOverlay');
}

// ---------- 收藏夹事件绑定 ----------
document.getElementById('btnNewCollection').onclick = () => {
  showInputDialog({
    title: '新建收藏夹',
    label: '名称',
    cb: function (name) { if (name && name.trim()) bridge.createCollection(name.trim(), 0, '', ''); }
  });
};
document.getElementById('collectionClose').onclick = () => closeSheet('collectionOverlay');
document.getElementById('collectionDone').onclick = () => closeSheet('collectionOverlay');
document.getElementById('manageGamesClose').onclick = () => closeSheet('manageGamesOverlay');
document.getElementById('manageGamesKw').addEventListener('input', () => renderManageGames());
document.getElementById('manageGamesSelAll').onclick = () => {
  manageGamesData.forEach(g => manageGamesSel.add(g.id));
  renderManageGames();
};
document.getElementById('manageGamesClear').onclick = () => {
  manageGamesSel.clear();
  renderManageGames();
};
document.getElementById('manageGamesSave').onclick = saveManageGames;

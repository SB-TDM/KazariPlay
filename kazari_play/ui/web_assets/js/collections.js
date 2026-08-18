// ============================================================
// collections.js — 收藏夹树 / 收藏夹管理抽屉（当前游戏加入/退出收藏夹）
// 依赖：state.js / core.js（esc/toast/chipColor）/ ui.js（showSheet/closeSheet/
//       showInputDialog/showConfirmDialog/showContextMenu）
// 定义：renderCollectionTree / renderCollectionGroup / renderCollectionCategory /
//       toggleExpand / bindCollectionItems / findCollectionNode / selectCollection /
//       findParentGroupId / clearCollectionFilter / showCollectionCtx / newCollection /
//       renameCollection / delCollection / openCollectionManager / renderGameCollections
//       + 收藏夹事件绑定
// 被依赖：games.js（refreshAll 调用 renderCollectionTree）、cards.js（openCardMenu）、
//         detail.js（renderDetailTags 调用 openCollectionManager）、manage_games.js（openManageGames）
// ============================================================

// ---------- 侧边栏树形收藏夹 ----------
function renderCollectionTree() {
  const cl = document.getElementById('collectionTree');
  cl.innerHTML = '';
  App.ui.state.collectionTree.forEach(group => cl.appendChild(renderCollectionGroup(group)));
  bindCollectionItems();
}

function renderCollectionGroup(group) {
  const el = document.createElement('div');
  el.className = 'collection-group';
  const open = App.ui.state.openGroupId === group.id;
  const hasChildren = (group.children || []).length > 0;
  el.innerHTML = `
    <div class="collection-group-header ${App.ui.state.collectionId === group.id ? 'active' : ''}" data-id="${group.id}">
      ${hasChildren ? `<button class="toggle ${open ? 'open' : ''}" title="${open ? '收起' : '展开'}">${open ? '▾' : '▸'}</button>` : ''}
      <span class="name">${esc(group.name)}</span>
      <span class="count">${group.game_count || 0}</span>
    </div>
    ${hasChildren && open ? `<div class="collection-children">${(group.children || []).map(renderCollectionCategory).join('')}</div>` : ''}`;
  const hdr = el.querySelector('.collection-group-header');
  // 点击分组名 → 直接筛选该分组（含子分类），不展开
  hdr.setAttribute('role', 'button');
  hdr.tabIndex = 0;
  hdr.addEventListener('click', () => selectCollection(group.id, group));
  hdr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); hdr.click(); } });
  hdr.addEventListener('contextmenu', (e) => { e.preventDefault(); showCollectionCtx(e.clientX, e.clientY, group); });
  // 小按钮 → 仅展开/收起子分类（手风琴），不筛选
  const tgl = el.querySelector('.toggle');
  if (tgl) tgl.addEventListener('click', (e) => { e.stopPropagation(); toggleExpand(group); });
  return el;
}

// 手风琴：仅切换分组展开/收起（不改变筛选）
function toggleExpand(group) {
  App.ui.state.openGroupId = App.ui.state.openGroupId === group.id ? null : group.id;
  renderCollectionTree();
}

function renderCollectionCategory(cat) {
  return `
    <div class="collection-item ${App.ui.state.collectionId === cat.id ? 'active' : ''}" data-id="${cat.id}">
      <span class="name">${esc(cat.name)}</span>
      <span class="count">${cat.game_count || 0}</span>
    </div>`;
}

function bindCollectionItems() {
  document.querySelectorAll('#collectionTree .collection-item').forEach(it => {
    const cid = +it.dataset.id;
    // 键盘可达：分类项作为可聚焦按钮（Enter/空格 触发）
    it.setAttribute('role', 'button');
    it.tabIndex = 0;
    it.onclick = () => selectCollection(cid, findCollectionNode(cid));
    it.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); it.onclick(); } };
    it.oncontextmenu = (e) => {
      e.preventDefault();
      const node = findCollectionNode(cid);
      if (node) showCollectionCtx(e.clientX, e.clientY, node);
    };
  });
}

function findCollectionNode(id) {
  for (const g of App.ui.state.collectionTree) {
    if (g.id === id) return g;
    const c = (g.children || []).find(x => x.id === id);
    if (c) return c;
  }
  return null;
}

// 收藏夹选择：分组显示其全部（含子分类），分类仅显示自身
function selectCollection(id, node) {
  const isGroup = node && node.parent_id == null;
  App.ui.state.collectionId = id;
  App.ui.state.collectionGroupId = isGroup ? id : (node ? findParentGroupId(id) : null);
  App.ui.state.nav = 'collection';
  // 高亮互斥：清除「全部作品 / 继续游玩 / 我的收藏」等侧边栏项高亮，
  // 只保留当前收藏夹项呈现粉色胶囊效果（与 clearCollectionFilter 对称）
  document.querySelectorAll('#sidebar .side-item').forEach(x => x.classList.remove('active'));
  // 选子分类时确保其父分组展开
  if (node && !isGroup) {
    const pg = findParentGroupId(id);
    if (pg) App.ui.state.openGroupId = pg;
  }
  renderAll();
  renderCollectionTree();
}

function findParentGroupId(id) {
  for (const g of App.ui.state.collectionTree) {
    if ((g.children || []).some(c => c.id === id)) return g.id;
  }
  return null;
}

// 清除收藏夹筛选，回到「全部作品」
function clearCollectionFilter() {
  App.ui.state.collectionId = null; App.ui.state.collectionGroupId = null; App.ui.state.openGroupId = null;
  App.ui.state.nav = '全部作品'; App.ui.state.kw = '';
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
  if (!App.data.currentGame) return;
  // 异步拉取最新数据（右键进入时 currentGame 可能是快照），再渲染
  bridge.getGame(App.data.currentGame.id, function (s) {
    try {
      const fresh = JSON.parse(s || '{}');
      if (fresh && fresh.id) {
        App.data.currentGame = fresh;
        const gi = App.data.games.findIndex(x => x.id === fresh.id);
        if (gi >= 0) App.data.games[gi] = fresh;
      }
    } catch (e) { }
    renderGameCollections();
  });
  showSheet('collectionOverlay');
}

function renderGameCollections() {
  const sec = document.getElementById('gameCollectionSection');
  if (!App.data.currentGame) { sec.style.display = 'none'; return; }
  sec.style.display = 'block';
  document.getElementById('gameCollectionTitle').textContent = '当前游戏：' + App.data.currentGame.title;
  const curIds = new Set((App.data.currentGame.collections || []).map(c => c.id));
  const t = document.getElementById('gameCollectionList');
  t.innerHTML = '';
  // 全部分组 + 子分类（带完整路径），均可勾选
  const all = [];
  App.ui.state.collectionTree.forEach(g => {
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
      bridge.setGameCollections(App.data.currentGame.id, JSON.stringify([...next]));
      // 本地同步 currentGame.collections，立即反映选中态（后端 refresh 也会回写）
      const had = curIds.has(col.id);
      if (had) { App.data.currentGame.collections = App.data.currentGame.collections.filter(x => x.id !== col.id); }
      else { App.data.currentGame.collections = App.data.currentGame.collections.concat([{ id: col.id, name: col.label, color: col.color, icon: col.icon || '' }]); }
      toast(had ? '已移除收藏夹' : '已加入收藏夹');
      renderGameCollections();
    };
    t.appendChild(c);
  });
}

document.getElementById('btnNewCollection').onclick = () => {
  showInputDialog({
    title: '新建收藏夹',
    label: '名称',
    cb: function (name) { if (name && name.trim()) bridge.createCollection(name.trim(), 0, '', ''); }
  });
};
document.getElementById('collectionClose').onclick = () => closeSheet('collectionOverlay');
document.getElementById('collectionDone').onclick = () => closeSheet('collectionOverlay');

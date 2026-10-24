// ============================================================
// collections.ts — 收藏夹树 / 收藏夹管理抽屉（当前游戏加入/退出收藏夹）
// 依赖：state.ts / icons.ts / core.ts（esc/toast/chipColor）/ ui.ts（showSheet/closeSheet/
//       showInputDialog/showConfirmDialog/showContextMenu）
// 定义：renderCollectionTree / renderCollectionGroup / renderCollectionCategory /
//       toggleExpand / bindCollectionItems / findCollectionNode / selectCollection /
//       findParentGroupId / clearCollectionFilter / showCollectionCtx /
//       renameCollection / delCollection / openCollectionManager / renderGameCollections
//       + 收藏夹事件绑定
// 被依赖：games.ts（refreshAll 调用 renderCollectionTree）、cards.ts（openCardMenu）、
//         detail.ts（renderDetailTags 调用 openCollectionManager）、manage_games.ts（openManageGames）
// ============================================================

// ---------- 侧边栏树形收藏夹 ----------
let _collectionTreeSig = '';

function renderCollectionTree(): void {
  const cl = document.getElementById('collectionTree')!;
  const allActive = App.ui.state.collectionId === null
    && App.ui.state.nav === '全部作品';
  const sig = JSON.stringify({
    active: App.ui.state.collectionId,
    allActive: allActive,
    total: (App.data.games || []).length,
    open: App.ui.state.openGroupId,
    tree: App.ui.state.collectionTree.map(g => ({
      id: g.id, name: g.name, count: g.game_count || 0,
      color: g.color || '', icon: g.icon || '',
      children: (g.children || []).map(c => ({
        id: c.id, name: c.name, count: c.game_count || 0,
        color: c.color || '', icon: c.icon || '',
      })),
    })),
  });
  if (sig === _collectionTreeSig) return;
  _collectionTreeSig = sig;
  cl.innerHTML = '';
  const all = document.createElement('div');
  all.className = 'collection-item collection-all' + (allActive ? ' active' : '');
  all.setAttribute('role', 'button');
  all.tabIndex = 0;
  all.innerHTML = `<span class="toggle-spacer" aria-hidden="true"></span>
    <span class="collection-mark collection-mark-all">${ICON.collection}</span>
    <span class="name">全部作品</span>
    <span class="count">${(App.data.games || []).length}</span>`;
  all.onclick = showAllWorks;
  all.onkeydown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      showAllWorks();
    }
  };
  cl.appendChild(all);
  App.ui.state.collectionTree.forEach(group => cl.appendChild(renderCollectionGroup(group)));
  bindCollectionItems();
}

function collectionMark(node: CollectionTreeNode, small: boolean = false): string {
  const color = node.color || chipColor(node.name);
  const icon = node.icon ? esc(node.icon) : '';
  return `<span class="collection-mark${small ? ' small' : ''}" style="background:${esc(color)}">${icon}</span>`;
}

function renderCollectionGroup(group: CollectionTreeNode): HTMLElement {
  const el = document.createElement('div');
  el.className = 'collection-group';
  const open = App.ui.state.openGroupId === group.id;
  const hasChildren = (group.children || []).length > 0;
  el.innerHTML = `
    <div class="collection-group-header ${App.ui.state.collectionId === group.id ? 'active' : ''}" data-id="${group.id}">
      ${hasChildren ? `<button class="toggle ${open ? 'open' : ''}" title="${open ? '收起' : '展开'}">${open ? ICON.chevronDown : ICON.chevronRight}</button>` : '<span class="toggle-spacer" aria-hidden="true"></span>'}
      ${collectionMark(group)}
      <span class="name">${esc(group.name)}</span>
      <span class="count">${group.game_count || 0}</span>
    </div>
    ${hasChildren && open ? `<div class="collection-children">${(group.children || []).map(renderCollectionCategory).join('')}</div>` : ''}`;
  const hdr = el.querySelector('.collection-group-header') as HTMLElement;
  // 点击分组名 → 直接筛选该分组（含子分类），不展开
  hdr.setAttribute('role', 'button');
  hdr.tabIndex = 0;
  hdr.onclick = () => selectCollection(group.id, group);
    hdr.onkeydown = (e: KeyboardEvent) => {
      if (e.target !== hdr) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectCollection(group.id, group); }
    };
  hdr.addEventListener('contextmenu', (e: MouseEvent) => { e.preventDefault(); showCollectionCtx(e.clientX, e.clientY, group); });
  // 小按钮：仅展开/收起子分类（手风琴），不筛选
  const tgl = el.querySelector('.toggle') as HTMLElement | null;
  if (tgl) {
    tgl.setAttribute('aria-expanded', open ? 'true' : 'false');
    tgl.addEventListener('click', (e: MouseEvent) => { e.stopPropagation(); toggleExpand(group); });
  }
  return el;
}

// 手风琴：仅切换分组展开/收起（不改变筛选）
function toggleExpand(group: CollectionTreeNode): void {
  App.ui.state.openGroupId = App.ui.state.openGroupId === group.id ? null : group.id;
  renderCollectionTree();
}

function renderCollectionCategory(cat: CollectionTreeNode): string {
  return `
    <div class="collection-item ${App.ui.state.collectionId === cat.id ? 'active' : ''}" data-id="${cat.id}">
      ${collectionMark(cat, true)}
      <span class="name">${esc(cat.name)}</span>
      <span class="count">${cat.game_count || 0}</span>
    </div>`;
}

function bindCollectionItems(): void {
  document.querySelectorAll<HTMLElement>('#collectionTree .collection-item[data-id]').forEach(it => {
    const cid = +it.dataset.id!;
    // 键盘可达：分类项作为可聚焦按钮（Enter/空格 触发）
    it.setAttribute('role', 'button');
    it.tabIndex = 0;
    it.onclick = () => selectCollection(cid, findCollectionNode(cid));
    it.onkeydown = (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectCollection(cid, findCollectionNode(cid)); }
    };
    it.oncontextmenu = (e: MouseEvent) => {
      e.preventDefault();
      const node = findCollectionNode(cid);
      if (node) showCollectionCtx(e.clientX, e.clientY, node);
    };
  });
}

function findCollectionNode(id: number): CollectionTreeNode | null {
  for (const g of App.ui.state.collectionTree) {
    if (g.id === id) return g;
    const c = (g.children || []).find(x => x.id === id);
    if (c) return c;
  }
  return null;
}

interface FlatCollectionNode {
  node: CollectionTreeNode;
  label: string;
}

function flattenCollectionTree(): FlatCollectionNode[] {
  const items: FlatCollectionNode[] = [];
  App.ui.state.collectionTree.forEach(g => {
    items.push({ node: g, label: g.name });
    (g.children || []).forEach(c => items.push({ node: c, label: g.name + ' / ' + c.name }));
  });
  return items;
}

// 收藏夹选择：分组显示其全部（含子分类），分类仅显示自身
function selectCollection(id: number, node: CollectionTreeNode | null): void {
  const isGroup = node && node.parent_id == null;
  App.ui.state.collectionId = id;
  App.ui.state.collectionGroupId = isGroup ? id : (node ? findParentGroupId(id) : null);
  App.ui.state.nav = '全部作品';
  // 收藏夹选项是「全部作品」的子视图，侧边栏保持「全部作品」选中
  setActiveSideNav('全部作品');
  // 选子分类时确保其父分组展开
  if (node && !isGroup) {
    const pg = findParentGroupId(id);
    if (pg) App.ui.state.openGroupId = pg;
  }
  renderAll(true);
  renderCollectionTree();
}

// 收藏夹侧边栏的「全部作品」：清除收藏夹筛选，保留当前搜索词
function showAllWorks(): void {
  App.ui.state.collectionId = null;
  App.ui.state.collectionGroupId = null;
  App.ui.state.openGroupId = null;
  App.ui.state.nav = '全部作品';
  setActiveSideNav('全部作品');
  renderAll(true);
  renderCollectionTree();
}

function findParentGroupId(id: number): number | null {
  for (const g of App.ui.state.collectionTree) {
    if ((g.children || []).some(c => c.id === id)) return g.id;
  }
  return null;
}

// 清除收藏夹筛选，回到「全部作品」
function clearCollectionFilter(): void {
  App.ui.state.collectionId = null; App.ui.state.collectionGroupId = null; App.ui.state.openGroupId = null;
  App.ui.state.nav = '全部作品';
  resetSearchInput();
  renderCollectionTree();
  setActiveSideNav('全部作品');
  renderAll(true);
}

// 收藏夹右键菜单（复用通用右键菜单，带图标）
function showCollectionCtx(x: number, y: number, node: CollectionTreeNode): void {
  showContextMenu([
    { icon: ICON.controller, text: '管理游戏', action: () => openManageGames(node) },
    { icon: ICON.edit, text: '重命名', action: () => renameCollection(node) },
    { icon: ICON.trash, text: '删除', action: () => delCollection(node), danger: true },
  ], x, y, 180);
}

function renameCollection(node: CollectionTreeNode): void {
  showInputDialog({
    title: '重命名收藏夹', label: '名称', value: node.name,
    cb: function (name) {
      if (name && name.trim() && name.trim() !== node.name) {
        bridge.updateCollection(node.id, JSON.stringify({ name: name.trim() }), function (s: unknown, failed?: boolean) {
          const r = bridgeResult(s);
          if (failed || !r.ok) { toast(r.msg || '重命名失败'); return; }
          toast('已重命名');
        });
      }
    }
  });
}

function delCollection(node: CollectionTreeNode): void {
  const kids = (node.children || []).length;
  showConfirmDialog({
    title: '删除收藏夹',
    message: `删除「${node.name}」？${kids ? `其 ${kids} 个子分类一并删除，` : ''}关联游戏将不再属于该收藏夹。`,
    danger: true, okText: '删除', cb: () => {
      const removedIds = [node.id].concat((node.children || []).map(c => c.id));
      bridge.deleteCollection(node.id, function (s: unknown, failed?: boolean) {
        const r = bridgeResult(s);
        if (failed || !r.ok) { toast(r.msg || '删除收藏夹失败'); return; }
        toast('已删除');
        if (App.ui.state.collectionId !== null && removedIds.includes(App.ui.state.collectionId)) {
          clearCollectionFilter();
        }
      });
    }
  });
}

// ---------- 收藏夹管理抽屉：当前游戏加入/退出收藏夹 ----------
// 请求代际：连续对不同游戏打开时，丢弃迟到响应（参考 screenshots.ts 的 request+gid）
let collectionMgrRequest = 0;

function openCollectionManager(): void {
  if (!App.data.currentGame) return;
  const gid = String(App.data.currentGame.id);
  const request = ++collectionMgrRequest;
  // 异步拉取最新数据（右键进入时 currentGame 可能是快照），再渲染
  bridge.getGame(gid, function (s: unknown) {
    if (request !== collectionMgrRequest || String(App.data.currentGame?.id) !== gid) return;
    try {
      const fresh = JSON.parse(String(s || '{}')) as Game;
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

const COLLECTION_COLORS = [
  '#ff8fab', '#ff6f91', '#c4b5fd', '#9ad3ff',
  '#7fd8be', '#ffd97d', '#ffc9a0', '#d8a7ff',
];

let colorPopover: HTMLElement | null = null;
let colorPopoverCleanup: (() => void) | null = null;

function closeCollectionColorPicker(): void {
  if (colorPopover) {
    colorPopover.remove();
    colorPopover = null;
  }
  if (colorPopoverCleanup) {
    colorPopoverCleanup();
    colorPopoverCleanup = null;
  }
}

function positionColorPopover(anchor: HTMLElement): void {
  if (!colorPopover) return;
  const rect = anchor.getBoundingClientRect();
  const popRect = colorPopover.getBoundingClientRect();
  const margin = 10;
  let left = Math.min(rect.left, window.innerWidth - popRect.width - margin);
  let top = rect.bottom + 8;
  left = Math.max(margin, left);
  if (top + popRect.height > window.innerHeight - margin) {
    top = rect.top - popRect.height - 8;
  }
  top = Math.max(margin, top);
  colorPopover.style.left = left + 'px';
  colorPopover.style.top = top + 'px';
  colorPopover.classList.add('show');
}

function applyCollectionColor(collectionId: number, color: string): void {
  const node = findCollectionNode(collectionId);
  const game = App.data.currentGame;
  const previous = node?.color || (game?.collections || []).find((item) => item.id === collectionId)?.color || '';

  const setColor = (next: string): void => {
    if (node) node.color = next;
    if (game) {
      game.collections = game.collections.map((item) =>
        item.id === collectionId ? { ...item, color: next } : item);
    }
    renderCollectionTree();
    renderGameCollections();
    if (document.getElementById('detailOverlay')?.classList.contains('show')) renderDetailTags();
  };

  setColor(color);
  bridge.updateCollection(collectionId, JSON.stringify({ color }), function (s: unknown, failed?: boolean) {
    const r = bridgeResult(s);
    if (failed || !r.ok) {
      setColor(previous);
      toast(r.msg || '颜色更新失败');
      return;
    }
    toast(color ? '已更新颜色' : '已恢复自动颜色');
  });
}

function openCollectionColorPicker(anchor: HTMLElement, collectionId: number): void {
  closeCollectionColorPicker();
  const node = findCollectionNode(collectionId);
  const pop = document.createElement('div');
  pop.className = 'collection-color-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', '选择收藏夹颜色');

  const title = document.createElement('div');
  title.className = 'color-popover-title';
  title.textContent = '收藏夹颜色';

  const palette = document.createElement('div');
  palette.className = 'color-palette';
  COLLECTION_COLORS.forEach((color) => {
    const swatch = document.createElement('button');
    swatch.type = 'button';
    swatch.className = 'color-swatch' + ((node?.color || '').toLowerCase() === color ? ' on' : '');
    swatch.style.background = color;
    swatch.setAttribute('aria-label', '颜色 ' + color);
    swatch.setAttribute('aria-pressed', (node?.color || '').toLowerCase() === color ? 'true' : 'false');
    swatch.addEventListener('click', function (e) {
      e.stopPropagation();
      closeCollectionColorPicker();
      applyCollectionColor(collectionId, color);
    });
    palette.appendChild(swatch);
  });

  const auto = document.createElement('button');
  auto.type = 'button';
  auto.className = 'color-auto' + (!node?.color ? ' on' : '');
  auto.textContent = '自动颜色';
  auto.setAttribute('aria-pressed', !node?.color ? 'true' : 'false');
  auto.addEventListener('click', function (e) {
    e.stopPropagation();
    closeCollectionColorPicker();
    applyCollectionColor(collectionId, '');
  });

  pop.append(title, palette, auto);
  pop.addEventListener('click', (e) => e.stopPropagation());
  document.body.appendChild(pop);
  colorPopover = pop;
  positionColorPopover(anchor);

  const onDocClick = (e: MouseEvent): void => {
    if (colorPopover && !colorPopover.contains(e.target as Node)) closeCollectionColorPicker();
  };
  const onKey = (e: KeyboardEvent): void => {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    closeCollectionColorPicker();
  };
  document.addEventListener('click', onDocClick);
  document.addEventListener('keydown', onKey, true);
  colorPopoverCleanup = (): void => {
    document.removeEventListener('click', onDocClick);
    document.removeEventListener('keydown', onKey, true);
  };
}

function renderGameCollections(): void {
  closeCollectionColorPicker();
  const sec = document.getElementById('gameCollectionSection')!;
  if (!App.data.currentGame) { sec.style.display = 'none'; return; }
  sec.style.display = 'block';
  document.getElementById('gameCollectionTitle')!.textContent = '当前游戏：' + App.data.currentGame.title;
  const curIds = new Set((App.data.currentGame.collections || []).map(c => c.id));
  const t = document.getElementById('gameCollectionList')!;
  t.innerHTML = '';
  const all = flattenCollectionTree().map(it => ({
    id: it.node.id, label: it.label, color: it.node.color, icon: it.node.icon,
  }));
  if (all.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'collection-option-empty';
    empty.textContent = '还没有收藏夹';
    t.appendChild(empty);
    return;
  }
  all.forEach(col => {
    const selected = curIds.has(col.id);
    const row = document.createElement('div');
    row.className = 'collection-option' + (selected ? ' on' : '');
    row.tabIndex = 0;
    row.setAttribute('role', 'checkbox');
    row.setAttribute('aria-checked', selected ? 'true' : 'false');
    row.setAttribute('aria-label', col.label + (selected ? '，已加入' : '，未加入'));
    const mark = document.createElement('button');
    mark.type = 'button';
    mark.className = 'collection-option-mark';
    mark.style.background = col.color || chipColor(col.label);
    mark.textContent = col.icon || '';
    mark.setAttribute('aria-label', '修改「' + col.label + '」的颜色');
    mark.setAttribute('aria-haspopup', 'dialog');
    mark.addEventListener('click', (e) => {
      e.stopPropagation();
      openCollectionColorPicker(mark, col.id);
    });
    const name = document.createElement('span');
    name.className = 'collection-option-name';
    name.textContent = col.label;
    const check = document.createElement('span');
    check.className = 'collection-option-check';
    check.setAttribute('aria-hidden', 'true');
    check.textContent = selected ? '✓' : '';
    row.append(mark, name, check);
    const toggle = (): void => {
      const g = App.data.currentGame!;
      const gid = String(g.id);
      const prev = g.collections || [];
      const had = prev.some(x => x.id === col.id);
      // 乐观更新，失败时回滚
      g.collections = had
        ? prev.filter(x => x.id !== col.id)
        : prev.concat([{ id: col.id, name: col.label, color: col.color || '', icon: col.icon || '' }]);
      renderGameCollections();
      bridge.setGameCollections(gid, JSON.stringify(g.collections.map(x => x.id)), function (s: unknown, failed?: boolean) {
        const r = bridgeResult(s);
        if (!failed && r.ok) { toast(had ? '已移除收藏夹' : '已加入收藏夹'); return; }
        g.collections = prev;
        if (String(App.data.currentGame?.id) === gid) renderGameCollections();
        toast(r.msg || (had ? '移出收藏夹失败' : '加入收藏夹失败'));
      });
    };
    row.onclick = toggle;
    row.addEventListener('keydown', (e) => {
      if (e.target !== row || (e.key !== 'Enter' && e.key !== ' ')) return;
      e.preventDefault();
      toggle();
    });
    t.appendChild(row);
  });
}

document.getElementById('btnNewCollection')!.onclick = () => {
  showInputDialog({
    title: '新建收藏夹',
    label: '名称',
    cb: function (name) { if (name && name.trim()) bridge.createCollection(name.trim(), 0, '', ''); }
  });
};
document.getElementById('collectionClose')!.onclick = () => {
  closeCollectionColorPicker();
  closeSheet('collectionOverlay');
};
document.getElementById('collectionDone')!.onclick = () => {
  closeCollectionColorPicker();
  closeSheet('collectionOverlay');
};
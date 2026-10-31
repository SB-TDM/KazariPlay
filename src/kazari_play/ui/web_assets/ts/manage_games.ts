// ============================================================
// manage_games.ts — 管理游戏对话框（批量勾选收藏夹内游戏）
// 依赖：state.ts / core.ts（esc/toast）/ ui.ts（showSheet/closeSheet）
// 定义：openManageGames / renderManageGames / updateManageCount / saveManageGames
//       + manageGames* 模块状态与事件绑定
// 被依赖：collections.ts（showCollectionCtx 调用 openManageGames）
// ============================================================

// ---------- 管理游戏对话框（批量勾选收藏夹内游戏）----------
let manageGamesId: number | null = null;        // 当前管理的收藏夹 id
let manageGamesIsGroup = false;  // 是否分组（分组时聚合子分类保存）
let manageGamesSel = new Set<string>();  // 已勾选游戏 id
let manageGamesData: Game[] = [];        // 全部游戏（title/id 缓存）
let manageGamesRequest = 0;
let manageGamesLoading = false;

function setManageGamesLoading(loading: boolean): void {
  manageGamesLoading = loading;
  ['manageGamesSave', 'manageGamesSelAll', 'manageGamesClear'].forEach(id => {
    const el = document.getElementById(id) as HTMLButtonElement | null;
    if (el) el.disabled = loading;
  });
}

function openManageGames(node: CollectionTreeNode): void {
  const request = ++manageGamesRequest;
  manageGamesId = node.id;
  manageGamesIsGroup = node.parent_id == null;
  manageGamesSel = new Set<string>();
  manageGamesData = App.data.games.slice();
  document.getElementById('manageGamesTitle')!.textContent = '管理游戏 · ' + node.name;
  (document.getElementById('manageGamesKw') as HTMLInputElement).value = '';
  setManageGamesLoading(true);
  renderManageGames();
  showSheet('manageGamesOverlay');
  // 分组：聚合其全部子分类的游戏；分类：仅自身
  const idsToFetch = manageGamesIsGroup
    ? [node.id].concat((node.children || []).map(c => c.id))
    : [node.id];
  const allSel = new Set<string>();
  let pending = idsToFetch.length;
  const finish = (): void => {
    if (request !== manageGamesRequest) return;
    manageGamesSel = allSel;
    setManageGamesLoading(false);
    renderManageGames();
  };
  if (!pending) { finish(); return; }
  idsToFetch.forEach(cid => {
    bridge.getGamesInCollection(cid, function (idsStr: unknown, failed?: boolean) {
      if (request !== manageGamesRequest) return;
      if (failed) {
        toast('读取收藏夹失败，请重试');
        manageGamesRequest++;
        setManageGamesLoading(false);
        closeSheet('manageGamesOverlay', true);
        return;
      }
      let ids: string[] = [];
      try { ids = JSON.parse(String(idsStr || '[]')) as string[]; } catch (e) { }
      ids.forEach(i => allSel.add(i));
      if (--pending === 0) finish();
    });
  });
}

function filteredManageGames(): Game[] {
  const kw = (document.getElementById('manageGamesKw') as HTMLInputElement).value.trim().toLowerCase();
  return manageGamesData.filter(g => !kw || g.title.toLowerCase().includes(kw));
}

function renderManageGames(): void {
  const list = filteredManageGames();
  const t = document.getElementById('manageGamesList')!;
  t.innerHTML = '';
  if (!list.length) { t.innerHTML = '<div class="cand-empty">没有符合条件的游戏</div>'; }
  list.forEach(g => {
    const checked = manageGamesSel.has(g.id);
    const d = document.createElement('div');
    d.className = 'mg-item' + (checked ? ' on' : '');
    // 行整体作为可聚焦复选框（role=checkbox）；内部 checkbox 仅作视觉展示
    d.setAttribute('role', 'checkbox');
    d.setAttribute('aria-checked', checked ? 'true' : 'false');
    d.setAttribute('aria-label', g.title || '游戏');
    d.tabIndex = 0;
    d.innerHTML = `<input type="checkbox" class="ui-check" tabindex="-1" aria-hidden="true" ${checked ? 'checked' : ''}><span class="mg-title">${esc(g.title)}</span>`;
    d.onclick = () => {
      toggleManageGame(d, g.id);
    };
    d.onkeydown = (e: KeyboardEvent) => {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggleManageGame(d, g.id); }
    };
    t.appendChild(d);
  });
  updateManageCount();
}

// 勾选/取消勾选一个管理游戏行（行整体点击 + 键盘 Enter/空格 共用）
function toggleManageGame(d: HTMLElement, gid: string): void {
  if (manageGamesSel.has(gid)) manageGamesSel.delete(gid); else manageGamesSel.add(gid);
  d.setAttribute('aria-checked', manageGamesSel.has(gid) ? 'true' : 'false');
  d.classList.toggle('on', manageGamesSel.has(gid));
  const cb = d.querySelector('input') as HTMLInputElement | null; if (cb) cb.checked = manageGamesSel.has(gid);
  updateManageCount();
}

function updateManageCount(): void {
  document.getElementById('manageGamesCount')!.textContent = `已选 ${manageGamesSel.size} 个`;
}

function saveManageGames(): void {
  if (manageGamesId == null || manageGamesLoading) return;
  const ids = [...manageGamesSel];
  // 分组：整体替换分组本身 + 每个子分类（保证分组筛选含全部勾选）
  const targets = [manageGamesId];
  if (manageGamesIsGroup) {
    const group = findCollectionNode(manageGamesId);
    targets.push(...((group && group.children) || []).map(c => c.id));
  }
  let pending = targets.length;
  let failedAny = false;
  targets.forEach(cid => bridge.setCollectionGames(cid, JSON.stringify(ids), function (ok: unknown, failed?: boolean) {
    if (failed || ok !== true) failedAny = true;
    if (--pending > 0) return;
    if (failedAny) { toast('收藏夹更新失败'); return; }
    toast('收藏夹已更新');
    closeSheet('manageGamesOverlay');
  }));
}

document.getElementById('manageGamesClose')!.onclick = () => {
  manageGamesRequest++;
  setManageGamesLoading(false);
  closeSheet('manageGamesOverlay');
};
let mgKwTimer: ReturnType<typeof setTimeout> | null = null;
document.getElementById('manageGamesKw')!.addEventListener('input', () => {
  clearTimeout(mgKwTimer as ReturnType<typeof setTimeout>);
  mgKwTimer = setTimeout(renderManageGames, 200);   // 防抖：连续输入只过滤一次
});
document.getElementById('manageGamesSelAll')!.onclick = () => {
  filteredManageGames().forEach(g => manageGamesSel.add(g.id));
  renderManageGames();
};
document.getElementById('manageGamesClear')!.onclick = () => {
  manageGamesSel.clear();
  renderManageGames();
};
document.getElementById('manageGamesSave')!.onclick = saveManageGames;

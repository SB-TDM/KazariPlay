// ============================================================
// games.ts — 游戏数据 / 筛选 / 整体渲染调度 + 卡片状态
// 依赖：state.ts / core.ts（esc/stars/toast）/ cards.ts（renderCards/renderEmpty）/
//       collections.ts（renderCollectionTree）/ batch.ts（updateBatchBar）/
//       detail.ts（refreshDetail/setActiveCard）
// 定义：refreshAll / _gamesChanged / syncCurrentGame / reloadCovers / applyCoverSize /
//       renderAll / filterGames / markRunning / toggleSelect / setActiveCard / renderEmpty
// 被依赖：app.ts（init/refreshAll）、state.ts 的 __app（refresh/reloadCovers）
// ============================================================

// ---------- 封面 ----------
// 强制重载所有可见卡片封面（VNDB 匹配 / 手动更换后由后端主动触发）
function reloadCovers(): void {
  document.querySelectorAll<HTMLElement>('.card').forEach(card => {
    const c = card.querySelector('.cover');
    if (!c) return;
    card.dataset.coverLoaded = '';
    c.classList.remove('loaded');   // 重新加载时先去掉淡入标记，实图到达后再淡入
    bridge.getCover(card.dataset.id!, function (uri: unknown) {
      if (!uri) return;
      card.dataset.coverLoaded = '1';
      c.classList.add('loaded');
      (c as HTMLElement).style.backgroundImage = `url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
    });
  });
}

// 封面尺寸档位（对应设置 cover_size）
const COVER_SIZES: Record<string, { w: number; h: number }> = {
  small: { w: 132, h: 180 }, medium: { w: 154, h: 210 }, large: { w: 180, h: 245 },
};
function applyCoverSize(size: string): void {
  const s = COVER_SIZES[size] || COVER_SIZES.medium;
  document.documentElement.style.setProperty('--card-w', s.w + 'px');
  document.documentElement.style.setProperty('--card-h', s.h + 'px');
}

// ---------- 数据刷新 ----------
function refreshAll(force: boolean): void {
  if (!bridge) return;
  bridge.getGames(function (s: unknown) {
    const fresh = JSON.parse(String(s)) as Game[];
    // 数据无变化时不重建网格，避免卡片闪烁（事件推送 / 轮询兜底）
    if (force || _gamesChanged(App.data.games, fresh)) {
      App.data.games = fresh; renderAll(); syncCurrentGame();
    } else {
      // 仅刷新运行状态等轻量字段
      App.data.games = fresh; syncCurrentGame(); markRunning();
    }
  });
  bridge.getCollectionsTree(function (s: unknown) {
    App.ui.state.collectionTree = JSON.parse(String(s || '[]')) as CollectionTreeNode[];
    renderCollectionTree();
  });
  bridge.getRunning(function (r: unknown) { App.data.runningId = (r as number | string) || ''; markRunning(); });
}

// 判断游戏列表是否有实质变化（比较影响卡片显示的字段）。
// 注意：last_text / play_time_text 是派生展示文本，已分别由 last_played / play_time
// 覆盖；相对时间（"3 分钟前"→"刚刚"）每分钟必变，纳入比较会误触发全量重渲染
// （进而重绘详情截图区、缩略图闪烁），故排除。
function _gamesChanged(a: Game[], b: Game[]): boolean {
  if (a.length !== b.length) return true;
  for (let i = 0; i < a.length; i++) {
    const x = a[i], y = b[i];
    const xc = (x.collections || []).map(c => c.id).join(','), yc = (y.collections || []).map(c => c.id).join(',');
    if (!x || !y || x.id !== y.id || x.fav !== y.fav || x.rating !== y.rating
      || x.dev !== y.dev || x.title !== y.title || x.last_played !== y.last_played
      || x.play_time !== y.play_time
      || !!x.has_cover !== !!y.has_cover
      || xc !== yc) return true;
  }
  return false;
}

// 后台数据变化后同步当前详情（收藏 / 评分等即时生效）
function syncCurrentGame(): void {
  if (!App.data.currentGame) return;
  const fresh = App.data.games.find(g => g.id === App.data.currentGame!.id);
  if (!fresh) { App.data.currentGame = null; return; }
  App.data.currentGame = fresh;
  if (document.getElementById('detailOverlay')!.classList.contains('show')) {
    refreshDetail();
  }
}

// ---------- 筛选与整体渲染 ----------
function renderAll(): void {
  // 渲染前后保持滚动位置，避免内容高度变化（筛选/排序/数据刷新）导致视口跳动
  const scroller = document.querySelector('.scroll');
  const keepTop = scroller ? scroller.scrollTop : 0;
  const list = filterGames(App.data.games);
  renderCards(list);
  renderEmpty(list);
  updateBatchBar();
  if (scroller && keepTop > 0) {
    requestAnimationFrame(() => { scroller.scrollTop = keepTop; });
  }
}

function filterGames(games: Game[]): Game[] {
  let list = games.slice();
  if (App.ui.state.nav === '继续游玩') {
    // 只显示最近 7 天游玩过的游戏
    const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
    list = list.filter(g => {
      if (!g.last_played) return false;
      const t = new Date(g.last_played).getTime();
      return !isNaN(t) && t >= weekAgo;
    });
  }
  else if (App.ui.state.nav === '我的收藏') list = list.filter(g => g.fav);
  if (App.ui.state.collectionId !== null) {
    // 分组选中：显示该分组 + 全部子分类内的游戏；分类选中：仅显示自身
    let ids = [App.ui.state.collectionId];
    if (App.ui.state.collectionGroupId && App.ui.state.collectionGroupId === App.ui.state.collectionId) {
      const grp = App.ui.state.collectionTree.find(g => g.id === App.ui.state.collectionId);
      if (grp && grp.children) ids = ids.concat(grp.children.map(c => c.id));
    }
    list = list.filter(g => (g.collections || []).some(c => ids.includes(c.id)));
  }
  if (App.ui.state.kw) {
    const k = App.ui.state.kw.toLowerCase();
    list = list.filter(g => g.title.toLowerCase().includes(k)
      || (g.dev || '').toLowerCase().includes(k)
      || (g.tags || []).some(t => t.includes(k)));
  }
  if (App.ui.state.sort === '名称') list.sort((a, b) => a.title.localeCompare(b.title, 'zh'));
  else if (App.ui.state.sort === '评分') list.sort((a, b) => b.rating - a.rating);
  else if (App.ui.state.collectionId === null) list.sort((a, b) => (b.last_played || '').localeCompare(a.last_played || ''));
  return list;
}

// 运行状态角标 + 详情启动按钮状态
function markRunning(): void {
  document.querySelectorAll<HTMLElement>('.card').forEach(c => {
    const has = c.querySelector('.running');
    if (c.dataset.id === App.data.runningId) {
      if (!has) {
        const s = document.createElement('span');
        s.className = 'running'; s.textContent = '运行中';
        const cover = c.querySelector('.cover'); if (cover) cover.appendChild(s);
      }
    }
    else if (has) { has.remove(); }
  });
  const b = document.getElementById('dlgStart') as HTMLButtonElement | null;
  if (b) {
    // 注意：保留原 JS 语义（currentGame.id 为 number，runningId 为 string，
    // 严格比较恒 false——原样迁移，不在此修复）
    if (App.data.currentGame && (App.data.currentGame.id as unknown as string) === App.data.runningId) {
      b.disabled = true; b.textContent = '运行中';
    }
    else { b.disabled = false; b.textContent = '开始游戏'; }
  }
}

// 批量模式下勾选 / 取消勾选
function toggleSelect(id: number, card: HTMLElement): void {
  if (App.ui.state.selected.has(id)) { App.ui.state.selected.delete(id); card.classList.remove('selected'); }
  else { App.ui.state.selected.add(id); card.classList.add('selected'); }
  updateBatchBar();
}

// 当前详情打开的卡片高亮（ring 主色描边 + shadow）
function setActiveCard(id: number | null): void {
  document.querySelectorAll('.card.active').forEach(c => c.classList.remove('active'));
  if (!id) return;
  const c = document.querySelector(`.card[data-id="${id}"]`);
  if (c) c.classList.add('active');
}

// 空状态提示（区分：收藏为空 / 筛选无结果 / 游戏库为空）
function renderEmpty(list: Game[]): void {
  const e = document.getElementById('empty')!;
  const show = list.length === 0;
  e.classList.toggle('show', show);
  if (!show) return;
  const favEmpty = App.ui.state.nav === '我的收藏';
  const filterEmpty = App.ui.state.collectionId !== null || !!App.ui.state.kw;
  if (favEmpty) {
    document.getElementById('emptyTitle')!.textContent = '还没有收藏的游戏';
    document.getElementById('emptySub')!.textContent = '点击卡片详情里的 ★ 收藏，游戏就会出现在这里';
    document.getElementById('btnShowAll')!.style.display = 'inline-block';
    document.getElementById('btnScan')!.style.display = 'none';
  } else if (filterEmpty) {
    document.getElementById('emptyTitle')!.textContent = '没有符合条件的结果';
    // 搜索空结果给可操作建议（阶段 G）
    if (App.ui.state.kw) {
      document.getElementById('emptySub')!.textContent = '没有找到「' + App.ui.state.kw + '」——检查关键词拼写、试试开发商名，或清除搜索条件';
    } else {
      document.getElementById('emptySub')!.textContent = '当前收藏夹还没有游戏，试试清除筛选条件';
    }
    document.getElementById('btnShowAll')!.style.display = 'inline-block';
    document.getElementById('btnScan')!.style.display = 'none';
  } else {
    document.getElementById('emptyTitle')!.textContent = '游戏库还是空的';
    document.getElementById('emptySub')!.textContent = '扫描游戏文件夹，开始构建你的游戏库';
    document.getElementById('btnShowAll')!.style.display = 'none';
    document.getElementById('btnScan')!.style.display = 'inline-block';
  }
}
// ============================================================
// cards.ts — 卡片 DOM 构建 / 增量渲染（懒加载） / 右键菜单
// 依赖：state.ts / icons.ts / core.ts（esc/toast）/ ui.ts（showContextMenu/showConfirmDialog）/
//       games.ts（toggleSelect / App.data.runningId）/
//       detail.ts（openDetail）/ collections.ts（openCollectionManager）/ form.ts（openEdit）
// 定义：buildCard / syncCard / renderCards / openCardMenu / loadCardCover + coverObserver / _renderedIds
// 被依赖：games.ts（renderAll 调用 renderCards）
// ============================================================

// 封面淡入动画播放一次后移除 animation 属性，避免 DOM 重算导致动画重播
function _playCoverFade(c: HTMLElement): void {
  c.classList.add('loaded');
  c.addEventListener('animationend', () => {
    c.style.animation = 'none';
  }, { once: true });
}

// 手动刷新后对所有已加载封面重播淡入动画（"已刷新"的视觉反馈）
// 复用已加载的 backgroundImage，仅重播 coverFade，不重新拉取封面
function replayCoverFade(): void {
  document.querySelectorAll<HTMLElement>('.card .cover.loaded').forEach(c => {
    c.style.animation = '';          // 清除内联 animation:none，恢复 CSS 动画
    c.classList.remove('loaded');
    void c.offsetHeight;             // 强制同步重排，确保动画重新触发
    _playCoverFade(c);
  });
}

// ---------- 卡片 ----------
let coverObserver: IntersectionObserver | null = null;
let _renderedIds: string[] = [];   // 当前网格已渲染的卡片 id 顺序

// ============ DOM 窗口化（只渲染可视区 ± 缓冲） ============
// WindowCalculator：由滚动位置 / 容器尺寸计算当前应渲染的数据项索引范围。
// 网格总高度 = 全量行数 × 行高，由顶部/底部 spacer 占位撑起（滚动条正确），
// 实际 DOM 只有窗口内卡片；滚动时增量替换（复用下方 renderCards 逻辑）。
const _WIN_BUFFER_ROWS = 2;          // 可视区上下各多渲染的缓冲行数
let _winStart = 0;                   // 当前窗口起始索引
let _winEnd = 0;                     // 当前窗口结束索引
let _topSpacer: HTMLElement | null = null;
let _bottomSpacer: HTMLElement | null = null;
let _winScrollBound = false;
let _winResizeBound = false;
let _winRaf = false;

const CARD_GAP = 14;   // 与 CSS .grid gap 对齐（窗口化与主页「继续游玩」共用）

// 指定宽度下可容纳的卡片列数（列表窗口化与主页共用；宽度为 0 时按 1 列处理）
function cardCols(width: number): number {
  const cardW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--card-w')) || 154;
  if (!width) return 1;
  return Math.max(1, Math.floor((width + CARD_GAP) / (cardW + CARD_GAP)));
}

// 列数 / 行高（与 CSS .grid auto-fill + gap 对齐）
function _winMetrics(): { cols: number; rowH: number } {
  const grid = document.getElementById('grid');
  const cardW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--card-w')) || 154;
  const cardH = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--card-h')) || 210;
  const width = grid ? grid.clientWidth : cardW;
  return { cols: cardCols(width), rowH: cardH + CARD_GAP };
}

// WindowCalculator：根据滚动位置 + 容器高度计算 [start, end) 索引范围
function _windowRange(listLen: number): { start: number; end: number } {
  const scroller = document.querySelector('.scroll');
  const { cols, rowH } = _winMetrics();
  const totalRows = Math.ceil(listLen / cols);
  const scrollTop = scroller ? scroller.scrollTop : 0;
  const viewH = scroller ? scroller.clientHeight : 0;
  const startRow = Math.max(0, Math.floor(scrollTop / rowH) - _WIN_BUFFER_ROWS);
  const endRow = Math.min(totalRows, Math.ceil((scrollTop + viewH) / rowH) + _WIN_BUFFER_ROWS);
  const start = Math.min(listLen, startRow * cols);
  const end = Math.max(start, Math.min(listLen, endRow * cols));
  return { start, end };
}

// 更新 spacer 高度（网格总高 = 全量行数 × 行高，窗口上下各一段占位）
function _updateSpacers(listLen: number, win: { start: number; end: number }): void {
  const { cols, rowH } = _winMetrics();
  const totalRows = Math.ceil(listLen / cols);
  const topRows = Math.floor(win.start / cols);
  const bottomRows = Math.max(0, totalRows - Math.ceil(win.end / cols));
  if (_topSpacer) _topSpacer.style.height = (topRows * rowH) + 'px';
  if (_bottomSpacer) _bottomSpacer.style.height = (bottomRows * rowH) + 'px';
}

// 确保 spacer 存在（网格首尾各一个，占满整行）
function _ensureSpacers(grid: HTMLElement): void {
  if (!_topSpacer) {
    _topSpacer = document.createElement('div');
    _topSpacer.className = 'grid-spacer';
    _topSpacer.setAttribute('aria-hidden', 'true');
    grid.insertBefore(_topSpacer, grid.firstChild);
  }
  if (!_bottomSpacer) {
    _bottomSpacer = document.createElement('div');
    _bottomSpacer.className = 'grid-spacer';
    _bottomSpacer.setAttribute('aria-hidden', 'true');
    grid.appendChild(_bottomSpacer);
  }
}

// 绑定滚动重算窗口（只渲染窗口内卡片，滚动时增量替换）
function _bindWindowScroll(): void {
  if (_winScrollBound) return;
  _winScrollBound = true;
  const scroller = document.querySelector('.scroll');
  if (!scroller) return;
  scroller.addEventListener('scroll', () => {
    if (_winRaf) return;
    _winRaf = true;
    requestAnimationFrame(() => {
      _winRaf = false;
      _recomputeWindow();
    });
  });
}

// 重算窗口范围并增量渲染；范围不变时仍刷新 spacer（列数/行高可能已变）
function _recomputeWindow(): void {
  const list = filterGames(App.data.games);
  const win = _windowRange(list.length);
  if (win.start === _winStart && win.end === _winEnd) {
    _updateSpacers(list.length, win);
    return;
  }
  _winStart = win.start; _winEnd = win.end;
  renderCards(list);
  _updateSpacers(list.length, win);
}

// 容器尺寸变化（窗口缩放 / 批量栏显隐）后重算窗口：滚动之外的第二条重算入口（FR-08）
function _bindWindowResize(): void {
  if (_winResizeBound) return;
  _winResizeBound = true;
  const scroller = document.querySelector('.scroll');
  if (!scroller || typeof ResizeObserver === 'undefined') return;
  let raf = false;
  const ro = new ResizeObserver(() => {
    if (raf) return;
    raf = true;
    requestAnimationFrame(() => {
      raf = false;
      _recomputeWindow();
    });
  });
  ro.observe(scroller);
}

// 卡片档位等外部度量变化后重算窗口与 spacer（保留 DOM 复用）
function refreshWindow(): void {
  if (!_renderedIds.length && !App.data.games.length) return;
  _recomputeWindow();
}

// 卡片闭包只保存 id，动作执行时解析当前对象（节点复用后创建时的 g 可能是旧快照）
function _currentGame(id: string): Game | null {
  return App.data.games.find(x => x.id === id) || null;
}

// 单卡封面加载（懒加载 observer 与主页卡片共用；优先 HTTP URL，失败回退 base64）
function loadCardCover(card: HTMLElement): void {
  const gid = card.dataset.id;
  if (!gid) return;
  loadCoverToCard(card, gid);
}

// 创建单张卡片 DOM（不含封面加载，封面由 observer 懒加载）
function buildCard(g: Game): HTMLElement {
  const card = document.createElement('div');
  card.className = 'card' + (App.ui.state.selected.has(g.id) ? ' selected' : '');
  card.dataset.id = String(g.id);
  card.dataset.coverVersion = String(g.cover_version || 0);
  card.dataset.coverUrl = g.cover_url || '';
  card.innerHTML = `<div class="cover" style="background-image:linear-gradient(160deg,#ffd7e0,#ff9fbc)">
      ${g.fav ? '<span class="fav">' + ICON.starFill + '</span>' : ''}
      <span class="check"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.4"><path d="M4 12l5 5L20 6"/></svg></span>
    </div>
    ${g.id === App.data.runningId ? '<span class="running">运行中</span>' : ''}
    <div class="meta"><span class="title" title="${esc(g.title || '未命名游戏')}">${esc(g.title || '未命名游戏')}</span><span class="score">${(g.rating || 0).toFixed(1)}</span></div>`;
  const gid = String(g.id);
  card.onclick = () => {
    if (App.ui.state.batch) { toggleSelect(gid, card); return; }
    const cur = _currentGame(gid);
    if (cur) openDetail(cur);
  };
  // 键盘可达：卡片作为可聚焦交互元素（Enter/空格 触发与点击一致）
  card.tabIndex = 0;
  card.setAttribute('role', 'button');
  const fullName = g.title || '未命名游戏';
  card.title = fullName;
  card.setAttribute('aria-label', fullName);
  card.onkeydown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (App.ui.state.batch) { toggleSelect(gid, card); return; }
      const cur = _currentGame(gid);
      if (cur) openDetail(cur);
    }
  };
  card.oncontextmenu = (e: MouseEvent) => { e.preventDefault(); openCardMenu(gid, e.clientX, e.clientY); };
  return card;
}

// 复用节点：把已有卡片同步到当前数据（标题/评分/选中/收藏）
// 封面版本变化时重置封面并返回 true（调用方决定重新懒加载或直接加载），未变化返回 false
function syncCard(card: HTMLElement, g: Game): boolean {
  const id = String(g.id);
  let coverStale = false;
  const urlChanged = card.dataset.coverUrl !== (g.cover_url || '');
  card.dataset.coverUrl = g.cover_url || '';
  if (card.dataset.coverVersion !== String(g.cover_version || 0) || urlChanged) {
    card.dataset.coverVersion = String(g.cover_version || 0);
    beginCoverRequest(card);   // 作废在途旧封面响应
    const c = card.querySelector('.cover');
    if (c) {
      c.classList.remove('loaded');
      (c as HTMLElement).style.backgroundImage = 'linear-gradient(160deg,#ffd7e0,#ff9fbc)';
    }
    coverStale = true;
  }
  if (card.className.indexOf('selected') >= 0 !== App.ui.state.selected.has(id))
    card.classList.toggle('selected', App.ui.state.selected.has(id));
  const meta = card.querySelector('.meta')!;
  const fullName = g.title || '未命名游戏';
  const titleEl = meta.querySelector('.title');
  if (titleEl && titleEl.textContent !== fullName) { titleEl.textContent = fullName; titleEl.setAttribute('title', fullName); }
  if (card.title !== fullName) { card.title = fullName; card.setAttribute('aria-label', fullName); }
  const scoreEl = meta.querySelector('.score');
  const scoreText = (g.rating || 0).toFixed(1);
  if (scoreEl && scoreEl.textContent !== scoreText) scoreEl.textContent = scoreText;
  const fav = card.querySelector('.fav');
  const needFav = !!g.fav;
  if (needFav && !fav) {
    const f = document.createElement('span'); f.className = 'fav'; f.innerHTML = ICON.starFill;
    card.querySelector('.cover')!.appendChild(f);
  } else if (!needFav && fav) { fav.remove(); }
  return coverStale;
}

// 增量渲染：对比新旧 id 列表，只增删改变化部分，未变化卡片原样保留（含已加载封面）
function renderCards(list: Game[]): void {
  const grid = document.getElementById('grid')!;
  _ensureSpacers(grid);
  _bindWindowScroll();
  _bindWindowResize();
  // 窗口化：只渲染 WindowCalculator 算出的可视区 ± 缓冲范围
  const win = _windowRange(list.length);
  _winStart = win.start; _winEnd = win.end;
  const winList = list.slice(win.start, win.end);
  _updateSpacers(list.length, win);
  const newIds = winList.map(g => g.id);
  const byId: Record<string, Game> = {}; winList.forEach(g => byId[g.id] = g);
  const oldMap: Record<string, HTMLElement> = {}; _renderedIds.forEach(id => {
    const c = grid.querySelector(`.card[data-id="${id}"]`) as HTMLElement | null; if (c) oldMap[id] = c;
  });

  // 焦点卡片若被窗口化移除，重渲染后恢复到邻近卡片（键盘滚动不丢焦点）
  const activeEl = document.activeElement as HTMLElement | null;
  const activeCard = activeEl && grid.contains(activeEl)
    ? activeEl.closest('.card') as HTMLElement | null : null;
  const activeId = activeCard?.dataset.id || '';
  const activeIndex = activeId ? _renderedIds.indexOf(activeId) : -1;

  // 1) 移除已不在窗口中的卡片
  //    同时解除 IntersectionObserver 对它们的观察——被移除的卡片若未滚入视口，
  //    不 unobserve 会被 observer 永久持有（连带 DOM 节点与封面加载闭包），
  //    频繁筛选/搜索下死节点会缓慢累积成内存泄漏。
  const removeIds = _renderedIds.filter(id => !byId[id]);
  removeIds.forEach(id => {
    const c = oldMap[id];
    if (c) {
      if (coverObserver) coverObserver.unobserve(c);
      c.remove();
    }
  });

  // 2) 按新顺序排列：复用的节点移动位置，新增节点创建
  //    注意 anchor 从 bottomSpacer 前开始插，保证卡片排在 spacer 之间
  let anchor: HTMLElement | null = _bottomSpacer;   // 从后往前插，保持顺序
  for (let i = newIds.length - 1; i >= 0; i--) {
    const id = newIds[i];
    let card = oldMap[id];
    if (!card) {
      card = buildCard(byId[id]);
      grid.insertBefore(card, anchor);
      if (coverObserver) coverObserver.observe(card);
    } else {
      grid.insertBefore(card, anchor);
      // 复用节点：同步数据字段；封面版本变化时重置并重新懒加载（syncCard 返回是否需重载）
      if (syncCard(card, byId[id]) && coverObserver) coverObserver.observe(card);
    }
    anchor = card;
  }
  _renderedIds = newIds;

  if (activeId && !newIds.includes(activeId)) {
    const idx = Math.min(Math.max(activeIndex, 0), Math.max(newIds.length - 1, 0));
    const targetId = newIds[idx];
    const target = targetId
      ? grid.querySelector<HTMLElement>(`.card[data-id="${targetId}"]`) : null;
    if (target) {
      target.focus();
    } else {
      const scroller = document.querySelector('.scroll') as HTMLElement | null;
      if (scroller) { scroller.tabIndex = -1; scroller.focus(); }
    }
  }

  if (!coverObserver) {
    coverObserver = new IntersectionObserver((entries) => {
      entries.forEach(en => {
        if (!en.isIntersecting) return;
        const card = en.target as HTMLElement;
        coverObserver!.unobserve(card);
        loadCardCover(card);
      });
    }, { root: document.querySelector('.scroll'), rootMargin: '160px' });
    grid.querySelectorAll('.card').forEach(c => coverObserver!.observe(c));
  }
}

// ---------- 卡片右键菜单（图标 + 分段，复用 ui.showContextMenu）----------
// 只接收 id；菜单打开与每个动作都解析当前对象，不携带卡片创建时的旧快照
function openCardMenu(gameId: string, x: number, y: number): void {
  if (!_currentGame(gameId)) return;
  showContextMenu([
    { icon: ICON.play, text: '启动游戏', action: () => launchGame(gameId) },
    { icon: ICON.folder, text: '打开本地目录', action: () => bridge.openFolder(gameId) },
    'sep',
    { icon: ICON.collection, text: '管理收藏夹', action: () => {
      const g = _currentGame(gameId); if (!g) return;
      App.data.currentGame = g; openCollectionManager();
    } },
    { icon: ICON.edit, text: '编辑', action: () => { const g = _currentGame(gameId); if (g) openEdit(g); } },
    { icon: ICON.refresh, text: '元数据匹配', action: () => {
      const g = _currentGame(gameId); if (!g) return;
      bridge.matchVndb(gameId, function (s: unknown, failed?: boolean) {
        if (failed) { toast('匹配未启动'); return; }
        let result: { ok?: boolean; msg?: string } = {};
        try { result = JSON.parse(String(s || '{}')); } catch (e) { }
        toast(result.ok ? '开始匹配：' + g.title : (result.msg || '匹配未启动'));
      });
    } },
    'sep',
    {
      icon: ICON.trash, text: '从库中移除', danger: true, action: () => {
        const g = _currentGame(gameId); if (!g) return;
        showConfirmDialog({
          title: '从库中移除',
          message: `从库中移除「${g.title}」？\n（不会删除实际文件）`,
          danger: true, okText: '移除', cb: () => bridge.deleteGame(gameId)
        });
      }
    },
  ], x, y, 170);
}

// 封面下载进度（后端 UISync cover_progress 域，payload 为「下载中游戏 → 进度」快照）：
// 只对已渲染（可见）卡片显示环形进度；不可见卡片忽略。失败不显示、不重试。
function updateCoverProgress(states: Record<string, number>): void {
  const map = states || {};
  Object.keys(map).forEach(id => {
    const cover = document.querySelector<HTMLElement>(`.card[data-id="${id}"] .cover`);
    if (!cover) return;
    cover.classList.add('cover-progress');
    cover.style.setProperty('--cover-pct', String(Math.round((map[id] || 0) * 100)));
  });
  // 移除已不在状态里的卡片（下载完成或失败）
  document.querySelectorAll<HTMLElement>('.card .cover.cover-progress').forEach(cover => {
    const card = cover.closest('.card') as HTMLElement | null;
    const id = card && card.dataset.id;
    if (!id || !(id in map)) cover.classList.remove('cover-progress');
  });
}

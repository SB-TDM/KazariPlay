// ============================================================
// cards.ts — 卡片 DOM 构建 / 增量渲染（懒加载） / 右键菜单
// 依赖：state.ts / core.ts（esc/stars/toast）/ ui.ts（showContextMenu/showConfirmDialog）/
//       games.ts（toggleSelect / App.data.runningId）/
//       detail.ts（openDetail）/ collections.ts（openCollectionManager）/ form.ts（openEdit）
// 定义：buildCard / renderCards / openCardMenu + coverObserver / _renderedIds
// 被依赖：games.ts（renderAll 调用 renderCards）
// ============================================================

// ---------- 卡片 ----------
let coverObserver: IntersectionObserver | null = null;
let _renderedIds: number[] = [];   // 当前网格已渲染的卡片 id 顺序

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
let _winRaf = false;

// 列数 / 行高（与 CSS .grid auto-fill + gap 对齐）
function _winMetrics(): { cols: number; rowH: number } {
  const grid = document.getElementById('grid');
  const cardW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--card-w')) || 154;
  const cardH = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--card-h')) || 210;
  const gap = 14;
  const width = grid ? grid.clientWidth : cardW;
  const cols = Math.max(1, Math.floor((width + gap) / (cardW + gap)));
  return { cols, rowH: cardH + gap };
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
  return { start: startRow * cols, end: Math.min(listLen, endRow * cols) };
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
      // 数据可能已变化，用当前全量 games 重算窗口
      const list = filterGames(App.data.games);
      const win = _windowRange(list.length);
      if (win.start === _winStart && win.end === _winEnd) return;
      _winStart = win.start; _winEnd = win.end;
      renderCards(list);          // 增量替换窗口内卡片
      _updateSpacers(list.length, win);
    });
  });
}

// 创建单张卡片 DOM（不含封面加载，封面由 observer 懒加载）
function buildCard(g: Game): HTMLElement {
  const card = document.createElement('div');
  card.className = 'card' + (App.ui.state.selected.has(g.id) ? ' selected' : '');
  card.dataset.id = String(g.id);
  card.dataset.coverVersion = String(g.cover_version || 0);
  card.dataset.coverLoaded = '';
  card.innerHTML = `<div class="cover" style="background-image:linear-gradient(160deg,#ffd7e0,#ff9fbc)">
      ${g.fav ? '<span class="fav">★</span>' : ''}
      ${(g.id as number | string) === App.data.runningId ? '<span class="running">运行中</span>' : ''}
      <span class="check"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.4"><path d="M4 12l5 5L20 6"/></svg></span>
    </div>
    <div class="meta"><span class="dev">${esc(g.dev || '未知')}</span><span class="stars">${stars(g.rating)}</span></div>`;
  card.onclick = () => { if (App.ui.state.batch) toggleSelect(g.id, card); else openDetail(g); };
  // 键盘可达：卡片作为可聚焦交互元素（Enter/空格 触发与点击一致）
  card.tabIndex = 0;
  card.setAttribute('role', 'button');
  card.onkeydown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (App.ui.state.batch) toggleSelect(g.id, card); else openDetail(g);
    }
  };
  card.oncontextmenu = (e: MouseEvent) => { e.preventDefault(); openCardMenu(g, e.clientX, e.clientY); };
  return card;
}

// 增量渲染：对比新旧 id 列表，只增删改变化部分，未变化卡片原样保留（含已加载封面）
function renderCards(list: Game[]): void {
  const grid = document.getElementById('grid')!;
  _ensureSpacers(grid);
  _bindWindowScroll();
  // 窗口化：只渲染 WindowCalculator 算出的可视区 ± 缓冲范围
  const win = _windowRange(list.length);
  _winStart = win.start; _winEnd = win.end;
  const winList = list.slice(win.start, win.end);
  _updateSpacers(list.length, win);
  const newIds = winList.map(g => g.id);
  const byId: Record<number, Game> = {}; winList.forEach(g => byId[g.id] = g);
  const oldMap: Record<number, HTMLElement> = {}; _renderedIds.forEach(id => {
    const c = grid.querySelector(`.card[data-id="${id}"]`) as HTMLElement | null; if (c) oldMap[id] = c;
  });

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
      // 复用节点：若封面版本变化（VNDB 匹配/手动更换后）则强制重新加载封面
      if (card.dataset.coverVersion !== String(byId[id].cover_version || 0)) {
        card.dataset.coverVersion = String(byId[id].cover_version || 0);
        card.dataset.coverLoaded = '';
        const c = card.querySelector('.cover');
        if (c) {
          c.classList.remove('loaded');
          (c as HTMLElement).style.backgroundImage = 'linear-gradient(160deg,#ffd7e0,#ff9fbc)';
        }
        if (coverObserver) coverObserver.observe(card);
      }
      // 复用节点：仅更新可能变化的字段（fav/选中/评分/开发商）
      if (card.className.indexOf('selected') >= 0 !== App.ui.state.selected.has(id))
        card.classList.toggle('selected', App.ui.state.selected.has(id));
      const meta = card.querySelector('.meta')!;
      const dev = meta.querySelector('.dev');
      if (dev && dev.textContent !== (byId[id].dev || '未知')) dev.textContent = byId[id].dev || '未知';
      const st = meta.querySelector('.stars');
      if (st && st.textContent !== stars(byId[id].rating)) st.textContent = stars(byId[id].rating);
      const fav = card.querySelector('.fav');
      const needFav = !!byId[id].fav;
      if (needFav && !fav) {
        const f = document.createElement('span'); f.className = 'fav'; f.textContent = '★';
        card.querySelector('.cover')!.appendChild(f);
      } else if (!needFav && fav) { fav.remove(); }
    }
    anchor = card;
  }
  _renderedIds = newIds;

  if (!coverObserver) {
    coverObserver = new IntersectionObserver((entries) => {
      entries.forEach(en => {
        if (!en.isIntersecting) return;
        const card = en.target as HTMLElement;
        const gid = card.dataset.id;
        coverObserver!.unobserve(card);
        bridge.getCover(gid!, function (uri: unknown) {
          if (!uri) return;
          const c = card.querySelector('.cover');
          if (c) {
            card.dataset.coverLoaded = '1';
            c.classList.add('loaded');
            (c as HTMLElement).style.backgroundImage = `url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
          }
        });
      });
    }, { root: document.querySelector('.scroll'), rootMargin: '160px' });
    grid.querySelectorAll('.card').forEach(c => coverObserver!.observe(c));
  }
}

// ---------- 卡片右键菜单（图标 + 分段，复用 ui.showContextMenu）----------
function openCardMenu(g: Game, x: number, y: number): void {
  showContextMenu([
    { icon: '▶', text: '启动游戏', action: () => launchGame(g.id) },
    { icon: '📂', text: '打开本地目录', action: () => bridge.openFolder(String(g.id)) },
    'sep',
    { icon: '🗂️', text: '管理收藏夹', action: () => { App.data.currentGame = g; openCollectionManager(); } },
    { icon: '✏️', text: '编辑', action: () => openEdit(g) },
    { icon: '🔄', text: 'VNDB 匹配', action: () => { bridge.matchVndb(String(g.id)); toast('开始匹配：' + g.title); } },
    'sep',
    {
      icon: '🗑️', text: '从库中移除', danger: true, action: () => showConfirmDialog({
        title: '从库中移除',
        message: `从库中移除「${g.title}」？\n（不会删除实际文件）`,
        danger: true, okText: '移除', cb: () => bridge.deleteGame(String(g.id))
      })
    },
  ], x, y, 170);
}
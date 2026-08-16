// ============================================================
// games.js — 游戏数据 + 卡片网格（渲染 / 过滤 / 懒加载 / 拖拽排序 / 右键菜单）
// 依赖：state.js / core.js（esc/stars/toast）/ ui.js（showContextMenu/showConfirmDialog）
// 定义：refreshAll / _gamesChanged / syncCurrentGame / reloadCovers / applyCoverSize /
//       renderAll / filterGames / buildCard / renderCards / markRunning /
//       toggleSelect / setActiveCard / renderEmpty / 卡片拖拽排序 / openCardMenu
// 被依赖：detail.js（syncCurrentGame 调用 refreshDetail）、app.js（refreshAll/init）、
//         state.js 的 window.__app（refresh/reloadCovers）
// ============================================================

// ---------- 封面 ----------
// 强制重载所有可见卡片封面（VNDB 匹配 / 手动更换后由后端主动触发）
function reloadCovers() {
  document.querySelectorAll('.card').forEach(card => {
    const c = card.querySelector('.cover');
    if (!c) return;
    card.dataset.coverLoaded = '';
    c.classList.remove('loaded');   // 重新加载时先去掉淡入标记，实图到达后再淡入
    bridge.getCover(card.dataset.id, function (uri) {
      if (!uri) return;
      card.dataset.coverLoaded = '1';
      c.classList.add('loaded');
      c.style.backgroundImage = `url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
    });
  });
}

// 封面尺寸档位（对应设置 cover_size）
const COVER_SIZES = { small: { w: 132, h: 180 }, medium: { w: 154, h: 210 }, large: { w: 180, h: 245 } };
function applyCoverSize(size) {
  const s = COVER_SIZES[size] || COVER_SIZES.medium;
  document.documentElement.style.setProperty('--card-w', s.w + 'px');
  document.documentElement.style.setProperty('--card-h', s.h + 'px');
}

// ---------- 数据刷新 ----------
function refreshAll(force) {
  if (!bridge) return;
  bridge.getGames(function (s) {
    const fresh = JSON.parse(s);
    // 数据无变化时不重建网格，避免卡片闪烁（事件推送 / 轮询兜底）
    if (force || _gamesChanged(App.data.games, fresh)) {
      App.data.games = fresh; renderAll(); syncCurrentGame();
    } else {
      // 仅刷新运行状态等轻量字段
      App.data.games = fresh; syncCurrentGame(); markRunning();
    }
  });
  bridge.getCollectionsTree(function (s) {
    App.ui.state.collectionTree = JSON.parse(s || '[]');
    renderCollectionTree();
  });
  bridge.getRunning(function (r) { App.data.runningId = r || ''; markRunning(); });
}

// 判断游戏列表是否有实质变化（比较影响卡片显示的字段）。
// 注意：last_text / play_time_text 是派生展示文本，已分别由 last_played / play_time
// 覆盖；相对时间（"3 分钟前"→"刚刚"）每分钟必变，纳入比较会误触发全量重渲染
// （进而重绘详情截图区、缩略图闪烁），故排除。
function _gamesChanged(a, b) {
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
function syncCurrentGame() {
  if (!App.data.currentGame) return;
  const fresh = App.data.games.find(g => g.id === App.data.currentGame.id);
  if (!fresh) { App.data.currentGame = null; return; }
  App.data.currentGame = fresh;
  if (document.getElementById('detailOverlay').classList.contains('show')) {
    refreshDetail();
  }
}

// ---------- 筛选与整体渲染 ----------
function renderAll() {
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

function filterGames(games) {
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
    // 收藏夹视图：默认按 sort_order 排序（拖拽持久化顺序）；显式名称/评分排序时覆盖
    if (App.ui.state.sort === '时间' && App.ui.state.collectionOrder && App.ui.state.collectionOrder.length) {
      const orderMap = {}; App.ui.state.collectionOrder.forEach((gid, i) => orderMap[gid] = i);
      list.sort((a, b) => (orderMap[a.id] ?? 9999) - (orderMap[b.id] ?? 9999));
    }
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

// ---------- 卡片 ----------
let coverObserver = null;
let _renderedIds = [];   // 当前网格已渲染的卡片 id 顺序

// 创建单张卡片 DOM（不含封面加载，封面由 observer 懒加载）
function buildCard(g) {
  const card = document.createElement('div');
  card.className = 'card' + (App.ui.state.selected.has(g.id) ? ' selected' : '');
  card.dataset.id = g.id;
  card.dataset.coverVersion = g.cover_version || 0;
  card.dataset.coverLoaded = '';
  card.innerHTML = `<div class="cover" style="background-image:linear-gradient(160deg,#ffd7e0,#ff9fbc)">
      ${g.fav ? '<span class="fav">★</span>' : ''}
      ${g.id === App.data.runningId ? '<span class="running">运行中</span>' : ''}
      <span class="check"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.4"><path d="M4 12l5 5L20 6"/></svg></span>
    </div>
    <div class="meta"><span class="dev">${esc(g.dev || '未知')}</span><span class="stars">${stars(g.rating)}</span></div>`;
  card.onclick = () => { if (App.ui.state.batch) toggleSelect(g.id, card); else openDetail(g); };
  // 键盘可达：卡片作为可聚焦交互元素（Enter/空格 触发与点击一致）
  card.tabIndex = 0;
  card.setAttribute('role', 'button');
  card.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.onclick(); } };
  card.oncontextmenu = (e) => { e.preventDefault(); openCardMenu(g, e.clientX, e.clientY); };
  bindCardDrag(card, g);
  return card;
}

// ---------- 卡片拖拽排序（仅收藏夹视图启用）----------
// 用 mousedown 自实现 + 位移阈值：点击打开详情不受轻微抖动影响，
// 按住移动超过 DRAG_THRESHOLD 才进入拖拽态（HTML5 drag & drop 无法判定位移阈值）。
let dragFromId = null;
let dragOverId = null;
let _dragState = null;      // {id, startX, startY} 按下后待判定
let _dragActive = false;    // 已超过阈值进入拖拽态
let _dragOffset = null;     // {ox, oy} 鼠标相对卡片左上角偏移（拖拽跟手用）
const DRAG_THRESHOLD = 6;   // px：小于该位移视为点击

function isDragOrderEnabled() {
  // 收藏夹视图 + 非批量模式 才允许拖拽重排
  return App.ui.state.collectionId !== null && !App.ui.state.batch;
}

function bindCardDrag(card, g) {
  card.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (!isDragOrderEnabled()) return;
    _dragState = { id: g.id, startX: e.clientX, startY: e.clientY };
    _dragActive = false;
    const r = card.getBoundingClientRect();
    _dragOffset = { ox: e.clientX - r.left, oy: e.clientY - r.top };
  });
}

// 全局 mouseup：拖拽结束落点（按下后 100ms 内未判定为拖拽则忽略）
document.addEventListener('mouseup', () => {
  if (!_dragState) return;
  if (_dragActive && dragFromId) {
    // 有落点则重排；无落点（拖回原处）仅清理
    if (dragOverId && dragFromId !== dragOverId) {
      reorderCards(dragFromId, dragOverId);
    }
    _dragActive = false;
    dragFromId = null; dragOverId = null; _dragOffset = null;
    document.querySelectorAll('.card.dragging,.card.drag-over')
      .forEach(c => c.classList.remove('dragging', 'drag-over'));
  }
  _dragState = null;
});

// 全局 mousemove：位移超过阈值进入拖拽态，拖拽中源卡片跟随鼠标 + 更新落点高亮
document.addEventListener('mousemove', (e) => {
  if (!_dragState) return;
  if (!_dragActive) {
    const dx = e.clientX - _dragState.startX;
    const dy = e.clientY - _dragState.startY;
    if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    _dragActive = true;
    dragFromId = _dragState.id;
    dragOverId = null;
    const c = document.querySelector(`.card[data-id="${dragFromId}"]`);
    if (c) c.classList.add('dragging');
    return;
  }
  // 拖拽中：源卡片跟手（相对按下点位移，translate 保持原布局占位）
  const c = document.querySelector(`.card[data-id="${dragFromId}"]`);
  if (c && _dragOffset) {
    c.style.transform =
      `translate(${e.clientX - _dragState.startX}px, ${e.clientY - _dragState.startY}px)`;
  }
  // 落点判定：鼠标下的卡片（排除自身）
  const el = document.elementFromPoint(e.clientX, e.clientY);
  const target = el && el.closest ? el.closest('.card') : null;
  const tid = target && target.dataset.id !== dragFromId ? target.dataset.id : null;
  if (tid !== dragOverId) {
    dragOverId = tid;
    markDragOver(tid ? target : null);
  }
});

function markDragOver(card) {
  document.querySelectorAll('.card.drag-over').forEach(c => c.classList.remove('drag-over'));
  if (card) card.classList.add('drag-over');
}

// 拖拽落点：把 from 移到 to 之前，并持久化到当前收藏夹
function reorderCards(fromId, toId) {
  const grid = document.getElementById('grid');
  const ids = [...grid.querySelectorAll('.card')].map(c => c.dataset.id);
  const from = ids.indexOf(fromId), to = ids.indexOf(toId);
  if (from < 0 || to < 0) return;
  ids.splice(from, 1);
  ids.splice(to, 0, fromId);
  // 更新本地顺序（先改 UI 再持久化，避免闪烁）
  App.ui.state.collectionOrder = ids;
  renderAll();
  // 持久化：分组视图聚合排序存到分组自身，分类视图存到分类
  bridge.setCollectionGames(App.ui.state.collectionId, JSON.stringify(ids));
  toast('排序已更新');
}

// 增量渲染：对比新旧 id 列表，只增删改变化部分，未变化卡片原样保留（含已加载封面）
function renderCards(list) {
  const grid = document.getElementById('grid');
  const newIds = list.map(g => g.id);
  const byId = {}; list.forEach(g => byId[g.id] = g);
  const oldMap = {}; _renderedIds.forEach(id => {
    const c = grid.querySelector(`.card[data-id="${id}"]`); if (c) oldMap[id] = c;
  });

  // 1) 移除已不在列表中的卡片
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
  let anchor = null;   // 从后往前插，保持顺序
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
        card.dataset.coverVersion = byId[id].cover_version || 0;
        card.dataset.coverLoaded = '';
        const c = card.querySelector('.cover');
        if (c) {
          c.classList.remove('loaded');
          c.style.backgroundImage = 'linear-gradient(160deg,#ffd7e0,#ff9fbc)';
        }
        if (coverObserver) coverObserver.observe(card);
      }
      // 复用节点：仅更新可能变化的字段（fav/选中/评分/开发商）
      if (card.className.indexOf('selected') >= 0 !== App.ui.state.selected.has(id))
        card.classList.toggle('selected', App.ui.state.selected.has(id));
      const meta = card.querySelector('.meta');
      const dev = meta.querySelector('.dev');
      if (dev && dev.textContent !== (byId[id].dev || '未知')) dev.textContent = byId[id].dev || '未知';
      const st = meta.querySelector('.stars');
      if (st && st.textContent !== stars(byId[id].rating)) st.textContent = stars(byId[id].rating);
      const fav = card.querySelector('.fav');
      const needFav = !!byId[id].fav;
      if (needFav && !fav) {
        const f = document.createElement('span'); f.className = 'fav'; f.textContent = '★';
        card.querySelector('.cover').appendChild(f);
      } else if (!needFav && fav) { fav.remove(); }
    }
    anchor = card;
  }
  _renderedIds = newIds;

  if (!coverObserver) {
    coverObserver = new IntersectionObserver((entries) => {
      entries.forEach(en => {
        if (!en.isIntersecting) return;
        const card = en.target;
        const gid = card.dataset.id;
        coverObserver.unobserve(card);
        bridge.getCover(gid, function (uri) {
          if (!uri) return;
          const c = card.querySelector('.cover');
          if (c) {
            card.dataset.coverLoaded = '1';
            c.classList.add('loaded');
            c.style.backgroundImage = `url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
          }
        });
      });
    }, { root: document.querySelector('.scroll'), rootMargin: '160px' });
    grid.querySelectorAll('.card').forEach(c => coverObserver.observe(c));
  }
}

// 运行状态角标 + 详情启动按钮状态
function markRunning() {
  document.querySelectorAll('.card').forEach(c => {
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
  const b = document.getElementById('dlgStart');
  if (App.data.currentGame && App.data.currentGame.id === App.data.runningId) { b.disabled = true; b.textContent = '运行中'; }
  else { b.disabled = false; b.textContent = '开始游戏'; }
}

// 批量模式下勾选 / 取消勾选
function toggleSelect(id, card) {
  if (App.ui.state.selected.has(id)) { App.ui.state.selected.delete(id); card.classList.remove('selected'); }
  else { App.ui.state.selected.add(id); card.classList.add('selected'); }
  updateBatchBar();
}

// 当前详情打开的卡片高亮（ring 主色描边 + shadow）
function setActiveCard(id) {
  document.querySelectorAll('.card.active').forEach(c => c.classList.remove('active'));
  if (!id) return;
  const c = document.querySelector(`.card[data-id="${id}"]`);
  if (c) c.classList.add('active');
}

// 空状态提示（区分：收藏为空 / 筛选无结果 / 游戏库为空）
function renderEmpty(list) {
  const e = document.getElementById('empty');
  const show = list.length === 0;
  e.classList.toggle('show', show);
  if (!show) return;
  const favEmpty = App.ui.state.nav === '我的收藏';
  const filterEmpty = App.ui.state.collectionId !== null || !!App.ui.state.kw;
  if (favEmpty) {
    document.getElementById('emptyTitle').textContent = '还没有收藏的游戏';
    document.getElementById('emptySub').textContent = '点击卡片详情里的 ★ 收藏，游戏就会出现在这里';
    document.getElementById('btnShowAll').style.display = 'inline-block';
    document.getElementById('btnScan').style.display = 'none';
  } else if (filterEmpty) {
    document.getElementById('emptyTitle').textContent = '没有符合条件的结果';
    // 搜索空结果给可操作建议（阶段 G）
    if (App.ui.state.kw) {
      document.getElementById('emptySub').textContent = '没有找到「' + App.ui.state.kw + '」——检查关键词拼写、试试开发商名，或清除搜索条件';
    } else {
      document.getElementById('emptySub').textContent = '当前收藏夹还没有游戏，试试清除筛选条件';
    }
    document.getElementById('btnShowAll').style.display = 'inline-block';
    document.getElementById('btnScan').style.display = 'none';
  } else {
    document.getElementById('emptyTitle').textContent = '游戏库还是空的';
    document.getElementById('emptySub').textContent = '扫描游戏文件夹，开始构建你的游戏库';
    document.getElementById('btnShowAll').style.display = 'none';
    document.getElementById('btnScan').style.display = 'inline-block';
  }
}

// ---------- 卡片右键菜单（图标 + 分段，复用 ui.showContextMenu）----------
function openCardMenu(g, x, y) {
  showContextMenu([
    { icon: '▶', text: '启动游戏', action: () => launchGame(g.id) },
    { icon: '📂', text: '打开本地目录', action: () => bridge.openFolder(g.id) },
    'sep',
    { icon: '🗂️', text: '管理收藏夹', action: () => { App.data.currentGame = g; openCollectionManager(); } },
    { icon: '✏️', text: '编辑', action: () => openEdit(g) },
    { icon: '🔄', text: 'VNDB 匹配', action: () => { bridge.matchVndb(g.id); toast('开始匹配：' + g.title); } },
    'sep',
    {
      icon: '🗑️', text: '从库中移除', danger: true, action: () => showConfirmDialog({
        title: '从库中移除',
        message: `从库中移除「${g.title}」？\n（不会删除实际文件）`,
        danger: true, okText: '移除', cb: () => bridge.deleteGame(g.id)
      })
    },
  ], x, y, 170);
}

// ============================================================
// home.ts — 主页（默认视图）：问候/日期、继续游玩、统计、收藏夹快捷、空库引导
// 依赖：state.ts / core.ts（bridge/esc）/ cards.ts（buildCard/loadCardCover）/
//       collections.ts（selectCollection，运行时调用）
// 定义：updateHomeView（由 games.renderAll / applyGamesDelta 调用）
// 被依赖：games.ts（渲染链路）；默认视图由 state.ts 的 nav='主页' 决定
// ============================================================

const HOME_CONTINUE_LIMIT = 6;   // 「继续游玩」最多展示的卡片数
const HOME_CHIP_LIMIT = 8;       // 「收藏夹」快捷最多展示的 chips

// 视图切换入口：切换 body.home-view 并渲染主页板块；返回当前是否主页
function updateHomeView(): boolean {
  const onHome = App.ui.state.nav === '主页';
  document.body.classList.toggle('home-view', onHome);
  if (onHome) renderHomeSections();
  return onHome;
}

function renderHomeSections(): void {
  renderHomeHead();
  renderHomeContinue();
  renderHomeStats();
  renderHomeCollections();
  document.getElementById('homeEmpty')!.hidden = App.data.games.length !== 0;
}

// ---------- 头部：问候 + 日期/副文案 ----------
function renderHomeHead(): void {
  const now = new Date();
  const h = now.getHours();
  const hello = h >= 5 && h < 12 ? '早上好' : h >= 12 && h < 18 ? '下午好' : '晚上好';
  document.getElementById('homeGreet')!.textContent = hello;
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][now.getDay()];
  document.getElementById('homeSub')!.textContent =
    `${now.getMonth() + 1} 月 ${now.getDate()} 日 ${week} · 今天想玩点什么？`;
}

// ---------- 继续游玩：按 last_played 倒序，数量随容器宽度自适应（1~6，一行放下） ----------
// 重建前比较签名（顺序 + 卡片展示字段 + cover_version）：完全未变则保留现有卡片与已加载封面
// （运行中角标由 markRunning 就地更新，不参与签名，避免启动/退出游戏引发无谓重建）
let _homeContinueSig: string | null = null;
function renderHomeContinue(): void {
  const box = document.getElementById('homeContinue')!;
  const sec = document.getElementById('homeContinueSec') as HTMLElement;
  const played = App.data.games.filter(g => !!g.last_played)
    .sort((a, b) => (b.last_played || '').localeCompare(a.last_played || ''));
  const empty = played.length === 0;
  if (!empty) sec.hidden = false;   // 数量依赖容器宽度：先显形再测量（隐藏时 clientWidth 为 0）
  const cardW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--card-w')) || 154;
  const gap = 14;
  const fit = box.clientWidth ? Math.floor((box.clientWidth + gap) / (cardW + gap)) : HOME_CONTINUE_LIMIT;
  const count = Math.max(1, Math.min(HOME_CONTINUE_LIMIT, fit));
  const list = played.slice(0, count);
  const sig = list.map(g => [g.id, g.title || '', g.rating || 0, g.fav ? 1 : 0,
    g.cover_version || 0].join(':')).join('|');
  if (sig === _homeContinueSig) return;   // 无变化：保留卡片与封面（含空态）
  _homeContinueSig = sig;
  if (empty) { sec.hidden = true; box.innerHTML = ''; return; }
  box.innerHTML = '';
  list.forEach(g => {
    const card = buildCard(g);
    box.appendChild(card);
    loadCardCover(card);   // 主页卡片不在列表滚动容器内，直接加载封面
  });
}

// 窗口尺寸变化后按新宽度重算「继续游玩」数量
let _homeResizeBound = false;
function bindHomeResize(): void {
  if (_homeResizeBound) return;
  _homeResizeBound = true;
  let raf = false;
  window.addEventListener('resize', () => {
    if (raf) return;
    raf = true;
    requestAnimationFrame(() => {
      raf = false;
      if (App.ui.state.nav === '主页') renderHomeContinue();
    });
  });
}

// ---------- 统计 ----------
// 总时长与后端 format_play_time 同口径（分钟；<60 按分钟；≥60 显示「X 小时 Y 分钟」）
function formatTotalMinutes(minutes: number): string {
  if (!minutes || minutes <= 0) return '0 分钟';
  if (minutes < 60) return minutes + ' 分钟';
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return m ? `${h} 小时 ${m} 分钟` : `${h} 小时`;
}

function renderHomeStats(): void {
  const games = App.data.games;
  const total = games.length;
  const fav = games.filter(g => g.fav).length;
  const minutes = games.reduce((s, g) => s + (g.play_time || 0), 0);
  const latest = games.filter(g => g.last_played)
    .sort((a, b) => (b.last_played || '').localeCompare(a.last_played || ''))[0] as Game | undefined;
  const recentText = latest ? (latest.last_text || '—') : '无';
  const box = document.getElementById('homeStats')!;
  box.innerHTML = `
    <button type="button" class="home-stat" id="homeStatTotal" aria-label="共 ${total} 部作品，查看全部作品"><b>${total}</b><span>作品总数</span></button>
    <button type="button" class="home-stat" id="homeStatFav" aria-label="共 ${fav} 部收藏，查看我的最爱"><b>${fav}</b><span>收藏数</span></button>
    <div class="home-stat"><b>${formatTotalMinutes(minutes)}</b><span>总游玩时长</span></div>
    <div class="home-stat"><b>${esc(recentText)}</b><span>最近一次游玩</span></div>`;
  (document.getElementById('homeStatTotal') as HTMLButtonElement).onclick = () =>
    (document.getElementById('btnNavAll') as HTMLElement).click();
  (document.getElementById('homeStatFav') as HTMLButtonElement).onclick = () =>
    (document.getElementById('btnNavFav') as HTMLElement).click();
}

// ---------- 收藏夹快捷：按树序平铺前 8 个，点击走抽屉同款筛选路径 ----------
function renderHomeCollections(): void {
  const box = document.getElementById('homeCollections')!;
  const sec = document.getElementById('homeCollectionsSec') as HTMLElement;
  const items: { node: CollectionTreeNode; label: string }[] = [];
  App.ui.state.collectionTree.forEach(g => {
    items.push({ node: g, label: g.name });
    (g.children || []).forEach(c => items.push({ node: c, label: g.name + ' / ' + c.name }));
  });
  const shown = items.slice(0, HOME_CHIP_LIMIT);
  if (!shown.length) { sec.hidden = true; box.innerHTML = ''; return; }
  sec.hidden = false;
  box.innerHTML = '';
  shown.forEach(it => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'home-chip';
    b.textContent = it.label;
    b.title = it.label;
    b.onclick = () => selectCollection(it.node.id, it.node);
    box.appendChild(b);
  });
}

// ---------- 事件绑定 ----------
document.getElementById('homeScanBtn')!.onclick = () => bridge.scanFolder();
bindHomeResize();

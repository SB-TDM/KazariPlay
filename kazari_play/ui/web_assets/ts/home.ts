// ============================================================
// home.ts — 主页（默认视图）：问候/日期、继续游玩、统计、收藏夹快捷、空库引导
// 依赖：state.ts / core.ts（bridge/esc）/ cards.ts（buildCard/syncCard/loadCardCover/cardCols）/
//       games.ts（compareLastPlayedDesc）/ collections.ts（selectCollection），均运行时调用
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
  renderHomeEmpty();
}

// 空库引导：有作品时隐藏
function renderHomeEmpty(): void {
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
// 与列表同款复用渲染：按 id 复用卡片节点（保留已加载封面），只增删/挪位/同步变化字段；
// 仅新卡或 cover_version 变化的卡才重新加载封面（运行角标由 markRunning 就地更新）
let _homeContinueIds: string[] = [];
function renderHomeContinue(): void {
  const box = document.getElementById('homeContinue')!;
  const sec = document.getElementById('homeContinueSec') as HTMLElement;
  const played = App.data.games.filter(g => !!g.last_played)
    .sort(compareLastPlayedDesc);
  if (!played.length) {
    if (_homeContinueIds.length) { box.innerHTML = ''; _homeContinueIds = []; }
    sec.hidden = true;
    return;
  }
  sec.hidden = false;   // 数量依赖容器宽度：先显形再测量（隐藏时 clientWidth 为 0）
  const fit = box.clientWidth ? cardCols(box.clientWidth) : HOME_CONTINUE_LIMIT;
  const count = Math.max(1, Math.min(HOME_CONTINUE_LIMIT, fit));
  const list = played.slice(0, count);
  const byId: Record<string, Game> = {}; list.forEach(g => byId[g.id] = g);
  const newIds = list.map(g => g.id);
  const oldMap: Record<string, HTMLElement> = {};
  _homeContinueIds.forEach(id => {
    const c = box.querySelector(`.card[data-id="${id}"]`) as HTMLElement | null;
    if (c) oldMap[id] = c;
  });
  // 1) 移除不再展示的卡片
  _homeContinueIds.forEach(id => { if (!byId[id]) { const c = oldMap[id]; if (c) c.remove(); } });
  // 2) 从后往前：复用节点挪位，新增节点创建
  let anchor: Node | null = null;
  for (let i = newIds.length - 1; i >= 0; i--) {
    const id = newIds[i];
    let card = oldMap[id];
    if (!card) {
      card = buildCard(byId[id]);
      box.insertBefore(card, anchor);
      loadCardCover(card);   // 新卡直接加载封面（主页卡片不在列表滚动容器内）
    } else {
      box.insertBefore(card, anchor);
      if (syncCard(card, byId[id])) loadCardCover(card);
    }
    anchor = card;
  }
  _homeContinueIds = newIds;
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

// 统计：就地更新静态骨架节点（不整体重建，保留节点身份与焦点）
function renderHomeStats(): void {
  const games = App.data.games;
  const total = games.length;
  const fav = games.filter(g => g.fav).length;
  const minutes = games.reduce((s, g) => s + (g.play_time || 0), 0);
  const latest: Game | undefined = games.filter(g => g.last_played).sort(compareLastPlayedDesc)[0];
  const recentText = latest ? (latest.last_text || '—') : '无';
  const totalBtn = document.getElementById('homeStatTotal') as HTMLButtonElement;
  const favBtn = document.getElementById('homeStatFav') as HTMLButtonElement;
  totalBtn.querySelector('b')!.textContent = String(total);
  totalBtn.setAttribute('aria-label', `共 ${total} 部作品，查看全部作品`);
  favBtn.querySelector('b')!.textContent = String(fav);
  favBtn.setAttribute('aria-label', `共 ${fav} 部最爱，查看我的最爱`);
  (document.getElementById('homeStatTime')!.querySelector('b') as HTMLElement).textContent = formatTotalMinutes(minutes);
  (document.getElementById('homeStatRecent')!.querySelector('b') as HTMLElement).textContent = recentText;
}

// ---------- 收藏夹快捷：按树序平铺前 8 个，点击走抽屉同款筛选路径 ----------
let _homeChipSig = '';
function renderHomeCollections(): void {
  const box = document.getElementById('homeCollections')!;
  const sec = document.getElementById('homeCollectionsSec') as HTMLElement;
  const items = flattenCollectionTree();
  const shown = items.slice(0, HOME_CHIP_LIMIT);
  const sig = shown.map(it => it.node.id + ':' + it.label).join('|');
  if (sig === _homeChipSig) return;   // 无变化：保留现有 chips（及其焦点）
  _homeChipSig = sig;
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
(document.getElementById('homeStatTotal') as HTMLButtonElement).onclick = () =>
  (document.getElementById('btnNavAll') as HTMLElement).click();
(document.getElementById('homeStatFav') as HTMLButtonElement).onclick = () =>
  (document.getElementById('btnNavFav') as HTMLElement).click();
bindHomeResize();

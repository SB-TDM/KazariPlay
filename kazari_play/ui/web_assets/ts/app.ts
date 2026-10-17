// ============================================================
// app.ts — 启动引导（最后加载）
// 职责：初始化入口 / 导航 / 搜索 / 筛选下拉 / FAB / 全局点击与键盘处理
// 依赖：state.ts / core.ts / ui.ts / window.ts / games.ts / collections.ts / batch.ts / form.ts / updater.ts
// 注意：本文件只负责「粘合」各模块与全局事件，不承载业务逻辑。
// ============================================================

// ---------- 初始化 ----------
// pywebview 注入时序：先注入 window.pywebview（api 为空对象 {}），导航完成后
// 才 _createApi 填充方法并派发 pywebviewready。因此不能只凭 api 真值判定就绪
// （空对象也为真，会过早执行导致全部桥接调用拿到空 api）。
// 这里用「方法数 > 0」判断就绪 + 轮询兜底 + pywebviewready 事件三重保障，且防重复执行。
function init(): void {
  let _ready = false;
  const onReady = function (): void {
    if (_ready) return;
    _ready = true;
    window.bridgeReady = true;
    bridge.getConfig(function (s: unknown, failed?: boolean) {
      if (failed) return;
      try {
        const cfg = JSON.parse(String(s || '{}')) as { theme?: string; cover_size?: string };
        if (window.Settings) window.Settings.initTheme(cfg.theme || 'light');
        applyCoverSize(cfg.cover_size || 'medium');
      } catch (e) { }
    });
    refreshAll(true, function () {
      // 更新后首启确认：首屏数据加载成功才算"界面就绪"；完成时返回「已更新到 vX」
      bridge.updateFrontendReady(function (msg: unknown, failed?: boolean) {
        if (!failed && msg) toast(String(msg));
      });
    });
    updaterStartupCheck();   // 启动静默检查更新（24h 缓存；发现新版只提示一次）
    setInterval(() => refreshAll(false), 30000);   // 长轮询兜底（数据无变化时不重建）
  };

  const apiReady = function (): boolean {
    const api = window.pywebview && window.pywebview.api;
    // 空对象 {} 不算就绪（_createApi 尚未填充）
    return !!(api && typeof api === 'object' && Object.keys(api).length > 0);
  };

  if (apiReady()) { onReady(); }
  else {
    // 事件 + 轮询双保险：任一先到都就绪（_ready 防重复）
    window.addEventListener('pywebviewready', onReady);
    const poll = function (): void {
      if (_ready) return;
      if (apiReady()) { onReady(); }
      else setTimeout(poll, 100);
    };
    setTimeout(poll, 100);
  }
}

// ---------- 筛选下拉 ----------
function bindFilterMenu(): void {
  const m = document.getElementById('filterMenu')!;
  m.querySelectorAll<HTMLElement>('.item').forEach(it => {
    it.onclick = () => {
      App.ui.state.sort = it.dataset.sort!;
      m.classList.remove('show');
      document.querySelectorAll<HTMLElement>('#filterMenu .item').forEach(x => x.classList.remove('on'));
      it.classList.add('on');
      renderAll();
      updateSortLabel();
    };
  });
}

// ---------- 事件绑定 ----------
// 搜索框（防抖：连续输入只触发一次过滤渲染，避免大库逐键全量重建）
let searchTimer: ReturnType<typeof setTimeout> | null = null;
(document.getElementById('searchInput') as HTMLInputElement).addEventListener('input', e => {
  const kw = (e.target as HTMLInputElement).value.trim();
  clearTimeout(searchTimer as ReturnType<typeof setTimeout>);
  searchTimer = setTimeout(() => {
    if (App.ui.state.kw === kw) return;
    App.ui.state.kw = kw;
    renderAll();
  }, 200);
});
// 筛选按钮 + 下拉
document.getElementById('filterBtn')!.onclick = function (e: MouseEvent) {
  e.stopPropagation();
  document.getElementById('filterMenu')!.classList.toggle('show');
};
bindFilterMenu();
updateSortLabel();

// 侧边栏导航（全部作品 / 我的收藏；收藏夹入口在下方浮层）
document.querySelectorAll<HTMLElement>('#sidebar .side-item[data-nav]').forEach(it => {
  it.onclick = () => {
    App.ui.state.nav = it.dataset.nav!;
    App.ui.state.collectionId = null;
    // 只清除导航项高亮：收藏夹入口的 active 表示抽屉展开，由 setCollectionDrawer 维护
    document.querySelectorAll<HTMLElement>('#sidebar .side-item[data-nav]').forEach(x => x.classList.remove('active'));
    document.querySelectorAll<HTMLElement>('#collectionTree .collection-item').forEach(x => x.classList.remove('active'));
    document.querySelectorAll<HTMLElement>('#collectionTree .collection-group-header').forEach(x => x.classList.remove('active'));
    it.classList.add('active');
    renderAll();
  };
});

// 设置入口
document.getElementById('btnSettings')!.onclick = () => {
  if (window.Settings) window.Settings.open();
  else toast('设置模块加载失败');
};

// 收藏夹浮层（S3）：副标题栏开关、遮罩收起、Esc 收起
const collectionDrawer = document.getElementById('collectionDrawer')!;
const collectionScrim = document.getElementById('collectionScrim')!;
const btnCollections = document.getElementById('btnCollections')!;

// 遮罩覆盖区域（卡片/空状态/FAB/批量栏）：鼠标由遮罩拦截，键盘靠 inert 同步禁用
function setDrawerBackgroundInert(inert: boolean): void {
  const blocked = [
    document.querySelector('.scroll'),
    document.getElementById('empty'),
    document.getElementById('fabRefresh'),
    document.getElementById('fab'),
    document.getElementById('fabMenu'),
    document.getElementById('batchBar'),
  ];
  blocked.forEach(el => { if (el) (el as HTMLElement).inert = inert; });
}

function setCollectionDrawer(open: boolean): void {
  const hadFocus = !open && collectionDrawer.contains(document.activeElement);
  collectionDrawer.classList.toggle('show', open);
  collectionScrim.classList.toggle('show', open);
  btnCollections.classList.toggle('active', open);   // 展开时按钮切换为收起样式（图标由 CSS 按 .active 切换）
  btnCollections.setAttribute('aria-expanded', open ? 'true' : 'false');
  btnCollections.setAttribute('aria-label', open ? '收起收藏夹' : '收藏夹');
  setDrawerBackgroundInert(open);
  if (hadFocus) btnCollections.focus();
}
btnCollections.onclick = () => setCollectionDrawer(!collectionDrawer.classList.contains('show'));
collectionScrim.onclick = () => setCollectionDrawer(false);

// 收藏夹开关只在「全部作品」视图存在；其它视图隐藏（抽屉若已打开保持原状，可经 Esc/遮罩收起）
function updateCollectionsEntry(): void {
  const isAllView = App.ui.state.nav === '全部作品' && App.ui.state.collectionId === null;
  btnCollections.hidden = !isAllView;
}

// 主题切换（即时持久化，复用设置模块）
document.getElementById('btnTheme')!.onclick = () => {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  if (window.Settings) window.Settings.pickTheme(dark ? 'light' : 'dark');
  else toast('设置模块加载失败');
};

// 空状态 / FAB
document.getElementById('btnScan')!.onclick = () => bridge.scanFolder();
document.getElementById('btnShowAll')!.onclick = () => clearCollectionFilter();
document.getElementById('fab')!.onclick = function (e: MouseEvent) {
  e.stopPropagation();
  document.getElementById('fabMenu')!.classList.toggle('show');
};
document.getElementById('fabRefresh')!.onclick = () => { refreshAll(true, () => { replayCoverFade(); toast('已刷新'); }); };
document.getElementById('fabAdd')!.onclick = () => { document.getElementById('fabMenu')!.classList.remove('show'); openAdd(); };
document.getElementById('fabScan')!.onclick = () => { document.getElementById('fabMenu')!.classList.remove('show'); bridge.scanFolder(); };

// 全局点击：收起所有浮层
document.addEventListener('click', () => {
  document.getElementById('filterMenu')!.classList.remove('show');
  document.getElementById('fabMenu')!.classList.remove('show');
  document.getElementById('dlgMoreMenu')!.classList.remove('show');
  hideShotMenu();
});

// 全局键盘：Esc 按「最上层优先」处理：
// 上层模态/输入/确认/设置等 > 收藏夹抽屉 > 批量模式
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  hideShotMenu();
  if (closeTopSheet()) return;
  if (collectionDrawer.classList.contains('show')) { setCollectionDrawer(false); return; }
  if (App.ui.state.batch) {
    App.ui.state.batch = false;
    document.body.classList.remove('batch');
    document.getElementById('batchBtn')!.classList.remove('active');
    App.ui.state.selected.clear();
    renderAll();
  }
});

// ---------- 启动 ----------
bindDrag();
bindResize();
init();
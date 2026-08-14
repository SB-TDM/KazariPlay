// ============================================================
// app.js — 启动引导（最后加载）
// 职责：初始化入口 / 导航 / 搜索 / 筛选下拉 / FAB / 全局点击与键盘处理
// 依赖：state.js / core.js / ui.js / window.js / games.js / collections.js / batch.js / form.js
// 注意：本文件只负责「粘合」各模块与全局事件，不承载业务逻辑。
// ============================================================

// ---------- 初始化 ----------
function init() {
  const onReady = function () {
    window.bridgeReady = true;
    bridge.getConfig(function (s) {
      try {
        const cfg = JSON.parse(s || '{}');
        if (window.Settings) Settings.applyTheme(cfg.theme || 'light');
        applyCoverSize(cfg.cover_size || 'medium');
      } catch (e) { }
    });
    refreshAll(true);
    setInterval(() => refreshAll(false), 30000);   // 长轮询兜底（数据无变化时不重建）
  };
  if (window.pywebview && window.pywebview.api) { onReady(); }
  else { window.addEventListener('pywebviewready', onReady); }
}

// ---------- 筛选下拉 ----------
function bindFilterMenu() {
  const m = document.getElementById('filterMenu');
  m.querySelectorAll('.item').forEach(it => {
    it.onclick = () => {
      state.sort = it.dataset.sort;
      m.classList.remove('show');
      document.querySelectorAll('#filterMenu .item').forEach(x => x.classList.remove('on'));
      it.classList.add('on');
      renderAll();
    };
  });
}

// ---------- 事件绑定 ----------
// 搜索框
document.getElementById('searchInput').addEventListener('input', e => { state.kw = e.target.value.trim(); renderAll(); });
// 筛选按钮 + 下拉
document.getElementById('filterBtn').onclick = function (e) {
  e.stopPropagation();
  document.getElementById('filterMenu').classList.toggle('show');
};
bindFilterMenu();

// 侧边栏导航（全部作品 / 继续游玩 / 我的收藏；收藏夹入口在 collections.js）
document.querySelectorAll('#sidebar .side-item').forEach(it => {
  if (it.id === 'btnNewCollection' || it.id === 'btnSettings') return;
  it.onclick = () => {
    state.nav = it.dataset.nav;
    state.collectionId = null;
    document.querySelectorAll('#sidebar .side-item').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('#collectionTree .collection-item').forEach(x => x.classList.remove('active'));
    it.classList.add('active');
    renderAll();
  };
});

// 设置入口
document.getElementById('btnSettings').onclick = () => {
  if (window.Settings) Settings.open();
  else toast('设置模块加载失败');
};

// 空状态 / FAB
document.getElementById('btnScan').onclick = () => bridge.scanFolder();
document.getElementById('btnShowAll').onclick = () => clearCollectionFilter();
document.getElementById('fab').onclick = function (e) {
  e.stopPropagation();
  document.getElementById('fabMenu').classList.toggle('show');
};
document.getElementById('fabRefresh').onclick = () => { refreshAll(true); toast('已刷新'); };
document.getElementById('fabAdd').onclick = () => { document.getElementById('fabMenu').classList.remove('show'); openAdd(); };
document.getElementById('fabScan').onclick = () => { document.getElementById('fabMenu').classList.remove('show'); bridge.scanFolder(); };

// 全局点击：收起所有浮层
document.addEventListener('click', () => {
  document.getElementById('filterMenu').classList.remove('show');
  document.getElementById('fabMenu').classList.remove('show');
  document.getElementById('dlgMoreMenu').classList.remove('show');
  hideShotMenu();
});

// 全局键盘：Esc 退出批量模式或关闭最上层 Sheet
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    hideShotMenu();
    if (state.batch) {
      state.batch = false;
      document.body.classList.remove('batch');
      document.getElementById('batchBtn').classList.remove('active');
      state.selected.clear();
      renderAll();
    }
    else closeTopSheet();
  }
});

// ---------- 启动 ----------
bindDrag();
bindResize();
init();

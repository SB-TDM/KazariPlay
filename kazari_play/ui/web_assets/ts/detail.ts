// ============================================================
// detail.ts — 详情底部抽屉（Modal Bottom Sheet）：展示 + 评分 + 收藏 + 事件
// 依赖：state.ts / core.ts（loadCoverTo/toast/chipColor/esc）/ ui.ts（showSheet/closeSheet/
//       showConfirmDialog）/ games.ts（setActiveCard/markRunning）/
//       screenshots.ts（renderScreenshots）/ collections.ts（openCollectionManager）/
//       detail_translate.ts（renderTransRow）
// 定义：openDetail / refreshDetail / renderInfoBar / initRateEdit /
//       collectionPath / renderDetailTags / updateFavBtn + 详情事件绑定
// ============================================================

// 打开详情（卡片闭包数据可能是快照，随后异步重取最新数据刷新）
function openDetail(g: Game): void {
  App.data.currentGame = g;
  setActiveCard(g.id);
  loadCoverTo(g.id, document.getElementById('dlgCover'), 'bg');
  document.getElementById('dlgTitle')!.textContent = g.title;
  renderInfoBar();
  initRateEdit();
  renderDetailTags();
  document.getElementById('dlgDesc')!.textContent = g.description || '暂无简介';
  updateFavBtn();
  document.getElementById('dlgMoreMenu')!.classList.remove('show');
  showSheet('detailOverlay');
  bridge.getGame(String(g.id), function (s: unknown) {
    try {
      const fresh = JSON.parse(String(s || '{}')) as Game;
      if (!fresh || !fresh.id) return;
      App.data.currentGame = fresh;
      // 同步 GAMES 中对应对象，保持后续轮询一致
      const gi = App.data.games.findIndex(x => x.id === fresh.id);
      if (gi >= 0) App.data.games[gi] = fresh;
      refreshDetail();
    } catch (e) { }
  });
}

// 详情整体刷新（打开与轮询刷新共用）
function refreshDetail(): void {
  if (!App.data.currentGame) return;
  loadCoverTo(App.data.currentGame.id, document.getElementById('dlgCover'), 'bg');
  document.getElementById('dlgTitle')!.textContent = App.data.currentGame.title;
  document.getElementById('dlgDesc')!.textContent = App.data.currentGame.description || '暂无简介';
  renderDetailTags();
  renderInfoBar();
  updateFavBtn();
  renderScreenshots();
  const rate = document.querySelector('.rate-edit') as HTMLElement | null;
  if (rate) { rate.dataset.r = String(App.data.currentGame.rating); initRateEdit(); }
  markRunning();
  renderTransRow();
}

// 详情信息栏（开发商/引擎/发售日/游玩时长/上次游玩/评分）
// 注意：dev/engine/released 等为用户可编辑字段，必须 esc() 后再进 innerHTML，防 XSS/破版
function renderInfoBar(): void {
  const g = App.data.currentGame!;
  document.getElementById('dlgInfo')!.innerHTML = [
    ['开发商', g.dev ? esc(g.dev) : '未知'], ['引擎', g.engine ? esc(g.engine) : '未知'],
    ['发售日', g.released ? esc(g.released) : '未知'],
    ['游玩时长', g.play_time_text ? esc(g.play_time_text) : '未游玩'],
    ['上次游玩', g.last_text ? esc(g.last_text) : '从未'],
    ['评分', '<span class="rate-edit" data-r="' + esc(String(g.rating)) + '"></span>'],
  ].map(x => `<div class="info-item"><b>${x[0]}</b>${x[1]}</div>`).join('');
}

// 详情评分：点击星级直接修改（调用后端 setRating）
function initRateEdit(): void {
  const el = document.querySelector('.rate-edit') as HTMLElement | null;
  if (!el) return;
  const r = +el.dataset.r! || 0;
  el.innerHTML = '';
  for (let n = 1; n <= 5; n++) {
    const s = document.createElement('span');
    s.textContent = n <= r ? '★' : '☆';
    s.style.cssText = 'cursor:pointer;color:var(--star);font-size:17px;letter-spacing:2px;';
    s.onmouseenter = () => { s.style.color = 'var(--pink-deep)'; };
    s.onmouseleave = () => { s.style.color = 'var(--star)'; };
    s.onclick = () => {
      if (!App.data.currentGame) return;
      bridge.setRating(String(App.data.currentGame.id), n);
      App.data.currentGame.rating = n; el.dataset.r = String(n); initRateEdit();
    };
    el.appendChild(s);
  }
}

// 收藏夹完整路径：分类显示「分组 / 分类」，分组仅显示分组名
function collectionPath(colId: number): string {
  for (const g of App.ui.state.collectionTree) {
    if (g.id === colId) return g.name;
    const c = (g.children || []).find(x => x.id === colId);
    if (c) return g.name + ' / ' + c.name;
  }
  return '';
}

// 详情中的收藏夹 chips + 「管理收藏夹」入口
function renderDetailTags(): void {
  const t = document.getElementById('dlgCollections')!;
  t.innerHTML = '';
  (App.data.currentGame!.collections || []).forEach(col => {
    const c = document.createElement('span');
    c.className = 'chip collection-chip';
    c.style.background = col.color || chipColor(col.name);
    c.style.color = '#4a4358';
    c.title = collectionPath(col.id);
    c.textContent = (col.icon || '') + ' ' + collectionPath(col.id);
    t.appendChild(c);
  });
  const m = document.createElement('span');
  m.className = 'chip manage';
  m.textContent = '管理收藏夹';
  m.onclick = () => { closeSheet('detailOverlay', true); openCollectionManager(); };
  t.appendChild(m);
}

// 收藏按钮状态
function updateFavBtn(): void {
  const b = document.getElementById('dlgFav')!;
  b.textContent = App.data.currentGame!.fav ? '★ 已收藏' : '☆ 收藏';
  b.classList.toggle('on', App.data.currentGame!.fav);
}

// ---------- 详情事件绑定 ----------
document.getElementById('dlgClose')!.onclick = () => closeSheet('detailOverlay');
document.getElementById('dlgStart')!.onclick = () => { if (App.data.currentGame) launchGame(App.data.currentGame.id); };
document.getElementById('dlgEdit')!.onclick = () => { if (App.data.currentGame) { closeSheet('detailOverlay', true); openEdit(App.data.currentGame); } };
document.getElementById('dlgFav')!.onclick = () => {
  if (!App.data.currentGame) return;
  App.data.currentGame.fav = !App.data.currentGame.fav;
  bridge.toggleFav(String(App.data.currentGame.id));
  updateFavBtn();
};
document.getElementById('dlgMore')!.onclick = function (e: MouseEvent) {
  e.stopPropagation();
  document.getElementById('dlgMoreMenu')!.classList.toggle('show');
};
document.querySelectorAll<HTMLElement>('#dlgMoreMenu .item').forEach(it => {
  it.onclick = () => {
    document.getElementById('dlgMoreMenu')!.classList.remove('show');
    if (!App.data.currentGame) return;
    const g = App.data.currentGame;
    if (it.dataset.act === 'vndb') { bridge.matchVndb(String(g.id)); toast('开始匹配：' + g.title); }
    else if (it.dataset.act === 'open') bridge.openFolder(String(g.id));
    else showConfirmDialog({
      title: '从库中移除',
      message: `从库中移除「${g.title}」？\n（不会删除实际文件）`,
      danger: true, okText: '移除', cb: () => bridge.deleteGame(String(g.id))
    });
  };
});
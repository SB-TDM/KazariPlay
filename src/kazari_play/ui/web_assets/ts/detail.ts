// ============================================================
// detail.ts — 详情底部抽屉（Modal Bottom Sheet）：展示 + 评分 + 收藏 + 事件
// 依赖：state.ts / icons.ts / core.ts（loadCoverTo/toast/chipColor/esc）/ ui.ts（showSheet/closeSheet/
//       showConfirmDialog）/ games.ts（setActiveCard/markRunning）/
//       screenshots.ts（renderScreenshots）/ collections.ts（openCollectionManager）/
// 定义：openDetail / refreshDetail / renderInfoBar / initRateEdit /
//       collectionPath / renderDetailTags / updateFavBtn + 详情事件绑定
// ============================================================

// 详情请求代际：连续打开不同游戏或已关闭时，丢弃迟到响应（参考 screenshots.ts 的 request+gid）
let detailRequest = 0;
let unmatchedInfoRequest = 0;
let detailRateSlider: StarSlider | null = null;

// 打开详情（卡片闭包数据可能是快照，随后异步重取最新数据刷新）
function openDetail(g: Game): void {
  App.data.currentGame = g;
  setActiveCard(g.id);
  loadCoverTo(g.id, document.getElementById('dlgCover'), 'bg');
  document.getElementById('dlgTitle')!.textContent = g.title;
  renderInfoBar();
  initRateEdit();
  renderUnmatchedState();
  renderUnmatchedCandidates([]);
  loadUnmatchedInfo(g);
  renderDetailTags();
  document.getElementById('dlgDesc')!.textContent = g.description || '暂无简介';
  updateFavBtn();
  document.getElementById('dlgMoreMenu')!.classList.remove('show');
  renderScreenshots();
  const detailBody = document.querySelector('.detail-body') as HTMLElement | null;
  if (detailBody) detailBody.scrollTop = 0;
  showSheet('detailOverlay');
  const gid = String(g.id);
  const request = ++detailRequest;
  bridge.getGame(gid, function (s: unknown) {
    // 期间又打开/关闭了详情，或目标已切换 → 丢弃本次迟到响应
    if (request !== detailRequest
      || String(App.data.currentGame?.id) !== gid
      || !document.getElementById('detailOverlay')!.classList.contains('show')) return;
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
  updateInfoValues();
  renderUnmatchedState();
  if (App.data.currentGame) loadUnmatchedInfo(App.data.currentGame);
  updateFavBtn();
  renderScreenshots();
  if (detailRateSlider) detailRateSlider.set(+App.data.currentGame.rating || 0);
  else initRateEdit();
  markRunning();
}

function updateInfoValues(): void {
  const g = App.data.currentGame!;
  const info = document.getElementById('dlgInfo')!;
  const rows: [string, string][] = [
    ['开发商', g.dev ? esc(g.dev) : '未知'], ['引擎', g.engine ? esc(g.engine) : '未知'],
    ['发售日', g.released ? esc(g.released) : '未知'],
    ['游玩时长', g.play_time_text ? esc(g.play_time_text) : '未游玩'],
    ['上次游玩', g.last_text ? esc(g.last_text) : '从未'],
  ];
  const items = info.querySelectorAll('.info-item');
  if (items.length !== rows.length + 1) { renderInfoBar(); return; }
  rows.forEach((row, i) => {
    items[i].innerHTML = `<b>${row[0]}</b>${row[1]}`;
  });
  const rate = info.querySelector('.rate-edit') as HTMLElement | null;
  if (rate) rate.dataset.r = String(g.rating || 0);
}

// 详情信息栏（开发商/引擎/发售日/游玩时长/上次游玩/评分）
// 注意：dev/engine/released 等为用户可编辑字段，必须 esc() 后再进 innerHTML，防 XSS/破版
function renderInfoBar(): void {
  detailRateSlider = null;
  const g = App.data.currentGame!;
  document.getElementById('dlgInfo')!.innerHTML = [
    ['开发商', g.dev ? esc(g.dev) : '未知'], ['引擎', g.engine ? esc(g.engine) : '未知'],
    ['发售日', g.released ? esc(g.released) : '未知'],
    ['游玩时长', g.play_time_text ? esc(g.play_time_text) : '未游玩'],
    ['上次游玩', g.last_text ? esc(g.last_text) : '从未'],
    ['评分', '<span class="rate-edit" data-r="' + esc(String(g.rating)) + '"></span>'],
  ].map(x => `<div class="info-item"><b>${x[0]}</b>${x[1]}</div>`).join('');
}

// 详情评分：星级滑条拖动/点击/键盘直接修改（0.5 步进，0 为未评分；调用后端 setRating）
function initRateEdit(): void {
  const el = document.querySelector('.rate-edit') as HTMLElement | null;
  if (!el) return;
  detailRateSlider = makeStarSlider(el, +el.dataset.r! || 0, (v: number) => {
    if (!App.data.currentGame) return;
    const g = App.data.currentGame;
    const prev = +g.rating || 0;
    g.rating = v;
    bridge.setRating(String(g.id), v, function (ok: unknown, failed?: boolean) {
      if (failed || ok !== true) {
        g.rating = prev;
        const cur = document.querySelector('.rate-edit') as HTMLElement | null;
        if (cur) { cur.dataset.r = String(prev); initRateEdit(); }
        toast('评分保存失败，请重试');
      }
    });
  });
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

function renderUnmatchedState(): void {
  const box = document.getElementById('dlgUnmatched');
  const reasonEl = document.getElementById('dlgUnmatchedReason');
  const mergeBtn = document.getElementById('dlgUnmatchedMerge') as HTMLElement | null;
  if (!box || !reasonEl) return;
  const game = App.data.currentGame;
  const reason = String(game?.unmatched_reason || '').trim();
  box.style.display = reason ? 'flex' : 'none';
  reasonEl.textContent = reason;
  if (mergeBtn) mergeBtn.style.display = game?.unmatched_code === 'duplicate_version' ? '' : 'none';
}

function renderUnmatchedCandidates(cands: MetadataCandidate[]): void {
  const box = document.getElementById('dlgUnmatchedCands');
  if (!box) return;
  box.innerHTML = '';
  if (!cands.length) {
    box.classList.remove('show');
    return;
  }
  box.classList.add('show');
  cands.forEach(c => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'unmatched-cand';
    const title = c.title || c.alt_title || '未命名候选';
    b.innerHTML = `<span class="unmatched-cand-title" title="${esc(title)}">${esc(title)}</span>
      <span class="unmatched-cand-sub">${esc(c.released || '')}${c.developer ? ' · ' + esc(c.developer) : ''}</span>
      <span class="unmatched-cand-src">${esc(c.source_name || c.source || '')}</span>`;
    b.onclick = () => {
      const g = App.data.currentGame;
      if (!g) return;
      App.data.editingId = String(g.id);
      openMetaApply(c);
    };
    box.appendChild(b);
  });
}

function loadUnmatchedInfo(game: Game): void {
  const request = ++unmatchedInfoRequest;
  if (!game.unmatched_reason) {
    renderUnmatchedCandidates([]);
    return;
  }
  bridge.getUnmatchedInfo(String(game.id), function (s: unknown) {
    if (request !== unmatchedInfoRequest
      || String(App.data.currentGame?.id) !== String(game.id)) return;
    let info: { reason?: string; code?: string; candidates?: MetadataCandidate[] } = {};
    try { info = JSON.parse(String(s || '{}')); } catch (e) { }
    if (App.data.currentGame) {
      App.data.currentGame.unmatched_reason = info.reason || App.data.currentGame.unmatched_reason || '';
      App.data.currentGame.unmatched_code = info.code || App.data.currentGame.unmatched_code || '';
    }
    renderUnmatchedState();
    renderUnmatchedCandidates(Array.isArray(info.candidates) ? info.candidates : []);
  });
}

// 收藏按钮状态
function updateFavBtn(): void {
  const b = document.getElementById('dlgFav')!;
  b.innerHTML = App.data.currentGame!.fav ? ICON.starFill + ' 已收藏' : ICON.star + ' 收藏';
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
document.getElementById('dlgUnmatchedEdit')!.onclick = () => {
  const g = App.data.currentGame;
  if (!g) return;
  closeSheet('detailOverlay', true);
  openEdit(g);
  setTimeout(() => (document.getElementById('fSearchKw') as HTMLInputElement | null)?.focus(), 50);
};
document.getElementById('dlgUnmatchedMerge')!.onclick = () => {
  const g = App.data.currentGame;
  if (!g) return;
  const targets = (App.data.games || []).filter(x => String(x.id) !== String(g.id));
  if (!targets.length) { toast('没有可合并的目标卡片'); return; }
  const items: PickerItem[] = targets.map((x, i) => ({
    label: `${x.title}${x.dev ? ' · ' + x.dev : ''}`,
    value: i,
  }));
  openPicker('选择要合并到的卡片', items, (index) => {
    const target = targets[index];
    if (!target) return;
    showConfirmDialog({
      title: '合并本地卡片',
      message: `将「${g.title}」合并到「${target.title}」？\n收藏夹、标签、来源记录、游玩时长和截图会合并，源卡片会被删除。此操作不可撤销。`,
      danger: true,
      okText: '合并并删除',
      cb: () => {
        bridge.mergeGames(String(g.id), String(target.id), function (s: unknown, failed?: boolean) {
          if (failed) { toast('合并失败'); return; }
          let r: { ok?: boolean; msg?: string } = {};
          try { r = JSON.parse(String(s || '{}')) as { ok?: boolean; msg?: string }; } catch (e) { }
          toast(r.msg || (r.ok ? '合并完成' : '合并失败'));
          if (r.ok) { closeSheet('detailOverlay', true); refreshAll(true); }
        });
      },
    });
  });
};
document.getElementById('dlgUnmatchedDismiss')!.onclick = () => {
  const g = App.data.currentGame;
  if (!g) return;
  bridge.dismissUnmatched(String(g.id), function (s: unknown, failed?: boolean) {
    if (failed) { toast('移出失败，请重试'); return; }
    let r: { ok?: boolean; msg?: string } = {};
    try { r = JSON.parse(String(s || '{}')) as { ok?: boolean; msg?: string }; } catch (e) { }
    if (r.ok !== true) { toast(r.msg || '移出失败'); return; }
    g.unmatched_reason = '';
    renderUnmatchedState();
    applyGamesDelta([String(g.id)]);
    toast(r.msg || '已移出未匹配区');
  });
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
    if (it.dataset.act === 'vndb') {
      bridge.matchVndb(String(g.id), function (s: unknown) {
        let result: { ok?: boolean; msg?: string } = {};
        try { result = JSON.parse(String(s || '{}')); } catch (e) { }
        toast(result.ok ? '开始匹配：' + g.title : (result.msg || '匹配未启动'));
      });
    }
    else if (it.dataset.act === 'open') bridge.openFolder(String(g.id));
    else showConfirmDialog({
      title: '从库中移除',
      message: `从库中移除「${g.title}」？\n（不会删除实际文件）`,
      danger: true, okText: '移除', cb: () => bridge.deleteGame(String(g.id))
    });
  };
});

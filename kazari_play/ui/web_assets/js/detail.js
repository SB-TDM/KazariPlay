// ============================================================
// detail.js — 详情底部抽屉（Modal Bottom Sheet）
// 依赖：state.js / core.js（loadCoverTo/toast）/ ui.js（showSheet/closeSheet/showConfirmDialog）/
//       games.js（setActiveCard/markRunning）/ screenshots.js（renderScreenshots）
// 定义：openDetail / refreshDetail / renderInfoBar / initRateEdit /
//       renderDetailTags / collectionPath / updateFavBtn + 详情事件绑定
// ============================================================

// 打开详情（卡片闭包数据可能是快照，随后异步重取最新数据刷新）
function openDetail(g) {
  currentGame = g;
  setActiveCard(g.id);
  loadCoverTo(g.id, document.getElementById('dlgCover'), 'bg');
  document.getElementById('dlgTitle').textContent = g.title;
  renderInfoBar();
  initRateEdit();
  renderDetailTags();
  document.getElementById('dlgDesc').textContent = g.description || '暂无简介';
  updateFavBtn();
  document.getElementById('dlgMoreMenu').classList.remove('show');
  showSheet('detailOverlay');
  bridge.getGame(g.id, function (s) {
    try {
      const fresh = JSON.parse(s || '{}');
      if (!fresh || !fresh.id) return;
      currentGame = fresh;
      // 同步 GAMES 中对应对象，保持后续轮询一致
      const gi = GAMES.findIndex(x => x.id === fresh.id);
      if (gi >= 0) GAMES[gi] = fresh;
      refreshDetail();
    } catch (e) { }
  });
}

// 详情整体刷新（打开与轮询刷新共用）
function refreshDetail() {
  loadCoverTo(currentGame.id, document.getElementById('dlgCover'), 'bg');
  document.getElementById('dlgTitle').textContent = currentGame.title;
  document.getElementById('dlgDesc').textContent = currentGame.description || '暂无简介';
  renderDetailTags();
  renderInfoBar();
  updateFavBtn();
  renderScreenshots();
  const rate = document.querySelector('.rate-edit');
  if (rate) { rate.dataset.r = currentGame.rating; initRateEdit(); }
  markRunning();
  renderTransRow();
}

// Hook 实时翻译开关行（V1.1）
function renderTransRow() {
  const row = document.getElementById('dlgTransRow');
  if (!row) return;
  const g = currentGame;
  row.style.display = 'block';
  const sw = document.getElementById('dlgTrans');
  sw.checked = !!g.translate_enabled;
  const badge = document.getElementById('dlgHookBadge');
  const rehook = document.getElementById('dlgRehook');
  if (g.has_hook_code) {
    badge.textContent = '已配置 Hook 点';
    badge.classList.add('on');
    rehook.textContent = '重新选择';
    rehook.onclick = () => {
      bridge.clearHookCode(g.id);
      g.has_hook_code = false;
      renderTransRow();
      toast('已清除 Hook 点，可重新选择');
    };
  } else {
    badge.textContent = '未配置 Hook 点';
    badge.classList.remove('on');
    rehook.textContent = '选择 Hook';
    rehook.onclick = () => {
      bridge.getRunning(function (rid) {
        if (rid && rid === g.id && window.HookSelect) {
          HookSelect.open(g.id);
        } else {
          toast('请先启动游戏，再选择 Hook 点');
        }
      });
    };
  }
  sw.onchange = () => {
    bridge.toggleGameTranslation(g.id, sw.checked);
    g.translate_enabled = sw.checked;
    toast(sw.checked ? '已启用实时翻译' : '已关闭实时翻译');
  };
  // 文本清洗配置（每游戏）
  const cleanBtn = document.getElementById('dlgCleanCfg');
  const cleanPanel = document.getElementById('dlgCleanPanel');
  if (cleanBtn && cleanPanel) {
    cleanBtn.onclick = () => {
      const show = cleanPanel.style.display === 'none';
      cleanPanel.style.display = show ? 'block' : 'none';
      if (show) loadCleanCfg(g.id);
    };
  }
  const cleanSave = document.getElementById('dlgCleanSave');
  if (cleanSave) cleanSave.onclick = saveCleanCfg;
  const cleanReset = document.getElementById('dlgCleanReset');
  if (cleanReset) cleanReset.onclick = resetCleanCfg;
}

// 清洗配置：加载某游戏当前过滤器状态并渲染勾选
function loadCleanCfg(gameId) {
  const box = document.getElementById('dlgCleanFilters');
  const defs = window.CLEAN_FILTER_DEFS || [];
  if (!box || !defs.length || !bridge) return;
  bridge.getCleanFilterConfig(gameId, function (s) {
    let data = {};
    try { data = JSON.parse(s || '{}'); } catch (e) { }
    let list = data.filters || [];
    const srcEl = document.getElementById('dlgCleanSrc');
    if (srcEl) {
      srcEl.textContent = data.source === 'runtime' ? '（当前运行中生效配置）'
        : data.source === 'override' ? '（自定义配置）'
        : '（引擎默认策略，保存后转为自定义）';
    }
    const byId = {};
    list.forEach((f) => { if (f && f.id) byId[f.id] = f; });
    const merged = defs.map((d) => {
      const cur = byId[d.id] || {};
      return Object.assign({}, d, {
        enabled: cur.enabled === undefined ? false : !!cur.enabled,
        order: cur.order === undefined ? 999 : cur.order,
      });
    });
    merged.sort((a, b) => (a.enabled === b.enabled ? a.order - b.order : (b.enabled ? 1 : 0) - (a.enabled ? 1 : 0)));
    box.innerHTML = '';
    merged.forEach((f) => {
      const row = document.createElement('label');
      row.className = 'clean-fil';
      row.innerHTML = `
        <input type="checkbox" class="clean-check" data-id="${esc(f.id)}" ${f.enabled ? 'checked' : ''}>
        <span class="clean-box"></span>
        <span class="clean-name">${esc(f.name)}${f.agg ? ' <em class="clean-agg">激进</em>' : ''}</span>
        <span class="clean-desc">${esc(f.desc || '')}</span>`;
      // 勾选即保存并实时下发（游戏运行中立即生效）
      row.querySelector('.clean-check').addEventListener('change', () => saveCleanCfg(true));
      box.appendChild(row);
    });
  });
}

function collectCleanCfg() {
  const defs = window.CLEAN_FILTER_DEFS || [];
  const checks = {};
  [...document.querySelectorAll('#dlgCleanFilters .clean-check')]
    .forEach((c) => { checks[c.dataset.id] = c.checked; });
  return defs.map((d, i) => ({ id: d.id, enabled: !!checks[d.id], order: i }));
}

function saveCleanCfg(silent) {
  if (!currentGame || !bridge) return;
  bridge.setCleanFilterConfig(currentGame.id, JSON.stringify(collectCleanCfg()));
  if (!silent) {
    const res = document.getElementById('dlgCleanRes');
    if (res) { res.textContent = '已保存'; setTimeout(() => { res.textContent = ''; }, 2000); }
  }
}

function resetCleanCfg() {
  if (!currentGame || !bridge) return;
  bridge.setCleanFilterConfig(currentGame.id, '[]');
  const res = document.getElementById('dlgCleanRes');
  if (res) { res.textContent = '已恢复引擎默认'; setTimeout(() => { res.textContent = ''; }, 2000); }
  loadCleanCfg(currentGame.id);
}

// 详情信息栏（开发商/引擎/发售日/游玩时长/上次游玩/评分）
function renderInfoBar() {
  const g = currentGame;
  document.getElementById('dlgInfo').innerHTML = [
    ['开发商', g.dev || '未知'], ['引擎', g.engine || '未知'], ['发售日', g.released || '未知'],
    ['游玩时长', g.play_time_text || '未游玩'], ['上次游玩', g.last_text || '从未'],
    ['评分', '<span class="rate-edit" data-r="' + g.rating + '"></span>'],
  ].map(x => `<div class="info-item"><b>${x[0]}</b>${x[1]}</div>`).join('');
}

// 详情评分：点击星级直接修改（调用后端 setRating）
function initRateEdit() {
  const el = document.querySelector('.rate-edit');
  if (!el) return;
  const r = +el.dataset.r || 0;
  el.innerHTML = '';
  for (let n = 1; n <= 5; n++) {
    const s = document.createElement('span');
    s.textContent = n <= r ? '★' : '☆';
    s.style.cssText = 'cursor:pointer;color:var(--star);font-size:17px;letter-spacing:2px;';
    s.onmouseenter = () => { s.style.color = 'var(--pink-deep)'; };
    s.onmouseleave = () => { s.style.color = 'var(--star)'; };
    s.onclick = () => {
      if (!currentGame) return;
      bridge.setRating(currentGame.id, n);
      currentGame.rating = n; el.dataset.r = n; initRateEdit();
    };
    el.appendChild(s);
  }
}

// 收藏夹完整路径：分类显示「分组 / 分类」，分组仅显示分组名
function collectionPath(colId) {
  for (const g of state.collectionTree) {
    if (g.id === colId) return g.name;
    const c = (g.children || []).find(x => x.id === colId);
    if (c) return g.name + ' / ' + c.name;
  }
  return '';
}

// 详情中的收藏夹 chips + 「管理收藏夹」入口
function renderDetailTags() {
  const t = document.getElementById('dlgCollections');
  t.innerHTML = '';
  (currentGame.collections || []).forEach(col => {
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
function updateFavBtn() {
  const b = document.getElementById('dlgFav');
  b.textContent = currentGame.fav ? '★ 已收藏' : '☆ 收藏';
  b.classList.toggle('on', currentGame.fav);
}

// ---------- 详情事件绑定 ----------
document.getElementById('dlgClose').onclick = () => closeSheet('detailOverlay');
document.getElementById('dlgStart').onclick = () => { if (currentGame) launchGame(currentGame.id); };
document.getElementById('dlgEdit').onclick = () => { if (currentGame) { closeSheet('detailOverlay', true); openEdit(currentGame); } };
document.getElementById('dlgFav').onclick = () => {
  if (!currentGame) return;
  currentGame.fav = !currentGame.fav;
  bridge.toggleFav(currentGame.id);
  updateFavBtn();
};
document.getElementById('dlgMore').onclick = function (e) {
  e.stopPropagation();
  document.getElementById('dlgMoreMenu').classList.toggle('show');
};
document.querySelectorAll('#dlgMoreMenu .item').forEach(it => {
  it.onclick = () => {
    document.getElementById('dlgMoreMenu').classList.remove('show');
    if (!currentGame) return;
    if (it.dataset.act === 'vndb') { bridge.matchVndb(currentGame.id); toast('开始匹配：' + currentGame.title); }
    else if (it.dataset.act === 'open') bridge.openFolder(currentGame.id);
    else showConfirmDialog({
      title: '从库中移除',
      message: `从库中移除「${currentGame.title}」？\n（不会删除实际文件）`,
      danger: true, okText: '移除', cb: () => bridge.deleteGame(currentGame.id)
    });
  };
});

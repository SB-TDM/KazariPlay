// ============================================================
// batch.js — 批量选择模式（勾选 / 全选 / 批量收藏夹 / 批量 VNDB / 批量删除）
// 依赖：state.js / games.js（filterGames/renderAll）/ ui.js（openPicker/showConfirmDialog）
// 定义：updateBatchBar / collectionPickerItems / batchPickCollection + 批量事件绑定
// ============================================================

// 批量工具栏状态（renderAll 时调用）
function updateBatchBar() {
  const n = state.selected.size;
  document.getElementById('batchCount').textContent = `已选择 ${n} 个`;
  document.querySelectorAll('#batchBar button:not(#btnSelAll)').forEach(b => b.disabled = n === 0);
  const all = n > 0 && n === filterGames(GAMES).length;
  document.getElementById('btnSelAll').textContent = all ? '取消全选' : '全选';
}

// 批量选择收藏夹（仅子分类可选，分组不直接接受批量归属）
function collectionPickerItems() {
  const items = [];
  state.collectionTree.forEach(g => {
    (g.children || []).forEach(c => {
      items.push({ label: (g.name + ' / ' + c.name), value: c.id });
    });
  });
  return items;
}

// 批量添加 / 移除 / 移动收藏夹
function batchPickCollection(mode) {
  const ids = [...state.selected];
  const items = collectionPickerItems();
  openPicker(mode === 'add' ? '批量添加收藏夹' : (mode === 'move' ? '移动到收藏夹' : '批量移除收藏夹'),
    items, function (cid) {
      if (mode === 'add') { bridge.addGamesToCollection(JSON.stringify(ids), cid); toast('已添加到收藏夹'); }
      else if (mode === 'remove') { bridge.removeGamesFromCollection(JSON.stringify(ids), cid); toast('已移出收藏夹'); }
      else { bridge.batchMoveToCollection(JSON.stringify(ids), cid); toast('已移动'); }
      state.selected.clear();
    });
}

// ---------- 批量事件绑定 ----------
document.getElementById('batchBtn').onclick = function () {
  state.batch = !state.batch;
  document.body.classList.toggle('batch', state.batch);
  this.classList.toggle('active', state.batch);
  if (!state.batch) state.selected.clear();
  renderAll();
};
document.getElementById('btnSelAll').onclick = () => {
  const ids = filterGames(GAMES).map(g => g.id);
  if (state.selected.size === ids.length) { state.selected.clear(); }
  else { state.selected = new Set(ids); }
  renderAll();
};
document.getElementById('btnBAdd').onclick = () => batchPickCollection('add');
document.getElementById('btnBRem').onclick = () => batchPickCollection('remove');
document.getElementById('btnBMove').onclick = () => batchPickCollection('move');
document.getElementById('btnBVndb').onclick = () => {
  if (state.selected.size === 0) return;
  bridge.matchVndbBatch(JSON.stringify([...state.selected]));
  state.selected.clear();
  toast('开始批量匹配 VNDB');
};
document.getElementById('btnBDel').onclick = () => {
  showConfirmDialog({
    title: '批量移除',
    message: `从库中移除选中的 ${state.selected.size} 个游戏？\n（不会删除实际文件）`,
    danger: true, okText: '移除',
    cb: () => { bridge.batchDelete(JSON.stringify([...state.selected])); state.selected.clear(); }
  });
};
document.getElementById('pickerClose').onclick = () => closeSheet('pickerOverlay');

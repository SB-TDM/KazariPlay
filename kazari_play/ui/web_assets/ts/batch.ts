// ============================================================
// batch.ts — 批量选择模式（勾选 / 全选 / 批量收藏夹 / 批量 VNDB / 批量删除）
// 依赖：state.ts / games.ts（filterGames/renderAll）/ ui.ts（openPicker/showConfirmDialog）
// 定义：updateBatchBar / collectionPickerItems / batchPickCollection + 批量事件绑定
// ============================================================

/** 批量进度数据（后端 getBatchProgress 返回） */
interface BatchProgress {
  running?: boolean;
  done?: number;
  total?: number;
}

// 批量工具栏状态（renderAll 时调用）
function updateBatchBar(): void {
  const n = App.ui.state.selected.size;
  document.getElementById('batchCount')!.textContent = `已选择 ${n} 个`;
  document.querySelectorAll<HTMLButtonElement>('#batchBar button:not(#btnSelAll)').forEach(b => b.disabled = n === 0);
  const all = n > 0 && n === filterGames(App.data.games).length;
  document.getElementById('btnSelAll')!.textContent = all ? '取消全选' : '全选';
}

// 批量选择收藏夹（仅子分类可选，分组不直接接受批量归属）
function collectionPickerItems(): PickerItem[] {
  const items: PickerItem[] = [];
  App.ui.state.collectionTree.forEach(g => {
    (g.children || []).forEach(c => {
      items.push({ label: (g.name + ' / ' + c.name), value: c.id });
    });
  });
  return items;
}

// 批量添加 / 移除 / 移动收藏夹
function batchPickCollection(mode: 'add' | 'remove' | 'move'): void {
  const ids = [...App.ui.state.selected];
  const items = collectionPickerItems();
  openPicker(mode === 'add' ? '批量添加收藏夹' : (mode === 'move' ? '移动到收藏夹' : '批量移除收藏夹'),
    items, function (cid) {
      if (mode === 'add') { bridge.addGamesToCollection(JSON.stringify(ids), cid); toast('已添加到收藏夹'); }
      else if (mode === 'remove') { bridge.removeGamesFromCollection(JSON.stringify(ids), cid); toast('已移出收藏夹'); }
      else { bridge.batchMoveToCollection(JSON.stringify(ids), cid); toast('已移动'); }
      App.ui.state.selected.clear();
    });
}

// ---------- 批量进度条（VNDB 批量匹配等耗时操作反馈） ----------
let bpTimer: ReturnType<typeof setInterval> | null = null;

function showBatchProgress(title: string): void {
  const box = document.getElementById('batchProgress');
  if (!box) return;
  document.getElementById('bpTitle')!.textContent = title || '批量处理中…';
  document.getElementById('bpSub')!.textContent = '正在准备…';
  box.classList.add('show');
}

function hideBatchProgress(): void {
  if (bpTimer) { clearInterval(bpTimer); bpTimer = null; }
  const box = document.getElementById('batchProgress');
  if (box) box.classList.remove('show');
}

// 轮询后端批量任务进度；完成（running=false）时收起并提示
function trackBatchProgress(title: string): void {
  hideBatchProgress();
  showBatchProgress(title);
  const box = document.getElementById('batchProgress');
  if (!box) return;
  const pctEl = document.getElementById('bpPct');
  const fillEl = document.getElementById('bpFill');
  const subEl = document.getElementById('bpSub');
  bpTimer = setInterval(function () {
    bridge.getBatchProgress(function (s: unknown) {
      let p: BatchProgress = {};
      try { p = JSON.parse(String(s || '{}')) as BatchProgress; } catch (e) { }
      if (!p || !p.running) {
        hideBatchProgress();
        return;
      }
      const done = p.done || 0, total = p.total || 0;
      const pct = total > 0 ? Math.round(done * 100 / total) : 0;
      if (pctEl) pctEl.textContent = pct + '%';
      if (fillEl) (fillEl as HTMLElement).style.width = pct + '%';
      if (subEl) subEl.textContent = `已完成 ${done} / ${total}`;
    });
  }, 600);
}

// ---------- 批量事件绑定 ----------
const batchBtnEl = document.getElementById('batchBtn') as HTMLButtonElement;
batchBtnEl.onclick = () => {
  App.ui.state.batch = !App.ui.state.batch;
  document.body.classList.toggle('batch', App.ui.state.batch);
  batchBtnEl.classList.toggle('active', App.ui.state.batch);
  if (!App.ui.state.batch) App.ui.state.selected.clear();
  // 批量模式仅切换勾选框显隐（body.batch 类控制）+ 刷新批量工具栏，
  // 不需要全量重建网格
  updateBatchBar();
  // 注意：原 JS 用 c.dataset.id（string）与 selected（number Set）比较，恒 false；
  // 用 cast 保持原运行时行为（不隐式转换），与原 JS 语义等价
  document.querySelectorAll<HTMLElement>('.card').forEach(c =>
    c.classList.toggle('selected', App.ui.state.selected.has(c.dataset.id as unknown as number)));
};
document.getElementById('btnSelAll')!.onclick = () => {
  const ids = filterGames(App.data.games).map(g => g.id);
  if (App.ui.state.selected.size === ids.length) { App.ui.state.selected.clear(); }
  else { App.ui.state.selected = new Set(ids); }
  // 局部同步全部卡片选中态，避免全量重建网格
  document.querySelectorAll<HTMLElement>('.card').forEach(c =>
    c.classList.toggle('selected', App.ui.state.selected.has(c.dataset.id as unknown as number)));
  updateBatchBar();
};
document.getElementById('btnBAdd')!.onclick = () => batchPickCollection('add');
document.getElementById('btnBRem')!.onclick = () => batchPickCollection('remove');
document.getElementById('btnBMove')!.onclick = () => batchPickCollection('move');
document.getElementById('btnBVndb')!.onclick = () => {
  if (App.ui.state.selected.size === 0) return;
  bridge.matchVndbBatch(JSON.stringify([...App.ui.state.selected]));
  App.ui.state.selected.clear();
  trackBatchProgress('VNDB 批量匹配中');
};
document.getElementById('btnBDel')!.onclick = () => {
  showConfirmDialog({
    title: '批量移除',
    message: `从库中移除选中的 ${App.ui.state.selected.size} 个游戏？\n（不会删除实际文件）`,
    danger: true, okText: '移除',
    cb: () => { bridge.batchDelete(JSON.stringify([...App.ui.state.selected])); App.ui.state.selected.clear(); }
  });
};
document.getElementById('pickerClose')!.onclick = () => closeSheet('pickerOverlay');
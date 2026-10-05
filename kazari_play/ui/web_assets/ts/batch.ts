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
  // 取消扫描进度的延迟隐藏，避免刚显示就被扫描结束的定时器收起
  if (scanHideTimer) { clearTimeout(scanHideTimer); scanHideTimer = null; }
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
  const cancelBtn = document.getElementById('bpCancel') as HTMLElement | null;
  cancelMode = 'match';
  if (cancelBtn) { cancelBtn.style.display = ''; cancelBtn.textContent = '取消匹配'; }
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

// ---------- 扫描进度（后端 UISync scan_progress 域推送）----------
interface ScanProgress {
  running?: boolean;
  dirs?: number;
  games?: number;
  folder?: string;
  index?: number;
  total?: number;
}

let scanHideTimer: ReturnType<typeof setTimeout> | null = null;
// 取消按钮当前作用对象（扫描 / VNDB 匹配）
let cancelMode: 'scan' | 'match' = 'scan';

// 扫描进度：按「已发现游戏数」估算百分比（S 型，越接近完成越慢，结束才 100%）
function updateScanProgress(p: ScanProgress): void {
  const box = document.getElementById('batchProgress');
  if (!box) return;
  const cancelBtn = document.getElementById('bpCancel') as HTMLElement | null;
  if (!p || !p.running) {
    // 扫描结束：延迟收起（让用户看到最终进度），隐藏取消按钮
    if (scanHideTimer) clearTimeout(scanHideTimer);
    scanHideTimer = setTimeout(() => {
      box.classList.remove('show');
      if (cancelBtn) cancelBtn.style.display = 'none';
    }, 800);
    return;
  }
  const games = p.games || 0;
  const pct = Math.min(95, Math.round(95 * games / (games + 20)));
  document.getElementById('bpTitle')!.textContent = '扫描游戏文件夹…';
  document.getElementById('bpPct')!.textContent = pct + '%';
  (document.getElementById('bpFill') as HTMLElement).style.width = pct + '%';
  const folderIdx = (p.index && p.total) ? `（目录 ${p.index}/${p.total}）` : '';
  document.getElementById('bpSub')!.textContent =
    `已扫描 ${p.dirs || 0} 个文件夹 · 发现 ${games} 个游戏 ${folderIdx}`;
  if (cancelBtn) { cancelBtn.style.display = ''; cancelBtn.textContent = '取消扫描'; }
  cancelMode = 'scan';
  box.classList.add('show');
}

// 批量任务进度信号（后端 UISync batch_progress 域推送）：
// 进入批量任务（如扫描后自动 VNDB 匹配）→ 启动轮询；结束 → 收起
function updateBatchProgress(p: { running?: boolean; title?: string }): void {
  if (p && p.running) {
    cancelMode = 'match';
    const cancelBtn = document.getElementById('bpCancel') as HTMLElement | null;
    if (cancelBtn) cancelBtn.textContent = '取消匹配';
    trackBatchProgress(p.title || '批量处理中…');
  } else {
    hideBatchProgress();
  }
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
  document.querySelectorAll<HTMLElement>('.card').forEach(c =>
    c.classList.toggle('selected', App.ui.state.selected.has(c.dataset.id!)));
};
document.getElementById('btnSelAll')!.onclick = () => {
  const ids = filterGames(App.data.games).map(g => g.id);
  if (App.ui.state.selected.size === ids.length) { App.ui.state.selected.clear(); }
  else { App.ui.state.selected = new Set(ids); }
  // 局部同步全部卡片选中态，避免全量重建网格
  document.querySelectorAll<HTMLElement>('.card').forEach(c =>
    c.classList.toggle('selected', App.ui.state.selected.has(c.dataset.id!)));
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

// ---------- 批量重新定位（选目录 → 按 identity 匹配 → 预览确认）----------
interface RelocateItem { id: string; title: string; old_exe: string; new_exe: string; status: string; }
let relocateItems: RelocateItem[] = [];

function closeRelocate(): void {
  document.getElementById('relocateOverlay')!.classList.remove('show');
}

function renderRelocatePreview(items: RelocateItem[]): void {
  relocateItems = items;
  const matched = items.filter(i => i.status === 'matched').length;
  const missing = items.filter(i => i.status === 'missing').length;
  const conflict = items.filter(i => i.status === 'conflict').length;
  document.getElementById('relocateSubText')!.textContent =
    `将更新 ${matched} 个 · 未找到 ${missing} 个 · 冲突 ${conflict} 个`;
  document.getElementById('relocateList')!.innerHTML = items.map((it, i) => {
    const label = it.status === 'matched' ? '将更新'
      : it.status === 'conflict' ? '冲突，跳过' : '未找到，跳过';
    const cls = it.status === 'matched' ? 'ok' : 'skip';
    const newp = it.new_exe ? esc(it.new_exe) : '—';
    const box = it.status === 'matched'
      ? `<input type="checkbox" class="relocate-check" data-idx="${i}" checked aria-label="选择">`
      : `<input type="checkbox" class="relocate-check" data-idx="${i}" disabled aria-label="不可选">`;
    return `<div class="relocate-row ${cls}">
      <div class="rl-head">${box}<div class="rl-title">${esc(it.title)}</div><div class="rl-status">${label}</div></div>
      <div class="rl-path">${esc(it.old_exe)}</div>
      <div class="rl-path new">→ ${newp}</div>
    </div>`;
  }).join('');
  document.querySelectorAll('#relocateList .relocate-check').forEach(cb =>
    cb.addEventListener('change', updateRelocateSelBtn));
  updateRelocateSelBtn();
  document.getElementById('relocateOverlay')!.classList.add('show');
}

document.getElementById('btnBRelocate')!.onclick = () => {
  if (App.ui.state.selected.size === 0) return;
  bridge.previewRelocate(JSON.stringify([...App.ui.state.selected]), function (res: unknown) {
    let r: { ok?: boolean; msg?: string; items?: RelocateItem[] } = {};
    try { r = JSON.parse(String(res || '{}')); } catch (e) { }
    if (!r.ok) { if (r.msg) toast(r.msg); return; }
    renderRelocatePreview(r.items || []);
  });
};
function relocateBoxes(): HTMLInputElement[] {
  return [...document.querySelectorAll<HTMLInputElement>('#relocateList .relocate-check:not(:disabled)')];
}
function updateRelocateSelBtn(): void {
  const boxes = relocateBoxes();
  const allOn = boxes.length > 0 && boxes.every(b => b.checked);
  document.getElementById('relocateSelBtn')!.textContent = allOn ? '取消全选' : '全选';
}
document.getElementById('relocateClose')!.onclick = closeRelocate;
document.getElementById('relocateCancel')!.onclick = closeRelocate;
document.getElementById('relocateSelBtn')!.onclick = () => {
  const boxes = relocateBoxes();
  const allOn = boxes.length > 0 && boxes.every(b => b.checked);
  boxes.forEach(b => { b.checked = !allOn; });
  updateRelocateSelBtn();
};
document.getElementById('relocateOk')!.onclick = () => {
  const mapping: { id: string; new_exe: string }[] = [];
  document.querySelectorAll<HTMLInputElement>('#relocateList .relocate-check:checked').forEach(cb => {
    const it = relocateItems[Number(cb.dataset.idx)];
    if (it && it.status === 'matched') mapping.push({ id: it.id, new_exe: it.new_exe });
  });
  if (mapping.length === 0) { toast('没有勾选要应用的项'); return; }
  bridge.applyRelocate(JSON.stringify(mapping));
  App.ui.state.selected.clear();
  closeRelocate();
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
// 扫描进度条上的「取消扫描」按钮
// 取消按钮：按当前阶段取消扫描或 VNDB 匹配
document.getElementById('bpCancel')!.onclick = () => {
  if (cancelMode === 'match') bridge.cancelMatch(); else bridge.cancelScan();
};

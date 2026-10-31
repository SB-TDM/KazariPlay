// ============================================================
// scan_preview.ts — 扫描结果确认弹窗（扫描后勾选要导入的游戏）
// 依赖：core.ts（bridge/esc/toast/makeCheckAll）
// 定义：showScanPreview / renderScanPreview / closeScanPreview
// 被依赖：state.ts（__app.showScanPreview）
// 样式：复用 form.css 的 .dialog.relocate / .relocate-* 行布局
// ============================================================

interface ScanPreviewItem {
  key: number;
  title: string;
  exe_path: string;
  duplicate: boolean;
}

interface ScanPreviewPayload {
  token?: number;
  items?: ScanPreviewItem[];
  duplicates?: number;
  cancelled?: boolean;
}

let scanPreviewToken = 0;
let scanPreviewItems: ScanPreviewItem[] = [];

function showScanPreview(payload: ScanPreviewPayload): void {
  const p = payload || {};
  scanPreviewToken = p.token || 0;
  scanPreviewItems = p.items || [];
  renderScanPreview(p.duplicates || 0, !!p.cancelled);
  document.getElementById('scanPreviewOverlay')!.classList.add('show');
}

function renderScanPreview(duplicates: number, cancelled: boolean): void {
  const okBtn = document.getElementById('scanPreviewOk') as HTMLButtonElement | null;
  const selectable = scanPreviewItems.filter(it => !it.duplicate).length;
  if (okBtn) okBtn.disabled = selectable === 0;
  const parts = [`共 ${scanPreviewItems.length} 个，可导入 ${selectable} 个`];
  if (duplicates) parts.push(`已存在 ${duplicates} 个`);
  if (cancelled) parts.push('扫描已取消');
  document.getElementById('scanPreviewSubText')!.textContent = parts.join(' · ');
  document.getElementById('scanPreviewList')!.innerHTML = scanPreviewItems.map(it => `
    <div class="relocate-row${it.duplicate ? ' skip' : ''}">
      <div class="rl-head">
        <input type="checkbox" class="relocate-check scan-preview-check" data-idx="${it.key}"
          aria-label="选择" ${it.duplicate ? 'disabled' : 'checked'}>
        <div class="rl-title">${esc(it.title)}</div>
        <div class="rl-status">${it.duplicate ? '已存在' : '新增'}</div>
      </div>
      <div class="rl-path">${esc(it.exe_path)}</div>
    </div>`).join('');
  document.querySelectorAll('#scanPreviewList .relocate-check').forEach(cb =>
    cb.addEventListener('change', scanPreviewSel.update));
  scanPreviewSel.update();
}

// 勾选列表 + 全选切换（复用 core.makeCheckAll）
const scanPreviewSel = makeCheckAll('#scanPreviewList', '.relocate-check:not(:disabled)', 'scanPreviewSelBtn');

function closeScanPreview(): void {
  scanPreviewToken = 0;
  scanPreviewItems = [];
  document.getElementById('scanPreviewOverlay')!.classList.remove('show');
}

document.getElementById('scanPreviewClose')!.onclick = closeScanPreview;
document.getElementById('scanPreviewCancel')!.onclick = closeScanPreview;
document.getElementById('scanPreviewOk')!.onclick = () => {
  if (!scanPreviewToken) return;
  const keys = scanPreviewSel.boxes().filter(b => b.checked).map(b => Number(b.dataset.idx));
  if (keys.length === 0) { toast('没有勾选要导入的游戏'); return; }
  const okBtn = document.getElementById('scanPreviewOk') as HTMLButtonElement;
  okBtn.disabled = true;
  bridge.applyScanPreview(scanPreviewToken, JSON.stringify(keys), function (s: unknown, failed?: boolean) {
    okBtn.disabled = false;
    const r = bridgeResult(s);
    if (failed || !r.ok) { toast(r.msg || '导入失败'); return; }
    closeScanPreview();
  });
};

// ============================================================
// window.ts — 无边框窗口控制
// 依赖：core.ts（bridge）
// 定义：toggleMax / bindDrag / bindResize
// 注意：toggleMax 被 index.html 内联 onclick（btnMax）直接引用。
// ============================================================

// 最大化 / 还原切换（HTML 标题栏按钮）
function toggleMax(): void {
  const b = document.getElementById('btnMax');
  const willMax = b && b.textContent === '□';
  bridge.windowToggleMaximize();
  document.body.classList.toggle('maximized', !!willMax);   // 最大化时隐藏缩放手柄
  if (b) {
    b.setAttribute('aria-label', willMax ? '还原窗口' : '最大化');
    b.textContent = willMax ? '❐' : '□';
  }
}

// ---------- 标题栏拖拽 ----------
function bindDrag(): void {
  const tb = document.getElementById('titlebar');
  if (!tb) return;
  let dragging = false;
  tb.addEventListener('mousedown', e => {
    if ((e.target as HTMLElement).closest('.winbtn')) return;
    dragging = true;
    if (bridge) bridge.windowStartDrag(e.screenX, e.screenY);
    e.preventDefault();
  });
  window.addEventListener('mousemove', e => { if (dragging && bridge) bridge.windowMoveDrag(e.screenX, e.screenY); });
  window.addEventListener('mouseup', () => { if (dragging) { dragging = false; if (bridge) bridge.windowEndDrag(); } });
  tb.addEventListener('dblclick', e => { if (!(e.target as HTMLElement).closest('.winbtn')) toggleMax(); });
}

// ---------- 窗口缩放手柄（四边 / 四角自由拉伸） ----------
function bindResize(): void {
  let rs: { dir: string; sx: number; sy: number } | null = null, raf = false;
  document.querySelectorAll<HTMLElement>('.resizer').forEach(h => {
    h.addEventListener('mousedown', (e: MouseEvent) => {
      e.preventDefault();
      rs = { dir: h.dataset.dir!, sx: e.clientX, sy: e.clientY };
      bridge.windowResizeStart(h.dataset.dir!);
    });
  });
  window.addEventListener('mousemove', (e: MouseEvent) => {
    if (!rs) return;
    if (raf) return;
    raf = true;
    requestAnimationFrame(() => {
      raf = false;
      if (!rs) return;
      const dx = e.clientX - rs.sx, dy = e.clientY - rs.sy;
      bridge.windowResize(rs.dir, dx, dy);
    });
  });
  window.addEventListener('mouseup', () => { rs = null; });
}
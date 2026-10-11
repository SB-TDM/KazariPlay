// ============================================================
// window.ts — 无边框窗口控制
// 依赖：core.ts（bridge）
// 定义：toggleMax / bindDrag / bindResize
// 注意：toggleMax 被 index.html 内联 onclick（btnMax）直接引用。
// ============================================================

// 最大化 / 还原切换（HTML 标题栏按钮）
// 以后端回传的真实窗口状态驱动 UI，避免前后端状态脱节导致按钮“点不动”
function toggleMax(): void {
  bridge.windowToggleMaximize(function (state: unknown, failed?: boolean) {
    if (failed) return;   // 桥失败保持现状
    const maximized = state === true;
    document.body.classList.toggle('maximized', maximized);   // 最大化时隐藏缩放手柄
    const b = document.getElementById('btnMax');
    if (!b) return;
    b.dataset.mode = maximized ? 'max' : 'restore';
    b.setAttribute('aria-label', maximized ? '还原窗口' : '最大化');
    b.innerHTML = maximized ? ICON.winRestore : ICON.winMax;
  });
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
      // 用屏幕坐标：上/左拉伸会同时移动窗口原点，client 坐标会被窗口自身位移反噬导致抖动
      rs = { dir: h.dataset.dir!, sx: e.screenX, sy: e.screenY };
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
      const dx = e.screenX - rs.sx, dy = e.screenY - rs.sy;
      bridge.windowResize(rs.dir, dx, dy);
    });
  });
  window.addEventListener('mouseup', () => { rs = null; });
}
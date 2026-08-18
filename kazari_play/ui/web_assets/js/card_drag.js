// ============================================================
// card_drag.js — 卡片拖拽排序（仅收藏夹视图启用）
// 依赖：state.js / core.js（toast）/ games.js（renderAll）
// 定义：isDragOrderEnabled / bindCardDrag / markDragOver / reorderCards + 全局拖拽事件
// 被依赖：cards.js（buildCard 调用 bindCardDrag）
// ============================================================

// ---------- 卡片拖拽排序（仅收藏夹视图启用）----------
// 用 mousedown 自实现 + 位移阈值：点击打开详情不受轻微抖动影响，
// 按住移动超过 DRAG_THRESHOLD 才进入拖拽态（HTML5 drag & drop 无法判定位移阈值）。
let dragFromId = null;
let dragOverId = null;
let _dragState = null;      // {id, startX, startY} 按下后待判定
let _dragActive = false;    // 已超过阈值进入拖拽态
let _dragOffset = null;     // {ox, oy} 鼠标相对卡片左上角偏移（拖拽跟手用）
const DRAG_THRESHOLD = 6;   // px：小于该位移视为点击

function isDragOrderEnabled() {
  // 收藏夹视图 + 非批量模式 才允许拖拽重排
  return App.ui.state.collectionId !== null && !App.ui.state.batch;
}

function bindCardDrag(card, g) {
  card.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (!isDragOrderEnabled()) return;
    _dragState = { id: g.id, startX: e.clientX, startY: e.clientY };
    _dragActive = false;
    const r = card.getBoundingClientRect();
    _dragOffset = { ox: e.clientX - r.left, oy: e.clientY - r.top };
  });
}

// 全局 mouseup：拖拽结束落点（按下后 100ms 内未判定为拖拽则忽略）
document.addEventListener('mouseup', () => {
  if (!_dragState) return;
  if (_dragActive && dragFromId) {
    // 有落点则重排；无落点（拖回原处）仅清理
    if (dragOverId && dragFromId !== dragOverId) {
      reorderCards(dragFromId, dragOverId);
    }
    _dragActive = false;
    dragFromId = null; dragOverId = null; _dragOffset = null;
    document.querySelectorAll('.card.dragging,.card.drag-over')
      .forEach(c => c.classList.remove('dragging', 'drag-over'));
  }
  _dragState = null;
});

// 全局 mousemove：位移超过阈值进入拖拽态，拖拽中源卡片跟随鼠标 + 更新落点高亮
document.addEventListener('mousemove', (e) => {
  if (!_dragState) return;
  if (!_dragActive) {
    const dx = e.clientX - _dragState.startX;
    const dy = e.clientY - _dragState.startY;
    if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    _dragActive = true;
    dragFromId = _dragState.id;
    dragOverId = null;
    const c = document.querySelector(`.card[data-id="${dragFromId}"]`);
    if (c) c.classList.add('dragging');
    return;
  }
  // 拖拽中：源卡片跟手（相对按下点位移，translate 保持原布局占位）
  const c = document.querySelector(`.card[data-id="${dragFromId}"]`);
  if (c && _dragOffset) {
    c.style.transform =
      `translate(${e.clientX - _dragState.startX}px, ${e.clientY - _dragState.startY}px)`;
  }
  // 落点判定：鼠标下的卡片（排除自身）
  const el = document.elementFromPoint(e.clientX, e.clientY);
  const target = el && el.closest ? el.closest('.card') : null;
  const tid = target && target.dataset.id !== dragFromId ? target.dataset.id : null;
  if (tid !== dragOverId) {
    dragOverId = tid;
    markDragOver(tid ? target : null);
  }
});

function markDragOver(card) {
  document.querySelectorAll('.card.drag-over').forEach(c => c.classList.remove('drag-over'));
  if (card) card.classList.add('drag-over');
}

// 拖拽落点：把 from 移到 to 之前，并持久化到当前收藏夹
function reorderCards(fromId, toId) {
  const grid = document.getElementById('grid');
  const ids = [...grid.querySelectorAll('.card')].map(c => c.dataset.id);
  const from = ids.indexOf(fromId), to = ids.indexOf(toId);
  if (from < 0 || to < 0) return;
  ids.splice(from, 1);
  ids.splice(to, 0, fromId);
  // 更新本地顺序（先改 UI 再持久化，避免闪烁）
  App.ui.state.collectionOrder = ids;
  renderAll();
  // 持久化：分组视图聚合排序存到分组自身，分类视图存到分类
  bridge.setCollectionGames(App.ui.state.collectionId, JSON.stringify(ids));
  toast('排序已更新');
}

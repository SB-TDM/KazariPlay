// ============================================================
// ui.ts — Sheet / 通用对话框 / 右键菜单基础设施
// 依赖：core.ts（esc）/ icons.ts（ICON）
// 定义：showSheet / closeSheet / closeTopSheet / setSheetLocked /
//       showConfirmDialog / confirmOk / showInputDialog / inputOk /
//       openPicker / showContextMenu / makeStarSlider
// 被依赖：games.ts（卡片右键菜单）、collections.ts（收藏夹右键菜单）、
//         batch.ts（openPicker）、detail.ts / screenshots.ts（对话框）、
//         detail.ts / form.ts（星级滑条）、updater.ts（更新弹层锁定）
// ============================================================

/** 确认对话框选项 */
interface ConfirmDialogOptions {
  title?: string;
  message?: string;
  okText?: string;
  danger?: boolean;
  cb?: () => void;
}

/** 输入对话框选项 */
interface InputDialogOptions {
  title?: string;
  label?: string;
  value?: string;
  cb?: (value: string) => void;
}

/** 选择器条目 */
interface PickerItem {
  label: string;
  value: number;
}

/** 右键菜单条目（'sep' 为分隔线） */
type ContextMenuEntry =
  | { icon?: string; text?: string; danger?: boolean; action?: () => void }
  | 'sep';

// ---------- Sheet（底部抽屉 / 居中弹层）----------
const sheetLocks = new Set<string>();
const sheetReturnFocus = new Map<string, HTMLElement | null>();

function setMenuOpen(menu: HTMLElement | null, trigger: HTMLElement | null, open: boolean): void {
  if (menu) menu.classList.toggle('show', open);
  if (trigger) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
}

// 弹层锁定：锁定期间遮罩点击 / Esc / 关闭按钮都不生效（更新下载中禁止关闭）
function setSheetLocked(id: string, locked: boolean): void {
  if (locked) sheetLocks.add(id);
  else sheetLocks.delete(id);
}

function syncAppInert(): void {
  const row = document.querySelector('.row') as HTMLElement | null;
  if (row) row.inert = !!document.querySelector('.overlay.show');
}

function showSheet(id: string): void {
  const o = document.getElementById(id);
  if (!o) return;
  const active = document.activeElement as HTMLElement | null;
  if (!(active && o.contains(active))) {
    sheetReturnFocus.set(id, active);
  }
  o.classList.remove('hiding');
  o.classList.add('show');
  if (!o.hasAttribute('role')) o.setAttribute('role', 'dialog');
  o.setAttribute('aria-modal', 'true');
  if (!o.hasAttribute('aria-labelledby')) {
    const title = o.querySelector<HTMLElement>('.dlg-title, .dlg-head h3, h2, h3');
    if (title) {
      if (!title.id) title.id = id + '-title';
      o.setAttribute('aria-labelledby', title.id);
    }
  }
  syncAppInert();
  setTimeout(() => {
    if (!o.classList.contains('show')) return;
    const preferred = o.querySelector<HTMLElement>('[data-autofocus]');
    const target = preferred || o.querySelector<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), ' +
      'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
    if (target) target.focus({ preventScroll: true });
  }, 30);
}

function closeSheet(id: string, instant?: boolean): void {
  if (sheetLocks.has(id)) return;
  const o = document.getElementById(id);
  if (!o) return;
  if (instant) {
    o.classList.remove('show', 'hiding');
    if (id === 'detailOverlay') setActiveCard(null);
  } else {
    o.classList.remove('show');
    o.classList.add('hiding');
    setTimeout(() => o.classList.remove('hiding'), 280);
    if (id === 'detailOverlay') setActiveCard(null);
  }
  syncAppInert();
  const target = sheetReturnFocus.get(id);
  sheetReturnFocus.delete(id);
  if (target && target.isConnected) {
    try { target.focus(); } catch (e) { }
  }
}

// 点击遮罩关闭。
document.querySelectorAll('.overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) closeSheet(o.id); });
});

// 焦点陷阱：弹层打开时 Tab/Shift+Tab 只在最上层弹层内循环（标题栏仍可用鼠标操作）
document.addEventListener('keydown', e => {
  if (e.key !== 'Tab') return;
  const overlays = document.querySelectorAll<HTMLElement>('.overlay.show');
  const top = overlays[overlays.length - 1];
  if (!top) return;
  const focusables = [...top.querySelectorAll<HTMLElement>(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), ' +
    'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
    .filter(el => el.getClientRects().length > 0);
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  const active = document.activeElement as HTMLElement | null;
  if (!active || !top.contains(active)) {
    e.preventDefault();
    (e.shiftKey ? last : first).focus();
    return;
  }
  if (e.shiftKey && active === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
});

// Esc 关闭最上层：overlay 分块按注入顺序层叠（后出现者在上），倒序取第一个可见者。
// 输入/确认清理对应回调；设置窗口走 Settings.close（含主题回退）；无可见弹层时返回 false。
function closeTopSheet(): boolean {
  const overlays = document.querySelectorAll<HTMLElement>('.overlay.show');
  const top = overlays[overlays.length - 1];
  if (!top) return false;
  if (top.id === 'inputOverlay') inputCb = null;
  else if (top.id === 'confirmOverlay') confirmCb = null;
  if (top.id === 'settingsOverlay' && window.Settings) window.Settings.close();
  else closeSheet(top.id);
  return true;
}

// ---------- 通用确认对话框（替代原生 confirm）----------
let confirmCb: (() => void) | null = null;
function showConfirmDialog(opts: ConfirmDialogOptions): void {
  document.getElementById('confirmTitle')!.textContent = opts.title || '确认';
  document.getElementById('confirmMsg')!.textContent = opts.message || '确定执行此操作？';
  confirmCb = opts.cb || null;
  const ok = document.getElementById('confirmOk')!;
  ok.textContent = opts.okText || '确定';
  showSheet('confirmOverlay');
}

function confirmOk(): void {
  const cb = confirmCb;
  confirmCb = null;
  closeSheet('confirmOverlay');
  if (cb) cb();
}

// ---------- 通用输入对话框（替代原生 prompt）----------
let inputCb: ((value: string) => void) | null = null;
function showInputDialog(opts: InputDialogOptions): void {
  document.getElementById('inputTitle')!.textContent = opts.title || '输入';
  document.getElementById('inputLabel')!.textContent = opts.label || '名称';
  (document.getElementById('inputValue') as HTMLInputElement).value = opts.value || '';
  inputCb = opts.cb || null;
  showSheet('inputOverlay');
}

function inputOk(): void {
  const v = document.getElementById('inputValue') as HTMLInputElement;
  closeSheet('inputOverlay');
  if (inputCb) { inputCb(v.value); inputCb = null; }
}

// ---------- 通用对话框按钮绑定（input/confirm 的打开与关闭由本模块负责）----------
document.getElementById('inputClose')!.onclick = () => { inputCb = null; closeSheet('inputOverlay'); };
document.getElementById('inputCancel')!.onclick = () => { inputCb = null; closeSheet('inputOverlay'); };
document.getElementById('inputOk')!.onclick = inputOk;
(document.getElementById('inputValue') as HTMLInputElement).addEventListener('keydown', e => { if (e.key === 'Enter') inputOk(); });
document.getElementById('confirmClose')!.onclick = () => { confirmCb = null; closeSheet('confirmOverlay'); };
document.getElementById('confirmCancel')!.onclick = () => { confirmCb = null; closeSheet('confirmOverlay'); };
document.getElementById('confirmOk')!.onclick = confirmOk;

// ---------- 通用选择器（批量收藏夹选择等）----------
function openPicker(title: string, items: PickerItem[], onPick: (value: number) => void): void {
  document.getElementById('pickerTitle')!.textContent = title;
  const list = document.getElementById('pickerList')!;
  list.innerHTML = '';
  items.forEach(it => {
    const d = document.createElement('div');
    d.className = 'p-item';
    d.textContent = it.label;
    d.onclick = () => { closeSheet('pickerOverlay'); onPick(it.value); };
    list.appendChild(d);
  });
  showSheet('pickerOverlay');
}

// ---------- 通用右键菜单（卡片 / 收藏夹共用）----------
// entries: {icon, text, danger?, action} | 'sep'（分隔线）
// 样式与定位逻辑统一在此维护，避免各调用方重复实现。
function showContextMenu(entries: ContextMenuEntry[], x: number, y: number, width?: number): HTMLElement {
  document.querySelectorAll('.ctx-menu').forEach(mm => mm.remove());
  const m = document.createElement('div');
  m.className = 'more-menu ctx-menu';
  const w = width || 170;
  // 固定定位：clamp 到视口内，避免超出屏幕右侧/底部
  const vw = window.innerWidth, vh = window.innerHeight;
  const mh = entries.length * 34 + 20;
  let px = x, py = y;
  if (px + w > vw - 8) px = vw - w - 8;
  if (py + mh > vh - 8) py = vh - mh - 8;
  px = Math.max(8, px); py = Math.max(8, py);
  m.style.cssText = `position:fixed;left:${px}px;top:${py}px;display:block;z-index:90;background:var(--bg-panel);border:1.5px solid var(--border-soft);border-radius:12px;padding:5px;width:${w}px;box-shadow:0 10px 24px var(--glow-med);`;
  m.innerHTML = entries.map(e =>
    e === 'sep'
      ? '<div class="menu-sep"></div>'
      : `<button type="button" class="item ${e.danger ? 'danger' : ''}"><span class="mi">${e.icon || ''}</span>${esc(e.text || '')}</button>`
  ).join('');
  [...m.children].forEach((d, i) => {
    if (d.classList.contains('menu-sep')) return;
    (d as HTMLButtonElement).onclick = () => {
      m.remove();
      const a = (entries[i] !== 'sep' && entries[i].action) || undefined;
      if (a) a();
    };
  });
  document.body.appendChild(m);
  setTimeout(() => document.addEventListener('click', function h() { m.remove(); document.removeEventListener('click', h); }), 0);
  return m;
}

// ---------- 星级滑条（详情评分 / 编辑表单共用）----------
/** 星级滑条实例（0-5，0.5 步进；0 表示未评分） */
interface StarSlider {
  get(): number;
  set(value: number): void;
}

// 五星星轨 + 覆盖其上的隐藏 range 输入：点击/拖动/键盘（←→ ±0.5）改值；
// 拖动中只更新本地显示，松手（change）才回调 onChange（避免高频保存）。
// 容器带 id 时给输入框衍生 id（el.id + 'Input'），供 <label for> 关联。
function makeStarSlider(el: HTMLElement, value: number, onChange?: (value: number) => void): StarSlider {
  el.classList.add('star-slider');
  const inputId = el.id ? el.id + 'Input' : '';
  el.innerHTML =
    `<span class="ss-wrap"><span class="ss-layer ss-base">${ICON.star.repeat(5)}</span>` +
    `<span class="ss-layer ss-fill">${ICON.starFill.repeat(5)}</span>` +
    `<input type="range" min="0" max="5" step="0.5" aria-label="评分"${inputId ? ` id="${inputId}"` : ''}></span>` +
    `<span class="ss-val"></span>`;
  const input = el.querySelector('input') as HTMLInputElement;
  const fill = el.querySelector('.ss-fill') as HTMLElement;
  const val = el.querySelector('.ss-val') as HTMLElement;
  const paint = (): void => {
    const v = Number(input.value);
    fill.style.width = (v / 5 * 100) + '%';
    val.textContent = v ? v.toFixed(1) : '未评分';
    el.dataset.r = String(v);
  };
  input.value = String(value || 0);
  paint();
  input.addEventListener('input', paint);
  input.addEventListener('change', () => { paint(); if (onChange) onChange(Number(input.value)); });
  return {
    get: () => Number(input.value),
    set: (v: number) => { input.value = String(v || 0); paint(); },
  };
}

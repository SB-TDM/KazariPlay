// ============================================================
// core.ts — bridge 代理 + 通用工具
// 依赖：state.ts（state 于运行时使用）
// 定义：bridge / esc / toast / stars / chipColor / loadCoverTo
// 注意：bridge 被 index.html 内联 onclick（窗口最小化等）直接引用，
//       必须是全局绑定（顶层 const），不能包进 IIFE。
// ============================================================

// pywebview 桥接兼容层：把 QWebChannel 风格的 bridge.xxx(cb) 转为 pywebview.api.xxx().then(cb)
// 代理按名转发到 window.pywebview.api，返回 Promise；最后一个函数参数视为回调（兼容旧调用方式）。
const bridge = new Proxy({} as Record<string, (...args: unknown[]) => Promise<unknown>>, {
  get(t, name: string) {
    if (name === 'dataChanged') return { connect: function (): void {} };  // 无信号，改为轮询
    return function (...args: unknown[]): Promise<unknown> {
      let cb: ((r: string) => void) | null = null;
      if (args.length && typeof args[args.length - 1] === 'function') { cb = args.pop() as (r: string) => void; }
      const api = window.pywebview && window.pywebview.api;
      const fn = api && (api as unknown as Record<string, unknown>)[name];
      if (typeof fn !== 'function') { if (cb) cb('[]'); return Promise.resolve('[]'); }
      const p = (fn as (...a: unknown[]) => Promise<unknown>).apply(api, args);
      if (cb) { Promise.resolve(p).then(r => cb(r as string)).catch(() => cb('[]')); }
      return p;
    };
  },
});

// HTML 转义（用户输入进 innerHTML 前必须转义：标题/开发商/收藏夹名等）
function esc(s: unknown): string {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
}

// 轻量 toast 提示（顶部胶囊，1.8s 自动消失）
let toastTimer: ReturnType<typeof setTimeout> | null = null;
function toast(msg: string): void {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer as ReturnType<typeof setTimeout>);
  toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
}

// 详情页和卡片菜单共用启动入口。后端返回 {ok:false} 时提示失败，不再静默。
function launchGame(gameId: string): void {
  if (!bridge) return;
  bridge.launch(String(gameId), function (s: unknown) {
    let r: { ok?: boolean; msg?: string } = {};
    try { r = JSON.parse(String(s || '{}')); } catch (e) { }
    if (r && r.ok === false) toast(r.msg || '启动失败');
  });
}

// 星级字符串（1-5，0 表示未评分）
function stars(r: number): string {
  r = Math.max(0, Math.min(5, r || 0));
  return '★'.repeat(r) + '☆'.repeat(5 - r);
}

// 标签/收藏夹色块颜色：字符串哈希 → 5 色糖果色板
function chipColor(tag: string): string {
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) % 997;
  return ['#ffb3c1', '#c4b5fd', '#b5ead7', '#ffd97d', '#ffc9a0'][h % 5];
}

// 把封面 data URI 应用到元素（prefix='img' → 设 src；否则设 backgroundImage + 渐变兜底）
function loadCoverTo(gameId: string, el: HTMLElement | null, prefix: string): void {
  if (!el) return;
  const gid = String(gameId);
  el.dataset.coverGid = gid;   // 记录元素当前目标，迟到封面据此丢弃
  bridge.getCover(gid, function (uri: unknown) {
    if (el.dataset.coverGid !== gid) return;
    if (!uri) return;
    if (prefix === 'img') { (el as HTMLImageElement).src = String(uri); return; }
    el.style.backgroundImage = `url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
  });
}

// 勾选列表 + 「全选/取消全选」切换按钮的通用绑定
// （重新定位预览、元数据字段勾选共用；checkSelector 可用 :not(:disabled) 排除不可选项）
function makeCheckAll(listSelector: string, checkSelector: string, btnId: string): {
  boxes: () => HTMLInputElement[];
  update: () => void;
} {
  const boxes = (): HTMLInputElement[] =>
    [...document.querySelectorAll<HTMLInputElement>(`${listSelector} ${checkSelector}`)];
  const update = (): void => {
    const bs = boxes();
    const allOn = bs.length > 0 && bs.every(b => b.checked);
    const btn = document.getElementById(btnId);
    if (btn) btn.textContent = allOn ? '取消全选' : '全选';
  };
  const btn = document.getElementById(btnId);
  if (btn) {
    btn.onclick = () => {
      const bs = boxes();
      const allOn = bs.length > 0 && bs.every(b => b.checked);
      bs.forEach(b => { b.checked = !allOn; });
      update();
    };
  }
  return { boxes, update };
}

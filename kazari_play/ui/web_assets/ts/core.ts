// ============================================================
// core.ts — bridge 代理 + 通用工具
// 依赖：state.ts（state 于运行时使用）
// 定义：bridge / esc / toast / chipColor / loadCoverTo
//       beginCoverRequest / isCoverRequestCurrent
// 注意：bridge 被 index.html 内联 onclick（窗口最小化等）直接引用，
//       必须是全局绑定（顶层 const），不能包进 IIFE。
// ============================================================

// 桥回调的失败标记：第二参 failed=true 表示"调用没到达后端或后端异常"，
// 与"空列表 / 对象不存在"区分开；业务回调自身的异常不会再触发第二次回调。
type BridgeCallback = (result: unknown, failed?: boolean) => void;

// pywebview 桥接兼容层：把 QWebChannel 风格的 bridge.xxx(cb) 转为 pywebview.api.xxx().then(cb)
// 代理按名转发到 window.pywebview.api，返回 Promise；最后一个函数参数视为回调（兼容旧调用方式）。
const bridge = new Proxy({} as Record<string, (...args: unknown[]) => Promise<unknown>>, {
  get(t, name: string) {
    if (name === 'dataChanged') return { connect: function (): void {} };  // 无信号，改为轮询
    return function (...args: unknown[]): Promise<unknown> {
      let cb: BridgeCallback | null = null;
      if (args.length && typeof args[args.length - 1] === 'function') { cb = args.pop() as BridgeCallback; }
      const notify = cb ? function (r: unknown, failed?: boolean): void {
        try { (cb as BridgeCallback)(r, failed); } catch (e) { }
      } : null;
      const api = window.pywebview && window.pywebview.api;
      const fn = api && (api as unknown as Record<string, unknown>)[name];
      if (typeof fn !== 'function') { if (notify) notify('[]', true); return Promise.resolve('[]'); }
      let p: Promise<unknown>;
      try {
        p = (fn as (...a: unknown[]) => Promise<unknown>).apply(api, args);
      } catch (e) {
        if (notify) notify('[]', true);
        return Promise.resolve('[]');
      }
      if (notify) { Promise.resolve(p).then(r => notify(r), () => notify('[]', true)); }
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

// 详情页和卡片菜单共用启动入口。后端返回 {ok:false} 或桥失败时提示，不再静默。
function launchGame(gameId: string): void {
  if (!bridge) return;
  bridge.launch(String(gameId), function (s: unknown, failed?: boolean) {
    if (failed) { toast('启动失败'); return; }
    let r: { ok?: boolean; msg?: string } = {};
    try { r = JSON.parse(String(s || '{}')); } catch (e) { }
    if (r && r.ok === false) toast(r.msg || '启动失败');
  });
}

// 标签/收藏夹色块颜色：字符串哈希 → 5 色糖果色板
function chipColor(tag: string): string {
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) % 997;
  return ['#ffb3c1', '#c4b5fd', '#b5ead7', '#ffd97d', '#ffc9a0'][h % 5];
}

// ---------- 封面请求身份 ----------
// 每次封面请求分配递增序号并写入目标元素；迟到响应按序号判断是否仍是最新请求，
// 覆盖"同 ID 连续请求 / A→B→A / 懒加载与定向重载交错"的乱序场景。
let _coverReqSeq = 0;
function beginCoverRequest(el: HTMLElement): string {
  const seq = String(++_coverReqSeq);
  el.dataset.coverSeq = seq;
  return seq;
}

function isCoverRequestCurrent(el: HTMLElement, seq: string): boolean {
  return el.dataset.coverSeq === seq;
}

// 把封面 URL / data URI 应用到元素（prefix='img' → 设 src；否则设 backgroundImage + 渐变兜底）
function applyCoverSrc(el: HTMLElement, src: string, prefix: string): void {
  if (prefix === 'img') { (el as HTMLImageElement).src = src; return; }
  el.style.backgroundImage = `url('${src}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
}

function loadCoverToCard(card: HTMLElement, gameId: string): void {
  const gid = String(gameId);
  const c = card.querySelector('.cover') as HTMLElement | null;
  if (!c) return;
  const seq = beginCoverRequest(card);
  const g = App.data.games.find(x => String(x.id) === gid);
  const url = g ? (g.cover_url || '') : '';
  const apply = (src: string): void => {
    if (!isCoverRequestCurrent(card, seq) || !src) return;
    card.dataset.coverLoaded = '1';
    applyCoverSrc(c, src, 'bg');
    _playCoverFade(c);
  };
  if (url) {
    const img = new Image();
    img.onload = () => apply(url);
    img.onerror = () => {
      bridge.getCover(gid, function (uri: unknown, failed?: boolean) {
        if (!failed && uri) apply(String(uri));
      });
    };
    img.src = url;
    return;
  }
  bridge.getCover(gid, function (uri: unknown, failed?: boolean) {
    if (!failed && uri) apply(String(uri));
  });
}

// 把封面应用到任意元素（详情/编辑预览）：优先本地 HTTP URL，失败回退 base64
function loadCoverTo(gameId: string, el: HTMLElement | null, prefix: string): void {
  if (!el) return;
  const gid = String(gameId);
  const seq = beginCoverRequest(el);
  const g = App.data.games.find(x => String(x.id) === gid) || App.data.currentGame;
  const url = g ? (g.cover_url || '') : '';
  const apply = (src: string): void => {
    if (!isCoverRequestCurrent(el, seq) || !src) return;
    applyCoverSrc(el, src, prefix);
  };
  if (url) {
    const img = new Image();
    img.onload = () => apply(url);
    img.onerror = () => {
      bridge.getCover(gid, function (uri: unknown, failed?: boolean) {
        if (!failed && uri) apply(String(uri));
      });
    };
    img.src = url;
    return;
  }
  bridge.getCover(gid, function (uri: unknown, failed?: boolean) {
    if (!failed && uri) apply(String(uri));
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

"use strict";
// ============================================================
// core.ts — bridge 代理 + 通用工具
// 依赖：state.ts（state 于运行时使用）
// 定义：bridge / esc / toast / stars / chipColor / loadCoverTo
// 注意：bridge 被 index.html 内联 onclick（窗口最小化等）直接引用，
//       必须是全局绑定（顶层 const），不能包进 IIFE。
// ============================================================
// pywebview 桥接兼容层：把 QWebChannel 风格的 bridge.xxx(cb) 转为 pywebview.api.xxx().then(cb)
// 代理按名转发到 window.pywebview.api，返回 Promise；最后一个函数参数视为回调（兼容旧调用方式）。
const bridge = new Proxy({}, {
    get(t, name) {
        if (name === 'dataChanged')
            return { connect: function () { } }; // 无信号，改为轮询
        return function (...args) {
            let cb = null;
            if (args.length && typeof args[args.length - 1] === 'function') {
                cb = args.pop();
            }
            const api = window.pywebview && window.pywebview.api;
            const fn = api && api[name];
            if (typeof fn !== 'function') {
                if (cb)
                    cb('[]');
                return Promise.resolve('[]');
            }
            const p = fn.apply(api, args);
            if (cb) {
                Promise.resolve(p).then(r => cb(r)).catch(() => cb('[]'));
            }
            return p;
        };
    },
});
// HTML 转义（用户输入进 innerHTML 前必须转义：标题/开发商/收藏夹名等）
function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
// 轻量 toast 提示（顶部胶囊，1.8s 自动消失）
let toastTimer = null;
function toast(msg) {
    const t = document.getElementById('toast');
    if (!t)
        return;
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
}
// 统一启动入口：所有启动按钮/菜单都走这里（详情页、卡片右键等），
// 保证「首次启用翻译且无 hook_code」时 Hook 选择弹窗必然弹出；
// 否则字幕会被等待选择状态吞掉（_awaiting_selection），用户看不到任何字幕。
function launchGame(gameId) {
    if (!bridge)
        return;
    bridge.launch(String(gameId), function (res) {
        try {
            const r = JSON.parse(String(res) || '{}');
            if (r && r.ok && r.need_hook_select && window.HookSelect) {
                window.HookSelect.open(gameId);
            }
        }
        catch (e) { /* 解析失败静默 */ }
    });
}
// 星级字符串（1-5，0 表示未评分）
function stars(r) {
    r = Math.max(0, Math.min(5, r || 0));
    return '★'.repeat(r) + '☆'.repeat(5 - r);
}
// 标签/收藏夹色块颜色：字符串哈希 → 5 色糖果色板
function chipColor(tag) {
    let h = 0;
    for (let i = 0; i < tag.length; i++)
        h = (h * 31 + tag.charCodeAt(i)) % 997;
    return ['#ffb3c1', '#c4b5fd', '#b5ead7', '#ffd97d', '#ffc9a0'][h % 5];
}
// 把封面 data URI 应用到元素（prefix='img' → 设 src；否则设 backgroundImage + 渐变兜底）
function loadCoverTo(gameId, el, prefix) {
    if (!el)
        return;
    bridge.getCover(String(gameId), function (uri) {
        if (!uri)
            return;
        if (prefix === 'img') {
            el.src = String(uri);
            return;
        }
        el.style.backgroundImage = `url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
    });
}

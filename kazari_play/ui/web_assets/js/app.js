"use strict";
// ============================================================
// app.ts — 启动引导（最后加载）
// 职责：初始化入口 / 导航 / 搜索 / 筛选下拉 / FAB / 全局点击与键盘处理
// 依赖：state.ts / core.ts / ui.ts / window.ts / games.ts / collections.ts / batch.ts / form.ts
// 注意：本文件只负责「粘合」各模块与全局事件，不承载业务逻辑。
// ============================================================
// ---------- 初始化 ----------
// pywebview 注入时序：先注入 window.pywebview（api 为空对象 {}），导航完成后
// 才 _createApi 填充方法并派发 pywebviewready。因此不能只凭 api 真值判定就绪
// （空对象也为真，会过早执行导致全部桥接调用拿到空 api）。
// 这里用「方法数 > 0」判断就绪 + 轮询兜底 + pywebviewready 事件三重保障，且防重复执行。
function init() {
    let _ready = false;
    const onReady = function () {
        if (_ready)
            return;
        _ready = true;
        window.bridgeReady = true;
        bridge.getConfig(function (s) {
            try {
                const cfg = JSON.parse(String(s || '{}'));
                if (window.Settings)
                    window.Settings.applyTheme(cfg.theme || 'light');
                applyCoverSize(cfg.cover_size || 'medium');
            }
            catch (e) { }
        });
        refreshAll(true);
        setInterval(() => refreshAll(false), 30000); // 长轮询兜底（数据无变化时不重建）
    };
    const apiReady = function () {
        const api = window.pywebview && window.pywebview.api;
        // 空对象 {} 不算就绪（_createApi 尚未填充）
        return !!(api && typeof api === 'object' && Object.keys(api).length > 0);
    };
    if (apiReady()) {
        onReady();
    }
    else {
        // 事件 + 轮询双保险：任一先到都就绪（_ready 防重复）
        window.addEventListener('pywebviewready', onReady);
        const poll = function () {
            if (_ready)
                return;
            if (apiReady()) {
                onReady();
            }
            else
                setTimeout(poll, 100);
        };
        setTimeout(poll, 100);
    }
}
// ---------- 筛选下拉 ----------
function bindFilterMenu() {
    const m = document.getElementById('filterMenu');
    m.querySelectorAll('.item').forEach(it => {
        it.onclick = () => {
            App.ui.state.sort = it.dataset.sort;
            m.classList.remove('show');
            document.querySelectorAll('#filterMenu .item').forEach(x => x.classList.remove('on'));
            it.classList.add('on');
            renderAll();
        };
    });
}
// ---------- 事件绑定 ----------
// 搜索框（防抖：连续输入只触发一次过滤渲染，避免大库逐键全量重建）
let searchTimer = null;
document.getElementById('searchInput').addEventListener('input', e => {
    const kw = e.target.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        if (App.ui.state.kw === kw)
            return;
        App.ui.state.kw = kw;
        renderAll();
    }, 200);
});
// 筛选按钮 + 下拉
document.getElementById('filterBtn').onclick = function (e) {
    e.stopPropagation();
    document.getElementById('filterMenu').classList.toggle('show');
};
bindFilterMenu();
// 侧边栏导航（全部作品 / 继续游玩 / 我的收藏；收藏夹入口在 collections.ts）
document.querySelectorAll('#sidebar .side-item').forEach(it => {
    if (it.id === 'btnNewCollection' || it.id === 'btnSettings')
        return;
    it.onclick = () => {
        App.ui.state.nav = it.dataset.nav;
        App.ui.state.collectionId = null;
        document.querySelectorAll('#sidebar .side-item').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('#collectionTree .collection-item').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('#collectionTree .collection-group-header').forEach(x => x.classList.remove('active'));
        it.classList.add('active');
        renderAll();
    };
});
// 设置入口
document.getElementById('btnSettings').onclick = () => {
    if (window.Settings)
        window.Settings.open();
    else
        toast('设置模块加载失败');
};
// 空状态 / FAB
document.getElementById('btnScan').onclick = () => bridge.scanFolder();
document.getElementById('btnShowAll').onclick = () => clearCollectionFilter();
document.getElementById('fab').onclick = function (e) {
    e.stopPropagation();
    document.getElementById('fabMenu').classList.toggle('show');
};
document.getElementById('fabRefresh').onclick = () => { refreshAll(true); toast('已刷新'); };
document.getElementById('fabAdd').onclick = () => { document.getElementById('fabMenu').classList.remove('show'); openAdd(); };
document.getElementById('fabScan').onclick = () => { document.getElementById('fabMenu').classList.remove('show'); bridge.scanFolder(); };
// 全局点击：收起所有浮层
document.addEventListener('click', () => {
    document.getElementById('filterMenu').classList.remove('show');
    document.getElementById('fabMenu').classList.remove('show');
    document.getElementById('dlgMoreMenu').classList.remove('show');
    hideShotMenu();
});
// 全局键盘：Esc 退出批量模式或关闭最上层 Sheet
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        hideShotMenu();
        if (App.ui.state.batch) {
            App.ui.state.batch = false;
            document.body.classList.remove('batch');
            document.getElementById('batchBtn').classList.remove('active');
            App.ui.state.selected.clear();
            renderAll();
        }
        else
            closeTopSheet();
    }
});
// ---------- 启动 ----------
bindDrag();
bindResize();
init();

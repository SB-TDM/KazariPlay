"use strict";
// ============================================================
// state.ts — 全局共享状态（命名空间收敛，阶段 D 第二步）
// 依赖：无（必须最先加载，位于 _JS_MANIFEST 首位）
// 被依赖：所有其它模块
// 注意：全部共享数据收敛到 App 命名空间（顶层 var → 全局），按功能域拆分：
//       App.data = 业务数据（游戏列表/当前游戏/编辑目标/运行状态）
//       App.ui   = UI 状态（导航/搜索/排序/批量/收藏夹筛选）
//       bridge 保持全局（core.ts 定义，index.html 内联 onclick 直接引用）。
// ============================================================
// 全局数据命名空间（各模块统一经 App.xxx 读写）
var App = {
    // ---- 业务数据（App.data）----
    data: {
        // 游戏列表快照（每次 refreshAll 整体替换）
        games: [],
        // 当前详情打开的游戏对象
        currentGame: null,
        // 当前编辑/添加表单对应的游戏 id（'' 表示手动添加）
        editingId: null,
        // 正在运行的游戏 id（由后端 getRunning 轮询）
        runningId: '',
    },
    // ---- UI 状态（App.ui）----
    ui: {
        // 全局 UI 状态（导航 / 搜索 / 排序 / 批量选择 / 收藏夹筛选）
        state: {
            nav: '全部作品', // 导航：全部作品 / 继续游玩 / 我的收藏 / collection
            kw: '', // 搜索关键词
            sort: '时间', // 排序：时间 / 名称 / 评分
            batch: false, // 批量选择模式
            selected: new Set(), // 批量模式下勾选的游戏 id
            collectionId: null, // 当前筛选的收藏夹 id
            collectionGroupId: null, // 当前筛选所属分组 id（分组筛选时等于 collectionId）
            openGroupId: null, // 侧边栏展开的分组 id（手风琴，互斥单开）
            collectionTree: [], // 收藏夹树形结构
        },
    },
};
// 后端 evaluate_js 注入的入口。
// refresh / toast / reloadCovers 在各自模块中定义，这里必须用函数包装
// （属性值在 state.ts 执行时即求值，直接引用会因跨脚本未定义而 ReferenceError），
// 调用发生在页面交互阶段，此时所有模块已加载完毕。
var __app = {
    refresh: function () { refreshAll(true); },
    toast: function (m) { toast(m); },
    reloadCovers: function () { reloadCovers(); },
    refreshScreenshots: function (gameId) { refreshScreenshots(gameId); },
};

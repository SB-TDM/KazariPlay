// ============================================================
// state.js — 全局共享状态
// 依赖：无（必须最先加载，位于 _JS_MANIFEST 首位）
// 被依赖：所有其它模块
// 注意：顶层 let/const 在所有经典 script 块间共享，各模块可直接引用。
// ============================================================

// 游戏列表快照（每次 refreshAll 整体替换）
let GAMES = [];
// 当前详情打开的游戏对象
let currentGame = null;
// 当前编辑/添加表单对应的游戏 id（'' 表示手动添加）
let editingId = null;
// 正在运行的游戏 id（由后端 getRunning 轮询）
let runningId = '';

// 全局 UI 状态（导航 / 搜索 / 排序 / 批量选择 / 收藏夹筛选）
const state = {
  nav: '全部作品',          // 导航：全部作品 / 继续游玩 / 我的收藏 / collection
  kw: '',                   // 搜索关键词
  sort: '时间',             // 排序：时间 / 名称 / 评分
  batch: false,             // 批量选择模式
  selected: new Set(),      // 批量模式下勾选的游戏 id
  collectionId: null,       // 当前筛选的收藏夹 id
  collectionGroupId: null,  // 当前筛选所属分组 id（分组筛选时等于 collectionId）
  openGroupId: null,        // 侧边栏展开的分组 id（手风琴，互斥单开）
  collectionTree: [],       // 收藏夹树形结构
  collectionOrder: [],      // 当前收藏夹内游戏 id 顺序（拖拽排序用）
};

// 后端 evaluate_js 注入的入口。
// refresh / toast / reloadCovers 在各自模块中定义，这里必须用函数包装
// （属性值在 state.js 执行时即求值，直接引用会因跨脚本未定义而 ReferenceError），
// 调用发生在页面交互阶段，此时所有模块已加载完毕。
window.__app = {
  refresh: function () { refreshAll(true); },
  toast: function (m) { toast(m); },
  reloadCovers: function () { reloadCovers(); },
  refreshScreenshots: function (gameId) { refreshScreenshots(gameId); },
};

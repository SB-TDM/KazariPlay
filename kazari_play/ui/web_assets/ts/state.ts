// ============================================================
// state.ts — 全局共享状态（命名空间收敛，阶段 D 第二步）
// 依赖：无（必须最先加载，位于 _JS_MANIFEST 首位）
// 被依赖：所有其它模块
// 注意：全部共享数据收敛到 App 命名空间（顶层 var → 全局），按功能域拆分：
//       App.data = 业务数据（游戏列表/当前游戏/编辑目标/运行状态）
//       App.ui   = UI 状态（导航/搜索/排序/批量/收藏夹筛选）
//       bridge 保持全局（core.ts 定义，index.html 内联 onclick 直接引用）。
// ============================================================

// ---- 数据模型（与后端 web_bridge.py _game_dict / 收藏夹 JSON 对齐）----

/** 游戏收藏夹关联（后端 collections 数组元素） */
interface CollectionRef {
  id: number;
  name: string;
  color: string;
  icon: string;
}

/** 游戏对象（后端 getGames / getGame 返回的 JSON 结构） */
interface Game {
  id: number;
  title: string;
  exe_path: string;
  dev: string;
  engine: string;
  rating: number;
  fav: boolean;
  tags: string[];
  cat_id: number;
  collections: CollectionRef[];
  play_time: number;
  last_played: string;
  released: string;
  description: string;
  play_time_text: string;
  last_text: string;
  cover_url: string;
  has_cover: boolean;
  cover_version: number;
  translate_enabled: boolean;
  has_hook_code: boolean;
}

/** 收藏夹树节点（后端 getCollectionsTree 返回） */
interface CollectionTreeNode {
  id: number;
  name: string;
  color?: string;
  icon?: string;
  children?: CollectionTreeNode[];
}

/** 全局业务数据命名空间（App.data） */
interface AppDataShape {
  /** 游戏列表快照（每次 refreshAll 整体替换） */
  games: Game[];
  /** 当前详情打开的游戏对象 */
  currentGame: Game | null;
  /** 当前编辑/添加表单对应的游戏 id（'' 表示手动添加） */
  editingId: number | null;
  /** 正在运行的游戏 id（由后端 getRunning 轮询） */
  runningId: string;
}

/** 全局 UI 状态命名空间（App.ui.state） */
interface AppUiStateShape {
  /** 导航：全部作品 / 继续游玩 / 我的收藏 / collection */
  nav: string;
  /** 搜索关键词 */
  kw: string;
  /** 排序：时间 / 名称 / 评分 */
  sort: string;
  /** 批量选择模式 */
  batch: boolean;
  /** 批量模式下勾选的游戏 id */
  selected: Set<number>;
  /** 当前筛选的收藏夹 id */
  collectionId: number | null;
  /** 当前筛选所属分组 id（分组筛选时等于 collectionId） */
  collectionGroupId: number | null;
  /** 侧边栏展开的分组 id（手风琴，互斥单开） */
  openGroupId: number | null;
  /** 收藏夹树形结构 */
  collectionTree: CollectionTreeNode[];
}

/** App 全局对象形状 */
interface AppShape {
  data: AppDataShape;
  ui: { state: AppUiStateShape };
}

// 全局数据命名空间（各模块统一经 App.xxx 读写）
var App: AppShape = {
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
      nav: '全部作品',          // 导航：全部作品 / 继续游玩 / 我的收藏 / collection
      kw: '',                   // 搜索关键词
      sort: '时间',             // 排序：时间 / 名称 / 评分
      batch: false,             // 批量选择模式
      selected: new Set(),      // 批量模式下勾选的游戏 id
      collectionId: null,       // 当前筛选的收藏夹 id
      collectionGroupId: null,  // 当前筛选所属分组 id（分组筛选时等于 collectionId）
      openGroupId: null,        // 侧边栏展开的分组 id（手风琴，互斥单开）
      collectionTree: [],       // 收藏夹树形结构
    },
  },
};

// 后端 evaluate_js 注入的入口。
// refresh / toast / reloadCovers 在各自模块中定义，这里必须用函数包装
// （属性值在 state.ts 执行时即求值，直接引用会因跨脚本未定义而 ReferenceError），
// 调用发生在页面交互阶段，此时所有模块已加载完毕。
var __app = {
  refresh: function (): void { refreshAll(true); },
  toast: function (m: string): void { toast(m); },
  reloadCovers: function (): void { reloadCovers(); },
  refreshScreenshots: function (gameId: number): void { refreshScreenshots(gameId); },
};
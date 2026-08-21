// ============================================================
// pywebview.d.ts — pywebview js_api 桥类型（核心契约，随 web_bridge.py 同步）
//
// 来源：kazari_play/ui/web_bridge.py 的全部公开方法（@expose / js_api）。
// 规则：
//   1. 所有方法名与 web_bridge.py 保持一致（pywebview 按名字注入 window.pywebview.api）。
//   2. 返回 JSON 字符串的方法类型为 string，语义见 JSDoc。
//   3. 后端改动方法时，此文件必须同步更新。
//
// 注意：这是模块声明（含 export {}），不产出运行时输出。
// ============================================================

/** pywebview 注入的 window.pywebview.api（js_api 桥） */
interface PyWebViewApi {
  // ---- 游戏 ----
  /** 全部游戏 JSON 字符串（数组，元素见 Game） */
  getGames(): Promise<string>;
  /** 单游戏 JSON 字符串 */
  getGame(game_id: string): Promise<string>;
  /** 封面 data URI（可能为空串） */
  getCover(game_id: string): Promise<string>;
  /** 标签 JSON 数组 */
  getTags(): Promise<string>;
  /** 分类 JSON 数组 */
  getCategories(): Promise<string>;

  // ---- 配置 ----
  getConfig(): Promise<string>;
  saveConfigs(data_json: string): Promise<unknown>;
  resetConfig(): Promise<unknown>;
  getConfigPath(): Promise<string>;

  // ---- 收藏 / 启动 ----
  toggleFav(game_id: string): Promise<unknown>;
  /** { ok, need_hook_select } */
  launch(game_id: string): Promise<string>;
  /** { list, error } */
  getHookCandidates(): Promise<string>;
  selectHook(game_id: string, handle: number, hook_code: string): Promise<boolean>;
  clearHookCode(game_id: string): Promise<boolean>;
  toggleGameTranslation(game_id: string, enabled: boolean): Promise<boolean>;
  /** 测试翻译：返回译文文本 */
  testTranslation(text?: string): Promise<string>;
  /** 每游戏清洗配置 JSON */
  getCleanFilterConfig(game_id: string): Promise<string>;
  setCleanFilterConfig(game_id: string, filters_json: string): Promise<boolean>;
  openFolder(game_id: string): Promise<unknown>;
  deleteGame(game_id: string): Promise<unknown>;

  // ---- 表单 / 编辑 ----
  saveGame(game_id: string, data_json: string): Promise<unknown>;
  addTag(name: string, color: string): Promise<string>;
  deleteTag(tag_id: number): Promise<unknown>;
  setGameTags(game_id: string, tags_json: string): Promise<unknown>;
  addCategory(name: string): Promise<string>;
  deleteCategory(cat_id: number): Promise<unknown>;
  setGameCategory(game_id: string, cat_id: number): Promise<unknown>;

  // ---- 批量 ----
  batchAddTag(ids_json: string, tag_id: number): Promise<unknown>;
  batchRemoveTag(ids_json: string, tag_id: number): Promise<unknown>;
  batchMoveCategory(ids_json: string, cat_id: number): Promise<unknown>;
  batchDelete(ids_json: string): Promise<unknown>;

  // ---- 收藏夹 ----
  getCollectionsTree(): Promise<string>;
  createCollection(name: string, parent_id: number, icon: string, color: string): Promise<string>;
  updateCollection(collection_id: number, data_json: string): Promise<unknown>;
  deleteCollection(collection_id: number): Promise<unknown>;
  reorderCollection(collection_id: number, new_sort_order: number): Promise<unknown>;
  addGamesToCollection(ids_json: string, collection_id: number): Promise<unknown>;
  removeGamesFromCollection(ids_json: string, collection_id: number): Promise<unknown>;
  setGameCollections(game_id: string, collection_ids_json: string): Promise<unknown>;
  setCollectionGames(collection_id: number, ids_json: string): Promise<boolean>;
  getGamesInCollection(collection_id: number): Promise<string>;
  moveGameInCollection(collection_id: number, game_id: string, new_sort_order: number): Promise<unknown>;
  batchMoveToCollection(ids_json: string, collection_id: number): Promise<unknown>;
  batchRemoveFromCollection(ids_json: string, collection_id: number): Promise<unknown>;

  // ---- 扫描 / VNDB 匹配 ----
  scanFolder(): Promise<string>;
  getBatchProgress(): Promise<string>;
  selectExe(): Promise<string>;
  matchVndb(game_id: string): Promise<string>;
  matchVndbBatch(ids_json: string): Promise<string>;
  setRating(game_id: string, rating: number): Promise<unknown>;
  getRunning(): Promise<string>;
  updateScreenshotHotkey(hotkey?: string): Promise<boolean>;

  // ---- 截图 ----
  takeScreenshot(game_id: string): Promise<string>;
  takeScreenshotRunning(): Promise<string>;
  getScreenshots(game_id: string): Promise<string>;
  getScreenshotThumb(game_id: string, filename: string): Promise<string>;
  deleteScreenshot(game_id: string, filename: string): Promise<boolean>;
  renameScreenshot(game_id: string, filename: string, new_name: string): Promise<boolean>;
  openScreenshotFolder(game_id: string, filename: string): Promise<boolean>;
  copyScreenshotToClipboard(game_id: string, filename: string): Promise<boolean>;

  // ---- 封面 / 元数据 ----
  pickCover(): Promise<string>;
  setCover(game_id: string, path: string): Promise<unknown>;
  searchMetadata(keyword: string, sources_json?: string): Promise<string>;
  getMetadataSources(): Promise<string>;
  saveMetadataSources(sources_json: string): Promise<unknown>;
  applyCandidate(game_id: string, candidate_json: string): Promise<unknown>;
  startAutoScan(): Promise<unknown>;

  // ---- 通用后端事件 ----
  refresh(): Promise<unknown>;
  notify(msg: string): Promise<unknown>;

  // ---- 字幕样式 ----
  getSubtitleStyle(): Promise<string>;
  setSubtitleStyle(style_json: string): Promise<unknown>;
  previewSubtitle(): Promise<unknown>;
  setSubtitleDrag(drag: boolean): Promise<unknown>;
  hideSubtitle(): Promise<unknown>;
  setSubtitleEnabled(enabled: boolean): Promise<unknown>;
  getSubtitleStylePresets(): Promise<string>;
  saveSubtitlePreset(name: string, style_json: string): Promise<string>;
  deleteSubtitlePreset(name: string): Promise<string>;

  // ---- 通用通知 ----
  reloadCovers(): Promise<unknown>;

  // ---- 窗口控制 ----
  windowMinimize(): Promise<unknown>;
  windowToggleMaximize(): Promise<unknown>;
  windowMaximize(): Promise<unknown>;
  windowRestore(): Promise<unknown>;
  windowClose(): Promise<unknown>;
  windowStartDrag(gx: number, gy: number): Promise<unknown>;
  windowMoveDrag(gx: number, gy: number): Promise<unknown>;
  windowEndDrag(): Promise<unknown>;
  windowResizeStart(direction: string): Promise<unknown>;
  windowResize(direction: string, dx: number, dy: number): Promise<unknown>;
}

declare global {
  /** pywebview 注入的 window.pywebview */
  interface PyWebView {
    api: PyWebViewApi;
    evaluate_js?(code: string): unknown;
  }

  interface Window {
    pywebview?: PyWebView;
    bridgeReady?: boolean;
  }
}

export {};
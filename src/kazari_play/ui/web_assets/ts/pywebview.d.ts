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
  /** 封面 data URI（服务不可用时的回退通道，可能为空串） */
  getCover(game_id: string): Promise<string>;
  /** 设置手动封面；返回 {ok, msg} JSON 字符串 */
  setCover(game_id: string, path: string): Promise<string>;
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
  /** { ok } */
  launch(game_id: string): Promise<string>;
  openFolder(game_id: string): Promise<unknown>;
  deleteGame(game_id: string): Promise<unknown>;

  // ---- 表单 / 编辑 ----
  /** { ok, msg }，空 game_id 表示新增 */
  saveGame(game_id: string, data_json: string): Promise<string>;
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
  // 写接口统一返回 {ok, msg} JSON 字符串；业务失败时 ok=false 并带提示
  updateCollection(collection_id: number, data_json: string): Promise<string>;
  deleteCollection(collection_id: number): Promise<string>;
  reorderCollection(collection_id: number, new_sort_order: number): Promise<string>;
  addGamesToCollection(ids_json: string, collection_id: number): Promise<string>;
  removeGamesFromCollection(ids_json: string, collection_id: number): Promise<string>;
  setGameCollections(game_id: string, collection_ids_json: string): Promise<string>;
  setCollectionGames(collection_id: number, ids_json: string): Promise<boolean>;
  getGamesInCollection(collection_id: number): Promise<string>;
  moveGameInCollection(collection_id: number, game_id: string, new_sort_order: number): Promise<string>;
  batchMoveToCollection(ids_json: string, collection_id: number): Promise<string>;
  batchRemoveFromCollection(ids_json: string, collection_id: number): Promise<string>;

  // ---- 扫描 / VNDB 匹配 ----
  scanFolder(): Promise<string>;
  /** 导入扫描预览中勾选的游戏（token 来自 showScanPreview 推送）；返回 {ok, added} */
  applyScanPreview(token: number, keys_json: string): Promise<string>;
  cancelScan(): Promise<unknown>;
  cancelMatch(): Promise<unknown>;
  getBatchProgress(): Promise<string>;
  selectExe(): Promise<string>;
  setTheme(theme: string): Promise<unknown>;
  matchVndb(game_id: string): Promise<string>;
  matchVndbBatch(ids_json: string): Promise<string>;
  retryFailedMatches(): Promise<string>;
  getUnmatchedInfo(game_id: string): Promise<string>;
  mergeGames(source_id: string, target_id: string): Promise<string>;
  dismissUnmatched(game_id: string): Promise<string>;
  previewRelocate(ids_json: string): Promise<string>;
  /** 取消正在进行的重新定位预览扫描；无任务时返回 false */
  cancelRelocate(): Promise<boolean>;
  applyRelocate(mapping_json: string): Promise<string>;
  setRating(game_id: string, rating: number): Promise<boolean>;

  // ---- 应用内更新 ----
  getUpdateState(): Promise<string>;
  checkUpdate(force?: boolean): Promise<string>;
  /** 本地探测就绪缓存（不联网）；启动时自动提示「更新包已就绪」 */
  probeReadyUpdate(): Promise<string>;
  downloadUpdate(): Promise<string>;
  skipUpdate(): Promise<string>;
  applyUpdate(): Promise<string>;
  openReleasePage(): Promise<boolean>;
  /** 前端首屏数据加载成功后的就绪握手；返回完成提示（如「已更新到 vX」），无更新时为空串 */
  updateFrontendReady(): Promise<string>;

  getRunning(): Promise<string>;
  updateScreenshotHotkey(hotkey?: string): Promise<boolean>;

  // ---- 截图 ----
  takeScreenshot(game_id: string): Promise<string>;
  takeScreenshotRunning(): Promise<string>;
  getScreenshots(game_id: string): Promise<string>;
  getScreenshotThumb(game_id: string, filename: string): Promise<string>;
  getScreenshotOriginal(game_id: string, filename: string): Promise<string>;
  deleteScreenshot(game_id: string, filename: string): Promise<boolean>;
  renameScreenshot(game_id: string, filename: string, new_name: string): Promise<boolean>;
  openScreenshotFolder(game_id: string, filename: string): Promise<boolean>;
  copyScreenshotToClipboard(game_id: string, filename: string): Promise<boolean>;

  // ---- 封面 / 元数据 ----
  pickCover(): Promise<string>;
  searchMetadata(keyword: string, sources_json?: string): Promise<string>;
  getMetadataSources(): Promise<string>;
  saveMetadataSources(sources_json: string): Promise<unknown>;
  /** 测试 VNDB/Bangumi/Kungal 连通性；payload={mode:"system|direct|custom",proxy_url} */
  testMetadataConnection(payload_json?: string): Promise<string>;
  applyCandidate(game_id: string, candidate_json: string, fields_json?: string): Promise<unknown>;

  // ---- 通用后端事件 ----
  refresh(): Promise<unknown>;
  notify(msg: string): Promise<unknown>;

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

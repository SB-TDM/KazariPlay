// ============================================================
// globals.d.ts — 未迁移 JS 模块暴露的全局声明（渐进迁移用）
//
// 作用：TS 模块迁移过程中，尚未迁移的 js/ 模块（如 games.js）定义
//       的全局函数/变量，需要在这里用 declare 声明，TS 侧才能引用。
//       每迁移一个模块，就把对应声明从这里删除（移到该模块的 .ts 里）。
//
// 注意：
//   1. 本文件是唯一允许 export {} 的文件（declare global 需要模块上下文，
//      但 d.ts 不产出运行时输出，不影响 script 加载形态）。
//   2. 声明必须与实际实现保持同步（verify 脚本会检查）。
//   3. 运行时名称只加类型不改名。
// ============================================================

// ---- state.ts 引用（定义在未迁移的 js/ 模块中）----
declare global {
  function refreshAll(force: boolean): void;              // js/games.js
  function toast(msg: string): void;                      // js/core.js
  function reloadCovers(): void;                          // js/games.js
  function refreshScreenshots(gameId: number): void;      // js/screenshots.js

  // ---- js/hook_select.js（IIFE，阶段 8 迁移）----
  interface HookSelectApi {
    open(gameId: number): void;
    close(): void;
  }
  var HookSelect: HookSelectApi;
}

export {};
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

// ---- 未迁移 JS 模块的全局声明（随迁移逐步清空）----
declare global {
  /** Hook 候选（后端 getHookCandidates 返回 list 元素） */
  interface HookCandidate {
    handle: number;
    hook_code?: string;
    hook_name?: string;
    text?: string;
  }

  /** js/settings.js 提供（IIFE，阶段 8 迁移） */
  var CLEAN_FILTER_DEFS: CleanFilterDef[];

  /** js/hook_select.js 提供（core.ts launchGame 引用） */
  interface HookSelectApi {
    open(gameId: number): void;
    close(): void;
  }
  var HookSelect: HookSelectApi;

  // ---- 以下 window 属性由 ts/ 中的 IIFE 模块自含定义 ----
  var updateSubtitlePos: ((x: number, y: number) => void) | undefined;
  interface SubtitleStyleApi {
    load(): void;
  }
  var SubtitleStyle: SubtitleStyleApi;
  interface SettingsApi {
    open(): void;
    close(): void;
    pickTheme(t: string): void;
    applyTheme(t: string): void;
  }
  var Settings: SettingsApi;
}

export {};
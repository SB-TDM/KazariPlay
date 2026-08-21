// ============================================================
// globals.d.ts — 全局类型契约（跨文件共享的类型与 window 属性声明）
//
// 演进：TS 渐进迁移完成后，原「未迁移 JS 模块的全局声明」已全部清空。
// 本文件现在只承担两类职责：
//   1. 跨文件共享的全局接口（HookCandidate 等），供多个 .ts 引用。
//   2. IIFE 模块暴露的 window 属性契约（HookSelect / SubtitleStyle / Settings 等），
//      供 core.ts / detail_translate.ts / app.ts 等消费方引用。
//
// 注意：
//   1. 本文件是唯一允许 export {} 的文件（declare global 需要模块上下文，
//      但 d.ts 不产出运行时输出，不影响 script 加载形态）。
//   2. window 属性的实现位于各自 ts/ 文件内（IIFE 赋值），此处仅声明类型。
//   3. 运行时名称只加类型不改名。
// ============================================================

declare global {
  /** Hook 候选（后端 getHookCandidates 返回 list 元素） */
  interface HookCandidate {
    handle: number;
    hook_code?: string;
    hook_name?: string;
    text?: string;
  }

  /** 清洗过滤器定义（settings.ts FILTER_DEFS 暴露） */
  var CLEAN_FILTER_DEFS: CleanFilterDef[];

  /** Hook 选择弹窗（hook_select.ts 暴露；core.ts launchGame 消费） */
  interface HookSelectApi {
    open(gameId: number): void;
    close(): void;
  }
  var HookSelect: HookSelectApi;

  /** 字幕样式面板（subtitle_style.ts 暴露；settings.ts 消费） */
  var updateSubtitlePos: ((x: number, y: number) => void) | undefined;
  interface SubtitleStyleApi {
    load(): void;
  }
  var SubtitleStyle: SubtitleStyleApi;

  /** 设置窗口（settings.ts 暴露；app.ts / core.ts 消费） */
  interface SettingsApi {
    open(): void;
    close(): void;
    pickTheme(t: string): void;
    applyTheme(t: string): void;
  }
  var Settings: SettingsApi;
}

export {};
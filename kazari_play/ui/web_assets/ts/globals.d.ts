// ============================================================
// globals.d.ts — 全局类型契约（跨文件共享的类型与 window 属性声明）
//
// 演进：TS 渐进迁移完成后，原「未迁移 JS 模块的全局声明」已全部清空。
// 本文件现在只承担两类职责：
//   IIFE 模块 Settings 暴露给其它经典脚本的 window 属性契约。
//
// 注意：
//   1. 本文件是唯一允许 export {} 的文件（declare global 需要模块上下文，
//      但 d.ts 不产出运行时输出，不影响 script 加载形态）。
//   2. window 属性的实现位于各自 ts/ 文件内（IIFE 赋值），此处仅声明类型。
//   3. 运行时名称只加类型不改名。
// ============================================================

declare global {
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

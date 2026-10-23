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
  interface SettingsHotkeyValues {
    emergency_hide: string;
    fullscreen_toggle: string;
    mute_toggle: string;
    screenshot: string;
  }

  interface SettingsCoverDownload {
    preferred_source: string;
    timeout: number;
    max_concurrent: number;
  }

  interface SettingsMetadataSourceConfig {
    shionlib_api_key: string;
    kungal_concurrency: number;
  }

  interface SettingsNetwork {
    proxy_mode: string;
    proxy_url: string;
  }

  interface SettingsConfig {
    cover_size?: string;
    log_level?: string;
    disguise_scene?: string;
    show_console?: boolean;
    cover_download?: Partial<SettingsCoverDownload>;
    metadata_sources?: Partial<SettingsMetadataSourceConfig>;
    network?: Partial<SettingsNetwork>;
    hotkeys?: Partial<SettingsHotkeyValues>;
    theme?: string;
    path?: string;
  }

  interface SettingsFormValues {
    cover_size: string;
    log_level: string;
    disguise_scene: string;
    show_console: boolean;
    cover_download: SettingsCoverDownload;
    metadata_sources: SettingsMetadataSourceConfig;
    network: SettingsNetwork;
  }

  interface SettingsModelApi {
    parse(raw: unknown): SettingsConfig | null;
    fmtKey(value: unknown): string;
    defaults: SettingsHotkeyValues;
    hotkeys(cfg: SettingsConfig): SettingsHotkeyValues;
  }

  interface SettingsThemeApi {
    beginLoad(): void;
    applyLoaded(theme: string): void;
    initTheme(theme: string): void;
    pickTheme(theme: string): void;
    applyTheme(theme: string): void;
    current(): string;
  }

  interface SettingsHotkeysApi {
    bindAll(): void;
    load(values: SettingsHotkeyValues): void;
    read(): SettingsHotkeyValues;
    stop(restore: boolean): void;
  }

  interface SettingsFieldsApi {
    bind(isCurrent: () => boolean): void;
    load(cfg: SettingsConfig): void;
    read(): SettingsFormValues;
  }

  interface SettingsSourcesApi {
    load(isCurrent: () => boolean): void;
    readChecked(): string[] | null;
  }

  interface SettingsKitApi {
    model: SettingsModelApi;
    theme: SettingsThemeApi;
    hotkeys: SettingsHotkeysApi;
    fields: SettingsFieldsApi;
    sources: SettingsSourcesApi;
  }

  interface Window {
    SettingsKit: SettingsKitApi;
  }

  /** 设置窗口（settings.ts 暴露；app.ts / core.ts 消费） */
  interface SettingsApi {
    open(): void;
    close(): void;
    pickTheme(t: string): void;
    applyTheme(t: string): void;
    /** 启动时初始主题：用户已自行选择过则不覆盖 */
    initTheme(t: string): void;
  }
  var Settings: SettingsApi;
}

export {};

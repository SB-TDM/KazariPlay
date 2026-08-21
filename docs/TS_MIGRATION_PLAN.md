# KazariPlay 前端 TypeScript 渐进迁移计划书

> 版本：V1.0（计划稿）
> 状态：**已实施完成（2026-08-21）**，全部 17 个模块迁移至 `ts/`，`js/` 为编译产物
> 日期：2026-08-21
> 范围：`kazari_play/ui/web_assets/` 前端 JS → TS 渐进迁移；main.py / verify_frontend.py / 打包流程零改动
> 原则：小步可验证、每模块独立可回退、JS 与 TS 全程共存、架构（经典 script 内联注入）保持不变

---

## 1. 背景与现状

### 1.1 现有架构

前端由 pywebview（Edge WebView2）以 `html=` 模式渲染：`main.py::_load_html()` 启动时把
`index.html` 的 `<!-- SCRIPTS -->` 占位符替换为 **17 个 `<script>` 块**（`_JS_MANIFEST`，
按依赖顺序），全部内联进单个 HTML 字符串。中文路径下无法用 `file://` 加载外部资源，
因此**前端不能使用 ES Module（import/export）**。

模块化采用「按文件拆分 + 顶层声明共享」的经典脚本方案：

```html
<script>/* state.js：顶层 var/function 即全局 */</script>
<script>/* core.js：可引用 state.js 的全局 */</script>
...
```

等价于"按文件拆分的单文件脚本"，顶层 `let/const/function` 在所有块间共享。

### 1.2 现状清单（17 模块，约 2400 行）

| 文件 | 职责 | 加载序 | 定义的关键全局 |
|---|---|---|---|
| state.js | 全局共享状态 | 1 | `window.App`（data/ui）`window.__app` |
| core.js | bridge 代理 + 通用工具 | 2 | `bridge` `esc` `toast` `stars` `chipColor` `loadCoverTo` |
| ui.js | Sheet / 对话框 / 右键菜单 | 3 | `showSheet` `closeSheet` `showConfirmDialog` 等 |
| window.js | 无边框窗口控制 | 4 | `toggleMax` `bindDrag` `bindResize` |
| games.js | 游戏数据 / 筛选 / 渲染调度 | 5 | `refreshAll` `renderAll` `filterGames` 等 |
| cards.js | 卡片 DOM / 懒加载 / 右键 | 6 | `buildCard` `renderCards` `openCardMenu` |
| detail.js | 详情抽屉 | 7 | `openDetail` `refreshDetail` 等 |
| detail_translate.js | 实时翻译行 + 清洗配置 | 8 | `renderTransRow` `loadCleanCfg` 等 |
| screenshots.js | 截图卡片 / 预览 / 管理 | 9 | `renderScreenshots` `refreshScreenshots` 等 |
| collections.js | 收藏夹树 / 管理抽屉 | 10 | `renderCollectionTree` 等 |
| manage_games.js | 管理游戏对话框 | 11 | `openManageGames` 等 |
| batch.js | 批量选择模式 | 12 | `updateBatchBar` 等 |
| form.js | 编辑 / 添加表单 | 13 | `openEdit` `openAdd` `saveForm` 等 |
| hook_select.js | Hook 选择弹窗（IIFE） | 14 | `window.HookSelect` |
| subtitle_style.js | 字幕样式面板（IIFE） | 15 | `window.SubtitleStyle` |
| settings.js | 设置窗口（IIFE） | 16 | `window.Settings` `window.CLEAN_FILTER_DEFS` |
| app.js | 启动引导（粘合层，最后） | 17 | `init` `bindFilterMenu` |

### 1.3 为什么值得迁移

1. **bridge 无类型**：`bridge.xxx(cb)` 走 Proxy，所有 API 返回 `Promise` / 字符串，跨模块全靠
   人肉记忆，改一个后端方法名编译期零反馈。
2. **跨模块隐式耦合**：UI_REDESIGN_PLAN 已记录的 P1-5 架构债——全局作用域共享 + 无类型，
   改一处崩三处。
3. **数据形状无契约**：`App.data.games` / 后端返回 JSON 均为 `any`，字段拼写错误只能运行时暴露。

---

## 2. 目标与非目标

### 目标
1. **渐进式替换**：17 个模块逐个迁移，任一时刻 JS 与 TS 产物共存，均可正常加载运行。
2. **架构零破坏**：保持「多 `<script>` 块内联 + 顶层声明共享」，`main.py`、`_JS_MANIFEST`、
   `verify_frontend.py`、PyInstaller 打包流程**全部不用改**。
3. **类型随迁随建**：每迁移一个模块，就为它暴露的全局建类型；bridge API 类型从
   `web_bridge.py` 的 `@expose` 方法人工提炼为 `.d.ts`，后续迁移模块直接受益。
4. **严格模式全开**：`strict: true`，迁移过程即 bug 暴露过程（隐式全局、空引用等）。

### 非目标（本计划不做）
- 不引入 ES Module / import / export / bundler（受 `html=` 内联注入约束，见 §7 风险）。
- 不引入前端框架（Vue/React），不做 UI 重构。
- 不一次性全量重写（就是渐进）。
- 不改 CSS / HTML / partials / web_bridge.py / C++ overlay。

---

## 3. 总体方案（已验证可行）

### 3.1 核心机制：TS 编译为"经典 script"，与手写 JS 产物形态完全一致

用 `tsc` 把每个 `.ts` 编译为**独立的全局脚本**（不包裹 IIFE、不产生 import/export），
产物与现有手写 JS 的加载形态一模一样：

```ts
// ts/state.ts —— 顶层声明即全局
interface AppShape { data: ...; ui: ...; }
var App: AppShape = { ... };          // 编译后仍是顶层 var（全局）
function refreshAll(force: boolean): void { ... }
```

```js
// 编译产物 js/state.js —— 与手写 JS 无差别
"use strict";
var App = { ... };
function refreshAll(force) { ... }
```

### 3.2 目录结构（新增 ts/，其余不动）

```
web_assets/
├── ts/                  # TS 源（本计划新增，逐步增加）
│   ├── state.ts
│   ├── core.ts
│   ├── ...（逐模块迁移）
│   ├── globals.d.ts     # 声明"未迁移 JS 模块"暴露的全局（随迁移逐步清空）
│   └── pywebview.d.ts   # bridge API / window.pywebview 类型（阶段 2 建立）
├── js/                  # 手写 JS（未迁移）+ TS 编译产物（迁移后同名覆盖）
├── tsconfig.json        # 本计划新增
├── package.json         # 本计划新增（仅 typescript devDependency）
└── index.html / css/ / partials/ / images/   # 不动
```

关键设计：
- **ts 源放 `ts/`，产物输出到 `js/` 同名文件**（`rootDir: ts`、`outDir: js`）。迁移一个模块 =
  新建 `ts/xxx.ts` → 编译覆盖 `js/xxx.js` → 删除手写 `js/xxx.js`。`_JS_MANIFEST` 只写文件名，
  **main.py 零改动**。
- 产物头部带 `// GENERATED from ts/xxx.ts — DO NOT EDIT` 注释，与手写 JS 区分。
- 未迁移模块的手写 JS 原地保留，与产物 JS 共存于 `js/`，加载顺序与行为完全不变。

### 3.3 编译配置（tsconfig.json，已实测验证）

```jsonc
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "preserve",        // TS6 已移除 module:"none"，preserve 下无 import/export 即 script
    "moduleDetection": "auto",   // 无 import/export 的文件按全局 script 处理
    "strict": true,
    "outDir": "js",
    "rootDir": "ts",
    "removeComments": false,     // 保留中文注释
    "sourceMap": false
  },
  "include": ["ts/**/*.ts"]
}
```

实测结论（TS 6.x）：
1. 多个 `.ts` 文件（无 import/export）编译为一个 program，**顶层声明跨文件类型共享**
   （a.ts 定义 `var App` + `function toast()`，b.ts 直接引用，类型检查通过）。
2. 产物为纯全局脚本，仅带 `"use strict";` 前缀，与手写 JS 共存无冲突。
3. 引用**未迁移 JS** 的全局：在任一 `.ts` 中 `declare function filterGames(): void;` 即可
   （集中放 `globals.d.ts`，随迁移清空）。
4. 产物覆盖 `js/` 同名文件时，未迁移的手写 JS 不受影响（tsc 只输出 ts/ 存在的文件）。

### 3.4 纪律（硬性约束）

1. **ts 源禁止 `import` / `export`**——一旦出现即被 `moduleDetection` 判为模块，产物形态改变，
   破坏全局共享。改用 `declare` + 全局声明（globals.d.ts）跨文件引用。
2. 文件头部保留「依赖 / 定义 / 被依赖」注释风格（对齐 web_assets/README.md 现有约定）。
3. 每迁移一个模块：`ts/xxx.ts`（源）+ `js/xxx.js`（产物）+ 删除手写旧文件，**同一个 commit**，
   可整体回退。
4. 不改任何全局的**运行时名称**（`bridge` / `App` / `refreshAll` 等），只加类型。
5. 顶层声明的**接口/类型**（`interface AppShape` 等）编译后不产生运行时输出，可放心用。

---

## 4. 阶段规划（17 模块按依赖序自底向上迁移）

> 每个阶段完成后：`npm run build` → `python tests/verify_frontend.py` → 手动冒烟 →
> 通过则提交。任何阶段可单独回退（git revert 该 commit）。

| 阶段 | 内容 | 交付物 / 验证重点 | 预计改动 |
|---|---|---|---|
| **0. 工具链** | 新建 `tsconfig.json`、`package.json`（typescript devDep）、`globals.d.ts` 骨架、README 增补 | 空转构建通过；verify_frontend.py 仍绿 | 小 |
| **1. state.js** | 建 `AppShape` 核心数据模型（games/collection/ui.state），`window.App` / `window.__app` 类型化 | 全站数据形状类型化；启动正常 | 小 |
| **2. core.js** | 建 `pywebview.d.ts`（从 web_bridge.py `@expose` 提炼全部 API 签名）；`bridge` 代理类型化（泛型 `bridge<T>(...)`）；`esc/toast/stars/chipColor/loadCoverTo` 加签名 | **bridge 全 API 有类型**，后续模块迁移最大受益点 | 中 |
| **3. ui.js + window.js** | Sheet / 对话框 / 右键菜单 / 窗口控制类型化 | 对话框链路正常 | 小 |
| **4. games.js + cards.js** | 筛选 / 渲染调度 / 卡片 DOM 类型化；`App.data.games` 全量接入类型 | 核心渲染链路正常 | 中 |
| **5. detail.js + detail_translate.js + screenshots.js** | 详情 / 翻译行 / 截图管理类型化 | 详情链路正常 | 中 |
| **6. collections.js + manage_games.js + batch.js** | 收藏夹 / 批量链路类型化 | 收藏夹 / 批量模式正常 | 中 |
| **7. form.js** | 表单 / 元数据候选类型化 | 添加 / 编辑表单正常 | 中 |
| **8. hook_select.js + subtitle_style.js + settings.js** | 三个 IIFE 模块迁移：`window.HookSelect` 等改为 `declare global` + 具名实现，暴露 API 不变 | 设置 / Hook 选择 / 字幕样式正常 | 中 |
| **9. app.js** | 粘合层最后迁移（依赖全部就绪） | 全站功能回归冒烟 | 小 |
| **10. 收尾** | 删除 `globals.d.ts` 残留声明；README 同步；可选：PyInstaller spec 排除 `ts/` 减小体积 | 全部 JS 为零，纯 TS 源 + 产物 | 小 |

### 4.1 依赖图（迁移顺序依据）

```
state(1) → core(2) → ui(3) ─┬→ games(4) → cards(4) → detail(5) → screenshots(5)
                            └→ window(3) ─→ collections(6) → manage_games(6) → batch(6)
                                          → detail_translate(5) → form(7)
                                          → hook_select(8) / subtitle_style(8) / settings(8)
                                          → app(9)
```

> 每个模块的"被依赖"模块必须先迁移（保证 TS 侧类型可见）；依赖它的模块可后迁移
> （通过 globals.d.ts 的 `declare` 临时声明，不影响运行）。

### 4.2 IIFE 模块迁移模板（阶段 8 用）

```ts
// ts/settings.ts —— 保持 IIFE，暴露方式不变
(function () {
  const $ = (id: string) => document.getElementById(id);
  // ...原逻辑，补类型
  window.Settings = { open, close, applyTheme, ... };
  window.CLEAN_FILTER_DEFS = FILTER_DEFS;
})();

// ts/globals.d.ts —— 声明给其它（含未迁移 JS）模块
declare global {
  interface Window { Settings: SettingsApi; CLEAN_FILTER_DEFS: FilterDef[]; ... }
}
export {};   // 仅此一个文件允许 export（模块上下文里才能 declare global）
```

> 注：`globals.d.ts` 是唯一允许 `export {}` 的文件——`declare global` 要求模块上下文，
> 而 d.ts 不产出运行时输出，不影响 script 加载形态。

---

## 5. 每阶段验证清单

| 检查 | 命令 / 方式 | 通过标准 |
|---|---|---|
| TS 编译 | `npm run build`（web_assets/ 下 `npx tsc`） | 0 错误 0 警告（strict） |
| 前端完整性 | `python tests/verify_frontend.py` | OK：script 块数 = 17、HTML id 无重复、JS id 引用全命中 |
| 手工冒烟 | `python kazari_play/main.py` | 启动 → 游戏列表 → 详情 → 设置 → 收藏夹 → 批量，无 console 报错 |
| 打包冒烟（里程碑） | 构建目录 PyInstaller 重打 | 打包产物功能与源码一致（阶段 2 / 5 / 9 各一次） |
| 回归（可选） | `python tests/smoke_*.py`、`verify_bridge` | 现有冒烟脚本通过 |

---

## 6. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| `"use strict"` 前缀改变运行行为（隐式全局赋值抛 ReferenceError） | 中 | 迁移时把隐式全局改为显式 `var` / `window.x`；**严格模式暴露的正是既有 bug**，迁移过程修复并记录 |
| TS6 移除 `module:"none"`，配置踩坑 | 低 | 已实测 `module:"preserve"` + `moduleDetection:"auto"` 可行（§3.3） |
| 编译产物与手写 JS 混淆 | 低 | 产物头部 `// GENERATED` 注释；git 历史可追溯；迁移后旧手写文件删除 |
| `declare` 声明与真实实现漂移（globals.d.ts 里声明了已迁移模块的函数） | 中 | 纪律：迁移即删声明；verify 脚本可选加"globals.d.ts 声明必须能在 js/ 或 ts/ 找到实现"检查 |
| 打包体积增加（ts/ 源被 PyInstaller 收进） | 低 | 阶段 10 可选在 spec datas 里排除 `ts/`（或只打 `js/`） |
| 中文路径 / WebView2 兼容性 | 低 | 产物仍是普通 JS，内联注入机制不变，无新风险 |

---

## 7. 明确不做的事（边界）

1. **不引入 ES Module**。若未来要彻底模块化，需先解决 `html=` 内联注入（改用打包器产出
   单文件 bundle 或本地 http 服务），这是独立的架构变更，不在本计划内。
2. **不引入 bundler / npm 运行时依赖**。typescript 仅为 devDependency，产物是纯 JS，
   打包产物与用户环境零 Node 依赖。
3. **不改 main.py 注入机制**。`_JS_MANIFEST` 顺序、`_load_html()`、verify_frontend.py 全部保持。

---

## 8. 里程碑与验收

- **M1（阶段 0-2）**：工具链 + state + core。bridge API 全部类型化——迁移的"最大单点收益"。
- **M2（阶段 3-6）**：核心链路（渲染 / 详情 / 收藏夹 / 批量）TS 化，此时约 60% 模块完成。
- **M3（阶段 7-9）**：全站 TS 化，手写 JS 归零。
- **M4（阶段 10）**：收尾清理 + 文档同步。

每里程碑做一次完整打包验证（构建目录 PyInstaller + 手动冒烟）。

---

## 9. 附：立即开工第一步（阶段 0 具体动作）

1. `web_assets/` 下新建 `package.json`（`{"devDependencies": {"typescript": "^6"}}`）与
   `tsconfig.json`（§3.3 配置）。
2. `web_assets/ts/` 新建空 `globals.d.ts`（含骨架注释）。
3. `npm install` 安装 typescript；`npx tsc` 空转验证 0 输出 0 错误。
4. 确认 `python tests/verify_frontend.py` 仍绿、`python kazari_play/main.py` 正常。
5. 提交阶段 0。
# KazariPlay UI 审查修复 + 字幕控制面板 — 交接文档

> 生成时间：2026-08-16
> 会话范围：① 前端（web_assets/）按 Web Interface Guidelines 全面审查与修复 → ② 按《Overlay 控制面板设计方案》实现字幕样式控制面板（C++ 渲染参数化 + pywebview 独立置顶窗口 + 管道下发）
> 对接提示：接手前先读本会话相关设计来源：《Overlay 控制面板设计方案（简洁落地版）》（对话中整理的 PRD）、`docs/CHANGELOG.md`

> **⚠️ V1.2.2 架构变更（2026-08-16）**：独立「字幕控制面板」窗口已**取消**，字幕样式控件并入主 GUI 设置窗口「翻译」tab（`settings.html` + `settings.js`），`control_panel.html` 已删除。下面第二、四、五、六、七、八节含独立窗口的内容以本节说明为准：
> - **删除**：`main.py` 的 `_panel_html` / `_create_panel_window`；`web_bridge.py` 的 `setPanelWindow` / `getPanelState` / `savePanelState` / `setPanelClickThrough` / `panelCollapse`；`control_panel.html`。
> - **保留**（桥接口不变）：`getSubtitleStyle` / `setSubtitleStyle` / `getSubtitleStylePresets` / `previewSubtitle` / `setSubtitleDrag` / `hideSubtitle` / `setSubtitleEnabled` / `_ensure_subtitle_pos_handler`。
> - **位置回传**：`_ensure_subtitle_pos_handler` 的 `_forward` 由 `_panel_win.evaluate_js` 改为主窗口 `self._window.evaluate_js` → 调用 `window.updateSubtitlePos`（在 settings.js 定义）。
> - **「显示字幕」开关**：设置页既有 `setSubtitleEnabled` 开关现与 C++ 字幕总开关统一——change 时实时下发 `set_subtitle_enabled`，持久化 `subtitle.enabled`（原 `overlay.subtitle_enabled` 为遗留键，读初始化后不再单独生效）。
> - 新字幕控件（`setSub*` 前缀）样式在 `style.css` 的 `.sub-sec` 区块（适配浅/深双主题）。

---

## 一、会话改动总览

### 阶段 1：前端审查与修复（web-design-guidelines）

对 `kazari_play/ui/web_assets/` 全部文件（index.html、css/style.css、12 个 JS、6 个 partials）审查，修复清单见第四节。全部通过 `tests/verify_frontend.py` 与 `node --check`。

### 阶段 2：Overlay 字幕控制面板（核心新功能）

**架构链路**：

```
[控制面板 pywebview 窗口 control_panel.html]   ← 独立置顶 330x560，可折叠 36，记住位置
        │ WebBridge（js_api，camelCase）
        ▼
[WebBridge.setSubtitleStyle / setSubtitleDrag / previewSubtitle / hideSubtitle / setSubtitleEnabled / setPanelClickThrough / panelCollapse]
        │ OverlayClient 单例（命名管道 KazariPlayOverlay_{pid}）
        ▼
[C++ overlay.exe]  set_subtitle_style / set_subtitle_drag / preview_subtitle
        │  SubtitleWindow::applyStyle → 重建 text format → reposition(force) → D2D 重绘
        ▼
[游戏画面底部字幕]   拖拽结束 → subtitle_pos 回传 → 控制面板滑块同步
```

---

## 二、Overlay 控制面板 — 关键文件

### C++（overlay/src/，`build.bat` 单版本编译，改后必须重编）
| 文件 | 职责 |
|---|---|
| `subtitle_style.h`（**新增**） | `SubtitleStyle` 结构体 + `ParseSubtitleStyle(JSON)`：全字段值域裁剪（ClampF），默认值 = 原半透明黑底主题。字段名 snake_case 与前端 JS 一一对应 |
| `subtitle_window.h/cpp` | 渲染全面参数化；新增 `applyStyle` / `setDragMode` / `showPreview` / `reposition(gr, force)` / `resolveTargetRect()` / `setPositionCallback`；拖拽处理（WM_LBUTTONDOWN/MOVE/UP） |
| `protocol.h` | 新增 `SetSubtitleStyle` / `SetSubtitleDrag` / `PreviewSubtitle` 入站消息 + `SubtitlePos` 出站序列化 |
| `main.cpp` | 处理 3 条新命令；`subtitle.setPositionCallback` → `sendToClient(serializeSubtitlePos)`（UI 线程，sendToClient 有临界区保护） |

### Python（kazari_play/）
| 文件 | 职责 |
|---|---|
| `core/overlay_client.py` | `send_subtitle_style` / `send_subtitle_drag` / `send_preview_subtitle` + `on_subtitle_pos` 回调（读线程分发） |
| `ui/web_bridge.py` | 控制面板桥接口：`getSubtitleStyle` / `setSubtitleStyle`（存 config + 下发）/ `getSubtitleStylePresets`（3 套预设）/ `previewSubtitle` / `setSubtitleDrag` / `hideSubtitle` / `setSubtitleEnabled` / `setPanelWindow` / `getPanelState` / `savePanelState` / `setPanelClickThrough` / `panelCollapse`；`_ensure_subtitle_pos_handler`（回传转发给面板 JS + 写回 config） |
| `main.py` | `_panel_html()` 读取页面；`_create_panel_window()` 创建第二个窗口（frameless + easy_drag + on_top，位置/折叠从 config 恢复）；5s 定时 daemon 保存窗口位置 |

### 前端（ui/web_assets/）
| 文件 | 职责 |
|---|---|
| `control_panel.html`（**新增，自包含**，不经过 _load_html 注入） | 深色简约面板：预设区（原作/极简/半透黑底 + 保存/加载）、背景设置、文字样式、位置布局（含「拖拽调整字幕」）、快捷操作（预览/隐藏/总开关/穿透）；所有控件改动 150ms 防抖实时下发 + **值去重** |

---

## 三、SubtitleStyle 字段（C++ 渲染 ↔ 前端控件映射）

| 字段 | 含义 | 默认 |
|---|---|---|
| `bg_mode` | 0=自适应底板 1=通栏 2=无底板 | 0 |
| `bg_r/g/b/a` | 背景色 RGBA | 0,0,0,0.72 |
| `corner` / `padding` | 圆角 / 内边距 px | 10 / 14 |
| `gradient` + `grad_r/g/b/a` | 垂直渐变（D2D LinearGradientBrush） | off |
| `border` + `border_w` + `border_r/g/b/a` | 边框 | off |
| `font` / `font_size` / `font_weight` | 字体（原文自动 0.7 倍字重×0.7） | YaHei UI / 22 / 700 |
| `text_r/g/b/a` | 文字色（原文 alpha×0.65） | 白 |
| `outline` + `outline_w` + 色 | 8 向偏移描边 | off |
| `shadow` + `shadow_off` + 色 | 下方偏移暗色文本模拟阴影 | off |
| `align` | 0=中 1=左 2=右 | 0 |
| `line_gap` / `max_width` | 原文译文间距 / 底板最大宽(占窗宽比) | 4 / 0.9 |
| `pos_x` / `pos_y` | **字幕中心水平 %** / **字幕条顶部垂直 %**（相对游戏窗口） | 0.5 / 0.82 |
| `avoid_bottom` + `avoid_bottom_px` | 底部避让（不与游戏对话框重叠） | true / 60 |
| `enabled` | 字幕总开关（false 时 show 不显示） | true |

### 位置 / 拖拽要点
- `computeGeometry`：`sx = gr.left + pos_x*w - w/2`，`sy = gr.top + pos_y*h`；避让时 `sy ≤ gr.bottom - sh - avoid_bottom_px`；再 clamp 屏幕内。
- **拖拽流程**：`setDragMode(true)` → 去 WS_EX_TRANSPARENT + 停跟随 → 鼠标拖动（SetCapture）→ `WM_LBUTTONUP` 换算 `pos_x/pos_y` 回传（无游戏窗口按主显示器）→ 自动 `setDragMode(false)` 恢复穿透与跟随。
- **预览模式**：`preview_subtitle` 显示示例字幕（无游戏窗口回退主显示器），拖滑块即时生效。

---

## 四、阶段 1 前端修复清单（按 Web Interface Guidelines）

### 高优先级
1. **XSS**：`detail.js renderInfoBar()` 的 dev/engine/released 等用户可编辑字段未转义直接进 innerHTML → 全部 `esc()` 包裹。
2. **焦点**：`style.css` 全局 `outline:none` → 改为 `:focus:not(:focus-visible){outline:none}` + `:focus-visible{outline:2px solid var(--pink)}`。
3. **图标按钮 aria-label + 语义化**：窗口三键/FAB/主题卡片 → `<button>` + aria-label；全部对话框关闭按钮补 aria-label；搜索框/热键/开关/管理游戏搜索补 aria-label。
4. **菜单按钮化**：筛选下拉、FAB 菜单、详情更多菜单、截图右键菜单、动态右键菜单（`ui.js showContextMenu` 生成 `<button>`）、侧边栏项 → `<button>` + `role="menu"/"menuitem"`；收藏夹树分组/分类项加 `role="button"` + tabindex + Enter/空格。

### 中优先级
5. **transition:all ×18 → 显式属性**（只过渡 transform/颜色等合成器友好属性）。
6. **prefers-reduced-motion**：`@media` 块关闭弹性动画。
7. **color-scheme**：`:root` light、`:root[data-theme="dark"]` dark（修复暗色原生滚动条/下拉）。
8. **user-select**：body 全局 none，内容区（detail-desc/dlg-content/表单输入等）恢复 `user-select:text`。
9. **表单内联校验**：`form.js showFormError/clearFormError`，错误行下红字 + 聚焦首个错误字段 + 输入即清除。
10. **搜索防抖**：主搜索框 + 管理游戏搜索框 200ms 防抖（值未变化不重建）。
11. **Toast 置顶修复**：`.toast` 改 `position:fixed` + `z-index:300`（原 99 低于 `.overlay` 100，详情/设置弹窗打开时提示被遮罩盖住）。
12. **Toast 双弹覆盖**：`saveMetadataSources` 后端 `notify("元数据源配置已保存")` 后到覆盖前端 `toast('设置已保存')` → 删除后端 notify，前端统一提示。
13. **CSS 重复清理**：`.confirm-msg`/`.pill-btn.danger` 死代码删除；两份 `.form-row` 合并为一份。
14. 其它：winbtn `cursor:pointer`、详情标题 `min-width:0`+换行、`sk-...→sk-…`、API Key `autocomplete="off" spellcheck="false"`、卡片 `role="button"`+tabindex、`dlgMore` 菜单 aria、`aria-live`（toast/测试结果）、overscroll-behavior。

---

## 五、验证方法

```bash
# C++ 编译（注意：在 overlay/ 目录下运行；overlay.exe 被占用会 LNK1104，先杀进程）
cd overlay && build.bat
# 或
Get-Process overlay -ErrorAction SilentlyContinue | Stop-Process -Force; cd overlay; .\build.bat

# 前端完整性
python tests/verify_frontend.py

# Python 语法
python -m py_compile kazari_play/main.py kazari_play/ui/web_bridge.py kazari_play/core/overlay_client.py

# 端到端管道冒烟（preview/style/drag/quit）
python tests/smoke_control_panel.py
```

**日志位置**：`overlay/bin/debug.log`（C++ `[sub] applyStyle / show / reposition / setDragMode`）、`kazari_play/debug.log`（Python）。

**窗口自检**（PowerShell Win32 FindWindow）：
```powershell
# Add-Type FindWindowW 后：
# "KazariPlay"      主窗口（frameless 约 1384x749）
# "字幕控制面板"     330x560 置顶（折叠后 330x36）
# class KazariPlaySubtitle 字幕窗口（无标题，按 class 查）
```

---

## 六、关键易错点 / 实现坑（其他 agent 务必知晓）

1. **build.bat 必须在 overlay/ 目录运行**（内部用相对路径 `src\...`）；`overlay.exe` 被运行中进程占用会 LNK1104，先 `Stop-Process overlay` 或停主程序。
2. **D2D1 1.0 无 blur effect** → 「背景模糊」未实现（需 D2D 设备上下文 + ID2D1DeviceContext::CreateEffect），面板 UI 中未放模糊开关，方案遗留项。
3. **reposition 语义**：`reposition(gr, force)`——force=true 用于 applyStyle（样式变但位置不变也必须重绘）；updatePosition 走 force=false（几何变化才重绘）。无游戏窗口时 `resolveTargetRect()` 回退主显示器，**预览模式因此也能实时重绘**。
4. **日志节流**：无游戏窗口时 updatePosition 每 200ms 轮询，已用 `m_noWinLogged` 状态标志只记一次，避免刷爆 debug.log。
5. **前端 push 值去重**：WebView2 对控件程序化赋值可能触发 input 事件（曾出现 applyStyle 频繁重复下发），`push()` 比较 JSON 未变化不发送。
6. **DPI 不一致**：overlay 进程 DPI aware（物理像素 2560x1440），外部 FindWindow 查询工具非 aware（逻辑 1707x960），坐标/尺寸数值不同是正常的，不是 bug。
7. **WS_EX_TRANSPARENT 穿透**：字幕窗口与面板窗口穿透通过 `SetWindowLongPtr(GWL_EXSTYLE)` 切换，调用后窗口即可接收/穿透鼠标。
8. **控制面板窗口位置保存**：easy_drag 拖动无结束事件，用 5s 定时 daemon 读 `panel_win.x/y` 存 config（`panel.pos`）；折叠状态由 `panelCollapse` 写 `panel.expanded`，启动时按它决定初始高度。注意定时器只存位置、不覆盖 expanded。
9. **新增前端文件登记**：control_panel.html 是独立窗口自包含页面，**不需要**登记进 `main.py` 的 `_JS_MANIFEST`/`_PARTIAL_MANIFEST`（那是主窗口注入清单）。
10. **OverlayClient 单例**：继续沿用——新命令都走 `_send_long`，拖拽回传走 `on_subtitle_pos`（读线程回调，必须快速返回，转发到面板用 evaluate_js）。

---

## 七、已知问题与待办

1. **背景模糊**：未实现（D2D1 限制），方案遗留。若要补：改用 ID2D1DeviceContext 渲染管线 + `CreateEffect(CLSID_D2D1GaussianBlur)`，或接受占位。
2. ~~控制面板窗口高度偶发异常~~（已修复 2026-08-16）：根因是 pywebview 默认 `min_size=(200,100)` 将折叠 `resize(330,36)` 钳制到 330x100；`_create_panel_window` 已补 `min_size=(330,36)`，实测折叠后 330x36。
3. ~~拖拽回传精度~~（已修复 2026-08-16）：无游戏窗口换算基准由主显示器改为字幕窗口当前所在显示器（`MonitorFromWindow MONITOR_DEFAULTTONEAREST`），`computeGeometry` 钳制同步改目标 rect 所在显示器；双版本重编译。单显示器环境已验证逻辑，副屏待真机确认。
4. **x86 版本**：`build32.bat` 未改（subtitle_style.h 为 header-only，subtitle_window/protocol/main 改动会自动带入），但**未编译验证 build32**，发布前需跑一次。
5. **预设「加载」按钮**：读 config 已保存样式刷新控件；「保存」与滑块改动共用 `setSubtitleStyle`（本就自动持久化），语义一致。
6. **运行确认**：控制面板交互已被实测（黑体/33 号/粉白渐变底/深灰字已持久化，overlay `applyStyle` 日志确认）；字幕渲染效果需用户最终确认配色/字号档位。

---

## 八、对接指引

1. 改 C++ 后必须重编 `build.bat`（本次只动了 x64 链路；x86 `build32.bat` 待验证）。
2. 新字幕样式字段：`subtitle_style.h` 加字段 + `ParseSubtitleStyle` 解析 + `control_panel.html` 控件 + `web_bridge.getSubtitleStylePresets`（如需预设）。
3. 前端修复遵循 Web Interface Guidelines 输出格式（`file:line`），新 UI 控件保持：`<button>` 语义、aria-label、focus-visible、prefers-reduced-motion。
4. 交接后建议先跑：`python tests/verify_frontend.py` + `python tests/smoke_control_panel.py` + 启动 `python kazari_play/main.py` 肉眼检查面板与字幕。

# KazariPlay Hook 实时翻译系统 — 交接文档

> 生成时间：2026-08-15
> 会话范围：从《Hook实时翻译系统计划书》评审 → 全量实施 → 真机验证 → 多轮问题修复（覆盖层显示、候选推送、编码、退出、双客户端冲突等）→ AI 翻译引擎接入 → 翻译 Skill 编写
> 对接提示：**接手前先读** `E:\文件夹\Launcher\minatoLauncher_V2.4\Hook实时翻译系统计划书.md`（附录 B 是实施与修复记录）与本会话的项目级 skill：`.dsh\skills\kazariplay-translation\SKILL.md`（DSH 会话中可用 `skill` 工具加载）

---

## 一、项目概述

**项目**：`E:\文件夹\Launcher\KazariPlay_V1.0`（视觉小说启动器，pywebview GUI）
**功能**：游戏内实时字幕翻译 —— Hook 提取游戏文本 → 文本稳定 → 翻译（百度/AI 大模型）→ 游戏画面底部渲染原文+译文
**技术路线**：C++ overlay.exe（注入+Hook+稳定+渲染）↔ Python（协调+翻译）↔ pywebview 前端（配置/开关/Hook 选择）
**核心依赖**：Textractor v5.2.0（host 静态库本机构建 + texthook DLL），见 `overlay/third_party/textractor/`

### 进程/数据流

```
[游戏进程] ← texthook.dll 注入（KiriKiriZ/BGI2 等引擎 hook 自动插入）
[C++ overlay.exe] TextractorHost 回调 → TextStabilizer（跨线程 SetTimer 去重合并）
    → 命名管道 stable_text（UTF-8 JSON）→ Python
[Python] SubtitleCoordinator（队列+单 worker 保序）→ Translator（baidu / ai）
    → 管道 subtitle（原文+译文）→ C++ SubtitleWindow（WIC+UpdateLayeredWindow）渲染底部字幕
```

### 双版本 overlay（按游戏位数选择）

```
overlay/bin/overlay.exe    (x64，链接 hostlib.lib + 同目录 texthook.dll x64)
overlay/bin32/overlay.exe  (x86，链接 hostlib32.lib + 同目录 texthook.dll x86)
```
`OverlayClient` 按 `is_x64` 自动选择；位数不匹配时自动重启切换。

---

## 二、目录结构与关键文件

### C++（overlay/，双版本可独立编译）
| 文件 | 职责 |
|---|---|
| `src/main.cpp` | 全集成：命令窗口（UI 线程编排）、StartHook/StopHook/Subtitle 分发、候选节流推送、30s 看门狗、日志 |
| `src/pipe_server.h/cpp` | 统一长连接双工管道（**FILE_FLAG_OVERLAPPED 重叠 I/O**）、sendToClient、断线重连、64KB 缓冲 |
| `src/protocol.h` | 12 种消息类型 + 序列化（含 codepage 字段、hook_candidates） |
| `src/textractor_host.h/cpp` | 静态链接 hostlib，封装 Host::Start/InjectProcess/InsertHook；文本回调、候选收集、HookParam 序列化(kzh:格式)、30s 看门狗配合 |
| `src/text_stabilizer.h/cpp` | 跨线程 SetTimer（feed 只入队+PostMessage，timer 在 UI 线程）、LCS 相似度去重、追加合并 |
| `src/subtitle_window.h/cpp` | 底部字幕（WIC+UpdateLayeredWindow）、**200ms 跟随游戏窗口**、找不到窗口回退屏幕底部 |
| `src/toast_window.h/cpp` | 截图 toast（原功能，未改） |
| `build.bat` / `build32.bat` | x64 / x86 编译（`/utf-8 /MD /DNOMINMAX` + hostlib(.32).lib + advapi32） |
| `third_party/textractor/` | 官方 v5.2.0 头文件 + `hostlib.lib`/`hostlib32.lib`（本机构建）+ `texthook.dll`（部署到 bin/bin32） |

### Python（kazari_play/）
| 文件 | 职责 |
|---|---|
| `core/overlay_client.py` | **进程内单例**（关键！见修复记录 #11）；重叠读写长连接；按位数选 overlay；读线程只分发 |
| `core/subtitle_coordinator.py` | 队列+单 worker 保序；`_awaiting_selection` 首配状态；stop() 逐个容错发送 |
| `core/translate.py` | 翻译器：`baidu`（百度开放平台）/ `ai`（OpenAI 兼容 chat/completions，默认 DeepSeek）；缓存+超时+失败降级空串 |
| `core/game_launcher.py` | `_start_translation`/`_is_process_x64`/`stop_translation`；从 config 读 codepage |
| `core/game_model.py` / `database/` | hook_code/hook_code_custom/translate_enabled 字段；`_row_to_game` 列名访问 |
| `utils/config.py` | **递归深合并默认值**（修复 #14）；`textractor.codepage`、`translate.ai.*` 等 |
| `ui/web_bridge.py` | camelCase 桥 API：`getHookCandidates`/`selectHook`/`toggleGameTranslation`/`testTranslation` 等；全屏检测提示 |
| `ui/web_assets/` | 设置页「翻译」tab（含 AI 字段+文本编码）、详情页翻译开关+重选 Hook、`hook_select` 弹窗（推荐高亮）、`core.js launchGame()` 统一启动 |

### 工具/测试/文档
| 文件 | 用途 |
|---|---|
| `tests/smoke_translation.py` | 离线回归（21 项断言：前端清单拼接/DB 字段往返/launcher 接线/队列保序），`python tests/smoke_translation.py` |
| `scripts/real_hook_smoke.py` | 真机冒烟：启动游戏→注入→观察 host console 与 STABLE 回传 |
| `scripts/diag_overlay.py` | **显示自检**：全屏检测+窗口状态+**自动像素验证**（亮度比值判断字幕是否真上屏） |
| `.dsh/skills/kazariplay-translation/SKILL.md` | 项目级 skill：架构/配置/测试/调试/常见问题（DSH 会话可加载） |
| `minatoLauncher_V2.4/Hook实时翻译系统计划书.md` | 设计文档 + 附录 B 实施与修复记录 |

---

## 三、已完成功能与验证状态

| 功能 | 状态 | 验证 |
|---|---|---|
| Hook 注入（x86/x64） | ✅ | 真机：素晴らしき日々(BGI2)、少女领域(KiriKiriZ)、9-nine(KiriKiriZ) |
| 文本采集→稳定→回传 | ✅ | STABLE 事件实测；候选推送已修复（#12） |
| 字幕渲染（底部原文+译文） | ✅ | BitBlt 抓屏像素验证（亮度比值 0.37≈0.28 设计值）；位图内容验证 |
| 字幕跟随游戏窗口 + 回退屏幕底部 | ✅ | 游戏移动后字幕重定位实测 |
| 截图 toast | ✅ | 完整用户路径实测（窗口右下角、3s 自动隐藏） |
| 翻译引擎：百度 / AI(DeepSeek/OpenAI 兼容) | ✅ | AI 未配置/401 优雅降级空串 |
| 前端：设置页/详情开关/Hook 选择/统一启动 | ✅ | node --check、前端拼接、GUI 启动存活 |
| 离线回归 | ✅ | 21 项 ALL PASS |
| GUI 端到端 | ✅ | pywebview 启动、自动扫描、VNDB 匹配正常 |

---

## 四、关键修复记录（其他 agent 务必知晓，避免重蹈覆辙）

1. **MSVC 编译**：源码含中文注释必须 `/utf-8`（否则 GBK 解析级联报错）；`/DNOMINMAX` 防 std::max 被宏破坏。
2. **统一长连接 + 重叠 I/O（双端）**：同步阻塞 ReadFile 会卡住同句柄 WriteFile。C++ 服务端 `FILE_FLAG_OVERLAPPED` 重叠读循环（**禁止在挂起时复用 OVERLAPPED 重发读**）；Python 客户端句柄 `FILE_FLAG_OVERLAPPED` **必须放 dwFlagsAndAttributes**（与 GENERIC_WRITE 同值 0x40000000，放 dwDesiredAccess 会被吸收），读/写均配 OVERLAPPED。
3. **sendToClient 禁止 FlushFileBuffers**：会阻塞到对端读取，客户端未读时卡死管道线程。
4. **PipeServer::stop() 必须 WaitForSingleObject 等管道线程退出**再删临界区，否则退出 0xC0000005。
5. **`_row_to_game` 用列名访问**（`row_factory=sqlite3.Row`）：ALTER 追加列导致新老库列序不同，索引硬编码错位。
6. **`_is_process_x64` 的 GetCurrentProcess 需 `restype=HANDLE`**：64 位伪句柄截断会误判系统为 32 位。
7. **web_bridge 桥方法名必须 camelCase**（pywebview 按 Python 名原样暴露；与现有 getConfig 一致）。
8. **禁止把 release zip 的旧 VC 运行库（14.29）复制到 bin/ 目录**：会抢先加载旧版导致 Host::Start 崩溃；bin/bin32 只保留 overlay.exe + texthook.dll，用系统运行库（14.44）。
9. **OverlayClient 是进程内单例**：C++ PipeServer 单实例管道，翻译会话与截图 toast 两个客户端各自建连会互相抢占（第二个静默失败）。任何新增使用方必须用 `OverlayClient()`（返回单例）。
10. **候选必须主动回传**：`serializeHookCandidates` 需在 C++ 侧候选变化回调中节流（500ms）推送（TextractorHost::setCandidatesCallback + main.cpp），否则前端候选列表恒空。
11. **字幕定位**：`FindMainWindowByPid`（可见+非 TOOLWINDOW）；找不到回退主显示器底部。游戏无边框全屏时窗口=屏幕，字幕=屏幕宽属正常。
12. **编码**：Textractor 默认 Shift-JIS 解码；中文汉化版（GBK）会乱码 → `textractor.codepage` 配置（0/932/936/65001）经 start_hook 透传到 HookParam.codepage。
13. **Config 深合并**：旧 config.json 缺嵌套新字段时用 `_deep_merge` 补默认值（浅合并会丢字段）。
14. **退出链路**：monitor on_exit → `launcher.stop_translation()` → `coordinator.stop()`（逐个容错发送，保证 hide_subtitle 必达）。

---

## 五、测试与验证方法

```bash
# 离线回归（21 项）
python tests/smoke_translation.py

# 真机冒烟（注入+文本回传，9-nine 路径示例）
python scripts/real_hook_smoke.py "E:\BaiduNetdiskDownload\PC[ぱれっと]9nine④-雪色雪花雪之痕_官方中文\PC[ぱれっと]9nine④-雪色雪花雪之痕_官方中文\PC[ぱれっと]9nine④-雪色雪花雪之痕_官方中文\nine_yukiiro.exe" --engine krkr --seconds 30

# overlay 显示自检（全屏检测 + 自动像素验证"字幕是否真上屏"）
python scripts/diag_overlay.py "<游戏exe>"

# 翻译引擎行为（未配置/假 key → 空串不崩溃）
python -c "import sys; sys.path.insert(0,'kazari_play'); from core.translate import Translator; print(repr(Translator().translate('おはよう')))"

# 重编译 overlay（改 C++ 后两个都要）
cd overlay && build.bat && build32.bat
```

**日志位置**：
- `kazari_play/debug.log`（Python：start_hook/hook_error/翻译）
- `overlay/bin/debug.log`、`overlay/bin32/debug.log`（C++：host console 注入引擎识别、`[sub]` 渲染日志）

**host console 关键行**：`pipe connected`（注入成功）/ `vnreng: INSERT KiriKiriZ`（引擎 hook）/ `KiriKiriZ2 inserted`。

---

## 六、已知问题与待办（接手后优先）

1. **9-nine 中文版字幕乱码**：已加文本编码设置（GBK 936），待用户实际确认；若仍乱码需查显示端（字体/DirectWrite locale）。
2. **字幕"参照屏幕"**：待确认是否游戏无边框全屏；若窗口化却回退屏幕，查 `[sub] show` 日志 pos 与 gamePid。
3. **x64 游戏未真机实测**（本机游戏全 32 位）；x64 overlay 已编译与管道冒烟，但未注入 x64 游戏。
4. **翻译 API 实调**：需用户提供百度/DeepSeek key；AI 引擎仅验证了 401 降级路径。
5. **打包分发**：未做 PyInstaller 打包；overlay 双版本 + texthook.dll + 系统运行库的部署结构已就绪（见部署结构）。
6. **Hook 点体验**：候选选择依赖游戏先出文本；已加推荐高亮；可考虑"选定后 15s 无文本自动提示重选"。
7. **计划书遗留**：游戏窗口移动跟随已实现（原 V2）；独占全屏限制（layered 无法覆盖）为系统限制，已做检测提示。

---

## 七、对接指引（给接手 agent）

1. **先加载 skill**：会话中执行 `skill` 工具加载 `kazariplay-translation`（含架构/调试/常见问题全量指引）。
2. **读计划书附录 B**：`minatoLauncher_V2.4\Hook实时翻译系统计划书.md` 的「实施状态与偏差记录」是完整历史。
3. **环境**：网络已通（下载 Textractor 源码/镜像可用）；MSVC Build Tools 14.44 + Python 3.11 + pywebview 6.2.1 已装。
4. **调试入口**：用户反馈"看不到/乱码/不显示"一律先跑 `scripts/diag_overlay.py` 拿客观证据（像素验证）再下结论。
5. **改 C++ 必须双版本重编译**（build.bat + build32.bat），并跑离线回归。
6. **新增 OverlayClient 使用方**：必须用单例，禁止再建实例。
7. **UI/桥改动**：方法名 camelCase；新增前端文件要登记 `main.py` 的 `_JS_MANIFEST`/`_PARTIAL_MANIFEST`。
8. **测试游戏**：本机可用 9-nine 雪色雪花雪之痕（krkr/KiriKiriZ，32 位，`nine_yukiiro.exe`）、素晴らしき日々（BGI）、少女领域（krkr）。

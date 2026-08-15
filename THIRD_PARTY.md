# 第三方组件声明（THIRD_PARTY）

本项目使用了以下开源组件。请遵守各组件各自的许可证条款。

## 需要遵守 GPLv3 的组件

### Textractor（GPL-3.0）
- **用途**：`overlay/third_party/textractor/` 的 host 头文件与 `hostlib.lib` 被**静态链接**进 `overlay.exe`，用于 Hook 提取游戏文本。
- **影响**：根据 GPLv3，`overlay.exe` 属于 Textractor 的衍生作品，`overlay/` 目录下的源码以 GPL-3.0 授权发布。
- **上游**：https://github.com/Artikash/Textractor

### LunaTranslator（GPL-3.0）
- **用途**：本项目 Hook 文本清洗过滤器链（去重字符/行、递增拼接等）的设计参考来源（仅参考设计思路，未复制其代码）。
- **上游**：https://github.com/HIllya51/LunaTranslator

## 宽松许可组件（不传染本项目）

| 组件 | 许可证 | 用途 |
|---|---|---|
| pywebview | BSD-3-Clause | 桌面 UI 渲染（WebView2） |
| Pillow | HPND | 封面/截图图片处理 |
| keyboard | MIT | 全局热键 |
| pywin32 | PSF | Windows API 桥接 |
| numpy | BSD-3-Clause | 数值计算 |
| nlohmann/json | MIT | C++ JSON 解析（`overlay/third_party/json.hpp`） |
| Microsoft Edge WebView2 Runtime | 专有（系统组件） | 运行时依赖（Windows 提供） |

## 源码获取

本项目（含 GPLv3 的 `overlay/` 部分）完整源码位于：
https://github.com/SB-TDM/KazariPlay

按 GPLv3 要求，`overlay.exe` 的对应源码与构建脚本（`overlay/build.bat`、`overlay/build32.bat`、`overlay/CMakeLists.txt`）随项目提供。

# 第三方组件声明（THIRD_PARTY）

本项目使用了以下开源组件。请遵守各组件各自的许可证条款。

## 分支范围

本文件描述无翻译原版。原版仍采用 GPL-3.0；移除翻译功能不改变项目现有许可。

以下组件只存在于 `feature/hook-translation` 及历史提交，不在原版源码、构建或打包清单中：

### Textractor（GPL-3.0）
- **实验版用途**：host 头文件与 `hostlib.lib` 静态链接进实验版 `overlay.exe`，用于提取文本；原版不使用或分发这些组件。
- **上游**：https://github.com/Artikash/Textractor

### LunaTranslator（GPL-3.0）
- **历史用途**：实验版文本清洗过滤器的设计参考来源；原版没有过滤器链。
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

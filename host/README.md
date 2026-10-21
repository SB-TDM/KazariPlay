# WinHost 构建

WinHost 使用 C++17、Win32/DWM 和 WebView2 Evergreen Runtime。构建不依赖全局 `cmake` PATH，而是由 `../scripts/build_host.ps1` 通过 `vswhere` 定位 Visual Studio 2022 Build Tools 自带的 CMake 和 CTest。

WebView2 SDK 固定为 `Microsoft.Web.WebView2 1.0.4129.50`，只使用 x64 `WebView2LoaderStatic.lib`。SDK 是编译依赖；终端用户仍需安装系统 WebView2 Runtime。恢复的包放在 `host/.packages/`，构建目录放在 `host/build/`，两者都不入库。

## 常用命令

```powershell
# 只检查工具链，不依赖 WebView2 SDK；可先验证 CMake 环境
powershell -NoProfile -File scripts/build_host.ps1 -ConfigureOnly -ProtocolOnly

# 构建并运行协议测试（Task 2 创建源码后）
powershell -NoProfile -File scripts/build_host.ps1 -ProtocolOnly -Target host_protocol_test -Test

# 构建并运行所有已创建的 Host 测试
powershell -NoProfile -File scripts/build_host.ps1 -Test

# 构建完整 Host（需要 WebView2 SDK）
powershell -NoProfile -File scripts/build_host.ps1
```

如果本机已有 SDK，可设置 `KAZARIPLAY_WEBVIEW2_SDK_ROOT` 指向包含 `build/native/include/WebView2.h` 的包目录；否则脚本先查找 NuGet 缓存，再通过 `packages.config` 恢复到 `host/.packages/`。

开发期可把 `KAZARIPLAY_ASSET_ROOT` 指向 `scripts/build_web_assets.py --output <目录>` 生成的目录，让 Host 通过 `https://kazariplay.local/index.html` 加载装配后的页面；未设置时加载内置输入测试页。

## 当前状态

当前只建立构建入口和条件目标。`src/main.cpp`、协议/窗口测试源码会在后续 Task 创建；在此之前，相应目标会显示为 skipped，不能用“配置成功”宣称 Host 已实现。

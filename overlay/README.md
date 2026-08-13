# KazariPlay Overlay（C++）

游戏内截图成功提示的独立置顶透明窗口，替代原先的 pywebview overlay。

- 形态：独立 C++ 进程，通过**命名管道**接收 KazariPlay 主程序（Python）消息
- 绘制：Direct2D + DirectWrite（圆角卡片 + 缩略图 + 中文文字）
- 仅覆盖**窗口化/无边框全屏**游戏；独占全屏不在目标内

## 构建

需要 Visual Studio 2022 Build Tools（含 C++ 工作负载）。

```bat
cd overlay
build.bat
```

或使用 CMake：

```bat
cmake -B build -A x64
cmake --build build --config Release
```

产物：`overlay/bin/overlay.exe`

## 依赖

- `third_party/json.hpp`（nlohmann/json 单头文件，已随项目分发）
- 系统库：d2d1 / dwrite / windowscodecs / ole32 / user32 / gdi32

## 运行

```
overlay.exe <管道名>
```

`<管道名>` 省略时默认 `KazariPlayOverlay`。KazariPlay 主程序会传入带 PID 后缀的管道名以避免多实例冲突。

## 通信协议（命名管道，单行 JSON，UTF-8）

| 消息 | 示例 | 说明 |
|------|------|------|
| show | `{"type":"show","hwnd":657700,"path":"D:\\...\\shot.png","title":"千恋万花","duration":3}` | 显示 toast，`duration` 为秒，可省略 |
| hide | `{"type":"hide"}` | 立即隐藏 |
| quit | `{"type":"quit"}` | 退出进程 |
| ping | `{"type":"ping"}` | 存活检测（预留） |

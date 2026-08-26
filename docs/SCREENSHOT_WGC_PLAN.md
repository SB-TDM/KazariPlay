# KazariPlay 截图内核改造方案 — Windows Graphics Capture(WGC)

> 生成时间：2026-08-25
> 修订时间：2026-08-25（修正依赖选型：原 `wgc` 库不存在 → 改用已实测验证的 `windows-capture`）
> 会话范围：截图黑屏问题定位（PrintWindow 抓不全独占渲染游戏）→ 方案选型（DXGI vs WGC）→ 选定 WGC → 本文档细化落地
> 状态：**已实施（三级回退接入 screenshot_service.py），含通道顺序修正（BGRA→RGB 用 [2,1,0]）；真机冒烟通过**

---

## 一、问题回顾

### 现象

部分游戏截图后：**整图尺寸 = 屏幕分辨率，但画面只在左上角一小块，其余全部纯黑**。

### 根因（已定位，非 pid 问题）

- pid 获取链路正常（`web_bridge._running_pid()` → `launcher.current_process.pid`），截图确实走的是**窗口截图** `capture_game_window()` 路径，而非全屏 `ImageGrab.grab()`。
- 若真走全屏，图片会是整块屏幕实拍，**不会出现大片纯黑**。
- 真正的病根在 [screenshot_service.py L37-L51](file:///e:/文件夹/Launcher/KazariPlay_V1.0/kazari_play/core/screenshot_service.py#L37-L51)：
  - 位图按客户区全尺寸创建（全屏游戏 = 屏幕分辨率）。
  - 用 `PrintWindow`（GDI 位图拷贝）抓取。
  - **全屏独占/硬件加速渲染的游戏（DirectX/OpenGL/Vulkan 直接写显存）不经 GDI 层，PrintWindow 拿不到像素** → 缓冲未写入 = 默认黑。
  - 左上角那一小块是偶然通过 GDI 呈现的内容被捕获。
- 这也解释了**为什么只有部分游戏有问题**：正常的是纯 GDI/兼容渲染引擎；黑屏的是 D3D/Vulkan 独占渲染。

### 目标

更换捕获内核为 **Windows Graphics Capture（WGC）**，兼容独占渲染的全屏游戏，同时保留原路径作兜底。

---

## 二、选型依据：WGC vs DXGI

| 维度 | DXGI Desktop Duplication | Windows Graphics Capture（WGC） |
|---|---|---|
| 定位目标 | 只能抓整块**显示器**输出，再手动按窗口矩形裁剪 | 直接按 **HWND / Monitor** 创建捕获项，天然对齐窗口 |
| 全屏独占游戏 | 支持，但全屏切换时丢帧/需重建 | 支持，**Win10 1903+ 默认可捕获**，无需重建 |
| 被遮挡窗口 | 抓不到（合成层下） | 同样抓不到（基于桌面合成） |
| 消息泵/生命周期 | 底层，需自己枚举输出、管理 Release | 框架级会话，资源管理更简单 |
| Python 生态 | dxcam（简单）或 ctypes 手写（重） | windows-capture（简单）或 winrt 手写（中等） |

**结论**：WGC 同时命中「按窗口捕获 + 全屏独占兼容」两个核心痛点，选它。

---

## 三、Python 实现路线选型（2026-08 实测验证）

> ⚠️ **修正说明**：原稿路线 A 依赖的 `wgc` 库 **在 PyPI 上不存在**（`pip install wgc` → No matching distribution）。
> 已实测核验真实可用库如下（`pip index versions` 均确认在 PyPI）。

| 路线 | 依赖（均已验证存在） | 优点 | 缺点 |
|---|---|---|---|
| **A. `windows-capture`**（推荐） | `pip install windows-capture`（2.0.1，Rust/Python，自动带 numpy+opencv） | 支持 `window_hwnd` 按 **HWND** 捕获（匹配 pid→hwnd→抓帧链路）；也可按窗口标题/监视器；性能最佳 | 事件驱动（回调 + 消息循环），抓"单帧即停"需自由线程模式；依赖 opencv-python（体积 ~100MB） |
| B. 手写 `winrt`（官方绑定） | `winrt-Windows.Graphics.Capture` + `winrt-Windows.Graphics.DirectX.Direct3D11`（3.2.1，微软 pywinrt） | 官方、可控、轻量（无 opencv）；可按 HWND 捕获单帧 | 代码量大：帧池/会话/纹理回读/消息泵都要自管 |
| C. `wgcapture`（备选） | `pip install wgcapture`（0.1.2） | API 极简（`capture_screen(标题)`） | 只能按**窗口标题**捕获，无 HWND 入口，需改 pid→标题链路，**不匹配本方案** |
| D. ctypes 手调 WinRT COM ABI | 无 | 零 Python 依赖 | `IInspectable` ABI 复杂易踩空，**不推荐** |

**策略**：先用 **路线 A（windows-capture）** 快速验证核心可行性；若在目标游戏上失败（或打包体积顾虑），降级到 **路线 B（手写 winrt）**。

### 路线 A：windows-capture 预研用法（2026-08-25 真机验证 ✅）

> 已在开发机实测：`WindowsCapture(window_hwnd=...)` 成功捕获 **KazariPlay 自身窗口**
> （1124×2076 物理像素，BGRA numpy `(h,w,4)`），转 PIL 落盘成功。三级回退链路可行。

```python
import threading
from windows_capture import WindowsCapture, Frame, InternalCaptureControl

# 注意：capture 实例不可复用（on_frame_arrived 里 stop 后即结束），
#       每次截图新建实例；D3D 设备由库内部管理（首次有几百 ms 开销）
capture = WindowsCapture(
    window_hwnd=hwnd,      # 由 pid→hwnd 得到；按窗口捕获
    cursor_capture=False,  # 截图不含光标
)

@capture.event
def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
    # frame.frame_buffer 是 BGRA numpy (h, w, 4)，物理像素
    bgra = frame.frame_buffer
    img = Image.fromarray(bgra[:, :, [2, 1, 0]])   # BGRA -> RGB（取 BGR 反转为 RGB，丢弃 alpha）
    control.stop()                             # 抓一帧即停
    got.set()                                  # 线程同步通知

@capture.event
def on_closed():
    pass

capture.start()          # 阻塞消息循环，需单独线程
got.wait(10)             # 等待帧到达 / 超时
```

> 实测 API 更正（避免踩坑）：
> - **取像素用 `frame.frame_buffer`**（BGRA numpy，`(h,w,4)`）——`frame.to_numpy()` / `convert_to_bgr()` 均非直接数组返回。
> - **通道转换用 `frame_buffer[:, :, [2,1,0]]`**（BGRA→RGB，丢弃 alpha）。⚠️ 不能整体 `[::-1]`（会得到 ARGB 通道错位 → 反相色调，已实测踩坑）。
> - 依赖 opencv 用于 `frame.save_as_image()`；**转 PIL 可完全避开 opencv**（用 `frame_buffer` + Pillow），减小运行时依赖风险。
> - `start_free_threaded()` 返回 `CaptureControl` 可外部 stop；`start()` 阻塞需自起线程。

---

## 四、架构：三级捕获回退

```
take_screenshot(pid)
  ├─ ① WGC：pid → HWND → WindowsCapture(window_hwnd=...) 抓帧 → 成功返回
  ├─ ② PrintWindow（保留）：WGC 不可用/失败/窗口不可见 → 原逻辑兜底
  └─ ③ ImageGrab.grab()：前两者都失败 → 全屏兜底
```

- **尺寸判定**：① WGC 裁剪偏移后保留**物理像素**（去掉标题栏/边框，内容对齐客户区；高 DPI 下比 PrintWindow 更清晰）；② PrintWindow 保持客户区逻辑尺寸；③ 全屏分辨率。
- **pid 链路不变**：仍由调用方 `web_bridge._running_pid()` 传入。
- **客户区对齐**（`_client_physical_offset`）：`ClientToScreen(0,0)×DPIscale − DwmGetWindowAttribute(EXTENDED_FRAME_BOUNDS)` 得物理偏移，裁剪掉系统标题栏/边框；无标题栏窗口偏移≈0。

---

## 五、改动清单

| 文件 | 改动 |
|---|---|
| `kazari_play/core/screenshot_service.py` | 新增 `_capture_via_wgc(pid)`（懒 import `windows_capture`，抓一帧即停）+ `_client_physical_offset(hwnd)`（客户区物理偏移，裁剪标题栏/边框）；`take_screenshot` 编排三级回退 |
| `requirements.txt` | 新增 `windows-capture`（标注可选，缺失静默降级） |
| `tests/smoke_screenshots.py` | 追加 WGC 分支冒烟（有显示环境时验证返回非 None） |
| （不改）`web_bridge.py`、尺寸/pid 判定、存储 | 保持不变 |

---

## 六、必须规避的坑

1. **可见性限制**：WGC 只能捕获**屏幕上可见**的窗口；最小化/被完全遮挡时失败 → **PrintWindow 兜底必须保留**。
2. **系统版本门槛**：WGC 需 **Win10 1809+**，全屏独占捕获需 **1903+**；老系统静默降级 PrintWindow（当前开发机 Build 26200 满足）。
3. **首次初始化开销**：创建 GraphicsCaptureItem/会话较慢（几百 ms）→ 在模块级**懒加载缓存**会话/捕获实例，避免每次截图重建。`windows-capture` 的 capture 实例不可复用（抓帧即 stop），需评估缓存粒度：可缓存 D3D 设备而非完整会话。
4. **后台/无显示/远程桌面**：WGC 初始化可能失败 → 三级回退覆盖。
5. **依赖缺失**：`import windows_capture` 放函数内并 try/except，缺失即走 PrintWindow，不拖垮主流程。opencv 未装时 `save_as_image` 不可用，改用 `frame.to_numpy()` 转 PIL。
6. **事件驱动模型**：`windows-capture` 是回调式（`start()` 阻塞 / `start_free_threaded()` 自由线程）；截图要"抓一帧即停"，需在 `on_frame_arrived` 里 `control.stop()`，并做好线程同步（Event 等待帧到达）。
7. **DPI**：确认 WGC 返回帧为物理像素；若出现尺寸漂移，需按 `GetDpiForWindow` 校正裁剪。

---

## 七、落地顺序

1. **预研验证（✅ 已完成）**：用 `windows-capture` 写独立脚本（`window_hwnd=hwnd`）已确认能按 HWND 捕获完整画面（实测 KazariPlay 窗口 1124×2076），三级回退链路可行。
2. **改代码**：接入三级回退到 `screenshot_service.py`。
3. **补依赖与测试**：`requirements.txt` + 冒烟测试。
4. **真机复测**：在黑屏游戏 + 正常游戏 + 无 pid 三场景各截一张验证。

---

## 八、风险与备选

| 风险 | 缓解 |
|---|---|
| `windows-capture` 事件模型/体积不满足（全屏独占仍有问题、opencv 依赖重） | 降级路线 B 手写 `winrt`（官方绑定，轻量可控） |
| 被遮挡窗口抓不到 | PrintWindow 兜底 |
| 老系统不支持 | 版本检测静默降级 |
| 新依赖体积（opencv ~100MB） | 打包时若顾虑大，优先路线 B（winrt 无 opencv）；或确认 numpy 转 PIL 路径不触发 opencv 导入 |

---

## 九、附：验证清单（真机复测用）

- [ ] 黑屏游戏（D3D/Vulkan 独占）：WGC 抓出完整画面，尺寸=窗口物理像素，无黑边
- [ ] 正常游戏：仍走 WGC，画面完整
- [ ] 无 pid（未启动游戏）：回退全屏，正常出图
- [ ] 未装 windows-capture：静默走 PrintWindow，不报错
- [ ] 最小化/被遮挡窗口：WGC 失败 → PrintWindow 兜底出图

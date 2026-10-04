# WebView2 性能参数记录

> 文档状态：当前决策记录，2026-10-02

## 当前决策

本次审查回滚了一组未经完整测量的 WebView2 启动参数扩展。当前保留提交前已有的参数：

```text
--disable-gpu-compositing
--renderer-process-limit=1
--disable-features=msWebOOUI,msPdfOOUI,msSmartScreen
```

本次回滚移除的实验性参数包括：

```text
--disable-gpu
--disable-background-networking
--disable-component-update
--disable-sync
--disable-extensions
--js-flags=--max-old-space-size=256
```

同时移除了对大量 Edge 专有功能的额外禁用项。原因是这些参数没有经过跨环境性能回归，部分参数会阻断 Runtime 更新或安全能力，JavaScript 堆上限也可能限制大型游戏库。

## 长期原则

1. 不以 Chromium 启动参数代替应用层性能优化。
2. 不默认阻断 WebView2 Runtime 或组件安全更新。
3. 不默认关闭 GPU，除非有可复现的硬件兼容性问题和对应降级开关。
4. 不设置未经容量测试验证的 JavaScript 堆上限。
5. 每次新增启动参数都必须有基线数据、适用环境和回滚方式。

## 推荐优化方向

优先优化 KazariPlay 自身的数据流和渲染行为：

- 继续使用封面缩略图、LRU 缓存和并发读取去重。
- 保持游戏卡片 DOM 窗口化，避免一次性创建全部卡片。
- 截图列表继续使用懒加载，不在主游戏列表中内联原图。
- 对批量元数据请求设置并发上限、取消机制和进度反馈。
- 记录启动内存、空闲内存、滚动帧率和长时间运行后的内存变化。

## 参数变更前的验证矩阵

任何新的 WebView2 参数都至少需要在以下场景对比默认配置：

- Windows 10 和 Windows 11
- 当前 WebView2 Runtime 与一个较旧的受支持版本
- 空库、100 个游戏、500 个以上游戏
- 快速滚动封面和打开详情页
- 截图缩略图加载、全屏预览和设置页切换
- 连续运行 2 小时后的内存与 UI 响应

记录以下指标后再决定是否保留参数：

```text
冷启动时间
启动后工作集内存
空闲 10 分钟后的工作集内存
快速滚动时的 UI 响应
截图和详情页操作是否出现异常
```

## 回滚规则

如果参数导致渲染退化、截图预览异常、页面崩溃、Runtime 更新异常或大库操作失败，应优先回到 WebView2 默认参数，再定位具体原因。不要通过继续叠加 `--disable-*` 参数来掩盖问题。

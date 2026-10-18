# 测试与验证

> `tests/` 含单元测试、回归测试、冒烟测试与前端组装校验。原则：**不动真实用户数据**（临时库 / 临时目录 / mock 网络）。

## 运行

```bash
# 快速门禁（提交前）
python tests/verify_frontend.py        # 前端组装完整性
python tests/test_scanner.py           # 扫描器
python -B tests/test_p0_data_flow.py   # P0 写入/取消
python -B tests/test_p1_reliability.py # P1 截图/身份/重定位/任务隔离
python tests/test_classic_boundary.py  # 无翻译边界 + 旧数据兼容
python tests/test_rating.py            # 评分规范化（0-5 半星）
python tests/test_ui_sync.py
python tests/test_multi_source.py
python tests/test_proxy_utils.py
python tests/test_cover_cache.py
python tests/test_cover_thumb.py
python tests/test_game_process.py
python tests/test_trial_paths.py
python tests/test_updater.py           # 自动更新核心（检查/下载/可信校验/包结构，0 网络）
python -B tests/test_update_apply.py   # 替换助手/回滚助手/启动自愈（含真实文件锁）

# 需显示环境 / 编译 overlay 的冒烟
python tests/smoke_screenshots.py
python tests/smoke_overlay.py          # 需先编译 overlay
python tests/smoke_collections.py
python tests/smoke_update_flow.py      # 更新流程进程级（正常替换/真实占用回滚/安装锁；需 overlay）

# 前端单测（node，需先 npm run build）
node tests/test_p0_frontend.cjs
node tests/test_p1_frontend.cjs
node tests/test_update_ui.cjs          # 更新弹层：就绪重开/失败恢复/轮询乱序/notice
```

## 分类与覆盖

### 前端组装 / 单测
| 文件 | 覆盖 |
|---|---|
| `verify_frontend.py` | `main.py::_load_html` 组装链路：`PARTIALS/SCRIPTS` 占位符全替换、script 块数 = `_JS_MANIFEST`、JS 引用的元素 id 全部存在于组装 HTML 且不重复、CSS `@import` 已展开且全局 `@layer` 顺序完整。**新增模块漏登记清单会立刻报错**。 |
| `test_p0_frontend.cjs` | 前端 P0（node + vm 沙箱） |
| `test_p1_frontend.cjs` | 前端 P1（截图区 DOM 行为） |
| `test_update_ui.cjs` | 更新弹层状态与轮询：就绪重开、双失败解锁、串行轮询与迟到响应丢弃、notice 展示 |

### 后端数据 / 业务
| 文件 | 覆盖 |
|---|---|
| `test_p0_data_flow.py` | P0 写入与取消：删除事务回滚、删除后记录消失且重扫可加回、批量操作、配置/DB/网络隔离 |
| `test_p1_reliability.py` | P1：截图、`identity` 回填、批量重新定位预览（多候选）、任务隔离 |
| `test_scanner.py` | 中文启动器过滤、体积优先选主 exe、标题清洗、进度回调、取消 |
| `test_classic_boundary.py` | 原版分离回归：无翻译能力、旧库与旧配置可读写兼容 |
| `test_rating.py` | 评分规范化与换算：0-5 半星对齐、非法拒绝、0-100 来源换算边界、低于 1 星归 0 |
| `test_ui_sync.py` | UISync：域→JS 语句、合并、payload 转义、未绑窗口降级、多线程 |
| `test_multi_source.py` | 多源注册表完整性、默认混合源、pending 剔除、`_wrap`/`_dedupe`、`set_mixed_sources`、候选详情补全 |
| `test_proxy_utils.py` | 代理地址规范化、HTTP/SOCKS 校验、system/direct/custom 代理选择、连通性探测成功路径 |
| `test_cover_cache.py` | 封面 base64 LRU：`move_to_end`、条目/字节双上限、clear |
| `test_cover_thumb.py` | 封面缩略图：首次生成、磁盘缓存命中、mtime 变化重建、data URI |
| `test_game_process.py` | 启动目标与关闭：模拟竞态 + Windows 真实父子进程 |
| `test_trial_paths.py` | `KAZARIPLAY_DATA_DIR` 覆盖不落到已安装用户库 |
| `test_updater.py` | 更新核心：版本比较、镜像候选、可信摘要、检查状态机、下载（摘要/官方源校验文件/镜像自报拒绝）、包结构预检（0 网络） |
| `test_update_apply.py` | 替换/回滚助手与启动自愈：备份/状态失败中止、拉起异常与早退回滚、两振回滚、真实文件锁等待、安装锁、桥接原子占用 |

### 冒烟（真实 Windows / overlay）
| 文件 | 覆盖 |
|---|---|
| `smoke_screenshots.py` | 截图服务（临时目录） |
| `smoke_overlay.py` | 截图 toast：临时配置 + 测试窗口驱动 overlay（需先编译 overlay） |
| `smoke_collections.py` | collections 后端（临时库） |
| `smoke_update_flow.py` | 更新流程进程级：真实助手子进程正常替换+握手清理、真实文件占用下回滚、安装锁互斥（需先编译 overlay） |
| `test_overlay_lifecycle.py` | 真实管道连接/退出/断连重连/架构切换 |
| `pipe_lifecycle.cpp` | 管道生命周期 C++ 侧 |
| `_process_fixture.py` | 受控启动器/游戏窗口 fixture（由上述测试启动，不碰真实游戏） |

### `scripts/`
| 文件 | 用途 |
|---|---|
| `verify_frontend.py`（tests 内） | 见上 |
| `frozen_smoke.py` | 冻结包（PyInstaller）冒烟：bundled overlay 管道 + 删除事务 |
| `verify_frozen_update.py`（scripts 内） | 冻结包受控更新/回滚演练：真实替换助手→拉起新版→前端握手→数据保全、真实占用回滚、安装锁（需先构建冻结包） |
| `package_develop.py` / `develop.spec` | 隔离试用包构建 |
| `runtime_portable.py` | 便携运行时 |

## 改动后的验证建议

| 改动 | 必跑 |
|---|---|
| 前端 ts / partials / css | `npm run build` → `verify_frontend.py`（+ 需要时 `node test_p*_frontend.cjs`） |
| 扫描 / 判重 / identity | `test_scanner.py` + `test_p0_data_flow.py` + `test_p1_reliability.py` |
| DB schema / repository | `test_p0_data_flow.py` + `test_classic_boundary.py` + `smoke_collections.py` |
| 桥 / UISync | `test_ui_sync.py` + `test_p0_frontend.cjs` |
| 封面缓存 / 缩略图 | `test_cover_cache.py` + `test_cover_thumb.py` |
| 多源搜索 | `test_multi_source.py` |
| 更新 / 替换助手 / 弹层 | `test_updater.py` + `test_update_apply.py` + `test_update_ui.cjs`（+ 前端 `npm run build`）；进程级过 `smoke_update_flow.py`（需 overlay） |
| overlay / 截图 | `smoke_screenshots.py` + `smoke_overlay.py` + `test_overlay_lifecycle.py` |
| 打包 | `package_develop.py` 流程 + `frozen_smoke.py` |

## 说明

- 多数测试是独立 `python xxx.py`（部分用 `unittest`），无统一 runner；建议按上表逐条跑。
- `test_p0_data_flow.py` / `test_p1_reliability.py` 用 `-B` 避免生成 `__pycache__`。
- 涉及 Windows 窗口/进程/管道/热键的测试需在真实 Windows 桌面会话运行。

# develop 试用包

## 使用

本轮产物是 Windows x64 的 PyInstaller onedir 文件夹版，版本 `1.4.0-beta.1`，仅无翻译原版。需要 Windows 10/11 x64、Microsoft Edge WebView2 Runtime 和系统 .NET Framework，运行不要求安装 Python 或 Node。

解压整个 KazariPlay 文件夹到可写位置，双击 `KazariPlay.exe` 或 `run_develop.cmd`。保留同目录 `_internal/`，不能只移动 EXE。运行时默认使用包旁 `data/` 保存 games.db、config.json、covers、logs 和 screenshots；首次运行是空库，不读取现有 `%APPDATA%/KazariPlay` 或迁移旧库。

`KAZARIPLAY_DATA_DIR` 可显式指定独立数据目录；指定目录不可写会报错，不静默退回正式库。源码直接启动且未设置该变量时维持既有数据策略。试用配置与正式库隔离，便于重复测试。

## 构建

从本地 `develop` worktree 根目录执行，确保 Python/PyInstaller、npm、前端依赖和 MSVC 可用：

```powershell
# 在 overlay/ 中顺序编译两个原版截图 Overlay
cmd /c build.bat
cmd /c build32.bat
# 以下在 worktree 根目录运行
python scripts/package_develop.py --output trial-build-1.4.0-beta.1-win64
```

新输出的父目录须已存在，输出本身必须不存在。脚本只操作全新目录，不使用 --clean、不清空旧输出，失败现场保留；重复构建用新目录，不覆盖用户试用数据。源码 js/node_modules、旧 Overlay、`KazariPlay_V1.0_build` 和用户库不清理。

脚本执行类型检查、TS 构建、前端组装、原版边界检查，再按 [develop.spec](../scripts/develop.spec) 打包。Windows 版本资源从 version.py 生成。资源清单只包含运行前端、图标、默认封面与两个截图 Overlay EXE，不递归打包截图、config、数据库或实验 Textractor DLL。

产物为 `<output>/dist/KazariPlay/`，BUILD_INFO.json 记录提交、构建时工作区状态、Python 和实际依赖版本；该文件比口头版本判断优先。本机验证环境使用 PyInstaller 6.21.0、pywebview 6.2.1、Python 3.11.9、Pillow 12.3.0、pywin32 312、windows-capture 2.0.1；Pillow/pywin32 与 requirements 固定版本存在差异，未在本轮重装全局依赖。

## 验证

实际冻结 EXE（不是源码替身）通过 WebView 桥、版本/关于页、无翻译 API、UI 新增/编辑/删除、SQLite、受控游戏窗口启动/监控/关闭、WGC 捕获 2076x1124 程序画面、Pillow 缩略图/重命名/删除、包内 x64/x86 Overlay 管道/零退出。截图直接捕获程序窗口，不依赖其他全屏程序上方的屏幕像素。

显式 `--smoke-test` 仅供离线验收，要求一个不存在的 `KAZARIPLAY_DATA_DIR` 和 `KAZARIPLAY_SMOKE_REPORT` 路径，测试会创建/删除自身临时游戏记录；普通双击不会启动自检。测试新建记录的元数据匹配被替身截获，不发网络请求。`KAZARIPLAY_SMOKE_GAME` 可指定受控窗口 fixture，仅对该明确的测试进程做启动/关闭。

PyInstaller 报告包含可选平台模块、pycparser lextab/yacctab 和 importlib_resources.trees 警告；上述 Windows 冻结流程已通过，但不能据此称所有可选路径都验证。未进行代码签名、安装器构建、另一台干净 Windows 验证、真实游戏/网络元数据、多显示器或独占全屏验收。

用户试用通过后，再核对从 develop 到 main 和旧 master 的合并范围、发布与推送授权；本轮不合并这些分支，也不创建 Release/tag。

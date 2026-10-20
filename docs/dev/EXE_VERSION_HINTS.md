# exe 版本资源字段探测

> 探测日期：2026-10-19  
> 样本：独立数据目录 `artifacts/dev-data` 中的 34 个游戏（用户当前库）  
> 目的：确认 exe 版本资源能否提供标题、开发商、引擎线索，避免把版权字段误当开发商。

## 1. 读取方式

Windows PE 的版本资源位于 `StringFileInfo`，通过 `version.dll` 读取：

- `GetFileVersionInfoSizeW`
- `GetFileVersionInfoW`
- `VerQueryValueW`

字段路径形如：

```text
\StringFileInfo\{lang:04x}{codepage:04x}\CompanyName
\StringFileInfo\{lang:04x}{codepage:04x}\LegalCopyright
```

资源可能有多组语言/代码页，需要依次尝试。当前实现见 `src/kazari_play/utils/infra/win_version.py`。

## 2. 字段覆盖情况

34 个游戏中的非空数量：

| 字段 | 非空 | 唯一值 | 主要用途 |
|---|---:|---:|---|
| `FileDescription` | 30/34 | 23 | 游戏标题，当前标题首选 |
| `ProductName` | 22/34 | 8 | 产品名/引擎，标题与引擎线索 |
| `CompanyName` | 14/34 | 7 | 开发商/会社，最可靠的开发商字段 |
| `LegalCopyright` | 28/34 | 16 | 版权声明，引擎线索强，开发商线索弱 |
| `OriginalFilename` | 28/34 | 9 | 引擎判断很强，如 `tvpwin32.exe`、`BGI.exe` |
| `InternalName` | 27/34 | 7 | 引擎判断很强，如 `Ethornell`、`SiglusEngine` |
| `Comments` | 16/34 | 8 | 引擎/Buriko/musica 线索 |
| `FileVersion` | 多数 | — | 版本号，不用于身份判断 |

按常见引擎关键词匹配：

| 字段 | 命中数 |
|---|---:|
| `LegalCopyright` | 21/34 |
| `ProductName` | 18/34 |
| `OriginalFilename` | 22/34 |
| `InternalName` | 24/34 |
| `CompanyName` | 7/34 |
| `Comments` | 7/34 |

这些命中包含 `KIRIKIRI` / `TVP`、`BURIKO` / `Ethornell`、`BGI`、`Siglus`、`CMVS`、`QLIE`、`musica` / `ClearRave` 等。

## 3. 实际样例

### 3.1 只有引擎、没有开发商

`9-nine-` 系列：

```text
FileDescription = 9-nine-:Episode 2
ProductName     = TVP(KIRIKIRI) Z core / Scripting Platform for Win32
CompanyName     = ""
LegalCopyright  = (KIRIKIRI core) (C) W.Dee and contributors ...
OriginalFilename= tvpwin32.exe
InternalName    = tvp2/win32
```

结论：可以稳定识别 KiriKiri，但拿不到游戏开发商。`LegalCopyright` 是引擎版权，不是游戏版权。

### 3.2 开发商和引擎都能拿到

`Summer Pockets REFLECTION BLUE`：

```text
CompanyName      = VisualArt's
ProductName      = Siglus
LegalCopyright   = Copyright (C) VisualArt's 2017
OriginalFilename = SiglusEngine.exe
```

`千之刃涛、桃花染之皇姬` / BGI 系列：

```text
CompanyName      = BURIKO Co.,Ltd.
LegalCopyright   = Copyright (C) 2007-2016 BURIKO Co.,Ltd.
OriginalFilename = BGI.exe
InternalName     = Ethornell
Comments         = BURIKO General Interpreter uses the OggVorbis libraries...
```

### 3.3 版权方是开发商/发行商

```text
eden* They were only two, on the planet.
CompanyName    = minori
LegalCopyright = Copyright (C) 2009-2015 minori,MangaGamer

いろとりどりのセカイ HD Edition
CompanyName    = FAVORITE
LegalCopyright = Copyright (C) 2021 FAVORITE

青鸟
CompanyName    = Yggdrasill
LegalCopyright = Copyright (C) 2017 Yggdrasill

纯白交响曲
CompanyName    = ClearRave
LegalCopyright = Copyright (C) 2009 ClearRave
```

### 3.4 版权信息不足

```text
天津罪
LegalCopyright = Copyright (C) 2005-2016
```

只有年份，没有可用名称。

## 4. 结论

### 开发商

`CompanyName` / `LegalCopyright` 不作为 `developer` 字段来源，只作为匹配线索和冲突校验：

1. 元数据源合并结果
2. 用户手动填写
3. `CompanyName` / `LegalCopyright` 仅用于判断候选是否明显不合理

限制：

- `LegalCopyright` 不是结构化的“开发商”字段，只是版权声明。
- KiriKiri 等引擎的版权会覆盖游戏开发商。
- `BURIKO` 既可能是品牌/开发商，也可能是引擎相关；不能无条件写入。
- 汉化组、发行商、引擎供应商都可能出现在版权文本中。
- 不新增 `company_hint` 字段，也不自动覆盖 `developer`。

### 引擎

优先级建议：

1. `OriginalFilename` / `InternalName`
2. `ProductName`
3. `LegalCopyright`
4. `Comments`
5. 文件结构/签名（`.xp3`、`BGI.exe`、`SiglusEngine` 等）

`LegalCopyright` 对 KiriKiri 这类引擎很有效，但不能单独作为引擎最终结论；应与现有 `GameScanner._detect_engine` 的文件特征合并。

## 5. 已实现范围

`read_version_info` 现在返回：

```text
FileDescription, ProductName, FileVersion, CompanyName,
LegalCopyright, OriginalFilename, InternalName, Comments
```

扫描器已接入：

- 版本资源只在扫描调用栈内临时使用，不新增 `Game` 字段，不写数据库。
- `GameScanner._engine_from_version` 在文件特征无法识别引擎时，用
  `ProductName`、`OriginalFilename`、`InternalName`、`Comments`、`LegalCopyright`
  补引擎。
- `title` 仍只使用 `FileDescription` / `ProductName` / 清洗后的文件夹名 / exe 名，
  不使用版权字段。
- `CompanyName` / `LegalCopyright` 只作为运行时线索，**不新增字段、不写数据库、不在 UI 展示，也不自动填入 `developer`**。
- 原始字段只存在于扫描过程的内存对象中；匹配流程只用它做引擎补充和候选校验，不把会社/版权文本当成开发商字段，也不保存到 `Game`。
- 引擎识别仍以文件特征为主，版本资源作为补充。

## 6. 复现

本次探测使用独立库中的 34 个游戏，读取上述字段并统计。探测结果只用于设计参考；样本仍偏小，后续应加入更多引擎、汉化版本和不同语言 exe 验证。

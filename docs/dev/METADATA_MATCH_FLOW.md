# 元数据匹配流程设计（讨论稿）

> 状态：讨论中，尚未实现。目标规模：1000+ 游戏。  
> 核心原则：搜索负责找到候选，身份判断负责确定是哪一个游戏。

## 1. 目标

- 匹配结果只有两个用户可见出口：**自动应用**、**未匹配区**。
- 网络失败不进入未匹配区，转为本次批量任务内的可重试失败。
- 不做候选图、多维证据模型和完整运行审计，保持流程可解释。

## 2. 结果状态

| 状态 | 含义 | 处理 |
|---|---|---|
| `accepted` | 存在唯一高置信候选 | 自动写回 |
| `unmatched` | 来源正常返回，但没有候选、多个候选难分、字段冲突，或发现同版本重复卡片 | 进入未匹配区，等待手动判断 |
| `retryable` | 超时、限流、来源不可用、来源熔断 | 不进入未匹配区；保留本次失败列表，提示重试 |
| `skipped` | 已有 ID 或字段完整 | 不改写 |

判定优先级：

```text
能确定唯一游戏
  → accepted

没有 accepted，但存在来源错误
  → retryable

没有 accepted，且来源都正常返回
  → unmatched
```

如果外部 ID 已经明确确定游戏，其他来源超时不影响结果，不需要重试。

## 3. 简化决策规则

只保留三条规则：

1. **外部 ID 命中**
   - Kungal / Hikarinagi 的 `vndb_id` 桥接一致
   - Bangumi ID 一致
   - 候选之间外部 ID 一致

   → `accepted`

2. **没有 ID，但标题和辅助信息一致**
   - 标题别名精确匹配
   - 年份一致或缺失
   - 开发商一致
   - FD / 部数 / Episode 编号不冲突

   → `accepted`

3. **信息不足或存在多个合理答案**
   - 同名多个条目
   - 年份冲突
   - 开发商冲突
   - 部数 / 版本不确定

   → `unmatched`

不在此版本引入候选图、多维置信度模型或复杂聚类。

## 4. 未匹配区

未匹配区只保存需要人工判断的情况，不保存网络错误。

包括：

- 无候选
- 多候选难分
- 年份 / 开发商 / 版本冲突
- 发现同版本重复卡片

同版本重复组只自动匹配一张：按 `date_added` 最早的卡片作为主卡，其余卡片全部进入未匹配区，原因标记为 `duplicate_version`。

建议表：

```sql
unmatched_games (
  game_id     TEXT PRIMARY KEY,
  reason      TEXT NOT NULL,     -- no_candidate / ambiguous / conflict / duplicate_version
  candidates_json TEXT,          -- 精简候选，可为空
  updated_at  TEXT NOT NULL
)
```

用户操作：

```text
未匹配区
  → 手动搜索 / 查看同版本卡片
  → 选择候选
  → 勾选字段应用
  → 自行决定是否合并本地卡片
  → 从队列移除
```

## 5. 可重试失败

- 失败列表只属于本次批量任务，默认不落库。
- 批量结束提示：`成功 820 / 未匹配 160 / 网络失败 20`。
- 提供「重试失败的 20 个」；只重跑失败项，不重新扫描。
- 来源熔断期间直接返回 `retryable`，避免拖慢整批。

## 6. 游戏身份来源

匹配使用的“游戏身份”与数据库判重使用的 `identity` 分开：

- `identity = 引擎 + 归一化文件夹名`：只用于入库判重。
- `MatchHints`：用于搜索和判断到底是哪一个游戏，不直接参与判重。

### MatchHints 建议字段

```text
existing_ids    已有 vndb_id / bangumi_id / game_sources
titles          当前标题、FileDescription、ProductName、exe 文件名、文件夹名
edition_tokens  HD / FHD / Remake / SANA / FD / Episode / 部数
year_hint       文件夹/标题中的年份
engine          扫描识别出的引擎
```

获取顺序：

1. 数据库已有外部 ID
2. exe 版本资源 `FileDescription` / `ProductName`
3. 当前标题
4. exe 文件名
5. 文件夹名
6. 引擎与版本标记

### 使用原则

- 外部 ID 是匹配候选的强证据，不用于自动合并卡片。
- 本地标题只作为候选搜索和标题证据，不单独决定身份。
- 网络失败与“候选不对”分开处理。
- 不把 FileDescription 或 exe 文件名写入 `identity`。
- 自动匹配只负责选择 source candidate 和写回字段，不删除或合并本地卡片。

### 已确认

- `MatchHints` 先不落库；匹配时从 `title / folder / exe_path / engine` 运行时构建，批量任务内缓存。
- FHD / SANA / HD 默认按独立版本处理；即使外部 ID / release 明确指向同一版本，也不自动合并，而是进入未匹配区等待手动判断。
- FD / 续篇 / Episode 始终独立成卡，不能与本篇或前作自动合并。
- 同版本重复组只自动匹配一张：按 `date_added` 最早的卡片作为主卡，其余卡片进入未匹配区。
- 主卡判断只使用入库时间 `date_added`，不比较完整度、外部 ID 或卡片 ID。

### 仍待确认

- 同一作品的不同语言 / 汉化目录是否始终合并为一张卡。

## 7. 后续实现顺序

1. 后端结果状态分层：`accepted / unmatched / retryable / skipped`
2. `unmatched_games` 表与未匹配区
3. 重试失败列表与批量结果提示
4. MatchHints 与身份判断规则
5. 查询去重、游戏级并发

性能优化独立于身份判断，避免把两件事混成一个复杂状态机。

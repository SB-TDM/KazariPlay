# 本地 HTTP 封面服务与单文件封面模型

> 状态：accepted（设计定稿 2026-10-17；待 beta.5 实施）

封面展示目前走 pywebview JS 桥 base64：每张 512 缩略图 40–183KB，原图 61KB–1.14MB；封面文件按来源分成 `_vndb/_ms/_manual` 多套命名，缩略图按 `md5(path+mtime)` 命名，换封面/删游戏/跨目录复制都会留下孤儿文件，且数据目录搬迁后绝对路径失效。参考 PotatoVN（本地路径 + 原生 BitmapImage）与 ReinaManager（WebView 原生 `<img>` + 自定义协议/HTTP 缓存），决定把封面传输改为**仅监听 127.0.0.1 的本地 HTTP 服务**，同时把封面收敛为**每游戏一个确定性文件 + 一个确定性缩略图**。

具体决定：

- 文件：`covers/{game_id}.{ext}`（按文件头识别 jpg/png/webp）；`thumbs/{game_id}_w512.jpg`；不再保留 `_vndb/_ms/_manual` 变体，来源只作为元数据记录。
- 服务：`ThreadingHTTPServer` 绑定 `127.0.0.1:0`；优先绑定 config 中持久化的首选端口（冲突才用随机端口）；URL 为 `/c/{token}/cover/{game_id}?v=<mtime>-<size>`；token 为每安装一次生成的持久随机值；GET/HEAD only，严格校验 game_id，不做目录遍历；窗口关闭即停。
- 内容：HTTP 只提供 512 缩略图；原图仅作为缩略图生成失败时的回退，不默认提供。
- 缓存：`Cache-Control: private, max-age=31536000, immutable`；替换封面后 `?v` 变化，跨重启因 token/端口稳定而继续命中 Chromium 缓存。
- 前端：`getGames/getGame` payload 直接内嵌 `cover_url`（卡片/详情零额外桥调用）；保留 `getCoverUrl(game_id)` 供显式刷新；`onerror` 回退默认图；服务启动失败时整会话回退旧 base64 `getCover`，保留一个 beta。
- 缩略图：保存/下载时丢到后台封面线程池预生成；HTTP 首次请求未就绪时按 game_id 加锁等待，超时回退原图；生成失败回退原图，原图缺失回退默认图。
- 迁移：当前 `cover_path` 有效则以其为准；失效/缺失时按 `_manual` > `_ms` > `_vndb`，同优先级取 mtime 最新；其余旧变体删除；迁移失败不阻塞启动，交给重新匹配下载。
- 范围：只迁移封面；截图、Logo、默认图仍走现有路径。配置增加隐藏开关 `cover_service.enabled`（默认 true）。
- HTML：先验证 `html=` 内联页能否加载 localhost 图片；不能则 HTML 也由同一服务提供（同源）。

## 备选方案与取舍

- 继续 base64 + 缩略图：实现最小，但每张封面仍要过 JS 桥，缓存/内存受 Python LRU 限制；本次不采用。
- Tauri 式自定义协议 / WebView2 虚拟主机：最接近 ReinaManager，但 pywebview 未暴露稳定的自定义协议注册接口，改动更大且依赖平台内部；暂不采用。
- HTTP 服务默认提供原图：省去缩略图生成，但 1411×1949 封面单张解码约 11MB，滚动内存代价高；不采用。
- 每次启动随机 token / 随机端口：更安全，但 URL 每次变化会让 Chromium 缓存全部失效；不采用。
- 固定端口/无 token：实现简单，但端口冲突与任意本机进程枚举；不采用。

## 后果

- 封面路径不再经过 base64，滚动/首屏依赖 WebView 原生加载与 HTTP 缓存；Python 侧封面 LRU 可删除。
- 多一个本地 HTTP 生命周期与安全面：只绑回环、token、game_id 白名单、关闭停服；启动失败必须回退 base64，否则封面全空。
- 单文件模型让“来源”不再对应文件；`_vndb/_ms/_manual` 成为历史术语，迁移后删除。
- 跨目录复制自测数据时，启动迁移会按文件名把 `cover_path` 修回当前数据目录；旧文件仍存在时先复制再改路径。

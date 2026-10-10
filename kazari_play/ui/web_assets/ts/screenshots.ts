// ============================================================
// screenshots.ts — 游戏截图（Steam 式：卡片 / 预览 / 右键管理）
// 依赖：state.ts / core.ts（esc/toast）/ ui.ts（showSheet/closeSheet/showInputDialog/showConfirmDialog）
// 定义：renderScreenshots / openShotPreview / showShotMenu / hideShotMenu /
//       renameShot / openShotFolder / copyShot / deleteShot + 截图事件绑定
// ============================================================

/** 截图对象（后端 getScreenshots 返回元素） */
interface Shot {
  file: string;
  created?: string;
}

let shotTarget: Shot | null = null;   // 当前预览/右键菜单的截图对象
let shotObserver: IntersectionObserver | null = null;   // 截图缩略图懒加载
let shotsGameId = '';
let shotTargetGameId = '';
let shotsRequest = 0;
let previewRequest = 0;

// ---------- 截图卡片 ----------
function renderScreenshots(): void {
  const grid = document.getElementById('shotsGrid');
  if (!grid || !App.data.currentGame) return;
  const gid = App.data.currentGame.id;
  const request = ++shotsRequest;
  if (shotsGameId !== gid) {
    shotObserver?.disconnect();
    shotObserver = null;
    grid.innerHTML = '';
    shotsGameId = gid;
    shotTarget = null;
    previewRequest++;
    hideShotMenu();
  }
  bridge.getScreenshots(gid, function (s: unknown) {
    if (request !== shotsRequest || App.data.currentGame?.id !== gid) return;
    let shots: Shot[] = [];
    try { shots = JSON.parse(String(s || '[]')) as Shot[]; } catch (e) { }
    if (!shots.length) {
      // 空态：清空并显示占位（若无占位则新增）
      const hasEmpty = grid.querySelector('.shots-empty');
      if (!hasEmpty) {
        shotObserver?.disconnect();
        grid.querySelectorAll('.shot-item').forEach(c => c.remove());
        grid.innerHTML = '<div class="shots-empty">暂无截图，按 F12 截取游戏画面</div>';
      }
      return;
    }
    // 移除空的占位（若有截图）
    const empty = grid.querySelector('.shots-empty');
    if (empty) empty.remove();

    // 增量更新：按 file 复用已有卡片（保留已加载缩略图），只增删变化项
    const existing = new Map<string, HTMLElement>();
    grid.querySelectorAll<HTMLElement>('.shot-item').forEach(el => {
      existing.set(el.dataset.shotFile!, el);
    });
    const wanted = new Set(shots.map(x => x.file));
    // 1) 移除已不存在的卡片
    existing.forEach((el, f) => {
      if (!wanted.has(f)) {
        if (shotObserver) shotObserver.unobserve(el);
        el.remove();
        existing.delete(f);
      }
    });
    // 2) 新增缺失的卡片（复用已有的不动）
    shots.forEach(shot => {
      if (existing.has(shot.file)) return;
      const el = document.createElement('div');
      el.className = 'shot-item';
      el.dataset.shotFile = shot.file;
      el.dataset.gameId = gid;
      el.innerHTML = `<div class="shot-thumb"></div><div class="shot-meta">
          <span class="shot-time">${esc(shot.created || '')}</span></div>`;
      // 缩略图懒加载：进入视口才请求（复用截图区根节点），避免全量并发取图
      if (shotObserver) shotObserver.observe(el);
      el.onclick = () => openShotPreview(shot);
      el.oncontextmenu = (e: MouseEvent) => { e.preventDefault(); showShotMenu(e.clientX, e.clientY, shot); };
      grid.appendChild(el);
    });
    if (!shotObserver) {
      shotObserver = new IntersectionObserver((entries) => {
        entries.forEach(en => {
          if (!en.isIntersecting) return;
          const item = en.target as HTMLElement;
          shotObserver!.unobserve(item);
          const gid = item.dataset.gameId || '';
          const f = item.dataset.shotFile;
          if (!gid || !f) return;
          bridge.getScreenshotThumb(gid, f, function (uri: unknown) {
            if (!item.isConnected || App.data.currentGame?.id !== gid) return;
            const th = item.querySelector('.shot-thumb') as HTMLElement | null;
            if (uri && th) th.style.backgroundImage = `url('${uri}')`;
          });
        });
      }, { root: grid.parentElement, rootMargin: '160px' });
      grid.querySelectorAll('.shot-item').forEach(c => shotObserver!.observe(c));
    }
  });
}

// 截图保存后由后端 evaluate_js 定向调用（与 reloadCovers 同风格的轻量更新）：
// 仅当详情抽屉正打开该游戏时重渲染截图卡片，立即显示新截图；
// 详情未打开或不是该游戏时无需处理（打开详情时会拉取最新列表）。
function refreshScreenshots(gameId: string): void {
  if (!App.data.currentGame || App.data.currentGame.id !== gameId) return;
  const overlay = document.getElementById('detailOverlay');
  if (overlay && overlay.classList.contains('show')) {
    renderScreenshots();
  }
}

// ---------- 预览（左键放大 + 加载动画；显示原图，占满主窗口）----------
function openShotPreview(shot: Shot): void {
  shotTarget = shot;
  const gid = App.data.currentGame!.id;
  shotTargetGameId = gid;
  const request = ++previewRequest;
  document.getElementById('shotPreviewTitle')!.textContent = '截图';
  showSheet('shotPreviewOverlay');
  const img = document.getElementById('shotPreviewImg') as HTMLImageElement;
  const loading = document.getElementById('shotPreviewLoading') as HTMLElement;
  img.classList.remove('loaded');
  img.src = '';
  loading.textContent = '加载中…';
  loading.style.display = 'flex';
  // 预览显示原图（非缩略图），适配全屏预览
  bridge.getScreenshotOriginal(gid, shot.file, function (uri: unknown) {
    if (request !== previewRequest || App.data.currentGame?.id !== gid) return;
    if (!uri) { loading.textContent = '加载失败'; return; }
    img.onload = () => { loading.style.display = 'none'; img.classList.add('loaded'); };
    img.src = String(uri);
  });
}

// ---------- 截图右键菜单（重命名 / 打开所在文件夹 / 复制 / 删除）----------
function showShotMenu(x: number, y: number, shot: Shot): void {
  shotTarget = shot;
  shotTargetGameId = App.data.currentGame!.id;
  const m = document.getElementById('shotMenu') as HTMLElement;
  const vw = window.innerWidth, vh = window.innerHeight;
  let px = x, py = y;
  if (px + 160 > vw - 8) px = vw - 168;
  if (py + 180 > vh - 8) py = vh - 188;
  px = Math.max(8, px); py = Math.max(8, py);
  m.style.left = px + 'px';
  m.style.top = py + 'px';
  m.classList.add('show');
}

function hideShotMenu(): void {
  document.getElementById('shotMenu')!.classList.remove('show');
}

function renameShot(): void {
  if (!shotTarget) return;
  const cur = shotTarget.file;
  const gid = shotTargetGameId;
  showInputDialog({
    title: '重命名截图', label: '新名称', value: cur.replace(/\.(png|jpg|jpeg)$/i, ''),
    cb: function (name) {
      if (name && name.trim() && name.trim() !== cur) {
        bridge.renameScreenshot(gid, cur, name.trim(), function (ok: unknown) {
          if (!ok) { toast('重命名失败'); return; }
          if (App.data.currentGame?.id === gid) renderScreenshots();
        });
      }
    }
  });
}

function openShotFolder(): void {
  if (!shotTarget) return;
  bridge.openScreenshotFolder(shotTargetGameId, shotTarget.file, function (ok: unknown) {
    toast(ok ? '已在资源管理器中定位' : '定位失败');
  });
}

function copyShot(): void {
  if (!shotTarget) return;
  bridge.copyScreenshotToClipboard(shotTargetGameId, shotTarget.file, function (ok: unknown) {
    toast(ok ? '已复制到剪贴板' : '复制失败');
  });
}

function deleteShot(): void {
  if (!shotTarget) return;
  const f = shotTarget.file;
  const gid = shotTargetGameId;
  showConfirmDialog({
    title: '删除截图',
    message: `删除「${f}」？`,
    danger: true, okText: '删除', cb: () => {
      bridge.deleteScreenshot(gid, f, function (ok: unknown) {
        if (!ok) { toast('删除失败'); return; }
        if (App.data.currentGame?.id === gid) renderScreenshots();
      });
    }
  });
}

// ---------- 截图事件绑定 ----------
document.getElementById('shotPreviewClose')!.onclick = () => {
  previewRequest++;
  closeSheet('shotPreviewOverlay');
};
document.querySelectorAll<HTMLElement>('#shotMenu .item').forEach(it => {
  it.onclick = () => {
    hideShotMenu();
    const act = it.dataset.act;
    if (act === 'rename') renameShot();
    else if (act === 'folder') openShotFolder();
    else if (act === 'copy') copyShot();
    else if (act === 'del') deleteShot();
  };
});

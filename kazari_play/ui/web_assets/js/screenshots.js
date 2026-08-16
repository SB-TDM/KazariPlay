// ============================================================
// screenshots.js — 游戏截图（Steam 式：卡片 / 预览 / 右键管理）
// 依赖：state.js / core.js（esc/toast）/ ui.js（showSheet/closeSheet/showInputDialog/showConfirmDialog）
// 定义：renderScreenshots / openShotPreview / showShotMenu / hideShotMenu /
//       renameShot / openShotFolder / copyShot / deleteShot + 截图事件绑定
// ============================================================

let shotTarget = null;   // 当前预览/右键菜单的截图对象

// ---------- 截图卡片 ----------
function renderScreenshots() {
  const grid = document.getElementById('shotsGrid');
  if (!grid || !App.data.currentGame) return;
  grid.innerHTML = '';
  bridge.getScreenshots(App.data.currentGame.id, function (s) {
    let shots = [];
    try { shots = JSON.parse(s || '[]'); } catch (e) { }
    if (!shots.length) {
      grid.innerHTML = '<div class="shots-empty">暂无截图，按 F12 截取游戏画面</div>';
      return;
    }
    shots.forEach(shot => {
      const el = document.createElement('div');
      el.className = 'shot-item';
      el.innerHTML = `<div class="shot-thumb"></div><div class="shot-meta">
          <span class="shot-time">${esc(shot.created || '')}</span></div>`;
      bridge.getScreenshotThumb(App.data.currentGame.id, shot.file, function (uri) {
        const th = el.querySelector('.shot-thumb');
        if (uri && th) th.style.backgroundImage = `url('${uri}')`;
      });
      el.onclick = () => openShotPreview(shot);
      el.oncontextmenu = (e) => { e.preventDefault(); showShotMenu(e.clientX, e.clientY, shot); };
      grid.appendChild(el);
    });
  });
}

// 截图保存后由后端 evaluate_js 定向调用（与 reloadCovers 同风格的轻量更新）：
// 仅当详情抽屉正打开该游戏时重渲染截图卡片，立即显示新截图；
// 详情未打开或不是该游戏时无需处理（打开详情时会拉取最新列表）。
function refreshScreenshots(gameId) {
  if (!App.data.currentGame || App.data.currentGame.id !== gameId) return;
  const overlay = document.getElementById('detailOverlay');
  if (overlay && overlay.classList.contains('show')) {
    renderScreenshots();
  }
}

// ---------- 预览（左键放大 + 加载动画）----------
function openShotPreview(shot) {
  shotTarget = shot;
  document.getElementById('shotPreviewTitle').textContent = '截图';
  showSheet('shotPreviewOverlay');
  const img = document.getElementById('shotPreviewImg');
  const loading = document.getElementById('shotPreviewLoading');
  img.classList.remove('loaded');
  img.src = '';
  loading.textContent = '加载中…';
  loading.style.display = 'flex';
  bridge.getScreenshotThumb(App.data.currentGame.id, shot.file, function (uri) {
    if (!uri) { loading.textContent = '加载失败'; return; }
    img.onload = () => { loading.style.display = 'none'; img.classList.add('loaded'); };
    img.src = uri;
  });
}

// ---------- 截图右键菜单（重命名 / 打开所在文件夹 / 复制 / 删除）----------
function showShotMenu(x, y, shot) {
  shotTarget = shot;
  const m = document.getElementById('shotMenu');
  const vw = window.innerWidth, vh = window.innerHeight;
  let px = x, py = y;
  if (px + 160 > vw - 8) px = vw - 168;
  if (py + 180 > vh - 8) py = vh - 188;
  px = Math.max(8, px); py = Math.max(8, py);
  m.style.left = px + 'px';
  m.style.top = py + 'px';
  m.classList.add('show');
}

function hideShotMenu() {
  document.getElementById('shotMenu').classList.remove('show');
}

function renameShot() {
  if (!shotTarget) return;
  const cur = shotTarget.file;
  showInputDialog({
    title: '重命名截图', label: '新名称', value: cur.replace(/\.(png|jpg|jpeg)$/i, ''),
    cb: function (name) {
      if (name && name.trim() && name.trim() !== cur) {
        bridge.renameScreenshot(App.data.currentGame.id, cur, name.trim());
        renderScreenshots();
      }
    }
  });
}

function openShotFolder() {
  if (!shotTarget) return;
  bridge.openScreenshotFolder(App.data.currentGame.id, shotTarget.file);
  toast('已在资源管理器中定位');
}

function copyShot() {
  if (!shotTarget) return;
  bridge.copyScreenshotToClipboard(App.data.currentGame.id, shotTarget.file);
  toast('已复制到剪贴板');
}

function deleteShot() {
  if (!shotTarget) return;
  const f = shotTarget.file;
  showConfirmDialog({
    title: '删除截图',
    message: `删除「${f}」？`,
    danger: true, okText: '删除', cb: () => {
      bridge.deleteScreenshot(App.data.currentGame.id, f);
      renderScreenshots();
    }
  });
}

// ---------- 截图事件绑定 ----------
document.getElementById('shotPreviewClose').onclick = () => closeSheet('shotPreviewOverlay');
document.querySelectorAll('#shotMenu .item').forEach(it => {
  it.onclick = () => {
    hideShotMenu();
    const act = it.dataset.act;
    if (act === 'rename') renameShot();
    else if (act === 'folder') openShotFolder();
    else if (act === 'copy') copyShot();
    else if (act === 'del') deleteShot();
  };
});

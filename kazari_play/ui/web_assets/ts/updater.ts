// ============================================================
// updater.ts — 应用内更新（关于页接线 / 更新弹层 / 启动检查 / 进度轮询）
// 依赖：core.ts（bridge / toast）、ui.ts（showSheet / closeSheet / setSheetLocked）
// 定义：updaterStartupCheck / updaterBindAbout / openUpdateModal / closeUpdateModal
// 说明：设计见 docs/dev/AUTO_UPDATE_DESIGN.md；实际替换（apply）在阶段 C 接入。
// ============================================================

/** 后端更新状态快照（getUpdateState / checkUpdate 返回） */
interface UpdateState {
  state: string;
  error?: string;
  reason?: string;
  current_version?: string;
  latest_version?: string;
  notes?: string;
  size?: number;
  percent?: number;
  downloaded?: number;
  total?: number;
  speed_mb?: number;
  eta_seconds?: number;
  downloaded_path?: string;
}

let updatePollTimer: ReturnType<typeof setInterval> | null = null;
let updatePrompted = false;               // 启动检查只提示一次
let updateCurrent: UpdateState | null = null;

function updaterById<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

function updaterParse(raw: unknown): UpdateState | null {
  try {
    const st = JSON.parse(String(raw || '{}')) as UpdateState;
    return st && typeof st.state === 'string' ? st : null;
  } catch (e) {
    return null;
  }
}

// 状态 → 关于页文案（空串 = 不显示；unsupported/auto_disabled 显示原因，静默场景自然为空）
function updaterStatusText(st: UpdateState): string {
  switch (st.state) {
    case 'up_to_date': return '已是最新版本';
    case 'available': return st.latest_version ? '发现新版本 v' + st.latest_version : '发现新版本';
    case 'skipped': return st.latest_version ? '已跳过 v' + st.latest_version : '已跳过该版本';
    case 'downloading': return '下载中…';
    case 'ready': return '更新包已就绪，可重启安装';
    case 'failed': return st.error || '更新失败';
    case 'unsupported': return st.reason || '当前运行方式不支持自动更新';
    case 'auto_disabled': return st.reason || '预发布版本默认不自动检查更新';
    default: return '';
  }
}

function updaterAboutStatus(text: string): void {
  const el = updaterById('updateStatus');
  if (el) el.textContent = text;
}

// ---------- 弹层阶段 ----------

function updateStopPolling(): void {
  if (updatePollTimer !== null) {
    clearInterval(updatePollTimer);
    updatePollTimer = null;
  }
}

// 下载中锁定弹层：遮罩点击 / Esc / 关闭按钮全部失效（设计：下载中禁止关闭）
function updateSetLocked(locked: boolean): void {
  setSheetLocked('updateOverlay', locked);
  const btn = updaterById('updateClose');
  if (btn) btn.hidden = locked;
}

function updateRenderProgress(st: UpdateState): void {
  const pct = typeof st.percent === 'number' ? st.percent : 0;
  const fill = updaterById('updateFill');
  if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
  const text = updaterById('updateProgText');
  if (!text) return;
  const parts: string[] = [pct.toFixed(0) + '%'];
  if (st.downloaded) {
    parts.push(st.downloaded.toFixed(1) + ' MB' + (st.total ? ' / ' + st.total.toFixed(1) + ' MB' : ''));
  }
  if (st.speed_mb) parts.push(st.speed_mb.toFixed(1) + ' MB/s');
  if (st.eta_seconds) parts.push('剩余约 ' + st.eta_seconds + ' 秒');
  text.textContent = parts.join(' · ');
}

function updateSetStage(stage: 'available' | 'downloading' | 'ready' | 'failed'): void {
  const st = updateCurrent || { state: '' };
  updaterById('updateFoot')!.hidden = stage !== 'available';
  updaterById('updateFootReady')!.hidden = stage !== 'ready';
  updaterById('updateFootFail')!.hidden = stage !== 'failed';
  updaterById('updateProg')!.hidden = stage !== 'downloading';
  updaterById('updateError')!.hidden = stage !== 'failed';
  updaterById('updateNotes')!.hidden = stage === 'downloading' || stage === 'ready';
  if (stage === 'failed') {
    updaterById('updateError')!.textContent = st.error || '更新失败，请重试';
  }
  updaterById('updateTitle')!.textContent =
    stage === 'downloading' ? '正在下载更新'
      : stage === 'ready' ? '更新包已就绪'
        : stage === 'failed' ? '更新失败' : '发现新版本';
}

function updateStartPolling(): void {
  updateStopPolling();
  updatePollTimer = setInterval(() => {
    bridge.getUpdateState(function (raw: unknown, failed?: boolean) {
      if (failed) return;
      const st = updaterParse(raw);
      if (!st) return;
      updateCurrent = st;
      updaterAboutStatus(updaterStatusText(st));
      if (st.state === 'downloading') {
        updateSetStage('downloading');
        updateRenderProgress(st);
        return;
      }
      updateStopPolling();
      updateSetLocked(false);
      if (st.state === 'ready') updateSetStage('ready');
      else if (st.state === 'failed') updateSetStage('failed');
      else if (st.state === 'available') updateSetStage('available');
    });
  }, 500);
}

function openUpdateModal(st?: UpdateState): void {
  const s = st || updateCurrent;
  if (!s) return;
  updateCurrent = s;
  const ver = updaterById('updateNewVer');
  if (ver) ver.textContent = 'v' + (s.latest_version || '-');
  const size = updaterById('updateSize');
  if (size) size.textContent = s.size ? (s.size / 1048576).toFixed(1) + ' MB' : '未知';
  const notes = updaterById('updateNotes');
  if (notes) notes.textContent = s.notes || '';
  const stage: 'available' | 'downloading' | 'ready' | 'failed' =
    s.state === 'ready' ? 'ready'
      : s.state === 'downloading' ? 'downloading'
        : s.state === 'failed' ? 'failed' : 'available';
  updateSetStage(stage);
  if (stage === 'downloading') {
    updateSetLocked(true);
    updateRenderProgress(s);
    updateStartPolling();
  } else if (stage === 'ready') {
    updateSetLocked(false);
  }
  showSheet('updateOverlay');
}

function closeUpdateModal(): void {
  updateStopPolling();
  closeSheet('updateOverlay');
}

// ---------- 动作 ----------

function updaterStartDownload(): void {
  updateSetStage('downloading');
  updateRenderProgress({ state: 'downloading', percent: 0 });
  updateSetLocked(true);
  bridge.downloadUpdate(function (raw: unknown, failed?: boolean) {
    if (failed) {
      updateSetLocked(false);
      updateCurrent = { state: 'failed', error: '无法开始下载，请重试' };
      updateSetStage('failed');
      return;
    }
    updateStartPolling();
  });
}

function updaterApply(mode: 'now' | 'exit'): void {
  const btn = mode === 'now' ? updaterById<HTMLButtonElement>('updateApplyNow') : updaterById<HTMLButtonElement>('updateApplyExit');
  if (btn) btn.disabled = true;
  bridge.applyUpdate(mode, function (raw: unknown, failed?: boolean) {
    if (btn) btn.disabled = false;
    let result: { ok?: boolean; msg?: string } = {};
    try { result = JSON.parse(String(raw || '{}')); } catch (e) { }
    if (failed || !result.ok) toast(result.msg || '更新应用失败，请重试');
  });
}

function updaterCheck(force: boolean, silent: boolean): void {
  const btn = updaterById<HTMLButtonElement>('btnCheckUpdate');
  if (btn && !silent) { btn.disabled = true; btn.textContent = '检查中…'; }
  bridge.checkUpdate(force, function (raw: unknown, failed?: boolean) {
    if (btn && !silent) { btn.disabled = false; btn.textContent = '检查更新'; }
    if (failed) {
      if (!silent) updaterAboutStatus('检查失败，请稍后重试');
      return;
    }
    const st = updaterParse(raw);
    if (!st) return;
    updateCurrent = st;
    updaterAboutStatus(updaterStatusText(st));
    if (st.state === 'available') {
      if (!silent) { openUpdateModal(st); return; }
      if (!updatePrompted) {
        updatePrompted = true;
        setTimeout(() => openUpdateModal(st), 1200);   // 启动提示：不打扰首屏渲染
      }
    }
  });
}

// ---------- 绑定 ----------

function updaterBindModal(): void {
  const close = updaterById('updateClose');
  if (close) close.onclick = () => closeUpdateModal();
  const later = updaterById('updateLater');
  if (later) later.onclick = () => closeUpdateModal();
  const skip = updaterById('updateSkip');
  if (skip) skip.onclick = () => {
    bridge.skipUpdate(function (raw: unknown, failed?: boolean) {
      if (failed) { toast('操作失败，请重试'); return; }
      const st = updaterParse(raw);
      if (st) updaterAboutStatus(updaterStatusText(st));
      closeUpdateModal();
      toast('已跳过该版本');
    });
  };
  const go = updaterById('updateGo');
  if (go) go.onclick = () => updaterStartDownload();
  const retry = updaterById('updateRetry');
  if (retry) retry.onclick = () => updaterStartDownload();
  const now = updaterById('updateApplyNow');
  if (now) now.onclick = () => updaterApply('now');
  const applyExit = updaterById('updateApplyExit');
  if (applyExit) applyExit.onclick = () => updaterApply('exit');
  const page = updaterById('updateOpenPage');
  if (page) page.onclick = () => bridge.openReleasePage();
  const leave = updaterById('updateExit');
  if (leave) leave.onclick = () => closeUpdateModal();
}

function updaterBindAbout(): void {
  const btn = updaterById('btnCheckUpdate');
  if (btn) btn.addEventListener('click', () => updaterCheck(true, false));
  updaterBindModal();
}

/** 启动后台静默检查（24h 缓存由后端保证；发现新版只提示一次） */
function updaterStartupCheck(): void {
  updaterCheck(false, true);
}

updaterBindAbout();

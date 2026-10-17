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
  notice?: string;
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
  offline?: boolean;
}

let updatePollTimer: ReturnType<typeof setTimeout> | null = null;
let updatePollGen = 0;                    // 轮询代际：停止 / 重启即作废在途回调
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

// 一次性提示（启动自愈的回滚 / 中断恢复）：后端在首个响应中带出，前端负责展示
function updaterShowNotice(st: UpdateState | null): void {
  if (st && st.notice) {
    toast(String(st.notice));
    st.notice = '';
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
  updatePollGen++;
  if (updatePollTimer !== null) {
    clearTimeout(updatePollTimer);
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
      : stage === 'ready' ? ('更新包已就绪' + (st.offline ? '（基于上次检查）' : ''))
        : stage === 'failed' ? '更新失败' : '发现新版本';
}

// 串行轮询：上一请求返回后才发下一个；代际不符的迟到响应直接丢弃
// （固定间隔允许请求重叠，晚发先回的响应会把就绪界面改回下载中）
function updateStartPolling(): void {
  updateStopPolling();
  const gen = updatePollGen;
  const tick = function (): void {
    if (gen !== updatePollGen) return;
    updatePollTimer = null;
    bridge.getUpdateState(function (raw: unknown, failed?: boolean) {
      if (gen !== updatePollGen) return;   // 迟到 / 旧代际响应：不得覆盖当前状态
      if (failed) { schedule(); return; }
      const st = updaterParse(raw);
      if (!st) { schedule(); return; }
      updateCurrent = st;
      updaterShowNotice(st);
      updaterAboutStatus(updaterStatusText(st));
      if (st.state === 'downloading') {
        updateSetStage('downloading');
        updateRenderProgress(st);
        schedule();
        return;
      }
      updateStopPolling();
      updateSetLocked(false);
      if (st.state === 'ready') updateSetStage('ready');
      else if (st.state === 'failed') updateSetStage('failed');
      else if (st.state === 'available') updateSetStage('available');
    });
  };
  const schedule = function (): void {
    if (gen !== updatePollGen) return;
    updatePollTimer = setTimeout(tick, 500);
  };
  tick();
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

// 下载发起与状态补查都失败：解除锁定并给出重试入口（避免永久停在锁定的下载界面）
function updaterDownloadRecover(): void {
  updateStopPolling();
  updateSetLocked(false);
  updateSetStage('failed');
  const err = updaterById('updateError');
  if (err) err.textContent = '下载请求失败，无法获取更新状态，请重试';
}

function updaterStartDownload(): void {
  if (!updateCurrent || updateCurrent.state !== 'downloading') {
    updateSetStage('downloading');
    updateRenderProgress({ state: 'downloading', percent: 0 });
    updateSetLocked(true);
  }
  bridge.downloadUpdate(function (raw: unknown, failed?: boolean) {
    let ok = false;
    try { ok = !!JSON.parse(String(raw || '{}')).ok; } catch (e) { }
    if (failed || !ok) {
      // 未真正开始（已就绪 / 已在下载 / 状态不符）：立刻按后端真实状态纠正界面；
      // 补查也失败时恢复为可重试的失败态，不锁死弹层
      bridge.getUpdateState(function (raw2: unknown, failed2?: boolean) {
        if (failed2) { updaterDownloadRecover(); return; }
        const st = updaterParse(raw2);
        if (!st) { updaterDownloadRecover(); return; }
        updateCurrent = st;
        updaterShowNotice(st);
        updaterAboutStatus(updaterStatusText(st));
        if (st.state === 'downloading') {
          updateSetStage('downloading');
          updateRenderProgress(st);
          updateSetLocked(true);
          updateStartPolling();
          return;
        }
        updateStopPolling();
        updateSetLocked(false);
        updateSetStage(st.state === 'ready' ? 'ready' : (st.state === 'failed' ? 'failed' : 'available'));
      });
      return;
    }
    updateStartPolling();
  });
}

function updaterApply(): void {
  const btn = updaterById<HTMLButtonElement>('updateApplyNow');
  if (btn) btn.disabled = true;
  bridge.applyUpdate(function (raw: unknown, failed?: boolean) {
    let result: { ok?: boolean; msg?: string; notice?: string } = {};
    try { result = JSON.parse(String(raw || '{}')); } catch (e) { }
    const okNow = !failed && !!result.ok;
    updaterShowNotice(result as UpdateState);
    // 成功发起时应用即将退出：保持按钮禁用，防止重复发起（后端亦有单次防护）
    if (btn && !okNow) btn.disabled = false;
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
    updaterShowNotice(st);
    updaterAboutStatus(updaterStatusText(st));
    if (st.state === 'available') {
      if (!silent) { openUpdateModal(st); return; }
      if (!updatePrompted) {
        updatePrompted = true;
        setTimeout(() => openUpdateModal(st), 1200);   // 启动提示：不打扰首屏渲染
      }
      return;
    }
    // 手动检查：按真实状态恢复对应操作界面（就绪弹层关闭后仍可重新打开）
    if (!silent && (st.state === 'ready' || st.state === 'downloading')) {
      openUpdateModal(st);
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
      if (st) { updaterShowNotice(st); updaterAboutStatus(updaterStatusText(st)); }
      closeUpdateModal();
      toast('已跳过该版本');
    });
  };
  const go = updaterById('updateGo');
  if (go) go.onclick = () => updaterStartDownload();
  const retry = updaterById('updateRetry');
  if (retry) retry.onclick = () => updaterStartDownload();
  const now = updaterById('updateApplyNow');
  if (now) now.onclick = () => updaterApply();
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

/** 启动检查：静默检查一次；预发布（auto_disabled）/失败时再本地探测就绪缓存
 *
 * 命中"就绪"与"发现新版本"一致提示一次（标题标注"基于上次检查"），
 * 让重启后无需先手动点检查更新也能看到已下载的更新包。
 */
function updaterStartupCheck(): void {
  const promptOnce = function (st: UpdateState): void {
    if (updatePrompted) return;
    updatePrompted = true;
    updateCurrent = st;
    updaterShowNotice(st);
    updaterAboutStatus(updaterStatusText(st));
    setTimeout(() => openUpdateModal(st), 1200);   // 启动提示：不打扰首屏渲染
  };
  const probe = function (): void {
    bridge.probeReadyUpdate(function (raw: unknown, failed?: boolean) {
      if (failed) return;
      const st = updaterParse(raw);
      if (st && st.state === 'ready') promptOnce(st);
    });
  };
  bridge.checkUpdate(false, function (raw: unknown, failed?: boolean) {
    if (!failed) {
      const st = updaterParse(raw);
      if (st) {
        updateCurrent = st;
        updaterShowNotice(st);
        updaterAboutStatus(updaterStatusText(st));
        if (st.state === 'available' || st.state === 'ready') {
          promptOnce(st);
          return;
        }
      }
    }
    probe();
  });
}

updaterBindAbout();

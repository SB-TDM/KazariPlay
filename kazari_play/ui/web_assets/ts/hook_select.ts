/* hook_select.ts — Hook 点选择弹窗（V1.1）
 * 触发：启动已启用翻译但无 hook_code 的游戏后（detail.ts 收到 need_hook_select）。
 * 流程：每 500ms 轮询 bridge.getHookCandidates()（C++ 收集 → Python 转发），
 *       点击某条 → bridge.selectHook(gameId, handle, hookCode) → 关闭并开始翻译。
 */
(function () {
  const $ = (id: string): HTMLElement => document.getElementById(id)!;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let gameId: number | null = null;
  let busy = false;

  function esc(s: unknown): string {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
  }

  function open(gid: number): void {
    gameId = gid;
    busy = false;
    $('hookSelectOverlay').classList.add('show');
    $('hookSelList').innerHTML = '';
    $('hookSelHint').textContent = '等待游戏文本…';
    startPoll();
  }

  function close(): void {
    stopPoll();
    closeSheet('hookSelectOverlay');
  }

  function startPoll(): void {
    stopPoll();
    pollTimer = setInterval(poll, 500);
  }

  function stopPoll(): void {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function poll(): void {
    if (!bridge || busy) return;
    bridge.getHookCandidates(function (s: unknown) {
      let data: { list: HookCandidate[]; error: string } = { list: [], error: '' };
      try { data = JSON.parse(String(s || '{}')) as { list: HookCandidate[]; error: string }; } catch (e) { }
      const list = data.list || [];
      const hint = $('hookSelHint');
      if (data.error) {
        hint.textContent = '⚠ ' + data.error;
      } else if (list.length) {
        hint.textContent = '共 ' + list.length + ' 个，选预览为「完整句」的那条（推荐靠前）：';
      }
      renderList(list);
    });
  }

  // 噪声候选识别：GDI 逐字渲染（连续重复字符）/ 乱码（有效字符占比过低）
  function isNoise(c: HookCandidate): boolean {
    const t = c.text || '';
    if (!t) return true;
    let rep = 1, maxRep = 1;
    for (let i = 1; i < t.length; i++) {
      rep = t[i] === t[i - 1] ? rep + 1 : 1;
      if (rep > maxRep) maxRep = rep;
    }
    if (maxRep >= 3) return true;   // 重复字符 → GDI 噪声
    let valid = 0;
    for (let i = 0; i < t.length; i++) {
      const code = t.charCodeAt(i);
      if ((code >= 0x41 && code <= 0x5A) || (code >= 0x61 && code <= 0x7A) ||
          (code >= 0x30 && code <= 0x39) ||
          (code >= 0x3000 && code <= 0x9FFF)) valid++;
    }
    return valid * 3 < t.length;    // 有效字符太少 → 乱码
  }

  // 预览清洗：连续重复字符压缩 + 整段周期重复（近似 C++ 过滤器链，供候选预览，
  // 让用户直接看到该 hook 清洗后的"完整句"，避免选到渲染缓冲的 handle）
  function cleanPreview(t: string | undefined): string {
    if (!t) return '';
    let s = '';
    for (let i = 0; i < t.length; i++) {
      if (s.length && s[s.length - 1] === t[i] && t[i] !== '.') continue;
      s += t[i];
    }
    for (let p = 2; p <= Math.floor(s.length / 2); p++) {
      let matched = 0;
      for (let i = 0; i < s.length; i++) if (s[i] === s[i % p]) matched++;
      if (matched * 10 >= s.length * 9) { s = s.slice(0, p); break; }
    }
    return s;
  }

  // 排序：完整句（清洗后以明确结束标点结尾）优先 > 清洗后长度短优先 > 原始长度短优先。
  // 渲染缓冲的 handle（逐字/递增、无标点结尾）自动排后。
  function renderList(list: HookCandidate[]): void {
    const box = $('hookSelList');
    const clean = (list || []).filter(c => !isNoise(c));
    const sorted = clean.slice().sort((a, b) => {
      const ap = cleanPreview(a.text), bp = cleanPreview(b.text);
      const aEnd = /[。！？！」』）…]$/.test(ap);
      const bEnd = /[。！？！」』）…]$/.test(bp);
      if (aEnd !== bEnd) return bEnd ? 1 : -1;
      if (ap.length !== bp.length) return ap.length - bp.length;
      return (a.text || '').length - (b.text || '').length;
    });
    box.innerHTML = '';
    if (!sorted.length) {
      box.innerHTML = '<div class="hook-empty">还没有捕获到对话文本，请在游戏里翻一句对话</div>';
      return;
    }
    sorted.forEach((c, idx) => {
      const row = document.createElement('div');
      const preview = cleanPreview(c.text) || '';
      const isRec = idx === 0 && preview.length > 3;
      row.className = 'hook-item' + (isRec ? ' recommend' : '');
      const name = c.hook_name || '';
      const recLabel = /[。！？！」』）…]$/.test(preview) ? '推荐 · 完整句' : '推荐 · 对话';
      row.innerHTML =
        (isRec ? '<div class="hook-rec">' + recLabel + '</div>' : '') +
        '<div class="hook-text">' + esc(preview.slice(0, 60) || '（空文本）') + '</div>' +
        (name ? '<div class="hook-meta">' + esc(name) + '</div>' : '');
      row.onclick = () => pick(c);
      box.appendChild(row);
    });
  }

  function pick(c: HookCandidate): void {
    if (busy) return;
    busy = true;
    bridge.selectHook(String(gameId), c.handle, c.hook_code || '', function () {
      busy = false;
      toast('已选择 Hook 点，开始翻译');
      close();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('hookSelClose').onclick = close;
    $('hookSelRefresh').onclick = function () { startPoll(); poll(); };
    document.addEventListener('keydown', function (e: KeyboardEvent) {
      if (e.key === 'Escape' && $('hookSelectOverlay').classList.contains('show')) close();
    });
  });

  window.HookSelect = { open: open, close: close };
})();
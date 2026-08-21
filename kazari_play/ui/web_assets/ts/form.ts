// ============================================================
// form.ts — 编辑 / 手动添加表单 + 元数据候选（VNDB / Bangumi）
// 依赖：state.ts / core.ts（loadCoverTo/toast/esc）/ ui.ts（showSheet/closeSheet）
// 定义：openEdit / openAdd / saveForm / renderCandidates + 表单事件绑定
// ============================================================

/** 元数据源（后端 getMetadataSources 返回元素） */
interface MetadataSource {
  id: string;
  name: string;
  icon?: string;
  status?: string;
  enabled?: boolean;
}

/** 元数据候选（后端 searchMetadata 返回元素） */
interface MetadataCandidate {
  source_id?: string;
  source_name?: string;
  source_icon?: string;
  title?: string;
  developer?: string;
  released?: string;
  rating?: number;
}

// 表单行显隐（添加模式只保留启动文件行，其余字段由后端从 exe 自动推导）
const FORM_ROWS = ['fTitleRow', 'fEngineRow', 'fDevRow', 'fRatingRow', 'fDescRow'];

function setFormRows(showList: string[], hideList: string[]): void {
  (showList || []).forEach(id => (document.getElementById(id) as HTMLElement).style.display = 'flex');
  (hideList || []).forEach(id => (document.getElementById(id) as HTMLElement).style.display = 'none');
}

// 打开编辑表单（复用详情对象的数据）
function openEdit(g: Game): void {
  App.data.editingId = g.id;
  document.getElementById('formTitle')!.textContent = '编辑游戏';
  (document.getElementById('fTitle') as HTMLInputElement).value = g.title || '';
  (document.getElementById('fEngine') as HTMLInputElement).value = g.engine || '';
  (document.getElementById('fDev') as HTMLInputElement).value = g.dev || '';
  (document.getElementById('fRating') as HTMLInputElement).value = String(g.rating || 0);
  (document.getElementById('fDesc') as HTMLTextAreaElement).value = g.description || '';
  (document.getElementById('fExe') as HTMLInputElement).value = g.exe_path || '';
  (document.getElementById('fCoverPrev') as HTMLImageElement).src = '';
  loadCoverTo(g.id, document.getElementById('fCoverPrev'), 'img');
  (document.getElementById('fSearchKw') as HTMLInputElement).value = g.title || '';
  document.getElementById('fCands')!.style.display = 'none';
  setFormRows(FORM_ROWS.concat(['fExeRow', 'fCoverRow', 'fMetaRow']), []);
  initMetaSources();   // 渲染来源工具栏（首次打开时拉取）
  showSheet('formOverlay');
}

// 打开手动添加表单：只保留「启动文件」，不强制取名（标题由后端自动推导为 exe 文件夹名）
function openAdd(): void {
  App.data.editingId = null;
  document.getElementById('formTitle')!.textContent = '手动添加单个 exe';
  ['fTitle', 'fEngine', 'fDev', 'fDesc', 'fExe'].forEach(id => (document.getElementById(id) as HTMLInputElement).value = '');
  (document.getElementById('fRating') as HTMLInputElement).value = '0';
  document.getElementById('fCands')!.style.display = 'none';
  setFormRows(['fExeRow'], FORM_ROWS.concat(['fCoverRow', 'fMetaRow']));
  showSheet('formOverlay');
}

// ---------- 表单内联校验错误 ----------
// 错误显示在对应行下方并聚焦首个错误字段（替代一次性 toast，避免提示一闪而过）
function showFormError(rowId: string, msg: string): void {
  const row = document.getElementById(rowId);
  if (!row) return;
  clearFormError(rowId);
  row.classList.add('has-error');
  const err = document.createElement('div');
  err.className = 'form-error';
  err.textContent = msg;
  row.appendChild(err);
  const input = row.querySelector('input, select, textarea') as HTMLElement | null;
  if (input) input.focus();
}

function clearFormError(rowId: string): void {
  const row = document.getElementById(rowId);
  if (!row) return;
  row.classList.remove('has-error');
  const old = row.querySelector('.form-error');
  if (old) old.remove();
}

function saveForm(): void {
  clearFormError('fTitleRow');
  clearFormError('fExeRow');
  const data = {
    title: (document.getElementById('fTitle') as HTMLInputElement).value,
    engine: (document.getElementById('fEngine') as HTMLInputElement).value,
    developer: (document.getElementById('fDev') as HTMLInputElement).value,
    rating: parseInt((document.getElementById('fRating') as HTMLInputElement).value || '0'),
    description: (document.getElementById('fDesc') as HTMLTextAreaElement).value,
    exe_path: (document.getElementById('fExe') as HTMLInputElement).value
  };
  // 编辑：标题仍必填；添加：只要求 exe（标题由后端自动推导，不强制取名）
  if (App.data.editingId && !data.title.trim()) { showFormError('fTitleRow', '标题不能为空'); return; }
  if (!App.data.editingId && !data.exe_path.trim()) { showFormError('fExeRow', '请先选择要添加的 exe 文件'); return; }
  bridge.saveGame(String(App.data.editingId), JSON.stringify(data));
  closeSheet('formOverlay');
}

// ---------- 多源元数据检索（源可自行配置，见 core/multi_source.py）----------
let metaSources: MetadataSource[] = [];     // 后端 getMetadataSources 返回的全部源
let metaSrcMode = 'mixed'; // 当前检索范围：'mixed' 或某源 id

// 拉取源列表并渲染工具栏（混合 + 各源 favicon）
function initMetaSources(): void {
  if (metaSources.length) return;
  bridge.getMetadataSources(function (s: unknown) {
    try { metaSources = JSON.parse(String(s || '[]')) as MetadataSource[]; } catch (e) { metaSources = []; }
    renderSrcBar();
  });
}

function renderSrcBar(): void {
  const bar = document.getElementById('fSrcBar');
  if (!bar) return;
  bar.innerHTML = '';
  const mk = (id: string, label: string, icon: string, on: boolean, usable: boolean) => {
    const chip = document.createElement('span');
    chip.className = 'src-chip' + (on ? ' on' : '') + (usable ? '' : ' off');
    chip.title = usable ? '仅检索该源' : '该源暂未接入，可在 设置-元数据 查看';
    chip.innerHTML = (icon ? `<img src="${esc(icon)}" onerror="this.style.display='none'" alt="">` : '')
      + `<span>${esc(label)}</span>`;
    if (usable) chip.onclick = () => { metaSrcMode = id; renderSrcBar(); };
    return chip;
  };
  bar.appendChild(mk('mixed', '混合', '', metaSrcMode === 'mixed', true));
  metaSources.forEach(src => {
    const usable = src.status === 'ready' || src.status === 'experimental';
    bar.appendChild(mk(src.id, src.name, src.icon || '', metaSrcMode === src.id, usable));
  });
}

// 当前检索范围对应的源 id 列表（mixed = 设置中勾选的启用源）
function currentSearchTargets(): string[] {
  if (metaSrcMode !== 'mixed') return [metaSrcMode];
  return metaSources.filter(s => s.enabled).map(s => s.id);
}

// ---------- 多源元数据候选渲染（带来源 favicon）----------
function renderCandidates(cands: MetadataCandidate[]): void {
  const box = document.getElementById('fCands')!;
  box.style.display = 'block';
  box.innerHTML = '';
  if (!cands.length) { box.innerHTML = '<div class="cand-empty">未找到结果</div>'; return; }
  cands.forEach(c => {
    const d = document.createElement('div');
    d.className = 'cand';
    const icon = c.source_icon
      ? `<img class="cand-src-icon" src="${esc(c.source_icon)}" onerror="this.style.display='none'" alt="">` : '';
    const srcName = c.source_name
      ? `<span class="cand-src-name">${esc(c.source_name)}</span>` : '';
    d.innerHTML = `<div class="cand-title">${icon}${srcName}${esc(c.title || '')}</div>
      <div class="cand-sub">${esc(c.developer || '')}${c.released ? ' · ' + esc(c.released) : ''}${c.rating ? ' · ★' + (+c.rating).toFixed(1) : ''}</div>`;
    d.onclick = () => {
      if (!App.data.editingId) return;
      bridge.applyCandidate(String(App.data.editingId), JSON.stringify(c));
      toast('已应用元数据（空字段已填充）');
    };
    box.appendChild(d);
  });
}

// ---------- 表单事件绑定 ----------
document.getElementById('btnPickExe')!.onclick = () => {
  if (bridge) bridge.selectExe(function (p: unknown) { if (p) (document.getElementById('fExe') as HTMLInputElement).value = String(p); });
};
document.getElementById('btnPickCover')!.onclick = () => {
  if (!App.data.editingId) { toast('请先保存游戏再更换封面'); return; }
  bridge.pickCover(function (s: unknown) {
    let r: { path?: string; preview?: string } = {};
    try { r = JSON.parse(String(s || '{}')) as { path?: string; preview?: string }; } catch (e) { }
    if (r.path) {
      (document.getElementById('fCoverPrev') as HTMLImageElement).src = r.preview || '';
      bridge.setCover(String(App.data.editingId), r.path);
      toast('封面已更换');
    }
  });
};
document.getElementById('btnMetaSearch')!.onclick = () => {
  const kw = (document.getElementById('fSearchKw') as HTMLInputElement).value.trim();
  if (!kw) { toast('请输入搜索关键词'); return; }
  toast('搜索中…');
  bridge.searchMetadata(kw, JSON.stringify(currentSearchTargets()), function (s: unknown) {
    let cands: MetadataCandidate[] = [];
    try { cands = JSON.parse(String(s || '[]')) as MetadataCandidate[]; } catch (e) { }
    renderCandidates(cands);
  });
};
document.getElementById('formClose')!.onclick = () => closeSheet('formOverlay');
document.getElementById('formCancel')!.onclick = () => closeSheet('formOverlay');
document.getElementById('formSave')!.onclick = saveForm;
// 输入即清除对应行的校验错误
(document.getElementById('fTitle') as HTMLInputElement).addEventListener('input', () => clearFormError('fTitleRow'));
(document.getElementById('fExe') as HTMLInputElement).addEventListener('input', () => clearFormError('fExeRow'));
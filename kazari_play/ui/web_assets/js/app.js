
// pywebview 桥接兼容层：把 QWebChannel 风格的 bridge.xxx(cb) 转为 pywebview.api.xxx().then(cb)
const bridge = new Proxy({}, {
  get(t, name){
    if(name === 'dataChanged') return { connect: function(){} };  // 无信号，改为轮询
    return function(...args){
      let cb = null;
      if(args.length && typeof args[args.length-1] === 'function'){ cb = args.pop(); }
      const api = window.pywebview && window.pywebview.api;
      const fn = api && api[name];
      if(!fn){ if(cb) cb('[]'); return Promise.resolve('[]'); }
      const p = fn.apply(api, args);
      if(cb){ p.then(r=>cb(r)).catch(()=>cb('[]')); }
      return p;
    };
  }
});

let GAMES = [];
let currentGame = null;
let editingId = null;
let runningId = '';
const state = { nav:'全部作品', kw:'', sort:'时间', batch:false, selected:new Set(), collectionId:null, collectionGroupId:null, openGroupId:null, collectionTree:[], collectionOrder:[] };

window.__app = { refresh: function(){ refreshAll(true); }, toast: function(m){ toast(m); }, reloadCovers: reloadCovers };

// 强制重载所有可见卡片封面（VNDB 匹配/手动更换后由后端主动触发）
function reloadCovers(){
  document.querySelectorAll('.card').forEach(card=>{
    const c=card.querySelector('.cover');
    if(!c) return;
    card.dataset.coverLoaded = '';
    bridge.getCover(card.dataset.id, function(uri){
      if(!uri) return;
      card.dataset.coverLoaded = '1';
      c.style.backgroundImage=`url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
    });
  });
}

// 封面尺寸档位（对应设置 cover_size）
const COVER_SIZES = { small:{w:132,h:180}, medium:{w:154,h:210}, large:{w:180,h:245} };
function applyCoverSize(size){
  const s = COVER_SIZES[size] || COVER_SIZES.medium;
  document.documentElement.style.setProperty('--card-w', s.w + 'px');
  document.documentElement.style.setProperty('--card-h', s.h + 'px');
}

function toggleMax(){
  const b=document.getElementById('btnMax');
  const willMax = b && b.textContent==='□';
  bridge.windowToggleMaximize();
  document.body.classList.toggle('maximized', !!willMax);   // 最大化时隐藏缩放手柄
  if(b) b.textContent = willMax ? '❐' : '□';
}

// ---------- 初始化 ----------
function init(){
  const onReady = function(){
    window.bridgeReady = true;
    bridge.getConfig(function(s){
      try{
        const cfg = JSON.parse(s||'{}');
        if(window.Settings) Settings.applyTheme(cfg.theme||'light');
        applyCoverSize(cfg.cover_size||'medium');
      }catch(e){}
    });
    refreshAll(true);
    setInterval(()=>refreshAll(false), 30000);   // 长轮询兜底（数据无变化时不重建）
  };
  if(window.pywebview && window.pywebview.api){ onReady(); }
  else { window.addEventListener('pywebviewready', onReady); }
}

function refreshAll(force){
  if(!bridge) return;
  bridge.getGames(function(s){
    const fresh=JSON.parse(s);
    // 数据无变化时不重建网格，避免卡片闪烁（事件推送/轮询兜底）
    if(force || _gamesChanged(GAMES, fresh)){
      GAMES=fresh; renderAll(); syncCurrentGame();
    } else {
      // 仅刷新运行状态等轻量字段
      GAMES=fresh; syncCurrentGame(); markRunning();
    }
  });
  bridge.getCollectionsTree(function(s){
    state.collectionTree = JSON.parse(s||'[]');
    renderCollectionTree();
  });
  bridge.getRunning(function(r){ runningId=r||''; markRunning(); });
}

// 判断游戏列表是否有实质变化（比较影响卡片显示的字段 + 派生文本）
function _gamesChanged(a, b){
  if(a.length!==b.length) return true;
  for(let i=0;i<a.length;i++){
    const x=a[i], y=b[i];
    const xc=(x.collections||[]).map(c=>c.id).join(','), yc=(y.collections||[]).map(c=>c.id).join(',');
    if(!x || !y || x.id!==y.id || x.fav!==y.fav || x.rating!==y.rating
       || x.dev!==y.dev || x.title!==y.title || x.last_played!==y.last_played
       || x.play_time!==y.play_time || x.last_text!==y.last_text
       || !!x.has_cover!==!!y.has_cover
       || xc!==yc
       || x.play_time_text!==y.play_time_text) return true;
  }
  return false;
}

// 后台数据变化后同步当前详情（收藏/标签/评分等即时生效）
function syncCurrentGame(){
  if(!currentGame) return;
  const fresh=GAMES.find(g=>g.id===currentGame.id);
  if(!fresh){ currentGame=null; return; }
  currentGame=fresh;
  if(document.getElementById('detailOverlay').classList.contains('show')){
    refreshDetail();
  }
}
// 按需加载封面并应用到元素（data URI 由后端缓存，重复取不重复解码）
function loadCoverTo(gameId, el, prefix){
  if(!el) return;
  bridge.getCover(gameId, function(uri){
    if(!uri) return;
    if(prefix==='img'){ el.src=uri; return; }
    el.style.backgroundImage=`url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
  });
}

function refreshDetail(){
  loadCoverTo(currentGame.id, document.getElementById('dlgCover'), 'bg');
  document.getElementById('dlgTitle').textContent=currentGame.title;
  document.getElementById('dlgDesc').textContent=currentGame.description||'暂无简介';
  renderDetailTags();
  renderInfoBar();
  updateFavBtn();
  renderScreenshots();
  const rate=document.querySelector('.rate-edit');
  if(rate){ rate.dataset.r=currentGame.rating; initRateEdit(); }
  markRunning();
}

// ---------- 游戏截图（Steam 式）----------
function renderScreenshots(){
  const grid=document.getElementById('shotsGrid');
  if(!grid || !currentGame) return;
  grid.innerHTML='';
  bridge.getScreenshots(currentGame.id, function(s){
    let shots=[]; try{ shots=JSON.parse(s||'[]'); }catch(e){}
    if(!shots.length){
      grid.innerHTML='<div class="shots-empty">暂无截图，按 F12 截取游戏画面</div>';
      return;
    }
    shots.forEach(shot=>{
      const el=document.createElement('div');
      el.className='shot-item';
      el.innerHTML=`<div class="shot-thumb"></div><div class="shot-meta">
          <span class="shot-time">${esc(shot.created||'')}</span></div>`;
      bridge.getScreenshotThumb(currentGame.id, shot.file, function(uri){
        const th=el.querySelector('.shot-thumb');
        if(uri && th) th.style.backgroundImage=`url('${uri}')`;
      });
      el.onclick=()=>openShotPreview(shot);
      el.oncontextmenu=(e)=>{ e.preventDefault(); showShotMenu(e.clientX, e.clientY, shot); };
      grid.appendChild(el);
    });
  });
}

let shotTarget=null;   // 当前预览/右键菜单的截图对象

function openShotPreview(shot){
  shotTarget=shot;
  document.getElementById('shotPreviewTitle').textContent='截图';
  showSheet('shotPreviewOverlay');
  const img=document.getElementById('shotPreviewImg');
  const loading=document.getElementById('shotPreviewLoading');
  img.classList.remove('loaded');
  img.src='';
  loading.textContent='加载中…';
  loading.style.display='flex';
  bridge.getScreenshotThumb(currentGame.id, shot.file, function(uri){
    if(!uri){ loading.textContent='加载失败'; return; }
    img.onload=()=>{ loading.style.display='none'; img.classList.add('loaded'); };
    img.src=uri;
  });
}

// 截图右键菜单（重命名 / 打开所在文件夹 / 复制 / 删除）
function showShotMenu(x, y, shot){
  shotTarget=shot;
  const m=document.getElementById('shotMenu');
  const vw=window.innerWidth, vh=window.innerHeight;
  let px=x, py=y;
  if(px+160>vw-8) px=vw-168;
  if(py+180>vh-8) py=vh-188;
  px=Math.max(8,px); py=Math.max(8,py);
  m.style.left=px+'px';
  m.style.top=py+'px';
  m.classList.add('show');
}
function hideShotMenu(){
  document.getElementById('shotMenu').classList.remove('show');
}

function renameShot(){
  if(!shotTarget) return;
  const cur=shotTarget.file;
  showInputDialog({
    title:'重命名截图', label:'新名称', value:cur.replace(/\.(png|jpg|jpeg)$/i,''),
    cb:function(name){
      if(name&&name.trim()&&name.trim()!==cur){
        bridge.renameScreenshot(currentGame.id, cur, name.trim());
        renderScreenshots();
      }
    }
  });
}

function openShotFolder(){
  if(!shotTarget) return;
  bridge.openScreenshotFolder(currentGame.id, shotTarget.file);
  toast('已在资源管理器中定位');
}

function copyShot(){
  if(!shotTarget) return;
  bridge.copyScreenshotToClipboard(currentGame.id, shotTarget.file);
  toast('已复制到剪贴板');
}

function deleteShot(){
  if(!shotTarget) return;
  const f=shotTarget.file;
  showConfirmDialog({
    title:'删除截图',
    message:`删除「${f}」？`,
    danger:true, okText:'删除', cb:()=>{
      bridge.deleteScreenshot(currentGame.id, f);
      renderScreenshots();
    }
  });
}

// 详情信息栏（游玩时长/上次游玩/开发商/发售日等），供打开与轮询刷新共用
function renderInfoBar(){
  const g=currentGame;
  document.getElementById('dlgInfo').innerHTML=[
    ['开发商',g.dev||'未知'],['引擎',g.engine||'未知'],['发售日',g.released||'未知'],
    ['游玩时长',g.play_time_text||'未游玩'],['上次游玩',g.last_text||'从未'],
    ['评分','<span class="rate-edit" data-r="'+g.rating+'"></span>'],
  ].map(x=>`<div class="info-item"><b>${x[0]}</b>${x[1]}</div>`).join('');
}

function renderAll(){
  const list = filterGames(GAMES);
  renderCards(list);
  renderEmpty(list);
  updateBatchBar();
}

function filterGames(games){
  let list = games.slice();
  if(state.nav==='继续游玩'){
    // 只显示最近 7 天游玩过的游戏
    const weekAgo = Date.now() - 7*24*3600*1000;
    list = list.filter(g=>{
      if(!g.last_played) return false;
      const t = new Date(g.last_played).getTime();
      return !isNaN(t) && t >= weekAgo;
    });
  }
  else if(state.nav==='我的收藏') list = list.filter(g=>g.fav);
  if(state.collectionId !== null){
    // 分组选中：显示该分组 + 全部子分类内的游戏；分类选中：仅显示自身
    let ids=[state.collectionId];
    if(state.collectionGroupId && state.collectionGroupId===state.collectionId){
      const grp=state.collectionTree.find(g=>g.id===state.collectionId);
      if(grp && grp.children) ids=ids.concat(grp.children.map(c=>c.id));
    }
    list = list.filter(g => (g.collections||[]).some(c => ids.includes(c.id)));
    // 收藏夹视图：默认按 sort_order 排序（拖拽持久化顺序）；显式名称/评分排序时覆盖
    if(state.sort==='时间' && state.collectionOrder && state.collectionOrder.length){
      const orderMap={}; state.collectionOrder.forEach((gid,i)=>orderMap[gid]=i);
      list.sort((a,b)=>(orderMap[a.id]??9999)-(orderMap[b.id]??9999));
    }
  }
  if(state.kw){ const k=state.kw.toLowerCase();
    list = list.filter(g=>g.title.toLowerCase().includes(k)
      || (g.dev||'').toLowerCase().includes(k)
      || (g.tags||[]).some(t=>t.includes(k))); }
  if(state.sort==='名称') list.sort((a,b)=>a.title.localeCompare(b.title,'zh'));
  else if(state.sort==='评分') list.sort((a,b)=>b.rating-a.rating);
  else if(state.collectionId===null) list.sort((a,b)=>(b.last_played||'').localeCompare(a.last_played||''));
  return list;
}
function stars(r){ r=Math.max(0,Math.min(5,r||0)); return '★'.repeat(r)+'☆'.repeat(5-r); }
function chipColor(tag){ let h=0; for(let i=0;i<tag.length;i++) h=(h*31+tag.charCodeAt(i))%997;
  return ['#ffb3c1','#c4b5fd','#b5ead7','#ffd97d','#ffc9a0'][h%5]; }

// ---------- 卡片 ----------
let coverObserver = null;
let _renderedIds = [];   // 当前网格已渲染的卡片 id 顺序

// 创建单张卡片 DOM（不含封面加载，封面由 observer 懒加载）
function buildCard(g){
  const card=document.createElement('div');
  card.className='card'+(state.selected.has(g.id)?' selected':'');
  card.dataset.id=g.id;
  card.dataset.coverVersion = g.cover_version || 0;
  card.dataset.coverLoaded = '';
  card.innerHTML=`<div class="cover" style="background-image:linear-gradient(160deg,#ffd7e0,#ff9fbc)">
      ${g.fav?'<span class="fav">★</span>':''}
      ${g.id===runningId?'<span class="running">运行中</span>':''}
      <span class="check"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.4"><path d="M4 12l5 5L20 6"/></svg></span>
    </div>
    <div class="meta"><span class="dev">${esc(g.dev||'未知')}</span><span class="stars">${stars(g.rating)}</span></div>`;
  card.onclick=()=>{ if(state.batch) toggleSelect(g.id,card); else openDetail(g); };
  card.oncontextmenu=(e)=>{ e.preventDefault(); openCardMenu(g, e.clientX, e.clientY); };
  bindCardDrag(card, g);
  return card;
}

// ---------- 卡片拖拽排序（仅收藏夹视图启用）----------
let dragFromId = null;
let dragOverId = null;

function isDragOrderEnabled(){
  // 收藏夹视图 + 非批量模式 才允许拖拽重排
  return state.collectionId !== null && !state.batch;
}

function bindCardDrag(card, g){
  card.draggable = isDragOrderEnabled();
  card.addEventListener('dragstart', (e)=>{
    if(!isDragOrderEnabled()){ e.preventDefault(); return; }
    dragFromId=g.id; dragOverId=null;
    card.classList.add('dragging');
    try{ e.dataTransfer.setData('text/plain', g.id); e.dataTransfer.effectAllowed='move'; }catch(err){}
  });
  card.addEventListener('dragend', ()=>{
    card.classList.remove('dragging');
    dragFromId=null; dragOverId=null;
    document.querySelectorAll('.card.drag-over').forEach(c=>c.classList.remove('drag-over'));
  });
  card.addEventListener('dragover', (e)=>{
    if(!isDragOrderEnabled() || !dragFromId || dragFromId===g.id) return;
    e.preventDefault();
    e.dataTransfer.dropEffect='move';
    if(dragOverId!==g.id){ dragOverId=g.id; markDragOver(card); }
  });
  card.addEventListener('dragleave', ()=>{ if(dragOverId===g.id) dragOverId=null; card.classList.remove('drag-over'); });
  card.addEventListener('drop', (e)=>{
    e.preventDefault();
    if(!isDragOrderEnabled() || !dragFromId || dragFromId===g.id) return;
    reorderCards(dragFromId, g.id);
  });
}

function markDragOver(card){
  document.querySelectorAll('.card.drag-over').forEach(c=>c.classList.remove('drag-over'));
  card.classList.add('drag-over');
}

// 拖拽落点：把 from 移到 to 之前，并持久化到当前收藏夹
function reorderCards(fromId, toId){
  const grid=document.getElementById('grid');
  const ids=[...grid.querySelectorAll('.card')].map(c=>c.dataset.id);
  const from=ids.indexOf(fromId), to=ids.indexOf(toId);
  if(from<0||to<0) return;
  ids.splice(from,1);
  ids.splice(to,0,fromId);
  // 更新本地顺序（先改 UI 再持久化，避免闪烁）
  state.collectionOrder=ids;
  renderAll();
  // 持久化：分组视图聚合排序存到分组自身，分类视图存到分类
  bridge.setCollectionGames(state.collectionId, JSON.stringify(ids));
  toast('排序已更新');
}

// 增量渲染：对比新旧 id 列表，只增删改变化部分，未变化卡片原样保留（含已加载封面）
function renderCards(list){
  const grid=document.getElementById('grid');
  const newIds=list.map(g=>g.id);
  const byId={}; list.forEach(g=>byId[g.id]=g);
  const oldMap={}; _renderedIds.forEach(id=>{
    const c=grid.querySelector(`.card[data-id="${id}"]`); if(c) oldMap[id]=c;
  });

  // 1) 移除已不在列表中的卡片
  const oldSet=new Set(_renderedIds);
  const removeIds=_renderedIds.filter(id=>!byId[id]);
  removeIds.forEach(id=>{ const c=oldMap[id]; if(c){ c.remove(); } });

  // 2) 按新顺序排列：复用的节点移动位置，新增节点创建
  let anchor=null;   // 从后往前插，保持顺序
  for(let i=newIds.length-1;i>=0;i--){
    const id=newIds[i];
    let card=oldMap[id];
    if(!card){
      card=buildCard(byId[id]);
      grid.insertBefore(card, anchor);
      if(coverObserver) coverObserver.observe(card);
    } else {
      grid.insertBefore(card, anchor);
      // 复用节点：若封面版本变化（VNDB 匹配/手动更换后）则强制重新加载封面
      if(card.dataset.coverVersion !== String(byId[id].cover_version||0)){
        card.dataset.coverVersion = byId[id].cover_version||0;
        card.dataset.coverLoaded = '';
        const c=card.querySelector('.cover');
        if(c) c.style.backgroundImage='linear-gradient(160deg,#ffd7e0,#ff9fbc)';
        if(coverObserver) coverObserver.observe(card);
      }
      // 复用节点：仅更新可能变化的字段（fav/选中/评分/开发商）
      if(card.className.indexOf('selected')>=0 !== state.selected.has(id))
        card.classList.toggle('selected', state.selected.has(id));
      const meta=card.querySelector('.meta');
      const dev=meta.querySelector('.dev');
      if(dev && dev.textContent!==(byId[id].dev||'未知')) dev.textContent=byId[id].dev||'未知';
      const st=meta.querySelector('.stars');
      if(st && st.textContent!==stars(byId[id].rating)) st.textContent=stars(byId[id].rating);
      const fav=card.querySelector('.fav');
      const needFav=!!byId[id].fav;
      if(needFav && !fav){
        const f=document.createElement('span'); f.className='fav'; f.textContent='★';
        card.querySelector('.cover').appendChild(f);
      } else if(!needFav && fav){ fav.remove(); }
    }
    anchor=card;
  }
  _renderedIds=newIds;

  if(!coverObserver){
    coverObserver = new IntersectionObserver((entries)=>{
      entries.forEach(en=>{
        if(!en.isIntersecting) return;
        const card=en.target;
        const gid=card.dataset.id;
        coverObserver.unobserve(card);
        bridge.getCover(gid, function(uri){
          if(!uri) return;
          const c=card.querySelector('.cover');
          if(c){
            card.dataset.coverLoaded = '1';
            c.style.backgroundImage=`url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
          }
        });
      });
    }, {root: document.querySelector('.scroll'), rootMargin:'160px'});
    grid.querySelectorAll('.card').forEach(c=>coverObserver.observe(c));
  }
}

function markRunning(){
  document.querySelectorAll('.card').forEach(c=>{
    const has=c.querySelector('.running');
    if(c.dataset.id===runningId){ if(!has){ const s=document.createElement('span');
      s.className='running'; s.textContent='运行中';
      const cover=c.querySelector('.cover'); if(cover) cover.appendChild(s); } }
    else if(has){ has.remove(); }
  });
  const b=document.getElementById('dlgStart');
  if(currentGame && currentGame.id===runningId){ b.disabled=true; b.textContent='运行中'; }
  else { b.disabled=false; b.textContent='开始游戏'; }
}

function toggleSelect(id, card){
  if(state.selected.has(id)){ state.selected.delete(id); card.classList.remove('selected'); }
  else { state.selected.add(id); card.classList.add('selected'); }
  updateBatchBar();
}

// 当前详情打开的卡片高亮（第 10 项：ring 主色描边 + shadow）
function setActiveCard(id){
  document.querySelectorAll('.card.active').forEach(c=>c.classList.remove('active'));
  if(!id) return;
  const c=document.querySelector(`.card[data-id="${id}"]`);
  if(c) c.classList.add('active');
}

function renderEmpty(list){
  const e=document.getElementById('empty');
  const show = list.length===0;
  e.classList.toggle('show', show);
  if(!show) return;
  const favEmpty = state.nav==='我的收藏';
  const filterEmpty = state.collectionId !== null || !!state.kw;
  if(favEmpty){
    document.getElementById('emptyTitle').textContent='还没有收藏的游戏';
    document.getElementById('emptySub').textContent='点击卡片详情里的 ★ 收藏，游戏就会出现在这里';
    document.getElementById('btnShowAll').style.display='inline-block';
    document.getElementById('btnScan').style.display='none';
  } else if(filterEmpty){
    document.getElementById('emptyTitle').textContent='没有符合条件的结果';
    document.getElementById('emptySub').textContent='试试清除搜索或筛选条件';
    document.getElementById('btnShowAll').style.display='inline-block';
    document.getElementById('btnScan').style.display='none';
  } else {
    document.getElementById('emptyTitle').textContent='游戏库还是空的';
    document.getElementById('emptySub').textContent='扫描游戏文件夹，开始构建你的游戏库';
    document.getElementById('btnShowAll').style.display='none';
    document.getElementById('btnScan').style.display='inline-block';
  }
}

// ---------- 详情 ----------
function openDetail(g){
  currentGame=g;
  setActiveCard(g.id);
  loadCoverTo(g.id, document.getElementById('dlgCover'), 'bg');
  document.getElementById('dlgTitle').textContent=g.title;
  renderInfoBar();
  initRateEdit();
  renderDetailTags();
  document.getElementById('dlgDesc').textContent=g.description||'暂无简介';
  updateFavBtn();
  document.getElementById('dlgMoreMenu').classList.remove('show');
  showSheet('detailOverlay');
  // 卡片闭包里的数据可能是构建时的快照，打开时异步重取最新数据刷新
  bridge.getGame(g.id, function(s){
    try{
      const fresh=JSON.parse(s||'{}');
      if(!fresh || !fresh.id) return;
      currentGame=fresh;
      // 同步 GAMES 中对应对象，保持后续轮询一致
      const gi=GAMES.findIndex(x=>x.id===fresh.id);
      if(gi>=0) GAMES[gi]=fresh;
      refreshDetail();
    }catch(e){}
  });
}

// 详情评分：点击星级直接修改（调用后端 setRating）
function initRateEdit(){
  const el=document.querySelector('.rate-edit');
  if(!el) return;
  const r=+el.dataset.r||0;
  el.innerHTML='';
  for(let n=1;n<=5;n++){
    const s=document.createElement('span');
    s.textContent=n<=r?'★':'☆';
    s.style.cssText='cursor:pointer;color:var(--star);font-size:17px;letter-spacing:2px;';
    s.onmouseenter=()=>{ s.style.color='var(--pink-deep)'; };
    s.onmouseleave=()=>{ s.style.color='var(--star)'; };
    s.onclick=()=>{ if(!currentGame) return;
      bridge.setRating(currentGame.id, n);
      currentGame.rating=n; el.dataset.r=n; initRateEdit();
    };
    el.appendChild(s);
  }
}

// 收藏夹完整路径：分类显示「分组 / 分类」，分组仅显示分组名
function collectionPath(colId){
  for(const g of state.collectionTree){
    if(g.id===colId) return g.name;
    const c=(g.children||[]).find(x=>x.id===colId);
    if(c) return g.name+' / '+c.name;
  }
  return '';
}

function renderDetailTags(){
  const t=document.getElementById('dlgCollections'); t.innerHTML='';
  (currentGame.collections||[]).forEach(col=>{
    const c=document.createElement('span');
    c.className='chip collection-chip';
    c.style.background = col.color || chipColor(col.name); c.style.color='#4a4358';
    c.title = collectionPath(col.id);
    c.textContent = (col.icon||'') + ' ' + collectionPath(col.id);
    t.appendChild(c);
  });
  const m=document.createElement('span');
  m.className='chip manage'; m.textContent='管理收藏夹';
  m.onclick=()=>{ closeSheet('detailOverlay', true); openCollectionManager(); };
  t.appendChild(m);
}

// ---------- 侧边栏树形收藏夹 ----------
function renderCollectionTree(){
  const cl=document.getElementById('collectionTree'); cl.innerHTML='';
  state.collectionTree.forEach(group=>cl.appendChild(renderCollectionGroup(group)));
  bindCollectionItems();
}

function renderCollectionGroup(group){
  const el=document.createElement('div');
  el.className='collection-group';
  const open = state.openGroupId===group.id;
  const hasChildren = (group.children||[]).length>0;
  el.innerHTML=`
    <div class="collection-group-header ${state.collectionId===group.id?'active':''}" data-id="${group.id}">
      ${hasChildren?`<button class="toggle ${open?'open':''}" title="${open?'收起':'展开'}">${open?'▾':'▸'}</button>`:''}
      <span class="name">${esc(group.name)}</span>
      <span class="count">${group.game_count||0}</span>
    </div>
    ${hasChildren&&open?`<div class="collection-children">${(group.children||[]).map(renderCollectionCategory).join('')}</div>`:''}`;
  const hdr=el.querySelector('.collection-group-header');
  // 点击分组名 → 直接筛选该分组（含子分类），不展开
  hdr.addEventListener('click',()=>selectCollection(group.id, group));
  hdr.addEventListener('contextmenu',(e)=>{ e.preventDefault(); showCollectionCtx(e.clientX,e.clientY,group); });
  // 小按钮 → 仅展开/收起子分类（手风琴），不筛选
  const tgl=el.querySelector('.toggle');
  if(tgl) tgl.addEventListener('click',(e)=>{ e.stopPropagation(); toggleExpand(group); });
  return el;
}

// 手风琴：仅切换分组展开/收起（不改变筛选）
function toggleExpand(group){
  state.openGroupId = state.openGroupId===group.id ? null : group.id;
  renderCollectionTree();
}

function renderCollectionCategory(cat){
  return `
    <div class="collection-item ${state.collectionId===cat.id?'active':''}" data-id="${cat.id}">
      <span class="name">${esc(cat.name)}</span>
      <span class="count">${cat.game_count||0}</span>
    </div>`;
}

function bindCollectionItems(){
  document.querySelectorAll('#collectionTree .collection-item').forEach(it=>{
    const cid=+it.dataset.id;
    it.onclick=()=>selectCollection(cid, findCollectionNode(cid));
    it.oncontextmenu=(e)=>{ e.preventDefault();
      const node = findCollectionNode(cid);
      if(node) showCollectionCtx(e.clientX,e.clientY,node); };
  });
}

function findCollectionNode(id){
  for(const g of state.collectionTree){
    if(g.id===id) return g;
    const c=(g.children||[]).find(x=>x.id===id);
    if(c) return c;
  }
  return null;
}

// 收藏夹选择：分组显示其全部（含子分类），分类仅显示自身
function selectCollection(id, node){
  const isGroup = node && node.parent_id==null;
  state.collectionId=id;
  state.collectionGroupId = isGroup ? id : (node ? findParentGroupId(id) : null);
  state.nav='collection';
  // 选子分类时确保其父分组展开
  if(node && !isGroup){
    const pg=findParentGroupId(id);
    if(pg) state.openGroupId=pg;
  }
  // 拉取收藏夹内 sort_order 顺序（拖拽排序用）
  state.collectionOrder=[];
  bridge.getGamesInCollection(id, function(idsStr){
    try{ state.collectionOrder=JSON.parse(idsStr||'[]'); }catch(e){}
    renderAll();
  });
  renderCollectionTree();
  renderAll();
}

function findParentGroupId(id){
  for(const g of state.collectionTree){
    if((g.children||[]).some(c=>c.id===id)) return g.id;
  }
  return null;
}

function clearCollectionFilter(){
  state.collectionId=null; state.collectionGroupId=null; state.openGroupId=null; state.collectionOrder=[]; state.nav='全部作品'; state.kw='';
  renderCollectionTree();
  document.querySelectorAll('#sidebar .side-item').forEach(x=>{
    x.classList.toggle('active', x.dataset.nav==='全部作品');
  });
  renderAll();
}

// 收藏夹右键菜单（复用卡片右键菜单样式，带图标 + 分段）
function showCollectionCtx(x, y, node){
  document.querySelectorAll('.ctx-menu').forEach(mm=>mm.remove());
  const m=document.createElement('div');
  m.className='more-menu ctx-menu';
  const vw=window.innerWidth, vh=window.innerHeight, mw=180, mh=210;
  let px=x, py=y;
  if(px+mw>vw-8) px=vw-mw-8;
  if(py+mh>vh-8) py=vh-mh-8;
  px=Math.max(8,px); py=Math.max(8,py);
  m.style.cssText=`position:fixed;left:${px}px;top:${py}px;display:block;z-index:90;background:var(--bg-panel);border:1.5px solid var(--border-soft);border-radius:12px;padding:5px;width:180px;box-shadow:0 10px 24px var(--glow-med);`;
  const items=[];
  items.push(['🎮', '管理游戏', ()=>openManageGames(node)]);
  items.push(['✏️', '重命名', ()=>renameCollection(node)]);
  items.push(['🗑️', '删除', ()=>delCollection(node), 'danger']);
  m.innerHTML=items.map(([ic,t,,cls])=>
    `<div class="item ${cls||''}"><span class="mi">${ic}</span>${t}</div>`).join('');
  [...m.children].forEach((d,i)=>{ d.onclick=()=>{ m.remove(); items[i][2](); }; });
  document.body.appendChild(m);
  setTimeout(()=>document.addEventListener('click',function h(){m.remove();document.removeEventListener('click',h);}),0);
}

function newCollection(parentId){
  showInputDialog({
    title: parentId?'新建分类':'新建分组',
    label: parentId?'分类名称':'分组名称',
    cb:function(name){ if(name&&name.trim()){ bridge.createCollection(name.trim(), parentId||0, '', ''); toast('已创建'); } }
  });
}

function renameCollection(node){
  showInputDialog({
    title:'重命名收藏夹', label:'名称', value:node.name,
    cb:function(name){ if(name&&name.trim()&&name.trim()!==node.name){
      bridge.updateCollection(node.id, JSON.stringify({name:name.trim()})); toast('已重命名'); } }
  });
}

function delCollection(node){
  const kids=(node.children||[]).length;
  showConfirmDialog({
    title:'删除收藏夹',
    message:`删除「${node.name}」？${kids?`其 ${kids} 个子分类一并删除，`:''}关联游戏将不再属于该收藏夹。`,
    danger:true, okText:'删除', cb:()=>{ bridge.deleteCollection(node.id); toast('已删除'); }
  });
}

// ---------- 管理游戏对话框（批量勾选收藏夹内游戏）----------
let manageGamesId = null;      // 当前管理的收藏夹 id
let manageGamesIsGroup = false;  // 是否分组（分组时聚合子分类保存）
let manageGamesSel = new Set();  // 已勾选游戏 id
let manageGamesData = [];        // 全部游戏（title/id 缓存）

function openManageGames(node){
  manageGamesId = node.id;
  manageGamesIsGroup = node.parent_id==null;
  document.getElementById('manageGamesTitle').textContent='管理游戏：'+node.name;
  document.getElementById('manageGamesKw').value='';
  showSheet('manageGamesOverlay');
  // 分组：聚合其全部子分类的游戏；分类：仅自身
  const idsToFetch = manageGamesIsGroup
    ? [node.id].concat((node.children||[]).map(c=>c.id))
    : [node.id];
  const allSel=new Set();
  let pending=idsToFetch.length;
  if(!pending){ manageGamesSel=new Set(); manageGamesData=GAMES.slice(); renderManageGames(); return; }
  idsToFetch.forEach(cid=>{
    bridge.getGamesInCollection(cid, function(idsStr){
      let ids=[]; try{ ids=JSON.parse(idsStr||'[]'); }catch(e){}
      ids.forEach(i=>allSel.add(i));
      if(--pending===0){
        manageGamesSel=allSel;
        manageGamesData=GAMES.slice();
        renderManageGames();
      }
    });
  });
}

function renderManageGames(){
  const kw=document.getElementById('manageGamesKw').value.trim().toLowerCase();
  const list=manageGamesData.filter(g=>!kw || g.title.toLowerCase().includes(kw));
  const t=document.getElementById('manageGamesList'); t.innerHTML='';
  if(!list.length){ t.innerHTML='<div class="cand-empty">没有符合条件的游戏</div>'; }
  list.forEach(g=>{
    const checked=manageGamesSel.has(g.id);
    const d=document.createElement('div');
    d.className='mg-item'+(checked?' on':'');
    d.innerHTML=`<input type="checkbox" ${checked?'checked':''}><span class="mg-title">${esc(g.title)}</span>`;
    d.onclick=()=>{
      if(manageGamesSel.has(g.id)) manageGamesSel.delete(g.id); else manageGamesSel.add(g.id);
      d.classList.toggle('on', manageGamesSel.has(g.id));
      const cb=d.querySelector('input'); if(cb) cb.checked=manageGamesSel.has(g.id);
      updateManageCount();
    };
    t.appendChild(d);
  });
  updateManageCount();
}

function updateManageCount(){
  document.getElementById('manageGamesCount').textContent=`已选 ${manageGamesSel.size} 个`;
}

function saveManageGames(){
  if(manageGamesId==null) return;
  const ids=[...manageGamesSel];
  if(manageGamesIsGroup){
    // 分组：整体替换分组本身 + 每个子分类（保证分组筛选含全部勾选）
    const group=findCollectionNode(manageGamesId);
    const targets=[manageGamesId].concat((group&&group.children||[]).map(c=>c.id));
    targets.forEach(cid=>bridge.setCollectionGames(cid, JSON.stringify(ids)));
    toast('收藏夹已更新');
  } else {
    bridge.setCollectionGames(manageGamesId, JSON.stringify(ids));
    toast('收藏夹已更新');
  }
  closeSheet('manageGamesOverlay');
}

// 收藏夹管理抽屉：当前游戏加入/退出收藏夹
function openCollectionManager(){
  if(!currentGame) return;
  // 异步拉取最新数据（右键进入时 currentGame 可能是快照），再渲染
  bridge.getGame(currentGame.id, function(s){
    try{
      const fresh=JSON.parse(s||'{}');
      if(fresh && fresh.id){
        currentGame=fresh;
        const gi=GAMES.findIndex(x=>x.id===fresh.id);
        if(gi>=0) GAMES[gi]=fresh;
      }
    }catch(e){}
    renderGameCollections();
  });
  showSheet('collectionOverlay');
}

function renderGameCollections(){
  const sec=document.getElementById('gameCollectionSection');
  if(!currentGame){ sec.style.display='none'; return; }
  sec.style.display='block';
  document.getElementById('gameCollectionTitle').textContent='当前游戏：'+currentGame.title;
  const curIds=new Set((currentGame.collections||[]).map(c=>c.id));
  const t=document.getElementById('gameCollectionList'); t.innerHTML='';
  // 全部分组 + 子分类（带完整路径），均可勾选
  const all=[];
  state.collectionTree.forEach(g=>{
    all.push({id:g.id,label:g.name,color:g.color,icon:g.icon});
    (g.children||[]).forEach(c=>all.push({id:c.id,label:(g.name+' / '+c.name),color:c.color,icon:c.icon}));
  });
  all.forEach(col=>{
    const selected=curIds.has(col.id);
    const c=document.createElement('span');
    c.className='chip'+(selected?' on':'');
    c.style.color = selected ? '' : '#4a4358';
    c.style.background = selected ? '' : (col.color||chipColor(col.label));
    c.textContent=(col.icon||'')+' '+col.label;
    c.onclick=()=>{
      const next=new Set(curIds);
      if(next.has(col.id)) next.delete(col.id); else next.add(col.id);
      bridge.setGameCollections(currentGame.id, JSON.stringify([...next]));
      // 本地同步 currentGame.collections，立即反映选中态（后端 refresh 也会回写）
      const had=curIds.has(col.id);
      if(had){ currentGame.collections=currentGame.collections.filter(x=>x.id!==col.id); }
      else { currentGame.collections=currentGame.collections.concat([{id:col.id,name:col.label,color:col.color,icon:col.icon||''}]); }
      toast(had?'已移除收藏夹':'已加入收藏夹');
      renderGameCollections();
    };
    t.appendChild(c);
  });
}

function updateFavBtn(){
  const b=document.getElementById('dlgFav');
  b.textContent = currentGame.fav?'★ 已收藏':'☆ 收藏';
  b.classList.toggle('on', currentGame.fav);
}

// 通用 Kawaii 确认对话框（替代原生 confirm）
let confirmCb=null;
function showConfirmDialog(opts){
  document.getElementById('confirmTitle').textContent=opts.title||'确认';
  document.getElementById('confirmMsg').textContent=opts.message||'确定执行此操作？';
  confirmCb=opts.cb||null;
  const ok=document.getElementById('confirmOk');
  ok.textContent=opts.okText||'确定';
  showSheet('confirmOverlay');
}
function confirmOk(){
  const cb=confirmCb; confirmCb=null;
  closeSheet('confirmOverlay');
  if(cb) cb();
}

// ---------- 筛选下拉 ----------
function bindFilterMenu(){
  const m=document.getElementById('filterMenu');
  m.querySelectorAll('.item').forEach(it=>{
    it.onclick=()=>{ state.sort=it.dataset.sort; m.classList.remove('show');
      document.querySelectorAll('#filterMenu .item').forEach(x=>x.classList.remove('on'));
      it.classList.add('on'); renderAll(); };
  });
}

// ---------- 批量 ----------
function updateBatchBar(){
  const n=state.selected.size;
  document.getElementById('batchCount').textContent=`已选择 ${n} 个`;
  document.querySelectorAll('#batchBar button:not(#btnSelAll)').forEach(b=>b.disabled=n===0);
  const all = n>0 && n===filterGames(GAMES).length;
  document.getElementById('btnSelAll').textContent = all?'取消全选':'全选';
}

function openPicker(title, items, onPick){
  document.getElementById('pickerTitle').textContent=title;
  const list=document.getElementById('pickerList'); list.innerHTML='';
  items.forEach(it=>{
    const d=document.createElement('div'); d.className='p-item'; d.textContent=it.label;
    d.onclick=()=>{ closeSheet('pickerOverlay'); onPick(it.value); };
    list.appendChild(d);
  });
  showSheet('pickerOverlay');
}

// 批量选择收藏夹（用于 批量添加/移除/移动）
function collectionPickerItems(){
  const items=[];
  state.collectionTree.forEach(g=>{
    (g.children||[]).forEach(c=>{
      items.push({label:(g.name+' / '+c.name), value:c.id});
    });
  });
  return items;
}

function batchPickCollection(mode){
  const ids=[...state.selected];
  const items=collectionPickerItems();
  openPicker(mode==='add'?'批量添加收藏夹':(mode==='move'?'移动到收藏夹':'批量移除收藏夹'),
    items, function(cid){
      if(mode==='add'){ bridge.addGamesToCollection(JSON.stringify(ids), cid); toast('已添加到收藏夹'); }
      else if(mode==='remove'){ bridge.removeGamesFromCollection(JSON.stringify(ids), cid); toast('已移出收藏夹'); }
      else { bridge.batchMoveToCollection(JSON.stringify(ids), cid); toast('已移动'); }
      state.selected.clear();
    });
}

// ---------- Sheet ----------
function showSheet(id){ const o=document.getElementById(id); o.classList.remove('hiding'); o.classList.add('show'); }
function closeSheet(id, instant){
  const o=document.getElementById(id);
  if(instant){
    o.classList.remove('show', 'hiding');
    if(id==='detailOverlay') setActiveCard(null);
    return;
  }
  o.classList.remove('show');
  o.classList.add('hiding');
  setTimeout(()=>o.classList.remove('hiding'),280);
  if(id==='detailOverlay') setActiveCard(null);
}
document.querySelectorAll('.overlay').forEach(o=>{
  o.addEventListener('click',e=>{ if(e.target===o) closeSheet(o.id); });
});
function closeTopSheet(){
  if(formOverlayVisible()) return closeSheet('formOverlay');
  if(document.getElementById('shotPreviewOverlay').classList.contains('show')) return closeSheet('shotPreviewOverlay');
  if(document.getElementById('manageGamesOverlay').classList.contains('show')) return closeSheet('manageGamesOverlay');
  if(document.getElementById('collectionOverlay').classList.contains('show')) return closeSheet('collectionOverlay');
  if(document.getElementById('pickerOverlay').classList.contains('show')) return closeSheet('pickerOverlay');
  if(document.getElementById('detailOverlay').classList.contains('show')) closeSheet('detailOverlay');
}
function formOverlayVisible(){ return document.getElementById('formOverlay').classList.contains('show'); }

// ---------- 编辑 / 添加 ----------
function openEdit(g){
  editingId=g.id;
  document.getElementById('formTitle').textContent='编辑游戏';
  document.getElementById('fTitle').value=g.title||'';
  document.getElementById('fEngine').value=g.engine||'';
  document.getElementById('fDev').value=g.dev||'';
  document.getElementById('fRating').value=String(g.rating||0);
  document.getElementById('fDesc').value=g.description||'';
  document.getElementById('fExeRow').style.display='flex';
  document.getElementById('fExe').value=g.exe_path||'';
  document.getElementById('fCoverRow').style.display='flex';
  document.getElementById('fMetaRow').style.display='flex';
  document.getElementById('fCoverPrev').src='';
  loadCoverTo(g.id, document.getElementById('fCoverPrev'), 'img');
  document.getElementById('fSearchKw').value=g.title||'';
  document.getElementById('fCands').style.display='none';
  showSheet('formOverlay');
}
function openAdd(){
  editingId='';
  document.getElementById('formTitle').textContent='手动添加游戏';
  ['fTitle','fEngine','fDev','fDesc','fExe'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('fRating').value='0';
  document.getElementById('fExeRow').style.display='flex';
  document.getElementById('fCoverRow').style.display='none';
  document.getElementById('fMetaRow').style.display='none';
  document.getElementById('fCands').style.display='none';
  showSheet('formOverlay');
}
function saveForm(){
  const data={title:document.getElementById('fTitle').value,
    engine:document.getElementById('fEngine').value,
    developer:document.getElementById('fDev').value,
    rating:parseInt(document.getElementById('fRating').value||'0'),
    description:document.getElementById('fDesc').value,
    exe_path:document.getElementById('fExe').value};
  if(!data.title){ toast('标题不能为空'); return; }
  bridge.saveGame(editingId, JSON.stringify(data));
  closeSheet('formOverlay');
}

// ---------- 卡片右键菜单（图标 + 分段）----------
function openCardMenu(g, x, y){
  // 右键其他卡片时，关闭已打开的右键菜单
  document.querySelectorAll('.ctx-menu').forEach(mm=>mm.remove());
  const m=document.createElement('div');
  m.className='more-menu ctx-menu';
  // 固定位置：菜单 170px 宽，clamp 到视口内，避免超出屏幕右侧/底部
  const vw=window.innerWidth, vh=window.innerHeight, mw=170, mh=200;
  let px=x, py=y;
  if(px+mw>vw-8) px=vw-mw-8;
  if(py+mh>vh-8) py=vh-mh-8;
  px=Math.max(8,px); py=Math.max(8,py);
  m.style.cssText=`position:fixed;left:${px}px;top:${py}px;display:block;z-index:90;background:var(--bg-panel);border:1.5px solid var(--border-soft);border-radius:12px;padding:5px;width:170px;box-shadow:0 10px 24px var(--glow-med);`;
  m.innerHTML=`
    <div class="item"><span class="mi">▶</span>启动游戏</div>
    <div class="item"><span class="mi">📂</span>打开本地目录</div>
    <div class="menu-sep"></div>
    <div class="item"><span class="mi">🗂️</span>管理收藏夹</div>
    <div class="item"><span class="mi">✏️</span>编辑</div>
    <div class="item"><span class="mi">🔄</span>VNDB 匹配</div>
    <div class="menu-sep"></div>
    <div class="item danger"><span class="mi">🗑️</span>从库中移除</div>`;
  const items=m.querySelectorAll('.item');
  items[0].onclick=()=>bridge.launch(g.id);
  items[1].onclick=()=>bridge.openFolder(g.id);
  items[2].onclick=()=>{ m.remove(); currentGame=g; openCollectionManager(); };
  items[3].onclick=()=>{ m.remove(); openEdit(g); };
  items[4].onclick=()=>{ m.remove(); bridge.matchVndb(g.id); toast('开始匹配：'+g.title); };
  items[5].onclick=()=>{ m.remove(); showConfirmDialog({title:'从库中移除',
    message:`从库中移除「${g.title}」？\n（不会删除实际文件）`,
    danger:true, okText:'移除', cb:()=>bridge.deleteGame(g.id)}); };
  document.body.appendChild(m);
  setTimeout(()=>document.addEventListener('click',function h(){m.remove();document.removeEventListener('click',h);}),0);
}

// ---------- 标题栏拖拽 ----------
function bindDrag(){
  const tb=document.getElementById('titlebar');
  let dragging=false;
  tb.addEventListener('mousedown',e=>{
    if(e.target.closest('.winbtn')) return;
    dragging=true; if(bridge) bridge.windowStartDrag(e.screenX,e.screenY);
    e.preventDefault();
  });
  window.addEventListener('mousemove',e=>{ if(dragging&&bridge) bridge.windowMoveDrag(e.screenX,e.screenY); });
  window.addEventListener('mouseup',()=>{ if(dragging){dragging=false; if(bridge) bridge.windowEndDrag();} });
  tb.addEventListener('dblclick',e=>{ if(!e.target.closest('.winbtn')) toggleMax(); });
}

// ---------- 窗口缩放手柄（四边/四角自由拉伸） ----------
function bindResize(){
  let rs=null, raf=false;
  document.querySelectorAll('.resizer').forEach(h=>{
    h.addEventListener('mousedown',e=>{
      e.preventDefault();
      rs={dir:h.dataset.dir, sx:e.clientX, sy:e.clientY};
      bridge.windowResizeStart(h.dataset.dir);
    });
  });
  window.addEventListener('mousemove',e=>{
    if(!rs) return;
    if(raf) return;
    raf=true;
    requestAnimationFrame(()=>{
      raf=false;
      if(!rs) return;
      const dx=e.clientX-rs.sx, dy=e.clientY-rs.sy;
      bridge.windowResize(rs.dir, dx, dy);
    });
  });
  window.addEventListener('mouseup',()=>{ rs=null; });
}

// ---------- 通用 ----------
function esc(s){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
let toastTimer;
function toast(msg){ const t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.classList.remove('show'),1800); }

// ---------- 事件绑定 ----------
document.getElementById('searchInput').addEventListener('input',e=>{ state.kw=e.target.value.trim(); renderAll(); });
document.getElementById('batchBtn').onclick=function(){
  state.batch=!state.batch;
  document.body.classList.toggle('batch',state.batch);
  this.classList.toggle('active',state.batch);
  if(!state.batch) state.selected.clear();
  renderAll();
};
document.getElementById('filterBtn').onclick=function(e){ e.stopPropagation();
  document.getElementById('filterMenu').classList.toggle('show'); };
bindFilterMenu();

document.querySelectorAll('#sidebar .side-item').forEach(it=>{
  if(it.id==='btnNewCollection'||it.id==='btnSettings') return;
  it.onclick=()=>{ state.nav=it.dataset.nav; state.collectionId=null;
    document.querySelectorAll('#sidebar .side-item').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('#collectionTree .collection-item').forEach(x=>x.classList.remove('active'));
    it.classList.add('active'); renderAll(); };
});
document.getElementById('btnNewCollection').onclick=()=>{
  showInputDialog({
    title:'新建收藏夹',
    label:'名称',
    cb:function(name){ if(name&&name.trim()) bridge.createCollection(name.trim(), 0, '', ''); }
  });
};

// 通用 Kawaii 输入对话框（替代原生 prompt）
let inputCb=null;
function showInputDialog(opts){
  document.getElementById('inputTitle').textContent=opts.title||'输入';
  document.getElementById('inputLabel').textContent=opts.label||'名称';
  document.getElementById('inputValue').value=opts.value||'';
  inputCb=opts.cb||null;
  showSheet('inputOverlay');
  setTimeout(()=>document.getElementById('inputValue').focus(), 50);
}
function inputOk(){
  const v=document.getElementById('inputValue').value;
  closeSheet('inputOverlay');
  if(inputCb){ inputCb(v); inputCb=null; }
}
document.getElementById('btnSettings').onclick=()=>{
  if(window.Settings) Settings.open();
  else toast('设置模块加载失败');
};

document.getElementById('btnSelAll').onclick=()=>{
  const ids=filterGames(GAMES).map(g=>g.id);
  if(state.selected.size===ids.length){ state.selected.clear(); }
  else { state.selected=new Set(ids); }
  renderAll();
};
document.getElementById('btnBAdd').onclick=()=>batchPickCollection('add');
document.getElementById('btnBRem').onclick=()=>batchPickCollection('remove');
document.getElementById('btnBMove').onclick=()=>batchPickCollection('move');
document.getElementById('btnBVndb').onclick=()=>{
  if(state.selected.size===0) return;
  bridge.matchVndbBatch(JSON.stringify([...state.selected]));
  state.selected.clear();
  toast('开始批量匹配 VNDB');
};
document.getElementById('btnBDel').onclick=()=>{
  showConfirmDialog({title:'批量移除',
    message:`从库中移除选中的 ${state.selected.size} 个游戏？\n（不会删除实际文件）`,
    danger:true, okText:'移除',
    cb:()=>{ bridge.batchDelete(JSON.stringify([...state.selected])); state.selected.clear(); }});
};

document.getElementById('btnScan').onclick=()=>bridge.scanFolder();
document.getElementById('btnShowAll').onclick=()=>clearCollectionFilter();
document.getElementById('fab').onclick=function(e){ e.stopPropagation();
  document.getElementById('fabMenu').classList.toggle('show'); };
document.getElementById('fabRefresh').onclick=()=>{ refreshAll(true); toast('已刷新'); };
document.getElementById('fabAdd').onclick=()=>{ document.getElementById('fabMenu').classList.remove('show'); openAdd(); };
document.getElementById('fabScan').onclick=()=>{ document.getElementById('fabMenu').classList.remove('show'); bridge.scanFolder(); };
document.getElementById('btnPickExe').onclick=()=>{ if(bridge) bridge.selectExe(function(p){ if(p) document.getElementById('fExe').value=p; }); };
document.getElementById('btnPickCover').onclick=()=>{
  if(!editingId){ toast('请先保存游戏再更换封面'); return; }
  bridge.pickCover(function(s){
    let r={}; try{ r=JSON.parse(s||'{}'); }catch(e){}
    if(r.path){ document.getElementById('fCoverPrev').src=r.preview||'';
      bridge.setCover(editingId, r.path); toast('封面已更换'); }
  });
};
document.getElementById('btnMetaSearch').onclick=()=>{
  const kw=document.getElementById('fSearchKw').value.trim();
  if(!kw){ toast('请输入搜索关键词'); return; }
  toast('搜索中…');
  bridge.searchMetadata(kw, function(s){
    let cands=[]; try{ cands=JSON.parse(s||'[]'); }catch(e){}
    renderCandidates(cands);
  });
};
function renderCandidates(cands){
  const box=document.getElementById('fCands');
  box.style.display='block';
  box.innerHTML='';
  if(!cands.length){ box.innerHTML='<div class="cand-empty">未找到结果</div>'; return; }
  cands.forEach(c=>{
    const d=document.createElement('div');
    d.className='cand';
    d.innerHTML=`<div class="cand-title">[${esc(c.source||'')}] ${esc(c.title||'')}</div>
      <div class="cand-sub">${esc(c.developer||'')}${c.released?' · '+esc(c.released):''}${c.rating?' · ★'+(+c.rating).toFixed(1):''}</div>`;
    d.onclick=()=>{ if(!editingId) return;
      bridge.applyCandidate(editingId, JSON.stringify(c));
      toast('已应用元数据（空字段已填充）'); };
    box.appendChild(d);
  });
}

document.getElementById('dlgClose').onclick=()=>closeSheet('detailOverlay');
document.getElementById('dlgStart').onclick=()=>{ if(currentGame) bridge.launch(currentGame.id); };
document.getElementById('dlgEdit').onclick=()=>{ if(currentGame){ closeSheet('detailOverlay', true); openEdit(currentGame); } };
document.getElementById('dlgFav').onclick=()=>{
  if(!currentGame) return;
  currentGame.fav=!currentGame.fav;
  bridge.toggleFav(currentGame.id);
  updateFavBtn();
};
document.getElementById('dlgMore').onclick=function(e){ e.stopPropagation();
  document.getElementById('dlgMoreMenu').classList.toggle('show'); };
document.querySelectorAll('#dlgMoreMenu .item').forEach(it=>{
  it.onclick=()=>{ document.getElementById('dlgMoreMenu').classList.remove('show');
    if(!currentGame) return;
    if(it.dataset.act==='vndb'){ bridge.matchVndb(currentGame.id); toast('开始匹配：'+currentGame.title); }
    else if(it.dataset.act==='open') bridge.openFolder(currentGame.id);
    else showConfirmDialog({title:'从库中移除',
      message:`从库中移除「${currentGame.title}」？\n（不会删除实际文件）`,
      danger:true, okText:'移除', cb:()=>bridge.deleteGame(currentGame.id)}); };
});

document.getElementById('shotPreviewClose').onclick=()=>closeSheet('shotPreviewOverlay');
document.querySelectorAll('#shotMenu .item').forEach(it=>{
  it.onclick=()=>{
    hideShotMenu();
    const act=it.dataset.act;
    if(act==='rename') renameShot();
    else if(act==='folder') openShotFolder();
    else if(act==='copy') copyShot();
    else if(act==='del') deleteShot();
  };
});

document.getElementById('collectionClose').onclick=()=>closeSheet('collectionOverlay');
document.getElementById('collectionDone').onclick=()=>closeSheet('collectionOverlay');
document.getElementById('manageGamesClose').onclick=()=>closeSheet('manageGamesOverlay');
document.getElementById('manageGamesKw').addEventListener('input',()=>renderManageGames());
document.getElementById('manageGamesSelAll').onclick=()=>{
  manageGamesData.forEach(g=>manageGamesSel.add(g.id));
  renderManageGames();
};
document.getElementById('manageGamesClear').onclick=()=>{
  manageGamesSel.clear();
  renderManageGames();
};
document.getElementById('manageGamesSave').onclick=saveManageGames;

document.getElementById('formClose').onclick=()=>closeSheet('formOverlay');
document.getElementById('inputClose').onclick=()=>{ inputCb=null; closeSheet('inputOverlay'); };
document.getElementById('inputCancel').onclick=()=>{ inputCb=null; closeSheet('inputOverlay'); };
document.getElementById('inputOk').onclick=inputOk;
document.getElementById('inputValue').addEventListener('keydown',e=>{ if(e.key==='Enter') inputOk(); });
document.getElementById('confirmClose').onclick=()=>{ confirmCb=null; closeSheet('confirmOverlay'); };
document.getElementById('confirmCancel').onclick=()=>{ confirmCb=null; closeSheet('confirmOverlay'); };
document.getElementById('confirmOk').onclick=confirmOk;
document.getElementById('formCancel').onclick=()=>closeSheet('formOverlay');
document.getElementById('formSave').onclick=saveForm;
document.getElementById('pickerClose').onclick=()=>closeSheet('pickerOverlay');

document.addEventListener('click',()=>{
  document.getElementById('filterMenu').classList.remove('show');
  document.getElementById('fabMenu').classList.remove('show');
  document.getElementById('dlgMoreMenu').classList.remove('show');
  hideShotMenu();
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){ hideShotMenu();
    if(state.batch){ state.batch=false; document.body.classList.remove('batch');
      document.getElementById('batchBtn').classList.remove('active'); state.selected.clear(); renderAll(); }
    else closeTopSheet(); }
});

bindDrag();
bindResize();
init();

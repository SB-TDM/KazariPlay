
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

let GAMES = [], ALL_TAGS = [], CATS = [];
let currentGame = null;
let editingId = null;
let runningId = '';
const state = { nav:'全部作品', kw:'', sort:'时间', batch:false, selected:new Set(), catId:0 };

window.__app = { refresh: function(){ refreshAll(true); }, toast: function(m){ toast(m); } };

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
  bridge.getTags(function(s){ ALL_TAGS=JSON.parse(s||'[]'); renderCatFilter(); });
  bridge.getCategories(function(s){ CATS=JSON.parse(s||'[]'); renderCategories(); renderCatSelect(); });
  bridge.getRunning(function(r){ runningId=r||''; markRunning(); });
}

// 判断游戏列表是否有实质变化（比较影响卡片显示的字段 + 派生文本）
function _gamesChanged(a, b){
  if(a.length!==b.length) return true;
  for(let i=0;i<a.length;i++){
    const x=a[i], y=b[i];
    if(!x || !y || x.id!==y.id || x.fav!==y.fav || x.rating!==y.rating
       || x.dev!==y.dev || x.title!==y.title || x.last_played!==y.last_played
       || x.play_time!==y.play_time || x.last_text!==y.last_text
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
  const rate=document.querySelector('.rate-edit');
  if(rate){ rate.dataset.r=currentGame.rating; initRateEdit(); }
  markRunning();
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
  if(state.catId) list = list.filter(g=>g.cat_id===state.catId);
  if(state.kw){ const k=state.kw.toLowerCase();
    list = list.filter(g=>g.title.toLowerCase().includes(k)
      || (g.dev||'').toLowerCase().includes(k)
      || (g.tags||[]).some(t=>t.includes(k))); }
  if(state.sort==='名称') list.sort((a,b)=>a.title.localeCompare(b.title,'zh'));
  else if(state.sort==='评分') list.sort((a,b)=>b.rating-a.rating);
  else list.sort((a,b)=>(b.last_played||'').localeCompare(a.last_played||''));
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
  card.innerHTML=`<div class="cover" style="background-image:linear-gradient(160deg,#ffd7e0,#ff9fbc)">
      ${g.fav?'<span class="fav">★</span>':''}
      ${g.id===runningId?'<span class="running">运行中</span>':''}
      <span class="check"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.4"><path d="M4 12l5 5L20 6"/></svg></span>
    </div>
    <div class="meta"><span class="dev">${esc(g.dev||'未知')}</span><span class="stars">${stars(g.rating)}</span></div>`;
  card.onclick=()=>{ if(state.batch) toggleSelect(g.id,card); else openDetail(g); };
  card.oncontextmenu=(e)=>{ e.preventDefault(); openCardMenu(g, e.clientX, e.clientY); };
  return card;
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
          if(c) c.style.backgroundImage=`url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;
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

function renderEmpty(list){
  const e=document.getElementById('empty');
  const show = list.length===0;
  e.classList.toggle('show', show);
  if(!show) return;
  const favEmpty = state.nav==='我的收藏';
  const filterEmpty = !!state.catId || !!state.kw;
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

function renderDetailTags(){
  const t=document.getElementById('dlgTags'); t.innerHTML='';
  (currentGame.tags||[]).forEach(tag=>{
    const c=document.createElement('span');
    c.className='chip'; c.style.background=chipColor(tag); c.style.color='#4a4358';
    c.textContent=tag;
    t.appendChild(c);
  });
  const m=document.createElement('span');
  m.className='chip manage'; m.textContent='管理标签';
  m.onclick=()=>{ closeSheet('detailOverlay'); openTagManager(); };
  t.appendChild(m);
}

// 管理标签抽屉：渲染当前游戏标签区（绑定/移除当前游戏标签）
function renderGameTags(){
  if(!currentGame){ document.getElementById('gameTagSection').style.display='none'; return; }
  document.getElementById('gameTagSection').style.display='block';
  document.getElementById('gameTagTitle').textContent='当前游戏：'+currentGame.title;
  const t=document.getElementById('gameTagList'); t.innerHTML='';
  (currentGame.tags||[]).forEach(tag=>{
    const c=document.createElement('span');
    c.className='chip'; c.style.background=chipColor(tag); c.style.color='#4a4358';
    c.innerHTML=esc(tag)+'<span class="x">✕</span>';
    c.querySelector('.x').onclick=()=>{
      currentGame.tags=currentGame.tags.filter(x=>x!==tag);
      bridge.setGameTags(currentGame.id, JSON.stringify(currentGame.tags));
      renderGameTags(); renderDetailTags();
    };
    t.appendChild(c);
  });
}
function addTagToCurrentGame(name){
  name=(name||'').trim(); if(!name) return;
  if(currentGame.tags.includes(name)){ toast('标签已存在'); return; }
  currentGame.tags.push(name);
  bridge.setGameTags(currentGame.id, JSON.stringify(currentGame.tags));
  renderGameTags(); renderDetailTags();
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

// ---------- 侧边栏 / 分类 ----------
function renderCategories(){
  const cl=document.getElementById('catList'); cl.innerHTML='';
  CATS.forEach(c=>{
    const d=document.createElement('div');
    d.className='side-item'; d.textContent=c.name;
    d.onclick=()=>{ setNavByCat(c.id); };
    d.oncontextmenu=(e)=>{ e.preventDefault();
      showConfirmDialog({title:'删除分组', message:`删除分组「${c.name}」？其下游戏将变为「未分类」。`,
        danger:true, okText:'删除', cb:()=>bridge.deleteCategory(c.id)}); };
    cl.appendChild(d);
  });
}

function setNavByCat(id){
  state.catId=id; state.nav='';
  document.querySelectorAll('.side-item').forEach(x=>x.classList.remove('active'));
  renderAll();
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

function batchPickTag(mode){
  const ids=[...state.selected];
  const items=ALL_TAGS.map(t=>({label:t.name,value:t.id}));
  openPicker(mode==='add'?'批量添加标签':'批量移除标签', items, function(tagId){
    if(mode==='add') bridge.batchAddTag(JSON.stringify(ids), tagId);
    else bridge.batchRemoveTag(JSON.stringify(ids), tagId);
    state.selected.clear();
  });
}

function batchPickCat(){
  const ids=[...state.selected];
  const items=[{label:'未分类',value:0}].concat(CATS.map(c=>({label:c.name,value:c.id})));
  openPicker('移动至分组', items, function(catId){
    bridge.batchMoveCategory(JSON.stringify(ids), catId);
    state.selected.clear();
  });
}

// ---------- Sheet ----------
function showSheet(id){ document.getElementById(id).classList.add('show'); }
function closeSheet(id){
  const o=document.getElementById(id);
  const d=o.querySelector('.dialog');
  d.classList.add('closing'); o.classList.remove('show');
  setTimeout(()=>d.classList.remove('closing'),300);
}
document.querySelectorAll('.overlay').forEach(o=>{
  o.addEventListener('click',e=>{ if(e.target===o) closeSheet(o.id); });
});
function closeTopSheet(){
  if(formOverlayVisible()) return closeSheet('formOverlay');
  if(document.getElementById('tagOverlay').classList.contains('show')) return closeSheet('tagOverlay');
  if(document.getElementById('pickerOverlay').classList.contains('show')) return closeSheet('pickerOverlay');
  if(document.getElementById('detailOverlay').classList.contains('show')) closeSheet('detailOverlay');
}
function formOverlayVisible(){ return document.getElementById('formOverlay').classList.contains('show'); }

// ---------- 标签管理 ----------
function renderCatFilter(){
  const c=document.getElementById('catFilter'); c.innerHTML='';
  const all=document.createElement('button'); all.className='cat-item on'; all.textContent='全部';
  all.onclick=()=>{ selectCatItem(all); };
  c.appendChild(all);
  CATS.forEach(cat=>{
    const b=document.createElement('button'); b.className='cat-item'; b.textContent=cat.name;
    b.onclick=()=>{ selectCatItem(b); };
    c.appendChild(b);
  });
}
function selectCatItem(btn){
  document.querySelectorAll('#catFilter .cat-item').forEach(x=>x.classList.remove('on'));
  btn.classList.add('on');
}

function openTagManager(){ renderGameTags(); renderCatFilter(); showSheet('tagOverlay'); }

// ---------- 编辑 / 添加 ----------
function openEdit(g){
  editingId=g.id;
  document.getElementById('formTitle').textContent='编辑游戏';
  document.getElementById('fTitle').value=g.title||'';
  document.getElementById('fEngine').value=g.engine||'';
  document.getElementById('fDev').value=g.dev||'';
  document.getElementById('fRating').value=String(g.rating||0);
  document.getElementById('fCat').value=String(g.cat_id||0);
  document.getElementById('fTags').value=(g.tags||[]).join(',');
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
  ['fTitle','fEngine','fDev','fTags','fDesc','fExe'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('fRating').value='0';
  document.getElementById('fCat').value='0';
  document.getElementById('fExeRow').style.display='flex';
  document.getElementById('fCoverRow').style.display='none';
  document.getElementById('fMetaRow').style.display='none';
  document.getElementById('fCands').style.display='none';
  showSheet('formOverlay');
}
function renderCatSelect(){
  const s=document.getElementById('fCat'); const cur=s.value;
  s.innerHTML='<option value="0">未分类</option>'+CATS.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  s.value=cur;
}
function saveForm(){
  const data={title:document.getElementById('fTitle').value,
    engine:document.getElementById('fEngine').value,
    developer:document.getElementById('fDev').value,
    rating:parseInt(document.getElementById('fRating').value||'0'),
    cat_id:parseInt(document.getElementById('fCat').value||'0'),
    tags:document.getElementById('fTags').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean),
    description:document.getElementById('fDesc').value,
    exe_path:document.getElementById('fExe').value};
  if(!data.title){ toast('标题不能为空'); return; }
  bridge.saveGame(editingId, JSON.stringify(data));
  closeSheet('formOverlay');
}

// ---------- 卡片右键菜单 ----------
function openCardMenu(g, x, y){
  // 右键其他卡片时，关闭已打开的右键菜单
  document.querySelectorAll('.ctx-menu').forEach(mm=>mm.remove());
  const m=document.createElement('div');
  m.className='more-menu ctx-menu';
  // 固定位置：菜单 150px 宽，clamp 到视口内，避免超出屏幕右侧/底部
  const vw=window.innerWidth, vh=window.innerHeight, mw=150, mh=200;
  let px=x, py=y;
  if(px+mw>vw-8) px=vw-mw-8;
  if(py+mh>vh-8) py=vh-mh-8;
  px=Math.max(8,px); py=Math.max(8,py);
  m.style.cssText=`position:fixed;left:${px}px;top:${py}px;display:block;z-index:90;background:var(--bg-panel);border:1.5px solid var(--border-soft);border-radius:12px;padding:5px;width:150px;box-shadow:0 10px 24px var(--glow-med);`;
  m.innerHTML=`<div class="item">启动游戏</div><div class="item">打开本地目录</div><div class="item">编辑</div><div class="item">VNDB 匹配</div><div class="item danger">从库中移除</div>`;
  const items=m.querySelectorAll('.item');
  items[0].onclick=()=>bridge.launch(g.id);
  items[1].onclick=()=>bridge.openFolder(g.id);
  items[2].onclick=()=>{ m.remove(); openEdit(g); };
  items[3].onclick=()=>{ m.remove(); bridge.matchVndb(g.id); toast('开始匹配：'+g.title); };
  items[4].onclick=()=>{ m.remove(); showConfirmDialog({title:'从库中移除',
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
  if(it.id==='addGroup'||it.id==='btnSettings') return;
  it.onclick=()=>{ state.nav=it.dataset.nav; state.catId=0;
    document.querySelectorAll('#sidebar .side-item').forEach(x=>x.classList.remove('active'));
    it.classList.add('active'); renderAll(); };
});
document.getElementById('addGroup').onclick=()=>{
  showInputDialog({
    title:'新建分组',
    label:'分组名称',
    cb:function(name){ if(name&&name.trim()) bridge.addCategory(name.trim()); }
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
document.getElementById('btnBAdd').onclick=()=>batchPickTag('add');
document.getElementById('btnBRem').onclick=()=>batchPickTag('remove');
document.getElementById('btnBMove').onclick=()=>batchPickCat();
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
document.getElementById('btnShowAll').onclick=()=>{ state.nav='全部作品'; state.catId=0; state.kw=''; renderAll(); };
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
document.getElementById('dlgEdit').onclick=()=>{ if(currentGame){ closeSheet('detailOverlay'); openEdit(currentGame); } };
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

document.getElementById('tagClose').onclick=()=>closeSheet('tagOverlay');
document.getElementById('tagDone').onclick=()=>closeSheet('tagOverlay');
document.getElementById('gameTagAdd').onclick=()=>{
  const inp=document.getElementById('gameTagInput');
  addTagToCurrentGame(inp.value); inp.value='';
};
document.getElementById('gameTagInput').addEventListener('keydown',e=>{
  if(e.key==='Enter'){ addTagToCurrentGame(e.target.value); e.target.value=''; }
});

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
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){ if(state.batch){ state.batch=false; document.body.classList.remove('batch');
      document.getElementById('batchBtn').classList.remove('active'); state.selected.clear(); renderAll(); }
    else closeTopSheet(); }
});

bindDrag();
bindResize();
init();

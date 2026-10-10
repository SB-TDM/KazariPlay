// 异步迟到响应回归：封面请求必须"最新请求生效"，被超越的迟到响应全部丢弃。
// 对抗顺序覆盖：不同 ID 新先旧后、A→B→A、同 ID 连续请求、重载入口交错。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const flush = () => new Promise(resolve => setImmediate(resolve));
const js = name => fs.readFileSync(path.join(__dirname, `../kazari_play/ui/web_assets/js/${name}`), 'utf8');

function makeContext() {
  const pending = [];
  const ctx = {
    window: {
      innerWidth: 1000, innerHeight: 700,
      pywebview: { api: { getCover: gid => new Promise(resolve => pending.push({ gid, resolve })) } },
    },
    document: { getElementById: () => null, querySelectorAll: () => [], querySelector: () => null },
    console, setImmediate, setTimeout, clearTimeout,
  };
  vm.createContext(ctx);
  vm.runInContext(js('core.js'), ctx);
  return { ctx, pending };
}

const makeCoverEl = () => ({ dataset: {}, style: {}, classList: { add() {}, remove() {} } });
const bg = uri => `url('${uri}'),linear-gradient(160deg,#ffd7e0,#ff9fbc)`;

(async () => {
  // 1) 不同 ID：B（新）先回、A（旧）后回，旧响应不得覆盖
  {
    const { ctx, pending } = makeContext();
    const el = makeCoverEl();
    ctx.loadCoverTo('a', el, 'bg');
    ctx.loadCoverTo('b', el, 'bg');
    pending[1].resolve('uri:b'); await flush();
    assert.equal(el.style.backgroundImage, bg('uri:b'), 'B 的新响应应生效');
    pending[0].resolve('uri:a'); await flush();
    assert.equal(el.style.backgroundImage, bg('uri:b'), 'B 之后迟到的 A 响应必须被丢弃');
  }
  // 2) A→B→A：最新的 A 先回，更早的 B / A 后回，最终必须保持最新 A
  {
    const { ctx, pending } = makeContext();
    const el = makeCoverEl();
    ctx.loadCoverTo('a', el, 'bg');
    ctx.loadCoverTo('b', el, 'bg');
    ctx.loadCoverTo('a', el, 'bg');
    pending[2].resolve('uri:a2'); await flush();
    pending[1].resolve('uri:b');
    pending[0].resolve('uri:a1'); await flush();
    assert.equal(el.style.backgroundImage, bg('uri:a2'), 'A→B→A 后旧 A/B 响应不得覆盖最新 A');
  }
  // 3) 同 ID 连续请求：旧请求迟到不得覆盖新请求
  {
    const { ctx, pending } = makeContext();
    const el = makeCoverEl();
    ctx.loadCoverTo('x', el, 'bg');
    ctx.loadCoverTo('x', el, 'bg');
    pending[1].resolve('uri:x2'); await flush();
    pending[0].resolve('uri:x1'); await flush();
    assert.equal(el.style.backgroundImage, bg('uri:x2'), '同 ID 旧请求迟到不得覆盖新请求');
  }
  // 4) games.reloadCover 同 ID 两次重载：旧响应不得覆盖
  {
    const { ctx, pending } = makeContext();
    const cover = makeCoverEl();
    const card = { dataset: {}, querySelector: sel => (sel === '.cover' ? cover : null) };
    ctx.document.querySelector = sel => (String(sel).includes('data-id') ? card : null);
    vm.runInContext(js('games.js'), ctx);
    ctx.reloadCover('g');
    ctx.reloadCover('g');
    pending[1].resolve('uri:new'); await flush();
    assert.equal(cover.style.backgroundImage, bg('uri:new'), '重载新响应应生效');
    pending[0].resolve('uri:old'); await flush();
    assert.equal(cover.style.backgroundImage, bg('uri:new'), '重载旧响应迟到不得覆盖新响应');
  }
  // 5) reloadCovers 与 reloadCover 交错：较晚发起的全量重载不得被更早的单卡响应覆盖
  {
    const { ctx, pending } = makeContext();
    const cover = makeCoverEl();
    const card = { dataset: { id: 'g' }, querySelector: sel => (sel === '.cover' ? cover : null) };
    ctx.document.querySelector = sel => (String(sel).includes('data-id') ? card : null);
    ctx.document.querySelectorAll = sel => (sel === '.card' ? [card] : []);
    vm.runInContext(js('games.js'), ctx);
    ctx.reloadCover('g');
    ctx.reloadCovers();
    pending[1].resolve('uri:batch'); await flush();
    pending[0].resolve('uri:single'); await flush();
    assert.equal(cover.style.backgroundImage, bg('uri:batch'), '后发起的全量重载不得被更早的单卡响应覆盖');
  }
  console.log('UI ORDERING PASS: stale cover responses discarded in all adversarial orders');
})().catch(err => { console.error(err); process.exitCode = 1; });

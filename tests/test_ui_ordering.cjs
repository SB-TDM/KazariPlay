// 异步迟到响应回归：验证 core.loadCoverTo 会丢弃被后续目标超越的迟到封面。
// 覆盖 C08/C09 使用的「元素绑定目标变化 → 丢弃迟到响应」保护模式。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const pendingCover = [];
const ctx = {
  window: {
    innerWidth: 1000, innerHeight: 700,
    pywebview: { api: { getCover: gid => new Promise(resolve => pendingCover.push({ gid, resolve })) } },
  },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  console,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../kazari_play/ui/web_assets/js/core.js'), 'utf8'), ctx);

const el = { dataset: {}, style: {} };
ctx.loadCoverTo('a', el, 'bg');
ctx.loadCoverTo('b', el, 'bg');

pendingCover.find(p => p.gid === 'a').resolve('uri:a');
pendingCover.find(p => p.gid === 'b').resolve('uri:b');

setImmediate(() => {
  assert.equal(
    el.style.backgroundImage,
    "url('uri:b'),linear-gradient(160deg,#ffd7e0,#ff9fbc)",
    '被超越的迟到封面不得覆盖当前目标');
  console.log('UI ORDERING PASS: stale cover response discarded');
});

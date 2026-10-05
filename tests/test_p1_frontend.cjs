const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor() { this.dataset = {}; this.items = []; this.style = {}; this.isConnected = false; this.classList = { add() {}, remove() {}, contains() { return true; } }; }
  set innerHTML(v) { this.items.forEach(x => x.isConnected = false); this.items = []; this.html = v; }
  querySelectorAll(s) { return s === '.shot-item' ? this.items : []; }
  querySelector(s) { return s === '.shot-thumb' ? this.thumb : null; }
  appendChild(x) { x.parent = this; x.isConnected = true; this.items.push(x); }
  remove() { this.isConnected = false; this.parent.items = this.parent.items.filter(x => x !== this); }
}
const nodes = new Map();
const element = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const requests = [], thumbnails = [], previews = [], deletes = [];
const ctx = {
  window: { innerWidth: 1000, innerHeight: 700 },
  App: { data: { currentGame: { id: 'a' } } },
  document: { getElementById: element, querySelectorAll() { return []; }, createElement() { const el = new Element(); el.thumb = new Element(); return el; } },
  bridge: { getScreenshots(id, cb) { requests.push({ id, cb }); }, getScreenshotThumb(id, file, cb) { thumbnails.push({ id, file, cb }); },
    getScreenshotOriginal(id, file, cb) { previews.push({ id, file, cb }); }, deleteScreenshot(id, file, cb) { deletes.push(id); cb(true); } },
  IntersectionObserver: class { constructor(cb) { this.cb = cb; } observe(item) { this.cb([{ isIntersecting: true, target: item }]); } unobserve() {} disconnect() {} },
  esc: x => x, showSheet() {}, closeSheet() {}, toast() {}, showConfirmDialog(x) { ctx.confirm = x.cb; },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../kazari_play/ui/web_assets/js/screenshots.js'), 'utf8'), ctx);
const list = '[{"file":"same.png"}]';
ctx.renderScreenshots();
requests.shift().cb(list);
const old = element('shotsGrid').items[0];
old.onclick();
ctx.App.data.currentGame = { id: 'b' };
ctx.renderScreenshots();
requests.shift().cb(list);
const fresh = element('shotsGrid').items[0];
assert.notEqual(old, fresh, 'different games must not reuse screenshot nodes');
thumbnails[0].cb('old-image');
assert.equal(fresh.thumb.style.backgroundImage, undefined);
previews[0].cb('old-preview');
assert.equal(element('shotPreviewImg').src, '');
ctx.renderScreenshots();
const late = requests.shift();
ctx.App.data.currentGame = { id: 'c' };
ctx.renderScreenshots();
const current = requests.shift();
late.cb(list);
assert.equal(element('shotsGrid').items.length, 0, 'old listing response ignored');
current.cb(list);
ctx.showShotMenu(10, 10, {file:'same.png'});
ctx.deleteShot();
ctx.App.data.currentGame = { id: 'd' };
ctx.confirm();
assert.deepEqual(deletes, ['c'], 'confirmation retains explicit original game target');
console.log('P1 FRONTEND PASS: nodes/list/thumb/preview response isolation and explicit operation target');

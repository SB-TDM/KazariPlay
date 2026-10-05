const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const js = path.join(__dirname, '../kazari_play/ui/web_assets/js');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', style: {}, classList: { add() {}, remove() {}, contains() { return false; } },
    querySelector() { return null; }, appendChild() {}, addEventListener() {},
  });
  return elements.get(id);
}
const context = {
  App: { data: { games: [{ id: 'a1b2c3d4e5f67890', title: 'A' }], currentGame: null, editingId: null },
         ui: { state: { nav: '', kw: '', sort: '', collectionId: null, selected: new Set() } } },
  bridge: { getGame(id, cb) { cb('{}'); } },
  document: { getElementById: element, querySelectorAll() { return []; }, createElement() { return element('new'); } },
  renderCards() {}, updateBatchBar() {}, showSheet() {},
  closeSheet(id) { context.closed.push(id); }, closed: [], console,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(js, 'games.js'), 'utf8'), context);
vm.runInContext('renderEmpty = () => {};', context);
context.applyGamesDelta(['a1b2c3d4e5f67890']);
assert.equal(context.App.data.games.length, 0, 'string ID must disappear');
vm.runInContext(fs.readFileSync(path.join(js, 'form.js'), 'utf8'), context);
element('fExe').value = 'C:/fixture/game.exe';
let submitted;
context.bridge.saveGame = (id, payload, cb) => { submitted = id; cb('{"ok":true}'); };
context.saveForm();
assert.equal(submitted, '', 'new game ID must be empty, not string null');
assert.deepEqual(context.closed, ['formOverlay']);
context.closed.length = 0;
context.bridge.saveGame = (id, payload, cb) => cb('{"ok":false,"msg":"fixture failure"}');
context.saveForm();
assert.deepEqual(context.closed, [], 'failed save must not close form');
console.log('P0 FRONTEND PASS: string-ID deletion, new-ID protocol, failed-save state');

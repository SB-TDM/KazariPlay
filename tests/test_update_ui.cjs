// 更新弹层状态与轮询回归（UPD-REV-08 ~ UPD-REV-11）
// 场景：就绪弹层关闭后重新打开 / 下载与补查双失败不锁死 / 迟到轮询响应丢弃 / 回滚提示展示
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class El {
  constructor(id) {
    this.id = id;
    this.hidden = false;
    this.textContent = '';
    this.style = {};
    this.disabled = false;
    this.onclick = null;
    this._classes = new Set();
    this.classList = {
      add: c => this._classes.add(c),
      remove: c => this._classes.delete(c),
      toggle: (c, on) => { on ? this._classes.add(c) : this._classes.delete(c); },
      contains: c => this._classes.has(c),
    };
  }
  addEventListener(type, fn) { this._listeners = this._listeners || {}; this._listeners[type] = fn; }
}

function makeEnv(bridgeImpl) {
  const els = new Map();
  const element = id => { if (!els.has(id)) els.set(id, new El(id)); return els.get(id); };
  const state = { sheets: [], locks: {}, toasts: [], timers: new Map(), timerSeq: 0 };
  const ctx = {
    window: {},
    document: { getElementById: element },
    console,
    setTimeout: (fn) => { state.timerSeq += 1; state.timers.set(state.timerSeq, fn); return state.timerSeq; },
    clearTimeout: id => { state.timers.delete(id); },
    setInterval: () => { throw new Error('updater 不应使用 setInterval（应为串行 setTimeout 轮询）'); },
    clearInterval: () => {},
    toast: msg => state.toasts.push(String(msg)),
    showSheet: id => state.sheets.push(['show', id]),
    closeSheet: id => state.sheets.push(['close', id]),
    setSheetLocked: (id, locked) => { state.locks[id] = !!locked; },
    bridge: bridgeImpl,
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../kazari_play/ui/web_assets/js/updater.js'), 'utf8'), ctx);
  return { ctx, element, state };
}

const noopBridge = () => ({
  getUpdateState() {}, checkUpdate() {}, downloadUpdate() {}, skipUpdate() {},
  applyUpdate() {}, openReleasePage() {},
});

// 1) UPD-REV-08：就绪后关闭弹层，手动检查应立即恢复安装入口（不重新下载）
{
  const requests = [];
  const env = makeEnv(Object.assign(noopBridge(), {
    checkUpdate: (force, cb) => requests.push({ force, cb }),
    downloadUpdate: () => { throw new Error('就绪状态不得重新下载'); },
  }));
  env.ctx.updaterCheck(true, false);
  requests[0].cb(JSON.stringify({ state: 'ready', latest_version: '1.0.1' }));
  assert.deepEqual(env.state.sheets, [['show', 'updateOverlay']], '首次检查就绪应打开弹层');
  assert.equal(env.element('updateFootReady').hidden, false, '就绪底栏应可见');
  env.ctx.closeUpdateModal();
  env.ctx.updaterCheck(true, false);
  requests[1].cb(JSON.stringify({ state: 'ready', latest_version: '1.0.1' }));
  assert.deepEqual(env.state.sheets, [['show', 'updateOverlay'], ['close', 'updateOverlay'], ['show', 'updateOverlay']],
    '就绪后再次检查应重新打开弹层');
  console.log('[REV-08 就绪弹层重开] OK');
}

// 2) UPD-REV-09：下载请求与状态补查都失败 → 解除锁定、给出重试反馈
{
  const env = makeEnv(Object.assign(noopBridge(), {
    downloadUpdate: cb => cb(JSON.stringify({ ok: false }), false),
    getUpdateState: cb => cb('[]', true),   // 补查失败
  }));
  vm.runInContext("updateCurrent = { state: 'available' };", env.ctx);
  env.ctx.updaterStartDownload();
  assert.equal(env.state.locks.updateOverlay, false, '双失败后不得保持锁定');
  assert.equal(env.element('updateProg').hidden, true, '不得继续显示下载进度');
  assert.equal(env.element('updateFootFail').hidden, false, '应显示失败底栏（重试入口）');
  assert.equal(env.element('updateError').hidden, false);
  assert.ok(env.element('updateError').textContent.includes('请重试'), env.element('updateError').textContent);
  assert.equal(env.state.timers.size, 0, '不得留下悬挂轮询');
  console.log('[REV-09 补查失败解锁] OK');
}

// 3) UPD-REV-10：轮询间隔不得重叠；迟到 / 旧代际响应不得覆盖当前状态
{
  const pending = [];
  const env = makeEnv(Object.assign(noopBridge(), {
    getUpdateState: cb => pending.push(cb),
  }));
  env.ctx.updateSetStage('downloading');
  env.ctx.updateSetLocked(true);
  env.ctx.updateStartPolling();                      // 代际 A
  assert.equal(pending.length, 1, '串行轮询：同时只允许一个请求在途');
  env.ctx.updateStopPolling();
  env.ctx.updateStartPolling();                      // 代际 B（旧回调作废）
  assert.equal(pending.length, 2, '重启轮询后只发新请求');
  pending[1](JSON.stringify({ state: 'ready', latest_version: '1.0.1' }));
  assert.equal(vm.runInContext('updateCurrent.state', env.ctx), 'ready', '就绪响应应生效');
  assert.equal(env.element('updateFootReady').hidden, false);
  assert.equal(env.state.locks.updateOverlay, false, '就绪后应解锁');
  pending[0](JSON.stringify({ state: 'downloading', percent: 42 }));   // 迟到旧响应
  assert.equal(vm.runInContext('updateCurrent.state', env.ctx), 'ready', '迟到响应不得覆盖就绪状态');
  assert.equal(env.element('updateTitle').textContent, '更新包已就绪');
  assert.equal(env.element('updateProg').hidden, true);
  console.log('[REV-10 迟到轮询丢弃] OK');
}

// 4) 弹层关闭后的在途轮询响应同样不得覆盖界面
{
  const pending = [];
  const env = makeEnv(Object.assign(noopBridge(), {
    getUpdateState: cb => pending.push(cb),
  }));
  vm.runInContext("updateCurrent = { state: 'downloading' };", env.ctx);
  env.ctx.updateSetStage('downloading');
  env.ctx.updateStartPolling();
  env.ctx.closeUpdateModal();                        // 关闭 → 代际作废
  pending[0](JSON.stringify({ state: 'ready' }));
  assert.equal(vm.runInContext('updateCurrent.state', env.ctx), 'downloading',
    '弹层关闭后的旧响应不得写入状态');
  console.log('[REV-10 关闭后响应丢弃] OK');
}

// 5) UPD-REV-11：后端一次性 notice（回滚/中断恢复）必须展示且只弹一次
{
  const responses = [
    { state: 'up_to_date', notice: '新版本启动失败，已回滚到更新前的版本' },
    { state: 'up_to_date' },
  ];
  const env = makeEnv(Object.assign(noopBridge(), {
    checkUpdate: (force, cb) => cb(JSON.stringify(responses.shift())),
  }));
  env.ctx.updaterCheck(true, false);
  assert.deepEqual(env.state.toasts, ['新版本启动失败，已回滚到更新前的版本'], 'notice 应弹出提示');
  env.ctx.updaterCheck(true, false);
  assert.equal(env.state.toasts.length, 1, '普通响应不得重复弹提示');
  console.log('[REV-11 回滚提示展示] OK');
}

console.log('UPDATE UI PASS: ready reopen / recover / late poll drop / notice');

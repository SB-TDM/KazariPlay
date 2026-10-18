// 桥失败语义回归：缺方法 / 同步异常 / Promise reject 必须向回调显式标记失败，
// 且每次请求的回调至多执行一次（业务回调自身抛错不得触发二次回调）。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const flush = () => new Promise(resolve => setImmediate(resolve));

const ctx = {
  window: {
    pywebview: {
      api: {
        ok: () => Promise.resolve('"fine"'),
        reject: () => Promise.reject(new Error('boom')),
        throwSync: () => { throw new Error('sync boom'); },
      },
    },
  },
  document: { getElementById: () => null },
  console, setImmediate, setTimeout, clearTimeout,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/kazari_play/ui/web_assets/js/core.js'), 'utf8'), ctx);
const seen = () => { ctx.__seen = []; return ctx.__seen; };

(async () => {
  // 1) 缺方法：只回调一次，且显式标记失败
  {
    const out = seen();
    vm.runInContext("bridge.notAClientMethod((r, failed) => __seen.push([r, failed]));", ctx);
    await flush();
    assert.equal(out.length, 1, '缺方法只允许回调一次');
    assert.equal(out[0][1], true, '缺方法必须标记失败');
  }
  // 2) Promise reject
  {
    const out = seen();
    vm.runInContext("bridge.reject((r, failed) => __seen.push([r, failed]));", ctx);
    await flush();
    assert.equal(out.length, 1, 'reject 只允许回调一次');
    assert.equal(out[0][1], true, 'reject 必须标记失败');
  }
  // 3) 同步 throw
  {
    const out = seen();
    vm.runInContext("bridge.throwSync((r, failed) => __seen.push([r, failed]));", ctx);
    await flush();
    assert.equal(out.length, 1, '同步异常只允许回调一次');
    assert.equal(out[0][1], true, '同步异常必须标记失败');
  }
  // 4) 业务回调自身抛错：不得触发第二次回调
  {
    const out = seen();
    vm.runInContext("bridge.ok(function (r) { __seen.push(r); throw new Error('callback boom'); });", ctx);
    await flush();
    assert.equal(out.length, 1, '业务回调抛错不得导致二次回调');
    assert.equal(out[0], '"fine"');
  }
  // 5) 正常成功：结果原样传递，且不标记失败
  {
    const out = seen();
    vm.runInContext("bridge.ok((r, failed) => __seen.push([r, failed]));", ctx);
    await flush();
    assert.equal(out.length, 1);
    assert.equal(out[0][0], '"fine"', '成功结果应原样传递');
    assert.equal(out[0][1], undefined, '成功结果不应标记失败');
  }
  console.log('BRIDGE CONTRACT PASS: failure is explicit, callbacks run at most once');
})().catch(err => { console.error(err); process.exitCode = 1; });

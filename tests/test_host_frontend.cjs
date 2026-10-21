// WinHost bridge path in the compiled core.js; run after npm run build.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const core = fs.readFileSync(path.join(root, 'src/kazari_play/ui/web_assets/js/core.js'), 'utf8');
const calls = [];
const context = {
  window: {
    __host: {
      ready: true,
      invoke(name, args) {
        calls.push({ name, args });
        if (name === 'fail') return Promise.reject(new Error('expected failure'));
        return Promise.resolve('{"ok":true}');
      },
    },
  },
  document: { getElementById() { return null; } },
  console,
  Promise,
  setTimeout,
  clearTimeout,
  Date,
  Map,
  Set,
};
vm.createContext(context);
vm.runInContext(`${core}\n;globalThis.__bridge = bridge;`, context);

function run(name, args) {
  return new Promise((resolve) => {
    let callbackCount = 0;
    context.__bridge[name](...args, (value, failed) => {
      callbackCount += 1;
      resolve({ value, failed, callbackCount });
    });
  });
}

(async () => {
  const ok = await run('getGames', []);
  if (ok.value !== '{"ok":true}' || ok.failed === true || ok.callbackCount !== 1) {
    throw new Error(`unexpected host result: ${JSON.stringify(ok)}`);
  }
  if (calls[0].name !== 'getGames' || calls[0].args.length !== 0) {
    throw new Error(`unexpected invocation: ${JSON.stringify(calls[0])}`);
  }
  const failed = await run('fail', []);
  if (failed.failed !== true || failed.callbackCount !== 1) {
    throw new Error(`unexpected host failure: ${JSON.stringify(failed)}`);
  }
  console.log('HOST_FRONTEND_PASS');
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});

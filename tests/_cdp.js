/* CDP 客户端（Node 24 内置 fetch/WebSocket，零依赖）
   用法：node _cdp.js <debugPort> <url> <exprFile>
   行为：等调试端口就绪 → 取/开 page target → 导航 → 等 load → 求值 exprFile
        → stdout 末行打印求值结果的 JSON。
   失败：stderr 输出 `CDP_ERROR <message>`，退出码非 0。
   说明：debugPort 由调用方运行时探测（空闲口），不写死——
       上一轮测试残留的 chrome 进程不会造成端口冲突或误连旧实例。 */
'use strict';
const fs = require('fs');

const debugPort = process.argv[2];
const url = process.argv[3];
const exprFile = process.argv[4];
if (!debugPort || !url || !exprFile) {
  console.error('usage: node _cdp.js <debugPort> <url> <exprFile>');
  process.exit(2);
}
const expr = fs.readFileSync(exprFile, 'utf-8');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function waitForDevtools(port, tries) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch('http://127.0.0.1:' + port + '/json/version');
      if (r.ok) return true;
    } catch (e) { /* 还没起来 */ }
    await sleep(100);
  }
  return false;
}

async function pickPage(port) {
  const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  let page = list.find(t => t.type === 'page');
  if (!page) {
    // 新版 chrome 的 /json/new 只接受 PUT
    const r = await fetch('http://127.0.0.1:' + port + '/json/new?' +
                          encodeURIComponent('about:blank'), { method: 'PUT' });
    page = await r.json();
  }
  return page;
}

async function main() {
  if (!await waitForDevtools(debugPort, 150)) {
    throw new Error('devtools port ' + debugPort + ' not reachable');
  }
  const page = await pickPage(debugPort);
  if (!page || !page.webSocketDebuggerUrl) {
    throw new Error('no page target with webSocketDebuggerUrl');
  }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let msgId = 0;
  const pending = new Map();
  const listeners = [];
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      if (m.error) p.reject(new Error(JSON.stringify(m.error)));
      else p.resolve(m.result);
      return;
    }
    listeners.slice().forEach(fn => fn(m));
  });
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', reject);
  });
  const send = (method, params) => new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id: id, method: method, params: params || {} }));
  });

  await send('Page.enable');
  await send('Runtime.enable');
  // 先挂监听再导航，否则 load 事件可能在监听建立前已经过去
  const loaded = new Promise(resolve => {
    const fn = m => {
      if (m.method === 'Page.loadEventFired') {
        const i = listeners.indexOf(fn);
        if (i >= 0) listeners.splice(i, 1);
        resolve();
      }
    };
    listeners.push(fn);
  });
  await send('Page.navigate', { url: url });
  await loaded;
  await sleep(900);            // 等前端 render() 与 vendor 懒加载落地
  const out = await send('Runtime.evaluate', {
    expression: expr,
    awaitPromise: true,
    returnByValue: true
  });
  if (out.exceptionDetails) {
    throw new Error('page exception: ' +
                    JSON.stringify(out.exceptionDetails).slice(0, 400));
  }
  const value = (out.result && out.result.value !== undefined) ? out.result.value : null;
  console.log(JSON.stringify(value));
  ws.close();
}

main().catch(e => {
  console.error('CDP_ERROR ' + (e && e.message ? e.message : String(e)));
  process.exit(1);
});

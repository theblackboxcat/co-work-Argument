/* ============================================================================
   真实时钟的浏览器探针（CDP）。

   为什么要有它：`--virtual-time-budget` 会**伪造时钟**。JSZip 这类库内部会周期性
   yield（setTimeout/await）来避免阻塞，虚拟时间下每次 yield 时钟就跳一大截，
   于是同一个 readEpub 在 --dump-dom 里量出 9836ms，在 Node 里量出 76ms。
   差 130 倍。任何"耗时"结论都不能用虚拟时间测——必须连真实浏览器。

   用法：
     node tests/browser/cdp.js <探针文件> [窗口尺寸]
   例：
     node tests/browser/cdp.js tests/browser/perf.probe.js

   探针写法与普通 .probe.js 相同：把结果写进 #VR（id="VR"）的 textContent，
   首尾包 ===VR-START=== / ===VR-END===。这里会一直轮询到出现 VR-END 为止。
   ========================================================================== */
const fs = require('fs');
const path = require('path');
const http = require('http');
const { spawn } = require('child_process');

const WEB = path.join(__dirname, '..', '..');
const EDGE = process.env.EDGE_BIN ||
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8790';
const PORT = 9333;

const probeFile = process.argv[2];
const SIZE = process.argv[3] || '1400,900';
if (!probeFile) { console.error('用法：node cdp.js <探针.js> [宽,高]'); process.exit(2); }

const probe = fs.readFileSync(probeFile, 'utf8').replace(/<\/script>/gi, '<\\/script>');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
const tmpName = '_cdp_' + path.basename(probeFile, '.js') + '.html';
fs.writeFileSync(path.join(WEB, tmpName),
  html.replace(/<\/body>/i, '<script>\n' + probe + '\n<\/script>\n</body>'));

function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, r => {
      let b = ''; r.on('data', c => b += c);
      r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
    }).on('error', rej);
  });
}

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-sandbox',
  '--remote-debugging-port=' + PORT, '--window-size=' + SIZE,
  BASE + '/' + tmpName
], { stdio: 'ignore' });

const WS = global.WebSocket;
if (!WS) { console.error('这个 Node 没有全局 WebSocket，需要 22.4+'); process.exit(2); }

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

(async function () {
  let target = null;
  for (let i = 0; i < 60 && !target; i++) {
    try {
      const list = await getJson('http://127.0.0.1:' + PORT + '/json/list');
      target = list.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch (e) { /* 还没起来 */ }
    if (!target) await sleep(500);
  }
  if (!target) { console.error('连不上 CDP（9222 没起来？）'); edge.kill(); process.exit(1); }

  const ws = new WS(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const waiting = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  };
  function send(method, params) {
    const mid = ++id;
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
    return new Promise(res => waiting.set(mid, res));
  }
  async function evalJs(expr, awaitPromise) {
    const r = await send('Runtime.evaluate', {
      expression: expr, awaitPromise: !!awaitPromise, returnByValue: true
    });
    if (r.result && r.result.exceptionDetails) {
      throw new Error(r.result.exceptionDetails.text || 'eval 抛异常');
    }
    return r.result && r.result.result ? r.result.result.value : undefined;
  }

  await send('Runtime.enable');
  await send('Page.enable');

  // 等页面就绪（探针是内联的，load 之后才开始跑）
  for (let i = 0; i < 60; i++) {
    const ready = await evalJs('!!document.getElementById("VR")');
    if (ready) break;
    await sleep(500);
  }

  let out = null;
  for (let i = 0; i < 240; i++) {          // 最多等 2 分钟
    const txt = await evalJs('(document.getElementById("VR")||{}).textContent || ""');
    if (/===VR-END===/.test(txt)) { out = txt; break; }
    await sleep(500);
  }

  if (out == null) console.log('探针超时（2 分钟）');
  else {
    const i = out.indexOf('===VR-START==='), j = out.indexOf('===VR-END===');
    console.log(out.slice(i, j + '===VR-END==='.length));
  }
  ws.close(); edge.kill();
  try { fs.unlinkSync(path.join(WEB, tmpName)); } catch (e) { }
  process.exit(0);
})().catch(e => { console.error('ERR ' + (e && e.stack || e)); try { edge.kill(); } catch (x) { } process.exit(1); });

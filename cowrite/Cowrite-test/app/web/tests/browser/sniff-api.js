/* ============================================================================
   嗅出某个页面**实际打的是哪个接口**。

   为什么需要它：现在的站点十有八九是 SPA——`curl` 拿回来的是一个几 KB 的空壳
   （`window.__nowYear` 之类），列表内容全是 JS 现拉的。此时"这个页面用哪个接口"
   是**看不出来的**，只能靠猜。而猜接口是纯浪费：我为一个归档页连着试了 4 个候选
   路径，全部 404。

   正确做法是让浏览器自己跑一遍，把网络请求录下来。

   用法：
     node tests/browser/sniff-api.js <页面URL> [等待毫秒] [过滤关键词]
   例：
     node tests/browser/sniff-api.js https://drunkfloats.lofter.com/view 15000
     node tests/browser/sniff-api.js https://x.com/list 12000 api

   只**看**请求（不点、不登录、不改动对方任何东西）。默认只看 XHR/Fetch，
   因为"页面骨架"的请求（html/css/js/图片）不是要找的东西。
   ========================================================================== */
const http = require('http');
const { spawn } = require('child_process');

const EDGE = process.env.EDGE_BIN ||
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = Number(process.env.SNIFF_PORT || 9334);

const target = process.argv[2];
const waitMs = Number(process.argv[3] || 12000);
const filter = process.argv[4] || '';
if (!target) {
  console.error('用法：node sniff-api.js <页面URL> [等待毫秒] [过滤关键词]');
  process.exit(2);
}

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-sandbox',
  '--remote-debugging-port=' + PORT, '--window-size=1400,900',
  'about:blank'
], { stdio: 'ignore' });

function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, r => {
      let b = ''; r.on('data', c => b += c);
      r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
    }).on('error', rej);
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async function () {
  const WS = global.WebSocket;
  if (!WS) { console.error('这个 Node 没有全局 WebSocket，需要 22.4+'); edge.kill(); process.exit(2); }

  let t = null;
  for (let i = 0; i < 40 && !t; i++) {
    try {
      const list = await getJson('http://127.0.0.1:' + PORT + '/json/list');
      t = list.find(x => x.type === 'page' && x.webSocketDebuggerUrl);
    } catch (e) { }
    if (!t) await sleep(400);
  }
  if (!t) { console.error('连不上 CDP'); edge.kill(); process.exit(1); }

  const ws = new WS(t.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const waiting = new Map();
  const seen = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); return; }
    if (m.method === 'Network.requestWillBeSent') {
      const r = m.params.request;
      const type = m.params.type;
      if (type !== 'XHR' && type !== 'Fetch') return;
      if (filter && r.url.indexOf(filter) < 0) return;
      seen.push({
        method: r.method, url: r.url,
        body: (r.postData || '').slice(0, 400)
      });
    }
  };
  function send(method, params) {
    const mid = ++id;
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
    return new Promise(res => waiting.set(mid, res));
  }

  await send('Network.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: target });
  await sleep(waitMs);

  console.log('\n=== 页面打过的请求（XHR / Fetch）===');
  if (!seen.length) console.log('（一个都没录到——可能是纯服务端渲染，或者等待时间不够）');
  const uniq = [];
  const k = new Set();
  seen.forEach(x => { const key = x.method + ' ' + x.url; if (!k.has(key)) { k.add(key); uniq.push(x); } });
  uniq.forEach((x, i) => {
    console.log('\n[' + (i + 1) + '] ' + x.method + ' ' + x.url);
    if (x.body) console.log('    body: ' + x.body.replace(/\n/g, ' '));
  });
  console.log('\n共 ' + uniq.length + ' 个不同请求（去重后）。');

  ws.close(); edge.kill();
  process.exit(0);
})().catch(e => { console.error('ERR ' + (e && e.stack || e)); try { edge.kill(); } catch (x) { } process.exit(1); });

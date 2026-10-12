/* ============================================================================
   浏览器探针 runner —— 把探针注入 index.html，用无头 Edge 跑一遍，读回结果。

   为什么是"注入"而不是"另开一个测试页"：这些探针要直接摸 index.html 里的
   活对象（ta / lta / TOC / expPayload / VIEW …），它们是脚本作用域的顶层
   const，只有同一份文档里的传统脚本才够得到。复制一份页面就摸不到了。

   用法：
     node tests/browser/run.js                    # 跑全部探针
     node tests/browser/run.js editor-lit         # 只跑一个
     node tests/browser/run.js layout --w 760,900 # 指定视口

   前提：server.py 已在跑（默认 http://127.0.0.1:8790）。

   ── 三个坑，都是踩出来的，改这个 runner 时别把它们踩回去 ──────────────
   1) 探针必须**内联**。写成 <script src="probe.js"> 的话，--dump-dom 抓到的是
      脚本还没执行的那一刻——探针一次都不会跑，还以为"零失败"。
   2) headless 的虚拟时间**不推进 CSS transition**。抽屉开合那类动画会永远停在
      飞行中的 rect 上，命中测试全废。探针里要量终态就先把 transition 关掉。
   3) setTimeout / Promise 是可以等的（--virtual-time-budget 会等），所以
      异步断言照写，最后统一 dump 结果即可。
   ========================================================================== */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const WEB = path.join(__dirname, '..', '..');
const EDGE = process.env.EDGE_BIN ||
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8790';

const argv = process.argv.slice(2);
const only = argv.find(a => !a.startsWith('--')) || null;
const wArg = argv.indexOf('--w');
const SIZE = wArg >= 0 ? argv[wArg + 1] : '1400,900';

const probes = fs.readdirSync(__dirname)
  .filter(f => f.endsWith('.probe.js'))
  .map(f => f.replace(/\.probe\.js$/, ''))
  .filter(n => !only || n === only);

if (!probes.length) { console.error('没有匹配的探针：' + only); process.exit(2); }

const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
let bad = 0;

for (const name of probes) {
  const src = fs.readFileSync(path.join(__dirname, name + '.probe.js'), 'utf8')
    .replace(/<\/script>/gi, '<\\/script>');
  const page = html.replace(/<\/body>/i, '<script>\n' + src + '\n<\/script>\n</body>');
  const tmp = path.join(WEB, '_probe_' + name + '.html');
  fs.writeFileSync(tmp, page);

  let dom = '';
  try {
    dom = execFileSync(EDGE, [
      '--headless=new', '--disable-gpu', '--no-sandbox',
      '--virtual-time-budget=15000', '--window-size=' + SIZE,
      '--dump-dom', BASE + '/_probe_' + name + '.html'
    ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 64 * 1024 * 1024 });
  } catch (e) {
    console.log('■ ' + name + ' → 跑不起来：' + (e.message || e));
    bad++; continue;
  } finally {
    try { fs.unlinkSync(tmp); } catch (e) { /* 留着也不影响，下次会被覆盖 */ }
  }

  const k = dom.lastIndexOf('id="VR"');
  if (k < 0) { console.log('■ ' + name + ' → 没拿到结果（#VR 不存在，探针可能抛在最外层）'); bad++; continue; }
  const seg = dom.slice(k, k + 20000);
  const i = seg.indexOf('===VR-START==='), j = seg.indexOf('===VR-END===');
  if (i < 0 || j < 0) { console.log('■ ' + name + ' → 结果块不完整'); bad++; continue; }
  const lines = seg.slice(i, j).split('\n').filter(x => /^(PASS|FAIL|ERR|INFO|FATAL)/.test(x));
  const fails = lines.filter(x => /^(FAIL|ERR|FATAL)/.test(x));
  console.log('■ ' + name + '  ' + lines.length + ' 项，' +
    (fails.length ? '失败 ' + fails.length : '全过'));
  if (fails.length) { fails.forEach(x => console.log('   ' + x)); bad++; }
  else if (process.env.VERBOSE) { lines.forEach(x => console.log('   ' + x)); }
}

process.exit(bad ? 1 : 0);

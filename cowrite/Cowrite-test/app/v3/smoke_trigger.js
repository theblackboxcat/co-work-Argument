/* 触发逻辑冒烟测试（node 跑，不需要浏览器）
 *
 * 为什么要有它：这个"停笔 8 秒不出声"的 bug 已经犯过两次——
 *   第一次：clearTimeout 写在节流判断之前 → 定时器没挂上；
 *   第二次：注意力在"她刚敲键"那一刻被问 → pause≈0 → 必然回"别说话" → 探针没挂上。
 * 单靠人眼 review 已经漏过两次，所以给这段逻辑配一个真测试：
 * 把 index.html 里的 <script> 抽出来，喂一套假的 DOM / fetch / 定时器，
 * 然后驱动"她动了一下"和"探针到点"，看它到底有没有挂上定时器、有没有出声。
 *
 *   node v3/smoke_trigger.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'index.html'), 'utf8');
/* 取**最长的那个内联块**，不是"第一个"。
   ⚠️ 原来是 `.match(...)[1]`——拿第一个 <script>。这在把 editor-core / doc-core
   那些拆成 `dist/*.js` 之后就**静默失效**了：前 12 个块是 `<script src=…></script>`，
   里面**是空的**，于是 code = ''，跑起来第一句就是 `touch is not defined`。
   它不是"跑失败"，是"根本没在跑"——比失败更坏，因为报告里看不出区别。 */
const code = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1])
  .sort((a, b) => b.length - a.length)[0] || '';
if (!code || code.indexOf('function touch') < 0) {
  console.error('没抽到主脚本块（长度 ' + code.length + '）——index.html 的结构变了？');
  process.exit(2);
}

// ── 假定时器：记录下来，不真等 ──────────────────────────────────
let seq = 0;
const timers = new Map();
function setTimeoutStub(fn, ms) {
  const id = ++seq;
  timers.set(id, { fn, ms, dead: false });
  return id;
}
function clearTimeoutStub(id) { if (timers.has(id)) timers.get(id).dead = true; }
function liveTimers() { return [...timers.values()].filter(t => !t.dead); }
// 找出"当前挂着的定时器"，人肉推进它
function fireTimer() {
  const live = liveTimers();
  if (!live.length) throw new Error('没有挂任何定时器 —— 这就是 bug 本身');
  const t = live[live.length - 1];
  t.dead = true;
  return t.fn();
}

// ── 假 DOM ────────────────────────────────────────────────────
function makeEl(sel) {
  const cls = new Set();
  return {
    _sel: sel, textContent: '', value: '', innerHTML: '', placeholder: '',
    style: {}, dataset: {}, disabled: false, selectionStart: 0,
    scrollTop: 0, scrollHeight: 0, files: [],
    classList: {
      add: c => cls.add(c), remove: c => cls.delete(c),
      contains: c => cls.has(c),
      toggle: (c, on) => { (on === undefined ? !cls.has(c) : on) ? cls.add(c) : cls.delete(c); }
    },
    addEventListener() {}, removeEventListener() {},
    querySelector: () => makeEl('sub'), querySelectorAll: () => [],
    appendChild() {}, remove() {}, focus() {}, click() {},
    closest: () => makeEl('card'),
  };
}
const cache = new Map();
function $(sel) {
  if (!cache.has(sel)) cache.set(sel, makeEl(sel));
  return cache.get(sel);
}

// ── 假 fetch：按 url 给不同回答；注意力回答可切换 ────────────────
let ATTN = { available: true, speak: true, state: 'PLANNING', name: 'P-burst',
             delay_sec: 8 };
let attentionCalls = 0;
let cowriteCalls = 0;
function fetchStub(url, opt) {
  const u = String(url);
  if (u.includes('/api/attention')) {
    attentionCalls++;
    return Promise.resolve({ json: async () => ATTN });
  }
  if (u.includes('/api/cowrite')) {
    cowriteCalls++;
    return Promise.resolve({ json: async () => ({ cards: [], mode: 'offline' }) });
  }
  if (u.includes('/api/status')) {
    return Promise.resolve({ json: async () => ({ online: true, model: 'stub' }) });
  }
  if (u.includes('/api/doc')) {
    return Promise.resolve({ json: async () => ({ text: '', meta: {} }) });
  }
  if (u.includes('/api/profile')) {
    return Promise.resolve({ json: async () => ({ status: 'none' }) });
  }
  return Promise.resolve({ json: async () => ({}) });
}

/* ── 假 EditorController ───────────────────────────────────────
   index.html 从 `const ta = EditorController.create({…})` 起就是它了
   （P1 ② 把 textarea 替身抽成控制器，接在 Quill 底下）。这里只要一个
   **形状相同的替身**——触发逻辑只用到 value / selectionStart /
   addEventListener 三样，别的给空实现。关键是让它返回 `$('#ta')` 那个对象，
   这样 setPara() 写的 value/selectionStart 就是 ta 自己的，两边不会各说各话。 */
function makeEditor() {
  const el = $('#ta');
  if (el.__editor) return el.__editor;
  el.quill = {
    root: { style: {} },
    getText: () => el.value,
    setText: v => { el.value = String(v); },
    setSelection: i => { el.selectionStart = i; },
    getSelection: () => ({ index: el.selectionStart }),
    on() {}, off() {}, focus() {}, blur() {},
  };
  el.caretIndex = () => el.selectionStart;
  el.setRichDoc = html => { el.value = String(html).replace(/<[^>]+>/g, ''); };
  el.append = t => { el.value += t; };
  el.__editor = el;
  return el;
}

/* window / document 下面这些是 index.html 在**求值阶段**就会摸到的东西
   （挂事件、量尺寸、建观察器）。给空实现就够——冒烟要驱动的是触发逻辑，
   不是真渲染。缺一个都会在求值的时候整段抛掉，那比断言失败更难看出问题。 */
function makeWin() {
  const w = makeEl('window');
  w.innerWidth = 1400; w.innerHeight = 900;
  w.location = { href: 'http://127.0.0.1:8790/', search: '', hash: '' };
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  w.getComputedStyle = () => ({ getPropertyValue: () => '' });
  w.requestAnimationFrame = fn => 0;
  w.cancelAnimationFrame = () => {};
  w.scrollTo = () => {};
  w.open = () => null;
  return w;
}

const sandbox = {
  EditorController: { create: makeEditor },
  document: {
    querySelector: $, querySelectorAll: () => [],
    addEventListener() {}, createElement: () => makeEl('div'),
    activeElement: null, body: makeEl('body'),
  },
  window: makeWin(), localStorage: { getItem: () => '', setItem() {} },
  fetch: fetchStub, setTimeout: setTimeoutStub, clearTimeout: clearTimeoutStub,
  setInterval: () => 0, clearInterval() {}, console,
  Date, Math, JSON, Promise, Set, Array, Object, String, Number,
  btoa: s => s, Uint8Array,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

// ── 断言 ──────────────────────────────────────────────────────
let fails = 0;
function ok(cond, msg) {
  console.log((cond ? '  ✓ ' : '  ✗ ') + msg);
  if (!cond) fails++;
}
const run = () => vm.runInContext('(1)', sandbox); // 保持上下文活着
// 每次换一段新文本，并清掉「这段已经伴写过」的节流记录——
// 否则 run() 会因为 lastKey 相同而提前 return，测出来的失败是假的。
function setPara(s) {
  vm.runInContext(
    "lastKey = ''; document.querySelector('#ta').value = " + JSON.stringify(s) +
    "; document.querySelector('#ta').selectionStart = " + s.length + ';', sandbox);
}

async function main() {
  console.log('\n【1】她动了一下 → 必须挂上探针');
  vm.runInContext('touch()', sandbox);
  ok(liveTimers().length === 1, 'touch() 之后有一个定时器挂着（上次就是挂不上）');
  ok(liveTimers()[0] && liveTimers()[0].ms === 8000,
     '探针 8000ms（不是 0、不是 NaN）');

  console.log('\n【2】探针到点、注意力说「说话」→ 出声');
  ATTN = { available: true, speak: true, state: 'PLANNING', name: 'P-burst',
           delay_sec: 8 };
  cowriteCalls = 0; attentionCalls = 0;
  setPara('她停在了一个句子的末尾。');
  vm.runInContext('touch()', sandbox);
  ok(attentionCalls === 0,
     'touch() 的那一刻**不问**注意力（旧 bug 正是在这里问 —— 那一刻 pause≈0，' +
     '必然判"别说话"→ 探针挂不上）');
  await fireTimer();
  await new Promise(r => process.nextTick(r));
  ok(attentionCalls >= 1, '到点才去问注意力（不是敲键那一刻问）');
  ok(cowriteCalls === 1, '注意力说说话 → 真的发出了伴写请求');

  console.log('\n【3】注意力说「不说」（CODING）→ 不请求，但再探一次');
  ATTN = { available: true, speak: false, state: 'CODING', name: '句中编码', delay_sec: 20 };
  cowriteCalls = 0;
  vm.runInContext('touch()', sandbox);
  await fireTimer();
  await new Promise(r => process.nextTick(r));
  ok(cowriteCalls === 0, '句中停顿 → 不打扰（没有发伴写请求）');
  ok(liveTimers().length === 1, '但会再探一次（等它可能变成"卡住"）');
  ok(liveTimers()[0] && liveTimers()[0].ms === 20000,
     '复探间隔取自该状态的建议延迟（CODING 20 秒，不再是写死的 15）');
  console.log('\n【4】注意力说「不说」（REVIEWING 终止态）→ 就此安静，不再探');
  ATTN = { available: true, speak: false, state: 'REVIEWING', name: '在通读', delay_sec: 0 };
  setPara('第三段，换一段新的。');
  vm.runInContext('touch()', sandbox);
  await fireTimer();
  await new Promise(r => process.nextTick(r));
  ok(liveTimers().length === 0, '通读态不重探（再等也没用，等下一次动静）');

  console.log('\n【5】v3 未启用（available:false）→ 保持旧行为，直接出声');
  ATTN = { available: false, speak: true, delay_sec: 8 };
  cowriteCalls = 0;
  setPara('第四段，再换一段新的文本。');
  vm.runInContext('touch()', sandbox);
  await fireTimer();
  await new Promise(r => process.nextTick(r));
  ok(cowriteCalls === 1, '拿不到注意力结论时照常出声（向后兼容）');

  console.log('\n【6】说话状态也要够到它自己的建议延迟（POLISHING 15 秒）');
  ATTN = { available: true, speak: true, state: 'POLISHING', name: '在打磨',
           delay_sec: 15, signals: { pause_ms: 6000 } };
  cowriteCalls = 0;
  setPara('第五段，换一段新文本。');
  vm.runInContext('touch()', sandbox);
  await fireTimer();
  await new Promise(r => process.nextTick(r));
  ok(cowriteCalls === 0, '只停了 6 秒、不到 POLISHING 的 15 秒 → 先不出声');
  ok(liveTimers().length === 1 && Math.abs(liveTimers()[0].ms - 9000) < 1,
     '补齐差额再探（15000 - 6000 = 9000ms）');
  ATTN = { available: true, speak: true, state: 'POLISHING', name: '在打磨',
           delay_sec: 15, signals: { pause_ms: 15000 } };
  cowriteCalls = 0;
  await fireTimer();
  await new Promise(r => process.nextTick(r));
  ok(cowriteCalls === 1, '停够了 15 秒 → 出声');

  console.log('\n' + (fails ? '✗ 失败 ' + fails + ' 项' : '全部通过'));
  process.exit(fails ? 1 : 0);
}
main();

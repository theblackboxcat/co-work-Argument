/*!
 * heading-core.test.js — heading-core.js 的 Node 单测（零第三方依赖）
 *
 * 跑法（在项目根目录，或任何目录）：
 *     node web/tests/heading-core.test.js
 * 退出码 0 = 全过，1 = 有失败。没有 package.json、没有测试框架，只用 node:assert。
 *
 * 为什么必须能在 Node 里裸跑：验收 A1–A3 的实质不是「文件里没有那几个字符串」，
 * 而是「这个模块能被 require 进来跑单测，不需要 jsdom、不需要浏览器」。
 * 它同时被 P1（我的目录面板）和 P2（lucy 的甲档打包器）依赖，是最需要单测的一块。
 *
 * 覆盖的裁定与验收编号：
 *   A1/A2/A3 · grep 门禁（PRD §6.1 / TC-4）        → 见「组 1」
 *   A4       · epub-core 导出清单不得缩水          → 见「组 2」
 *   A5       · B5：data-id 不得被当成真 id         → 见「组 4」
 *   A6/B1    · nextIndex 逐章累加、保留 id 不占号   → 见「组 5」
 *   T-9a     · 甲档三章全局编号连续无重复          → 见「组 5」
 *   T-16     · 候选 E 的三类行为变更面             → 见「组 4」
 *   T-KL1    · [^>]* 截断现状锁（KL-9，本轮不修）   → 见「组 7」
 *   KL-8     · id="" 本轮不修                      → 见「组 4」
 *   KL-10    · decodeEntities 双解码现状锁          → 见「组 7」
 *   R33      · 检测与提取同为大小写敏感            → 见「组 3」n09
 *   R40      · attrMap 只解析一次、不拆成两个函数   → 见「组 8」
 *   R42/L10(c)· 面板与甲档吃逐字节相同的字符串      → 见「组 6」
 *   14 例真值表（lucy 用 Python html.parser 做独立裁判跑出来的那张，
 *   nat 在 R32 用它把 B5 的修法从 B 改判为 E）    → 见「组 4」
 *
 * 版本：1.0.0 · 2026-09-18 · owner: tom
 */

'use strict';

var assert = require('node:assert/strict');
var fs = require('node:fs');
var path = require('node:path');
var vm = require('node:vm');

var DIST = path.join(__dirname, '..', 'dist');
var LIB = path.join(__dirname, '..', 'lib');

var HC = require(path.join(DIST, 'heading-core.js'));

/* ------------------------------------------------------------------ *
 * 载入 epub-core 只为拿 sanitizeHtml（A5 要求输入先过它）。
 * 它的 UMD 在 CommonJS 下走 require('jszip')，本机没有 node_modules，
 * 所以用 vm 造一个「浏览器形状」的沙箱：module 未定义、JSZip 已就位，
 * 它就会走 else 分支 global.EpubCore = factory(global.JSZip, global.HeadingCore)。
 * B5(E) 迁移之后它多要一个 HeadingCore（浏览器侧靠 <script> 顺序保证），
 * 沙箱里必须手动挂 —— withHC=false 是用来测那条加载时守卫的。
 * ------------------------------------------------------------------ */
function loadEpubCore(withHC) {
  var sandbox = {};
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.JSZip = require(path.join(LIB, 'jszip.min.js'));
  if (withHC !== false) sandbox.HeadingCore = HC;
  sandbox.console = console;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(DIST, 'epub-core.js'), 'utf8'), sandbox, {
    filename: 'epub-core.js'
  });
  if (!sandbox.EpubCore) throw new Error('epub-core 未在沙箱里挂上 EpubCore');
  return sandbox.EpubCore;
}
var EC = loadEpubCore();

/* A5：单测输入必须先过 sanitizeHtml 再进 ensureHeadingIds —— 线上就是这个顺序
   （epub-core.js:431 的 clean 已是 sanitize 后的串）。跳过它测的就不是线上路径。 */
function S(html) { return EC.sanitizeHtml(html); }

/* ============================ 微型测试框架 ============================ */
var cases = [];
var group = '(未分组)';
function describe(name) { group = name; }
function test(name, fn) { cases.push({ group: group, name: name, fn: fn }); }

function run() {
  var pass = 0, fail = 0, last = null, failures = [];
  for (var i = 0; i < cases.length; i++) {
    var c = cases[i];
    if (c.group !== last) { console.log('\n■ ' + c.group); last = c.group; }
    try {
      c.fn();
      pass++;
      console.log('  ✓ ' + c.name);
    } catch (e) {
      fail++;
      failures.push({ c: c, e: e });
      console.log('  ✗ ' + c.name);
    }
  }
  console.log('\n──────────────────────────────────────────');
  console.log('合计 ' + cases.length + ' 例：通过 ' + pass + '，失败 ' + fail);
  if (fail) {
    console.log('\n失败详情：');
    failures.forEach(function (f) {
      console.log('\n[' + f.c.group + '] ' + f.c.name);
      console.log('  ' + (f.e && f.e.message ? f.e.message : f.e));
    });
    process.exit(1);
  }
  console.log('全过。');
  process.exit(0);
}

/* 数一个开标签里**顶层** id 属性出现了几次（用于「不得补出第二个 id」这类断言）。
   🔴 这里不能用正则数 —— 我的第一版写的是 /(?:^|[\s"'/])id\s*=/gi，它当场掉进了
   B5 自己要抓的那个坑，两处都错：
     · class="id=5"  引号后面紧跟 id= → 被数成一个 id 属性（其实它在**值里面**）
     · ID="aa"       i 标志让 XML 里两个不同属性看起来相等
   所以改用「引号状态机」：只在引号外、且属性名左侧是空白/串首时才计数，
   并且**大小写敏感**。它与被测的 attrMap 是两套不同算法（状态机 vs 名值分词），
   这样才是独立裁判，而不是拿被测代码自证。 */
function countIdAttrs(openTag) {
  var s = String(openTag);
  var i = s.indexOf('<');
  if (i >= 0) s = s.slice(i + 1);            /* 去掉标签名起始的 < */
  var gt = -1, q = '';
  for (var k = 0; k < s.length; k++) {        /* 找到引号外的那个 > */
    var ch = s.charAt(k);
    if (q) { if (ch === q) q = ''; continue; }
    if (ch === '"' || ch === "'") { q = ch; continue; }
    if (ch === '>') { gt = k; break; }
  }
  if (gt >= 0) s = s.slice(0, gt);
  /* 左边界规则：串首 / 空白 / 斜杠 / **闭合引号之后**。最后一条是 HTML5 允许的
     「引号属性值后省略空白」，也正是 n04 那个用例 —— 少了它就会把 class="x"id="aa"
     数成 0 个 id（而真实是 1 个）。 */
  var count = 0, inQ = '', atBoundary = true;
  for (var j = 0; j < s.length; j++) {
    var c = s.charAt(j);
    if (inQ) { if (c === inQ) { inQ = ''; atBoundary = true; } continue; }
    if (c === '"' || c === "'") { inQ = c; atBoundary = false; continue; }
    if (/\s/.test(c) || c === '/') { atBoundary = true; continue; }
    if (atBoundary && c === 'i' && /^id\s*=/.test(s.slice(j))) count++;
    atBoundary = false;
  }
  return count;
}
/* 取开标签。同样必须引号感知：indexOf('>') 会在值里的 > 处切错（KL-9 那几例）。 */
function openTagOf(html) {
  var s = String(html), q = '';
  for (var i = 0; i < s.length; i++) {
    var c = s.charAt(i);
    if (q) { if (c === q) q = ''; continue; }
    if (c === '"' || c === "'") { q = c; continue; }
    if (c === '>') return s.slice(0, i + 1);
  }
  return s;
}

/* ============================ 组 1：A1/A2/A3 grep 门禁 ============================ */
describe('组 1 · A1/A2/A3 — grep 门禁（PRD §6.1 / TC-4）');

var SRC = fs.readFileSync(path.join(DIST, 'heading-core.js'), 'utf8');

/* 🔴 这里曾经记着一条判据冲突（方案 §2.6 的 A3 原文要 `window.` = 1，而 PRD §6.1 / TC-4 要 = 0）。
   **冲突已消失，是我自己那条写错了**：方案 §2.6 已在 v4.1 更正为 `window.` = 0。
   原 A3 与它**自己的立法理由**互相矛盾 —— A1–A3 的实质是「模块必须能被 Node 直接 require」，
   而一处 `window.HeadingCore = …` 的出口正好会让 require 抛 `window is not defined`。
   所以本模块的宿主出口用 globalThis，四个禁用串全部断言 0。
   这条测试留着的意义是**机械护栏**：若有人把 window. 加回来，这里会红。 */
['JSZip', 'document', 'Quill', 'window.'].forEach(function (bad) {
  test('A1/A2/A3：源码里 "' + bad + '" 命中数为 0（连注释一起算）', function () {
    var n = SRC.split(bad).length - 1;
    assert.equal(n, 0, '命中 ' + n + ' 次');
  });
});

test('A1–A3 的实质：模块能被 require 且导出形状完整', function () {
  assert.equal(HC.VERSION, '1.0.0');
  assert.equal(HC.DEFAULT_PREFIX, 'eebk');
  ['attrMap', 'decodeEntities', 'headingsFromHtml', 'ensureHeadingIds',
   'nestHeadings', 'anchorOf'].forEach(function (k) {
    assert.equal(typeof HC[k], 'function', k + ' 不是函数');
  });
});

test('R40：不得把「检测」与「提取」暴露成两个函数', function () {
  /* attrMap 是唯一入口；不存在 hasId/detectId/extractId/getIdOf 这类第二入口 */
  Object.keys(HC).forEach(function (k) {
    assert.ok(!/^(has|detect|extract|get).*[Ii]d/.test(k), '出现了第二个属性入口：' + k);
  });
  assert.equal(typeof HC.attrMap, 'function');
});

/* ============================ 组 2：A4 epub-core 导出清单 ============================ */
describe('组 2 · A4 — epub-core.js 导出清单不得缩水');

/* 迁移前（基线 da22c15）的 18 个键。改成 re-export 之后键数不得减少 ——
   lucy 的甲档打包器与 exportEpub 都消费这个清单，缩水会静默打断 P2。 */
var BASELINE_KEYS = ['MIME_EPUB', 'parseXml', 'parseBook', 'loadChapter', 'restoreChapter',
  'exportEpub', 'exportHtml', 'buildNavXhtml', 'buildNcx', 'headingsFromHtml',
  'sanitizeHtml', 'resolvePath', 'normPath', 'findZipEntry', 'entryText',
  'entryBytes', 'flattenToc', 'decodeEntities'];

test('A4：18 个基线键一个都不能少', function () {
  var missing = BASELINE_KEYS.filter(function (k) { return !(k in EC); });
  assert.deepEqual(missing, [], '缺少：' + missing.join(', '));
  assert.ok(Object.keys(EC).length >= BASELINE_KEYS.length,
    '键数 ' + Object.keys(EC).length + ' < ' + BASELINE_KEYS.length);
});

test('A4：headingsFromHtml 迁移后仍可用，且与 heading-core 结论一致', function () {
  var html = S('<h1 data-id="x">第一章</h1><h2 id="ok">1.1</h2>');
  var mine = HC.headingsFromHtml(html);
  /* 迁移完成后这一行会变成「epub-core 的 re-export 等于 heading-core 的实现」；
     迁移之前它记录的是**旧实现的缺陷**，所以两条断言分开写。 */
  if (EC.headingsFromHtml === HC.headingsFromHtml) {
    assert.deepEqual(EC.headingsFromHtml(html), mine, 're-export 后必须逐字节同结果');
  } else {
    /* 现状锁：旧 :193 的 /id\s*=\s*(...)/ 没有属性名左边界，会从 data-id="x" 里
       捞出幽灵 id "x"，而元素真实没有 id —— 这正是 B5（nav 指向不存在的片段，全程无报错）。
       heading-core 按候选 E 给出 ''（没有 id 属性就是空串，由 ensureHeadingIds 补号）。
       这一条在 epub-core 改成 re-export 之后会变红 —— 那是**期望的**变红，
       请把断言换成上面那支，不要为了让它绿而改 heading-core。 */
    assert.equal(EC.headingsFromHtml(html)[0].id, 'x', '旧实现的幽灵 id');
    assert.equal(mine[0].id, '', 'E：没有 id 属性 → 空串');
    assert.equal(mine[1].id, 'ok', '真 id 照常取出');
  }
});

/* ============================ 组 3：attrMap（R33/R40 的语法唯一来源） ============================ */
describe('组 3 · attrMap — 属性串解析（R33 三条冻结约束）');

test('基本：双引号取值', function () {
  assert.deepEqual(HC.attrMap(' id="aa"'), { id: 'aa' });
});
test('基本：单引号取值（R33 约束 2，两个引号分支都要留）', function () {
  assert.deepEqual(HC.attrMap(" id='aa'"), { id: 'aa' });
});
test('基本：无引号取值（R33 约束 3；n10 只有 E 过）', function () {
  assert.deepEqual(HC.attrMap(' id=aa'), { id: 'aa' });
});
test('基本：等号两侧任意空白', function () {
  assert.deepEqual(HC.attrMap(' id = "aa" '), { id: 'aa' });
});
test('基本：无值属性记为空串，不抛', function () {
  assert.deepEqual(HC.attrMap(' hidden'), { hidden: '' });
  assert.deepEqual(HC.attrMap(' hidden id="a"'), { hidden: '', id: 'a' });
});
test('基本：空串 / null / undefined 都返回空对象', function () {
  assert.deepEqual(HC.attrMap(''), {});
  assert.deepEqual(HC.attrMap(null), {});
  assert.deepEqual(HC.attrMap(undefined), {});
});

test('🔴 R33 约束 1：属性名大小写原样保留，绝不 toLowerCase', function () {
  var m = HC.attrMap(' ID="aa"');
  assert.deepEqual(m, { ID: 'aa' });
  assert.equal('id' in m, false, 'ID 不得被归一成 id');
});

test('🔴 HTML5：引号属性值后可以省略空白（n04 的决定性语法）', function () {
  assert.deepEqual(HC.attrMap(' class="x"id="aa"'), { class: 'x', id: 'aa' });
  assert.deepEqual(HC.attrMap(' data-x="1"id="y"class="z"'),
    { 'data-x': '1', id: 'y', class: 'z' });
});

test('🔴 HTML5：重复属性第一个胜出', function () {
  assert.deepEqual(HC.attrMap(' id="aa" id="bb"'), { id: 'aa' });
});

test('未闭合的引号吃到串尾，不抛异常（导入的 epub 可能有残缺标记）', function () {
  assert.deepEqual(HC.attrMap(' id="aa'), { id: 'aa' });
  assert.deepEqual(HC.attrMap(" id='aa"), { id: 'aa' });
});

test('自闭合斜杠不得变成一个叫 "/" 的属性名', function () {
  /* 这是我这版字符扫描器比 lucy 原提议的正则版更严的一处：
     正则版的 ([^\s=]+) 会把 "<h1 id="a"/" 里那个 / 收成一个属性名。
     / 是标签语法的一部分，不是属性名。 */
  var m = HC.attrMap(' id="a"/');
  assert.deepEqual(m, { id: 'a' });
  assert.equal('/' in m, false);
});

test('属性值里的 id= 不得被当成属性（n08/n12）', function () {
  assert.equal('id' in HC.attrMap(' class="id=5"'), false);
  assert.equal('id' in HC.attrMap(' title="id=5"'), false);
  assert.deepEqual(HC.attrMap(' class="id=5"'), { class: 'id=5' });
});

test('近似名不得被当成 id（n05 data-id / n06 xid / aria-labelledby）', function () {
  [' data-id="5"', ' xid="7"', ' data-xid="7"', ' aria-labelledby="foo"'].forEach(function (a) {
    assert.equal('id' in HC.attrMap(a), false, a + ' 被误判成有 id');
  });
});

test('不会死循环：畸形串也在有限步内返回', function () {
  ['===', ' = ', 'a=', '=b', '"', "'", '/ / /', 'id=', '\t\n ', 'ididid'].forEach(function (a) {
    assert.equal(typeof HC.attrMap(a), 'object', JSON.stringify(a) + ' 未返回');
  });
});

/* ============================ 组 4：14 例真值表 + T-16 + KL-8 ============================ */
describe('组 4 · 14 例真值表（R32 改判 E 的依据）+ T-16 + A5 + KL-8');

/* 14 例真值表。⚠️ 编号 provenance 要说清，别当成 nat R32 那张表的逐行复刻：
   lucy §7.2 与 nat R32 的编号**互相冲突**（lucy 的 n10 = 单引号，nat 的 n10 = 无引号），
   而 n12（title="id=5"）是**我自己加的**，不在 nat 的 14 例里。
   下面沿用的是 nat R32 的编号，n01/n02/n03/n07/n12/n13 由我补齐。

   🔬 已执行的对照组（自规第七条要求的「附一次已执行的对照」，我跑了）：
   把 A（现行 :432+:193）、B（nat R23 的两行 (?:^|\s)）、E（本模块，**真模块不是转录**）
   三个候选各按 R32 的方法学更正**同时替换检测与提取两处**，跑全部 14 例，
   并用**两个独立裁判**判定：Python html.parser（lucy 用的那个）与 xml.etree（expat）。
   结果：**剔除 n09 与 n12 之后，A = 5 死锚点 / B = 3 / E = 1（只剩 n11）—— 与 nat R32 逐条吻合。**
   致命 dupId 同样吻合（A=1 / B=2 / E=1*，* = n14）。E 的实现复现了 R32 的改判依据。

   🔴 但对照组查出三件 R32 没说到的事，**都不改判，只改理由**（已报 nat）：

   1. **n04 / n10 / n14 的输入本身就不是合法 XML。** XML 要求属性之间必须有空白，
      而 HTML5 允许引号值后省略；无引号取值也是 HTML-only。实测：
        · n04 `<h1 class="x"id="aa">` → expat 报 not well-formed，column 13（正是那个 id）
        · n10 `<h1 id=aa>`            → expat 报 not well-formed，column 7
        · n14 `<h1 id="aa" id="bb">`  → expat 报 duplicate attribute
      所以这三例**只在 HTML 解析器下才有区分力**；在 XML 下三个候选同挂。
      → nat R32 那句「XML 侧则是重复属性致命」**把输入的致命算到了 B 头上**：
        B 补不补号，那本书在严格阅读器里都打不开。B 的真实危害是 HTML 侧的死锚点。
      → 连带 lucy 的可达性论证要收窄：**合规的 EPUB 不可能含 n04/n10 这两种写法**，
        所以可达面只剩「读者用 HTML 解析器容忍的非合规 EPUB」与客户端其它导入路径。

   2. **html.parser 会把属性名折成小写**（实测 `ID="aa"` 被它看成 `id="aa"`），
      所以它**无权裁决 n09** —— lucy 的表与 nat 的复跑都继承了这个盲区。
      n09 必须按 XML 语义判：`<h1 ID="aa" id="eebk-1">` 在 XML 下是**两个不同属性、合法**，
      expat 实测通过，nav 指 eebk-1 → **活锚点**。这正是 R33 冻结「attrMap 不转小写」的依据，
      已执行确认。

   3. 🔴 **n09 的正确性与解析器有关，这是一个无法两全的残留**：XML 下 E 对；
      HTML 下 `ID` 折成 `id` → 与补出来的 id 重名 → 第一个胜出 = aa，而 nav 指 eebk-1 → 死锚点。
      三个候选在这一例上行为完全相同，所以它**不是区分项**；但它是 R33 那条冻结约束的
      固有代价（要同时满足两种解析器就得知道读者用哪个，做不到）。
      → 建议记一条新 KL，不在本轮修。

   real = 规范级 tokenizer 认定的元素真实 id；期望 E 的 nav 与它对齐（无死锚点）。
   n11/n14 是全候选皆挂的两例，分别落 KL-8 / KL-7，本轮不修，只锁行为。 */
var TRUTH = [
  /* n, 属性串, 期望 heading.id, 期望是否补号, 备注 */
  ['n01', '', 'eebk-1', true, '没有属性'],
  ['n02', ' class="a"', 'eebk-1', true, '只有 class'],
  ['n03', ' id="aa"', 'aa', false, '标准双引号'],
  ['n04', ' class="x"id="aa"', 'aa', false, '🔴 引号后省空白；B 在这里补出第二个 id → XHTML 致命'],
  ['n05', ' data-id="5"', 'eebk-1', true, '🔴 A5：近似名；旧 :193 会提出幽灵 id "5"'],
  ['n06', ' xid="7"', 'eebk-1', true, '近似名（后缀）'],
  ['n07', ' id = "aa"', 'aa', false, '等号两侧多空白'],
  ['n08', ' class="id=5"', 'eebk-1', true, '值里含 id='],
  ['n09', ' ID="aa"', 'eebk-1', true, '🔴 R33：大小写敏感，ID 不是 id；补号后 nav 指 eebk-1，锚点是活的'],
  ['n10', ' id=aa', 'aa', false, '🔴 无引号；A/B 在这一例都是死锚点，只有 E 过'],
  ['n11', ' id=""', '', false, 'KL-8：有属性但值为空，A/B/E 全挂，本轮不修'],
  ['n12', ' title="id=5"', 'eebk-1', true, '值里含 id=（另一个属性名）'],
  ['n13', " id='aa'", 'aa', false, '🔴 R33 约束 2：单引号分支必须留'],
  ['n14', ' id="aa" id="bb"', 'aa', false, 'KL-7：输入本身已是无效 XHTML，heading-core 不负责修，只保证不添第三个']
];

TRUTH.forEach(function (row) {
  var n = row[0], attrs = row[1], wantId = row[2], wantAppended = row[3], note = row[4];
  test(n + '：<h1' + attrs + '> → id="' + wantId + '"' + (wantAppended ? '（补号）' : '（原样）') + ' · ' + note, function () {
    var input = S('<h1' + attrs + '>第一章</h1>');
    var r = HC.ensureHeadingIds(input);
    assert.equal(r.headings.length, 1);
    assert.equal(r.headings[0].id, wantId, 'heading.id 不对');
    assert.equal(r.headings[0].level, 1);
    assert.equal(r.headings[0].text, '第一章');
    assert.equal(r.nextIndex, wantAppended ? 2 : 1, 'nextIndex 不对（保留 id 不占号）');

    var tag = openTagOf(r.html);
    /* 死锚点的机械判据：nav 会写 '#' + heading.id，所以产物里必须真有那个片段。
       id 为空时（n11）无法校验，那是 KL-8 的已知残留。 */
    if (wantId) {
      assert.equal(new RegExp('\\bid\\s*=\\s*["\']?' + wantId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '["\']?\\b')
        .test(r.html), true, '产物里没有 id=' + wantId + '，nav 会指向不存在的片段（死锚点）');
    }
    if (!wantAppended) {
      assert.equal(r.html, input, '不该补号时产物必须逐字节等于输入');
      assert.ok(countIdAttrs(tag) <= (n === 'n14' ? 2 : 1),
        'n=' + n + ' 产物里 id 属性数 = ' + countIdAttrs(tag) + '，E 不得新增 id 属性');
    } else {
      assert.equal(countIdAttrs(tag), 1, '补号后必须恰好 1 个 id 属性，实得 ' + tag);
    }
  });
});

test('A5（nat 已采纳的验收）：<h1 data-id="x">第一章</h1><h2>1.1</h2>', function () {
  var r = HC.ensureHeadingIds(S('<h1 data-id="x">第一章</h1><h2>1.1</h2>'));
  assert.deepEqual(r.headings.map(function (h) { return h.id; }), ['eebk-1', 'eebk-2']);
  assert.deepEqual(r.headings.map(function (h) { return h.level; }), [1, 2]);
  assert.deepEqual(r.headings.map(function (h) { return h.text; }), ['第一章', '1.1']);
  assert.equal(r.headings.some(function (h) { return h.id === 'x' || h.id === ''; }), false,
    '没有任何一项的 id 可以是 x 或空串');
  assert.equal(r.nextIndex, 3);
});

test('A5 附：U-7 那一类（无引号 id）检测与提取结论必须一致，不得是空锚点', function () {
  var r = HC.ensureHeadingIds(S('<h1 id=x>t</h1>'));
  assert.equal(r.headings[0].id, 'x', 'id 不得为空串');
  assert.equal(r.html, S('<h1 id=x>t</h1>'), '已检测到 id，不得补号');
  assert.equal(HC.anchorOf(r.headings[0], 'chap.xhtml'), 'chap.xhtml#x');
});

test('T-16 ①：引号值后省空白 → 检测到 id、不补新 id、产物里 id 属性数 == 1', function () {
  var input = S('<h1 a="1"id="2">x</h1>');
  var r = HC.ensureHeadingIds(input);
  assert.equal(r.headings[0].id, '2');
  assert.equal(r.html, input, '不得改动一个字节');
  assert.equal(countIdAttrs(openTagOf(r.html)), 1,
    '旧正则会补出第二个 id → XHTML 解析失败、整本 epub 打不开');
});

test('T-16 ②：大写 ID → 不当作 id（大小写敏感，绝不 toLowerCase）', function () {
  var r = HC.ensureHeadingIds(S('<h1 ID="x">x</h1>'));
  assert.equal(r.headings[0].id, 'eebk-1', '补号必须发生');
  assert.equal(openTagOf(r.html), '<h1 ID="x" id="eebk-1">',
    'XML 里 ID 与 id 是两个不同属性，合法；nav 指 eebk-1，锚点是活的');
});

test('T-16 ③：无引号 id → 检测与提取结论一致，不出现「检测说有、提取说空」', function () {
  var r = HC.ensureHeadingIds(S('<h1 id=x>x</h1>'));
  assert.equal(r.headings[0].id, 'x');
  assert.notEqual(r.headings[0].id, '', '空锚点');
});

test('KL-8：id="" 本轮不修 —— 锁住「不补号 + 报空 id」这个已知残留', function () {
  var input = S('<h1 id="">x</h1>');
  var r = HC.ensureHeadingIds(input);
  assert.equal(r.html, input, '不补号（补了就是重复 id，更坏）');
  assert.equal(r.headings[0].id, '', 'A/B/E 在这一例全挂；真要修得就地改写空值，那是第三种行为');
  assert.equal(r.nextIndex, 1, '不占号');
  /* 同时锁住只读扫描的一致性：面板不会因为走了另一个函数就给出不同答案 */
  assert.deepEqual(HC.headingsFromHtml(input), r.headings);
});

test('KL-7：重复 id 属性不由 heading-core 处置，只保证不添第三个', function () {
  var input = S('<h1 id="aa" id="bb">x</h1>');
  var r = HC.ensureHeadingIds(input);
  assert.equal(r.html, input);
  assert.equal(countIdAttrs(openTagOf(r.html)), 2, '产物仍是两个 id，仍是坏的，但不是 E 造成的');
});

/* ============================ 组 5：A6 / B1 / T-9a ============================ */
describe('组 5 · A6（B1 的 nextIndex）+ T-9a（甲档三章全局连续）');

test('A6：一章内 1 个原有 id="eebk-3" + 1 个无 id，startIndex=1 → nextIndex === 2', function () {
  var r = HC.ensureHeadingIds(S('<h1 id="eebk-3">原有</h1><h2>新来的</h2>'), { startIndex: 1 });
  assert.equal(r.nextIndex, 2, '不是 3、不是 4 —— 保留原 id 的标题不占号');
  assert.deepEqual(r.headings.map(function (h) { return h.id; }), ['eebk-3', 'eebk-1']);
});

test('A6：opts 缺省 / 非法 startIndex 一律回到 1', function () {
  var html = S('<h1>a</h1>');
  assert.equal(HC.ensureHeadingIds(html).nextIndex, 2);
  assert.equal(HC.ensureHeadingIds(html, {}).nextIndex, 2);
  assert.equal(HC.ensureHeadingIds(html, { startIndex: 'abc' }).nextIndex, 2, 'NaN → 1');
  assert.equal(HC.ensureHeadingIds(html, { startIndex: -5 }).nextIndex, 2, '负数 → 1');
  assert.equal(HC.ensureHeadingIds(html, { startIndex: null }).nextIndex, 2);
  assert.equal(HC.ensureHeadingIds(html, { prefix: '' }).headings[0].id, 'eebk-1', '空前缀 → 默认');
  assert.equal(HC.ensureHeadingIds(html, { prefix: null }).headings[0].id, 'eebk-1');
});

test('A6：startIndex=0 是合法的（从 0 开始编号）', function () {
  var r = HC.ensureHeadingIds(S('<h1>a</h1>'), { startIndex: 0 });
  assert.equal(r.headings[0].id, 'eebk-0');
  assert.equal(r.nextIndex, 1);
});

test('A6：自定义前缀', function () {
  var r = HC.ensureHeadingIds(S('<h1>a</h1><h1>b</h1>'), { prefix: 'sec', startIndex: 7 });
  assert.deepEqual(r.headings.map(function (h) { return h.id; }), ['sec-7', 'sec-8']);
  assert.equal(r.nextIndex, 9);
});

test('T-9a：甲档按 h1 切章 + 累加器 → c1:1,2 / c2:3,4,5 / c3:6，全局连续无重复', function () {
  /* lucy seq=43 的实测样例。这是 L10(c) 的正向断言：甲档从零产物必须逐条对齐面板。 */
  var chapters = [
    S('<h1>卷一</h1><h2>第一章</h2>'),
    S('<h1>卷二</h1><h2>第二章</h2><h3>2.1</h3>'),
    S('<h1>卷三</h1>')
  ];
  var want = [['eebk-1', 'eebk-2'], ['eebk-3', 'eebk-4', 'eebk-5'], ['eebk-6']];
  var cursor = 1, all = [];
  chapters.forEach(function (c, i) {
    var r = HC.ensureHeadingIds(c, { startIndex: cursor });
    cursor = r.nextIndex;
    assert.deepEqual(r.headings.map(function (h) { return h.id; }), want[i], '第 ' + (i + 1) + ' 章编号不对');
    all = all.concat(r.headings.map(function (h) { return h.id; }));
    /* 甲档产物里 nav 的 href 形如 cN.xhtml#eebk-M */
    assert.deepEqual(r.headings.map(function (h) { return HC.anchorOf(h, 'c' + (i + 1) + '.xhtml'); }),
      want[i].map(function (id) { return 'c' + (i + 1) + '.xhtml#' + id; }));
  });
  assert.equal(cursor, 7, '三章之后游标应停在 7');
  assert.deepEqual(all, ['eebk-1', 'eebk-2', 'eebk-3', 'eebk-4', 'eebk-5', 'eebk-6']);
  assert.equal(new Set(all).size, all.length, '全局编号有重复');
});

test('T-9a 反面：面板全文一次扫（startIndex=1）得到同一串编号', function () {
  /* L10(c) 的另一半：面板吃全文、甲档吃切章后的分片，两边算出来的 id 必须一模一样。 */
  var whole = S('<h1>卷一</h1><h2>第一章</h2><h1>卷二</h1><h2>第二章</h2><h3>2.1</h3><h1>卷三</h1>');
  var panel = HC.ensureHeadingIds(whole).headings.map(function (h) { return h.id; });
  assert.deepEqual(panel, ['eebk-1', 'eebk-2', 'eebk-3', 'eebk-4', 'eebk-5', 'eebk-6']);
});

/* ============================ 组 6：R42 / L10(c) 一致性 ============================ */
describe('组 6 · R42/L10(c) — 只读扫描与补号扫描必须同源');

var CONSISTENCY_INPUTS = [
  '<h1>a</h1>',
  '<h1 data-id="x">第一章</h1><h2>1.1</h2>',
  '<h1 class="x"id="aa">t</h1>',
  '<h1 id=x>t</h1>',
  "<h1 id='aa'>t</h1>",
  '<h1 ID="aa">t</h1>',
  '<h1 id="">t</h1>',
  '<h1 id="aa" id="bb">t</h1>',
  '<h2 class="id=5">t</h2>',
  '<H1>大写标签</H1>',
  '<h3><em>带内联标签</em>的标题</h3>',
  '<h1>实体&amp;与&nbsp;空白</h1>',
  '<p>没有标题</p>',
  ''
];

CONSISTENCY_INPUTS.forEach(function (raw, i) {
  test('L10(c) #' + (i + 1) + '：headingsFromHtml(ensureHeadingIds(x).html) === ensureHeadingIds(x).headings', function () {
    var input = S(raw);
    var r = HC.ensureHeadingIds(input);
    assert.deepEqual(HC.headingsFromHtml(r.html), r.headings,
      '两个入口在同一份产物上给出了不同的目录 —— 面板与 nav 会不一致');
  });
});

test('L10(c)：幂等 —— 对补过号的产物再补一次，一个字节都不变', function () {
  var once = HC.ensureHeadingIds(S('<h1>a</h1><h2>b</h2>'));
  var twice = HC.ensureHeadingIds(once.html);
  assert.equal(twice.html, once.html, '第二次不得改动产物');
  assert.deepEqual(twice.headings, once.headings);
  assert.equal(twice.nextIndex, 1, '没有新分配的 id');
});

test('不共用模块级 /g 正则：同一输入连调三次结果完全相同', function () {
  /* 共用带 lastIndex 的 /g 正则会表现为「同一个函数两次调用结果不同」。
     ⚠️ 注意 headingsFromHtml 与 ensureHeadingIds 的结果**本来就该不同**
     （前者不补号、后者补号），所以只能各自与自己的第二次调用比，
     跨函数比要走「补号后的产物」那一步（组 6 的 L10(c) 已经覆盖）。 */
  var html = S('<h1>a</h1><h2>b</h2><h3>c</h3>');
  var a = HC.headingsFromHtml(html);
  var b = HC.headingsFromHtml(html);
  assert.deepEqual(a, b, 'headingsFromHtml 两次调用结果不同 → 疑似共用 lastIndex');
  assert.equal(a.length, 3);
  assert.deepEqual(a.map(function (h) { return h.id; }), ['', '', ''], '只读扫描不补号');

  var e1 = HC.ensureHeadingIds(html);
  var e2 = HC.ensureHeadingIds(html);
  assert.deepEqual(e1, e2, 'ensureHeadingIds 两次调用结果不同 → 疑似共用 lastIndex');
  assert.deepEqual(e1.headings.map(function (h) { return h.id; }), ['eebk-1', 'eebk-2', 'eebk-3']);

  /* 交替调用也不得互相污染 */
  HC.headingsFromHtml(html);
  var e3 = HC.ensureHeadingIds(html);
  HC.headingsFromHtml(html);
  assert.deepEqual(e3.headings, e1.headings);
  assert.deepEqual(HC.headingsFromHtml(e1.html), e1.headings);
});

test('headings 里的 id 恒为字符串，JSON.stringify 不会静默丢字段', function () {
  var r = HC.ensureHeadingIds(S('<h1>a</h1>'));
  var h = HC.headingsFromHtml(S('<h1>a</h1>'))[0];
  assert.equal(typeof h.id, 'string');
  assert.equal(JSON.parse(JSON.stringify(h)).id, h.id);
  assert.equal(Object.keys(JSON.parse(JSON.stringify(r.headings[0]))).length, 3,
    'level/id/text 三个键都必须在 JSON 里活着');
  /* 没有 id 时是 ''，不是 undefined */
  assert.equal(HC.headingsFromHtml(S('<h1>a</h1>'))[0].id, '');
});

test('R42：heading-core 不做清洗 —— p.html 不过 sanitizeHtml 是裁定，不是遗漏', function () {
  /* 安全性依据是 Quill 的 formats 白名单（index.html:1878-1888，无 script/iframe/object/embed/image），
     不是 heading-core。这里锁住「heading-core 绝不改内容」这条边界：
     喂脏 html 进去，出来的还是那段脏 html（只多了 id 属性）。 */
  var dirty = '<h1 onclick="x()">t</h1>';
  var r = HC.ensureHeadingIds(dirty);   /* 故意不过 S() */
  assert.equal(r.html, '<h1 onclick="x()" id="eebk-1">t</h1>',
    'heading-core 越权清洗会破 L10(c)：面板与甲档必须吃逐字节相同的字符串');
});

/* ============================ 组 7：现状锁（KL-9 / KL-10） ============================ */
describe('组 7 · 现状锁 — KL-9（T-KL1）与 KL-10 都锁住不改');

test('T-KL1 ①：属性值里含 > 时开标签被截断（epub-core.js:431 的既有行为，本轮不修）', function () {
  var r = HC.ensureHeadingIds('<h1 id="a>b">x</h1>');
  /* [^>]* 在值里的 > 处停下，于是 "b">x" 被当成元素内容 */
  assert.equal(r.headings[0].text, 'b">x', '截断的可见症状必须保持不变');
});

test('T-KL1 ②：截断之后检测与提取仍然一致（这是 R32/R33 的裁定，不是静默变更）', function () {
  var r = HC.ensureHeadingIds('<h1 id="a>b">x</h1>');
  assert.equal(r.headings[0].id, 'a',
    '旧 :432 说「有 id」而旧 :193 提出空串 —— 那个自相矛盾正是 U-7 同族的死锚点，E 修掉的是它');
  assert.equal(r.html, '<h1 id="a>b">x</h1>', '不得补号');
  /* 诚实边界：这个输入在 XML 层本来就是致命错误（属性值未闭合），
     所以这里断言的不是「产物可用」，而是「行为可预期且两个入口同源」。 */
  assert.deepEqual(HC.headingsFromHtml(r.html), r.headings);
});

test('T-KL1 ③：将来谁修 [^>]* 截断，这条会变红 —— 这是现状锁的用途', function () {
  var r = HC.ensureHeadingIds('<h1 title="a>b" id="real">x</h1>');
  /* 今天：attrs 被截成 ' title="a'，id="real" 根本没进解析器 → 补出 eebk-1 */
  assert.equal(r.headings[0].id, 'eebk-1');
  assert.equal(r.headings[0].text, 'b" id="real">x');
});

test('KL-10：decodeEntities 是双解码，&amp;lt; 被解成 "<" 而不是字面的 &lt;', function () {
  assert.equal(HC.decodeEntities('&amp;lt;'), '<', '单遍解码会给 "&lt;"，那才是对的 —— 但本轮不修');
  assert.equal(HC.decodeEntities('&amp;'), '&');
  assert.equal(HC.decodeEntities('&nbsp;'), ' ');
  assert.equal(HC.decodeEntities('&quot;'), '"');
  assert.equal(HC.decodeEntities('&#39;'), "'");
  assert.equal(HC.decodeEntities('&#65;'), 'A');
  assert.equal(HC.decodeEntities('&#x41;'), 'A');
  /* 与 epub-core 的同名函数逐字等价（迁移不得改变已上线的解码行为） */
  ['&amp;lt;', '&amp;', '&lt;', '&gt;', '&quot;', '&#39;', '&#x4e2d;', '&#20013;', 'a&nbsp;b']
    .forEach(function (s) {
      assert.equal(HC.decodeEntities(s), EC.decodeEntities(s), s + ' 与 epub-core 不一致');
    });
});

test('cleanText：剥内联标签成空格、压空白、去首尾（与 epub-core.js:194 同形）', function () {
  var r = HC.ensureHeadingIds(S('<h2><em>带</em>内联<span>标签</span>的标题</h2>'));
  assert.equal(r.headings[0].text, '带 内联 标签 的标题');
  var r2 = HC.ensureHeadingIds(S('<h1>  多个   空白\n和换行  </h1>'));
  assert.equal(r2.headings[0].text, '多个 空白 和换行');
});

/* ============================ 组 8：ensureHeadingIds 产物形状 ============================ */
describe('组 8 · ensureHeadingIds / headingsFromHtml 的产物形状');

test('只改写开标签：<H1>x</H1> 的大写闭标签必须原样保留（DV-7）', function () {
  /* 🔴 本条注释原先写的是「切片式写法与 epub-core 旧实现逐字等价」—— **实测证明说过头了**。
     旧实现（迁移前的 loadChapter）用 '<h' + level + attrs + ' id=…>' **重建开标签**，
     于是大写输入会变成：  <H1>x</H1>  →  <h1 id="eebk-1">x</H1>
     开标签被转小写、闭标签原样保留 = **开闭标签大小写不配对**，而 EPUB 内容文档是 XHTML，
     XML 没有错误恢复：expat 实测 `mismatched tag`，**致命解析错误**。
     本实现只切片插入 id、原样保留标签名大小写 → <H1 id="eebk-1">x</H1>，XML 解析通过。
     所以这一处**不是**逐字等价，而是**修掉了一个 XML 致命缺陷**。它超出 B5 的裁定范围，
     已作为 DV-7 报 nat 追认；可达性：只有「导入的 epub 章节里带大写标题标签」才走得到
     （Quill 的 getSemanticHTML 与甲档的输入都恒为小写）。 */
  var r = HC.ensureHeadingIds('<H1>x</H1>');
  assert.equal(r.html, '<H1 id="eebk-1">x</H1>');
  assert.equal(r.headings[0].level, 1);
  /* 对照：旧的重建式写法会给什么（钉在这里，免得将来有人"顺手统一"回去） */
  var old = '<H1>x</H1>'.replace(/<h([1-6])\b([^>]*)>/gi, function (whole, level, attrs) {
    return '<h' + level + attrs + ' id="eebk-1">';
  });
  assert.equal(old, '<h1 id="eebk-1">x</H1>', '旧写法的产物（大小写不配对）');
  assert.equal(old === r.html, false, '新旧在这一例上**故意**不同');
});

test('标签内换行：开标签长度算术仍然准确', function () {
  var r = HC.ensureHeadingIds('<h1\n class="a">x</h1>');
  assert.equal(r.html, '<h1\n class="a" id="eebk-1">x</h1>');
});

test('已有 id 的标签一个字节都不动（含属性顺序与引号风格）', function () {
  var input = S("<h3 class='c' id='k' data-z=\"1\">t</h3>");
  assert.equal(HC.ensureHeadingIds(input).html, input);
});

test('h1–h6 全部识别，h7 与 h0 不识别', function () {
  var r = HC.ensureHeadingIds(S('<h1>1</h1><h2>2</h2><h3>3</h3><h4>4</h4><h5>5</h5><h6>6</h6><h7>7</h7><h0>0</h0>'));
  assert.deepEqual(r.headings.map(function (h) { return h.level; }), [1, 2, 3, 4, 5, 6]);
  assert.equal(r.nextIndex, 7);
});

test('<header>/<hr> 等 h 开头的非标题标签不得被当成标题', function () {
  var r = HC.ensureHeadingIds(S('<header>x</header><hr><h1>真标题</h1>'));
  assert.equal(r.headings.length, 1);
  assert.equal(r.headings[0].text, '真标题');
  assert.equal(r.html.indexOf('<header'), 0, 'header 不得被改写');
});

test('未闭合的标题（没有 </h1>）不产出条目，也不抛', function () {
  var r = HC.ensureHeadingIds('<h1>没有闭标签');
  assert.deepEqual(r.headings, []);
  assert.equal(r.html, '<h1>没有闭标签');
  assert.equal(r.nextIndex, 1);
});

test('非标题内容逐字节不变', function () {
  var input = S('<p>正文</p><ul><li>a</li></ul>');
  var r = HC.ensureHeadingIds(input);
  assert.equal(r.html, input);
  assert.deepEqual(r.headings, []);
});

test('null / undefined / 非字符串输入不抛', function () {
  [null, undefined, '', 0, {}, []].forEach(function (v) {
    var r = HC.ensureHeadingIds(v);
    assert.deepEqual(r.headings, []);
    assert.equal(r.nextIndex, 1);
    assert.deepEqual(HC.headingsFromHtml(v), []);
  });
});

test('返回值形状固定为 { html, headings, nextIndex }，三个键都在', function () {
  var r = HC.ensureHeadingIds(S('<h1>a</h1>'));
  assert.deepEqual(Object.keys(r).sort(), ['headings', 'html', 'nextIndex']);
  assert.equal(typeof r.html, 'string');
  assert.ok(Array.isArray(r.headings));
  assert.equal(typeof r.nextIndex, 'number');
  assert.deepEqual(Object.keys(r.headings[0]).sort(), ['id', 'level', 'text']);
});

/* ============================ 组 9：nestHeadings / anchorOf ============================ */
describe('组 9 · nestHeadings（面板与 nav.xhtml 共用）+ anchorOf');

/* nestHeadings 靠 h.level 决定嵌套 —— 少了 level 全部退化成一条链。
   （我第一版的辅助函数就漏了它，于是「三级嵌套」那例**因为错误的原因通过了**，
   而「同级兄弟」那例失败。level 是必需入参，不是可选装饰。） */
function flat(level, text, href) { return { level: level, text: text, href: href }; }

test('节点形状必须是 { text, href, children } —— renderNestedOl 就按这三个键读', function () {
  var t = HC.nestHeadings([flat(1, 'a', '#a')]);
  assert.deepEqual(Object.keys(t[0]).sort(), ['children', 'href', 'text']);
  assert.equal('level' in t[0], false, '不得把 level 带进产物（epub-core.js:617 就没带）');
});

test('h1 > h2 > h3 三级嵌套', function () {
  var t = HC.nestHeadings([flat(1, '卷', '#1'), flat(2, '章', '#2'), flat(3, '节', '#3')]);
  assert.equal(t.length, 1);
  assert.equal(t[0].text, '卷');
  assert.equal(t[0].children[0].text, '章');
  assert.equal(t[0].children[0].children[0].text, '节');
  assert.deepEqual(t[0].children[0].children[0].children, []);
});

test('同级兄弟挂在同一个父下', function () {
  var t = HC.nestHeadings([flat(1, '卷', '#1'), flat(2, '章一', '#2'), flat(2, '章二', '#3')]);
  assert.equal(t[0].children.length, 2);
  assert.deepEqual(t[0].children.map(function (n) { return n.text; }), ['章一', '章二']);
});

test('跳级（h1 直接到 h3）不得凭空造出 h2 层', function () {
  var t = HC.nestHeadings([flat(1, '卷', '#1'), flat(3, '节', '#3')]);
  assert.equal(t[0].children.length, 1);
  assert.equal(t[0].children[0].text, '节');
});

test('回到上级：新的 h1 是根级兄弟，不是上一个 h1 的孩子', function () {
  var t = HC.nestHeadings([flat(1, '卷一', '#1'), flat(2, '章', '#2'), flat(1, '卷二', '#3')]);
  assert.equal(t.length, 2);
  assert.equal(t[1].text, '卷二');
  assert.deepEqual(t[1].children, []);
});

test('深层回退：h3 之后来 h1，中间的 h2/h3 层都要弹掉', function () {
  var t = HC.nestHeadings([flat(1, 'A', '#1'), flat(2, 'B', '#2'), flat(3, 'C', '#3'),
    flat(1, 'D', '#4'), flat(2, 'E', '#5')]);
  assert.equal(t.length, 2);
  assert.equal(t[0].children[0].children[0].text, 'C');
  assert.equal(t[1].children[0].text, 'E');
});

test('现状锁：缺 level 的入参退化成一条链（逐字迁移，不得「顺手修好」）', function () {
  /* 0 >= undefined 与 undefined >= undefined 都是 false，所以栈只增不减。
     这是 epub-core.js:612-622 今天的既有行为，真实调用方（:590/:598）永远带 level，
     所以不可达。锁住它，是为了让「迁移改变了行为」这件事立刻可见。 */
  var t = HC.nestHeadings([{ text: 'a', href: '#a' }, { text: 'b', href: '#b' }]);
  assert.equal(t.length, 1);
  assert.equal(t[0].children[0].text, 'b');
});

test('空列表返回空数组，不抛', function () {
  assert.deepEqual(HC.nestHeadings([]), []);
});

test('逐字迁移：nestHeadings 与 epub-core.js:612-622 的算法文本等价', function () {
  function bodyOf(src, name) {
    var i = src.indexOf('function ' + name + '(');
    if (i < 0) return null;
    var d = 0, j = src.indexOf('{', i);
    for (var k = j; k < src.length; k++) {
      if (src.charAt(k) === '{') d++;
      else if (src.charAt(k) === '}') { d--; if (!d) return src.slice(j, k + 1); }
    }
    return null;
  }
  function norm(s) { return s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s+/g, ' ').trim(); }
  var ecSrc = fs.readFileSync(path.join(DIST, 'epub-core.js'), 'utf8');
  var fromEc = bodyOf(ecSrc, 'nestHeadings');
  var fromHc = bodyOf(SRC, 'nestHeadings');
  assert.ok(fromHc, 'heading-core 里找不到 nestHeadings');
  if (fromEc) {
    assert.equal(norm(fromHc), norm(fromEc),
      '迁移不是逐字的 —— 两边嵌套规则一旦漂移，就会出现「面板上 h3 挂在 h1 下、epub 目录里挂在 h2 下」');
  } else {
    /* 迁移完成后 epub-core 里只剩一个**内部**委托别名。
       🔴 它故意**不进导出清单**：全仓没有外部消费者（buildNavXhtml 是内部调用），
       公开面越小越稳；而且导出清单归 lucy 否决，加键要先过她。
       所以这里断言源码层的委托，而不是断言 EC.nestHeadings 存在。 */
    assert.equal(/var nestHeadings = HeadingCore\.nestHeadings;/.test(ecSrc), true,
      'epub-core 里既没有本地 nestHeadings，也没有指向 HeadingCore 的委托别名');
    assert.equal(/function nestHeadings/.test(ecSrc), false,
      '还留着第二份函数体 —— 两份必然漂移');
  }
});

test('anchorOf：有 id 拼片段，无 id 返回裸 href（不返回 "#"）', function () {
  assert.equal(HC.anchorOf({ id: 'eebk-7' }, 'chap3.xhtml'), 'chap3.xhtml#eebk-7');
  assert.equal(HC.anchorOf({ id: '' }, 'chap3.xhtml'), 'chap3.xhtml',
    '空片段会让阅读器跳到文件开头，看起来像「链接坏了」而不是「没有锚点」');
  assert.equal(HC.anchorOf({}, 'chap3.xhtml'), 'chap3.xhtml');
  assert.equal(HC.anchorOf(null, 'chap3.xhtml'), 'chap3.xhtml');
  assert.equal(HC.anchorOf({ id: 'x' }, ''), '#x');
  assert.equal(HC.anchorOf({ id: 'x' }, null), '#x');
});

test('anchorOf 不做任何路径运算（relPath 留在 epub-core）', function () {
  assert.equal(HC.anchorOf({ id: 'x' }, '../Text/chap.xhtml'), '../Text/chap.xhtml#x');
});

/* ============================ 组 10：epub-core 迁移后的等价性 ============================ */
describe('组 10 · 迁移等价性 —— 换成 re-export 之后这些必须继续成立');

test('epub-core.flattenToc 消费的 flat 项形状与 anchorOf 的产物相容', function () {
  /* flattenToc(:715-734 导出) 吃的是 nav 解析结果，不吃 heading-core 的节点，
     这里只锁住「href 里带 # 片段」这个双方共识。 */
  var r = HC.ensureHeadingIds(S('<h1>卷</h1><h2>章</h2>'));
  var hrefs = r.headings.map(function (h) { return HC.anchorOf(h, 'c1.xhtml'); });
  assert.deepEqual(hrefs, ['c1.xhtml#eebk-1', 'c1.xhtml#eebk-2']);
  hrefs.forEach(function (h) {
    assert.equal(h.indexOf('#') > 0, true);
    assert.equal(h.split('#').length, 2, '恰好一个 #');
  });
});

test('headingsFromHtml 与 ensureHeadingIds 的 text 计算完全同源', function () {
  var html = S('<h1>  A  <em>B</em>  C&nbsp;D </h1>');
  assert.equal(HC.headingsFromHtml(html)[0].text, HC.ensureHeadingIds(html).headings[0].text);
});

/* ============================ 组 11：B5(E) 迁移落地后的 epub-core 侧回归 ============================ */
describe('组 11 · B5(E) 迁移 —— epub-core 侧落地回归（re-export / A4 / N4 / 加载守卫 / KL-1 冻结）');

var ECSRC = fs.readFileSync(path.join(DIST, 'epub-core.js'), 'utf8');

test('re-export：epub-core.headingsFromHtml 与 heading-core 是同一个函数对象', function () {
  /* 引用相等，不只是结果相等 —— 结果相等可能来自两份各自正确的实现，
     而 P-SINGLE 要的是**只有一份**。 */
  assert.equal(EC.headingsFromHtml === HC.headingsFromHtml, true,
    '不是同一个引用：epub-core 里还留着第二份属性取值语法');
});

test('B5：epub-core 源码里 id 正则命中数为 0（连注释一起算）', function () {
  /* 迁移前有【两处】：loadChapter 的检测（原 :432）与 headingsFromHtml 的提取（原 :193）。
     两处都必须消失 —— 只换一处正是自规 7 明令禁止的「半换」。
     注释里也不许留字面串，理由写在 epub-core 那段迁移注释里。 */
  var n = (ECSRC.match(/id\\s\*=/g) || []).length;
  assert.equal(n, 0, '还剩 ' + n + ' 处');
});

test('B5：两处缺陷点在 epub-core 侧都真的修好了（不是只在 heading-core 里对）', function () {
  var h = EC.headingsFromHtml(S('<h5 data-id="x">t</h5>'));
  assert.equal(h[0].id, '', 'data-id 仍被当成 id → 死锚点没修掉');
  var u = EC.headingsFromHtml('<h5 id=aa>t</h5>');
  assert.equal(u[0].id, 'aa', '无引号取值读不到 → 会追加出第二个 id');
});

test('nestHeadings：已改成 var 别名，不再有第二份函数声明', function () {
  assert.equal(/var nestHeadings = HeadingCore\.nestHeadings;/.test(ECSRC), true,
    '找不到 re-export 别名');
  assert.equal(/function nestHeadings/.test(ECSRC), false,
    'epub-core 里还留着 nestHeadings 的函数体（两份必然漂移）');
});

test('加载守卫：拿不到 HeadingCore 时必须抛，绝不静默降级', function () {
  /* 静默降级正是 E3 的成因。守卫一旦被人"简化"掉，这条会红。 */
  var threw = null;
  try { loadEpubCore(false); } catch (e) { threw = e; }
  assert.ok(threw, '没抛 —— 缺依赖会静默降级');
  assert.equal(/heading-core/.test(threw.message), true,
    '错误信息要说清缺的是谁，实际：' + threw.message);
});

test('KL-1 / T-9 冻结：loadChapter 的 startIndex 恒为 1，idCounter 已消失', function () {
  assert.equal(/ensureHeadingIds\(clean,\s*\{\s*startIndex:\s*1\s*\}\)/.test(ECSRC), true,
    '找不到 ensureHeadingIds(clean, { startIndex: 1 }) —— 有人动了本章计数器');
  assert.equal(/idCounter/.test(ECSRC), false, 'idCounter 又出现了');
  /* 这条断言的存在理由写在 loadChapter 的注释里：把它改成累计值会静默改变回写式产物。 */
});

test('N4：escapeXml / mimeOf 已导出且可用（lucy 的甲档打包器要）', function () {
  assert.equal(typeof EC.escapeXml, 'function', 'escapeXml 未导出');
  assert.equal(EC.escapeXml('a&b<c>d"e'), 'a&amp;b&lt;c&gt;d&quot;e');
  assert.equal(typeof EC.mimeOf, 'function', 'mimeOf 未导出');
  assert.equal(EC.mimeOf('img/Cover.PNG'), 'image/png', '扩展名要大小写无关');
  assert.equal(EC.mimeOf('x.unknown'), 'application/octet-stream');
});

test('A4：导出清单 18 → 20（N4 是【加】不是【缩】）', function () {
  var keys = Object.keys(EC);
  assert.deepEqual(BASELINE_KEYS.filter(function (k) { return !(k in EC); }), [],
    '基线 18 键有缺失');
  assert.equal(keys.length, 20, '实际 ' + keys.length + ' 键：' + keys.join(', '));
  /* 故意不把 nestHeadings 加进清单：全仓没有外部消费者，公开面越小越稳。
     若将来甲档要用它，加键是允许的（A4 只禁缩水），但要先过 lucy 的否决权。 */
});

run();

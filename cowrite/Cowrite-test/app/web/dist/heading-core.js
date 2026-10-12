/*!
 * heading-core.js — 标题扫描 / 补 id / 目录嵌套（纯函数，零依赖）
 * License: MIT
 *
 * 依赖：无。不碰 DOM、不碰 zip 库、不碰编辑器实例，也不绑定任何特定宿主对象，
 * 所以同一份文件能被浏览器、Node、以及 Worker 直接加载 —— 验收 A1/A2/A3 的实质
 * 就是「能被 Node require 跑单测，不需要 jsdom」。
 *
 * 依赖方向必须单向（TC-4）：
 *     heading-core  ←  目录面板（P1）
 *     heading-core  ←  epub-core / 甲档打包器（P2）
 * heading-core 自己不依赖上面任何一个，也不得反向依赖。
 *
 * 🔴 本文件受一条 grep 门禁管着（PRD §6.1 / TC-4 / 方案 §2.6 A1-A3）：
 *    四个禁用串的命中数必须为 0 —— zip 库名、DOM 入口对象、编辑器构造器名、
 *    以及「浏览器宿主对象 + 点」。这条门禁**连注释一起算**，所以上面这几句
 *    只能这样绕着说。这不是洁癖：门禁若分不清「真引入了依赖」和「只是解释了
 *    一句」，它就会被一句正确的注释弄红（lucy 的 3b4ca07 已经在 index.html 上
 *    演示过一次）。判据本身该改成「非注释行命中数为 0」，已报 nat。
 *
 * 版本：1.0.0 · 2026-09-18 · owner: tom
 * 依据：R32（B5 采候选 E）、R33（大小写敏感冻结约束）、R40（一个标题只解析一次、
 *       attrMap 不得暴露成检测/提取两个函数）、B1（返回 nextIndex）、
 *       B6（不发 keepExisting 开关）、R22/KL-6（不发 avoidCollisions 开关）、
 *       KL-8（id="" 本轮不修）、KL-9（[^>]* 截断本轮不修，T-KL1 现状锁）。
 */
(function (factory) {
  if (typeof module === 'object' && typeof module.exports === 'object') {
    module.exports = factory();
  } else {
    // 宿主出口只有这一处。用 globalThis 而不是浏览器专有对象，理由见文件头：
    // 那样做会让本文件在 Node 里加载即抛，A1-A3 就跑不起来。
    // 方案 §2.6 的 A3 原文要求「命中数 = 1」，而 PRD §6.1 / TC-4 要求「= 0」——
    // 两条判据互相矛盾，本文件按更严的那条（= 0）实现，A3 已相应修订。
    (typeof globalThis !== 'undefined' ? globalThis : this).HeadingCore = factory();
  }
})(function () {
  'use strict';

  var VERSION = '1.0.0';

  /* 与 epub-core.js:433 现行前缀一致。改成别的会让已导出的 epub 锚点全部失效。 */
  var DEFAULT_PREFIX = 'eebk';
  var DEFAULT_START = 1;

  /* ======================= 标题元素扫描（唯一正则来源） ======================= */

  /*
   * 三个捕获组：1=层级数字、2=属性串、3=元素内容。
   * 只在函数内 new RegExp，绝不共用模块级 /g 正则 —— 共用会带上 lastIndex，
   * 让第二次调用从上一次的位置继续扫，表现为「同一个函数两次调用结果不同」。
   * 死循环不可能：三个分支每个都至少吃掉 1 个字符（<h、层级、>、内容或闭标签）。
   *
   * ⚠️ 第 2 组的 [^>]* 在属性值里含 > 时会把属性串截断（例：<h1 title="a>b">）。
   *    这是 epub-core.js:431 的现行行为，本轮**不修**（KL-9），并由 T-KL1 现状锁
   *    钉住：将来谁修它，那条测试会变红，而不是静默改掉已上线的产物。
   */
  var RE_HEADING_SRC = '<h([1-6])\\b([^>]*)>([\\s\\S]*?)<\\/h\\1>';

  function headingRe() {
    return new RegExp(RE_HEADING_SRC, 'gi');
  }

  /* ======================= 实体解码（自 epub-core.js:107-116 逐字迁入） ======================= */

  /*
   * ⚠️ KL-10：这是**双解码**。先替换 &amp; 再替换 &lt;，于是 "&amp;lt;" 被解成 "<"
   * 而不是字面的 "&lt;"。触发条件是用户在标题里打出 "&lt;" 这四个字符。
   * 面板与 nav 消费的是同一个 heading.text，所以两边**错得一模一样** —— 不是分歧，
   * 只是共同的不准确。修法（单遍回调，4 行换 9 行）排在 P2、不阻塞本轮，
   * 迁进来时**故意逐字保留**，以免在 P0 里夹带一个没人报批的行为变更。
   */
  function decodeEntities(s) {
    return String(s)
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&#x([0-9a-fA-F]+);/g, function (_, h) { return String.fromCodePoint(parseInt(h, 16)); })
      .replace(/&#(\d+);/g, function (_, d) { return String.fromCodePoint(parseInt(d, 10)); });
  }

  /* 与 epub-core.js:194 逐字同形：先剥内部标签成空格，再解实体，再压空白、去首尾。 */
  function cleanText(inner) {
    return decodeEntities(String(inner).replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ').trim();
  }

  /* ======================= 属性串解析：R23-b / R40 / TC-5 要求的唯一来源 ======================= */

  /*
   * attrMap(s) → { 属性名: 值 }
   *
   * B5 的根因就是「属性取值语法」被写了两遍然后漂移：epub-core.js:432 的检测
   * （/\bid\s*=/）不要引号、:193 的提取（/id\s*=\s*("([^"]*)"|'([^']*)')/）要引号，
   * 而且检测那个 \b 会在 "-" 与 "i" 之间成立。于是：
   *   · <h1 data-id="x">  被判成「已有 id」→ 跳过补号，而 :193 又从 data-id 里
   *     提出一个幽灵 id "x" → nav 指向文档里不存在的片段（死锚点，全程无报错）
   *   · <h1 id=x>         被跳过补号（检测认为有 id），:193 却取不到（要引号）
   *     → 报出空 id → 空锚点
   * 两个缺陷同族、反方向、今天就存在。修法只有一种：把语法收敛成**一次解析**，
   * 检测（'id' in map）与提取（map.id）读同一个结果，结构上不可能再分叉。
   *
   * 🔴 三条冻结约束（R33，nat 已实测；不要「顺手优化」任何一条）：
   *
   *  1. 属性名**原样保留大小写，绝不 toLowerCase**。EPUB 内容文档是 XHTML/XML，
   *     属性名大小写敏感，ID 不是 id。转小写会让 ID="aa" 被判成「有 id」→ 不补号
   *     → 而提取端大小写敏感取不到 → nav 空锚点。（lucy 的结论对、机制写反了，
   *     nat 在 R33(b) 已更正：不是「看起来没 id 所以追加」，是「看起来有 id 所以
   *     追加被抑制」。机制写反会诱导人去补追加逻辑，那是错的修法。）
   *  2. 单引号与双引号**两个分支都要留**。只写 "[^"]*" 时 <h1 id='aa'> 返回
   *     undefined，而 JSON.stringify 会静默丢掉值为 undefined 的字段 —— 缺陷
   *     不报错，只在下游表现为「目录少一项」。
   *  3. **无引号取值必须支持**（第三个分支）。<h1 id=aa> 只有走这一支才对；
   *     A 与 B 两个候选在这一例上都是死锚点，只有 E 过（R32 实测）。
   *
   * 另外三条 HTML5 语法事实，都是本函数能过 14 用例真值表的原因：
   *  · 引号后**可以省空白**：<h1 class="x"id="aa"> 是合法的两属性标签。
   *    这正是候选 B 的 (?:^|\s) 判据挂掉的决定性用例 n04 —— 它在引号与 id 之间
   *    不成立，于是判「无 id」→ 追加 → 同一标签两个 id。HTML5 重复属性第一个胜出，
   *    元素真实 id 是 aa，而 nav 指 #eebk-1 → 死锚点；XML 侧则是重复属性致命。
   *  · **重复属性第一个胜出**（下面的 if (!(name in out))）。
   *  · 未闭合的引号吃到串尾，**不抛异常**（导入的 epub 可能有残缺标记）。
   */
  function attrMap(s) {
    var out = {};
    s = String(s == null ? '' : s);
    var i = 0;
    var n = s.length;

    while (i < n) {
      while (i < n && /\s/.test(s.charAt(i))) i++;
      if (i >= n) break;

      var ns = i;
      while (i < n && !/[\s=/>]/.test(s.charAt(i))) i++;
      var name = s.slice(ns, i);
      if (!name) { i++; continue; }

      while (i < n && /\s/.test(s.charAt(i))) i++;

      if (s.charAt(i) !== '=') {
        /* 无值属性（如 <h1 hidden>），HTML 合法，值记为空串 */
        if (!(name in out)) out[name] = '';
        continue;
      }
      i++;
      while (i < n && /\s/.test(s.charAt(i))) i++;

      var q = s.charAt(i);
      var val;
      if (q === '"' || q === "'") {
        var vs = ++i;
        var ve = s.indexOf(q, i);
        if (ve < 0) { val = s.slice(vs); i = n; }   /* 未闭合：吃到结尾 */
        else { val = s.slice(vs, ve); i = ve + 1; }
      } else {
        var us = i;
        while (i < n && !/[\s>]/.test(s.charAt(i))) i++;
        val = s.slice(us, i);
      }
      if (!(name in out)) out[name] = val;          /* 重复属性：第一个胜出 */
    }
    return out;
  }

  /* ======================= 只读扫描：不补 id ======================= */

  /*
   * headingsFromHtml(html) → [{ level, id, text }]
   *
   * 🔴 id **恒为字符串**：没有 id 属性时是 ''，不是 undefined。
   * 两个理由：① 与 epub-core.js:195 的现行契约一致（那里返回 ''），:436 与
   * :590/:598 都按 falsy 判断，换成 undefined 虽然同样 falsy，但会改变
   * JSON.stringify 的输出（undefined 字段被静默丢掉）；② 让单测能直接断言
   * id === ''，不必区分「字段不存在」和「字段是 undefined」。
   *
   * ⚠️ 有 id 属性但值为空（<h1 id="">）时同样返回 ''，与「没有 id」不可区分。
   *    这是 KL-8：A/B/E 三个候选在这一例上全挂 —— 既不能追加（会造重复 id），
   *    也不能不追加（nav 取空）。真要修得就地改写空值，那是第三种行为，本轮不做。
   */
  function headingsFromHtml(html) {
    var out = [];
    var re = headingRe();
    var src = String(html == null ? '' : html);
    var m;
    while ((m = re.exec(src))) {
      var map = attrMap(m[2]);
      out.push({
        level: parseInt(m[1], 10),
        id: ('id' in map) ? String(map.id) : '',
        text: cleanText(m[3])
      });
    }
    return out;
  }

  /* ======================= 扫描 + 补 id：一次遍历，检测与提取共享同一份解析结果 ======================= */

  /*
   * ensureHeadingIds(html, opts) → { html, headings, nextIndex }
   *
   *   opts.prefix     默认 'eebk'（与 epub-core.js:433 一致）
   *   opts.startIndex 默认 1
   *   nextIndex       = startIndex + 本次**实际分配掉**的 id 数
   *
   * 🔴 nextIndex 是 B1 的产物，是甲档切章的**唯一硬阻塞点**：{html, headings}
   * 推不出下一章该从几开始编号 —— lucy 用三种「看似合理」的推导方式分别得到
   * 2 / 3 / 4。这个计数器本来就存在（epub-core.js:430 的 idCounter），只是从来没
   * 被返回过，所以修法是返回它，不是重新设计它。
   *
   * 🔴 **不发 keepExisting 开关**（B6 撤回）：「保留已有 id」是无条件行为。
   *    发一个语义未定义的开关会产出 <h1 id="aa" id="eebk-1"> —— 两个 id 属性，
   *    epub 解析器直接硬失败。
   * 🔴 **不发 avoidCollisions 开关**（R22 → KL-6）：甲档与面板路径 A 都不可能碰撞
   *    （formats 白名单剥掉所有 id），唯一暴露面是回写式导出，而那条路一启用就要
   *    重新验证。把未验证的行为藏在默认关闭的旗标后面，比写成已知限制更糟。
   *    → 两个开关都没有调用者。
   *
   * ⚠️ 补过 id 的 html **绝不写回编辑器**（TC-10 配套禁令）：既不写 DOM，也不缓存
   *    后当作 editor.html() 的返回值。否则面板补一遍、甲档再补一遍 = B2 的重复 id。
   */
  function ensureHeadingIds(html, opts) {
    opts = opts || {};
    var prefix = (opts.prefix == null || opts.prefix === '') ? DEFAULT_PREFIX : String(opts.prefix);
    var start = parseInt(opts.startIndex, 10);
    if (!(start >= 0)) start = DEFAULT_START;        /* NaN / 负数 / 缺省 一律回到 1 */

    var re = headingRe();
    var src = String(html == null ? '' : html);
    var headings = [];
    var assigned = 0;

    var out = src.replace(re, function (whole, level, attrs, inner) {
      var map = attrMap(attrs);                       /* 🔴 一个标题只解析这一次（R40） */
      var hasOwn = ('id' in map);
      var id;

      if (hasOwn) {
        id = String(map.id);
      } else {
        id = prefix + '-' + (start + assigned);
        assigned++;
      }

      headings.push({ level: parseInt(level, 10), id: id, text: cleanText(inner) });

      if (hasOwn) return whole;                       /* 原样返回，一个字节都不动 */

      /*
       * 只改写开标签，闭标签与内容按原样拼回。
       * 不用「重建整个元素」的写法，因为那会把 <H1>x</H1> 的闭标签也转成小写 ——
       * 现行 epub-core.js:431-434 只重建开标签，本文件保持逐字等价的产物。
       * 开标签长度 = '<h'(2) + 层级(1) + 属性串 + '>'(1)；正则里的 \b 是零宽断言，
       * 不占字符，所以这个算术是准的。
       */
      var openLen = 2 + String(level).length + attrs.length + 1;
      var openTag = whole.slice(0, openLen);
      return openTag.slice(0, -1) + ' id="' + id + '">' + whole.slice(openLen);
    });

    return { html: out, headings: headings, nextIndex: start + assigned };
  }

  /* ======================= 嵌套（自 epub-core.js:612-622 逐字迁入） ======================= */

  /*
   * 面板要做层级缩进与折叠，nav.xhtml 要做嵌套 <ol>。两边各写一套嵌套规则的话，
   * 就会出现「面板上 h3 挂在 h1 下面、epub 目录里 h3 却挂在 h2 下面」。
   * 这套栈式算法已经是对的，直接共用，成本 0。
   *
   * 🔴 逐字迁移，**不改节点形状**：产出 { text, href, children }，
   * 因为 epub-core.js:624-634 的 renderNestedOl 就按这三个键读。
   * 入参需要 href —— 用 anchorOf() 从 flat 项算出来再传进来。
   */
  function nestHeadings(list) {
    var root = [];
    var stack = [{ level: 0, children: root }];
    for (var i = 0; i < list.length; i++) {
      var h = list[i];
      var node = { text: h.text, href: h.href, children: [] };
      while (stack.length && stack[stack.length - 1].level >= h.level) stack.pop();
      stack[stack.length - 1].children.push(node);
      stack.push({ level: h.level, children: node.children });
    }
    return root;
  }

  /*
   * anchorOf(item, fileHref) → 'chap3.xhtml#eebk-7'
   *
   * 与 epub-core.js:590 / :598 现行拼法逐字同形：没有 id 时返回裸 href，
   * 不返回 '#'（空片段会让阅读器跳到文件开头，看起来像「链接坏了」而不是「没有锚点」）。
   * 路径解析（relPath）留在 epub-core，本函数不做任何路径运算。
   */
  function anchorOf(item, fileHref) {
    var href = String(fileHref == null ? '' : fileHref);
    var id = item && item.id ? String(item.id) : '';
    return href + (id ? '#' + id : '');
  }

  return {
    VERSION: VERSION,
    DEFAULT_PREFIX: DEFAULT_PREFIX,
    /* attrMap 导出只为单测（T-16 / A5）。调用方请用 ensureHeadingIds ——
       R40 禁止把「检测」与「提取」暴露成两个函数，所以这里只有一个。 */
    attrMap: attrMap,
    decodeEntities: decodeEntities,
    headingsFromHtml: headingsFromHtml,
    ensureHeadingIds: ensureHeadingIds,
    nestHeadings: nestHeadings,
    anchorOf: anchorOf
  };
});

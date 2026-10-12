/* ============================================================================
   doc-core.js — 窗口化文档模型（P1 · 大文档不整本进编辑器）

   为什么要它：40 万字的 epub 整本塞进 Quill，实测（真实时钟）
   setRichDoc 一次 1109ms，之后**每敲一个字 77ms**（1 万多个 DOM 节点全量重排）。
   导入时卡死、之后一直卡。

   治法不是"优化 Quill"，是**换掉文档的家**：真正的文档住在内存里（这个模型），
   编辑区只是它的一个窗口——只装当前章。她打字只回写当前章，
   全文只在探针 / 导出 / 复盘真要的时候才重组一次。

   ⚠️ 两条硬约束（改这个文件之前先读）：
   1. **不许依赖 DOM。** 全部是字符串运算，这样 Node 里能直接单测
      （`node web/tests/doc-core.test.js`）——不依赖 DOM 是它可比
      editor-core 更放心地被改的前提。
   2. **重组是惰性的。** `commit()` 只标脏，绝不重组全文。一旦 commit 里
      去拼全文，每敲一个字就又变成 O(全文)，这个文件就白写了。
   ========================================================================== */
(function (global) {
  var api = { create: create, split: split, textOf: textOf, _version: '1.0.0' };

  /* Quill / 编辑器里那套 HTML 就是这一份方言：块级标签换算行，再解实体。 */
  function textOf(html) {
    var s = String(html == null ? '' : html)
      .replace(/<(script|style)[\s\S]*?<\/\1>/gi, '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/(p|div|h[1-6]|li|tr|blockquote|pre)>/gi, '\n')
      .replace(/<[^>]+>/g, '');
    /* 实体解码的顺序是**有讲究**的：&amp; 必须最后。
       先解 &amp; 的话，`&amp;lt;` 会被解成 `&lt;` 再被下一行解成 `<`——
       原文里本来写的是"&lt;"四个字符，出来变成一个尖括号。 */
    return s.replace(/&nbsp;/g, ' ')
      .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
      .replace(/&amp;/g, '&')
      .replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  function hText(s) {
    return textOf(s).replace(/\s+/g, ' ').trim();
  }

  /* 按标签切块，用于没有标题时按字数硬切。切点必须在块边界上——
     把一个 <p> 劈成两半，两个窗口各自都是坏掉的 HTML。 */
  function blocks(src) {
    var re = /[\s\S]*?<\/(?:p|div|h[1-6]|blockquote|li|pre)>|[\s\S]+$/gi;
    return String(src || '').match(re) || [];
  }

  /* 分章：
     ① 有 h1 → 按 h1 切（epub 导入的天然形态）
     ② 没有 h1 但有 h2 → 按 h2 切
     ③ 都没有 → 按 chunkChars 在块边界硬切
     切不切得动不影响正确性：全文拼回来一个字不多、一个字不少（有单测管）。 */
  function split(html, opts) {
    opts = opts || {};
    var limit = opts.chunkChars || 30000;
    var src = String(html == null ? '' : html);
    if (!src.trim()) return [];

    var lv = null;
    if (/<h1\b/i.test(src)) lv = 1;
    else if (/<h2\b/i.test(src)) lv = 2;

    var parts = [];
    if (lv) {
      var idx = [], re = new RegExp('<h' + lv + '\\b', 'gi'), m;
      while ((m = re.exec(src))) idx.push(m.index);
      if (idx[0] > 0) parts.push(src.slice(0, idx[0]));
      for (var i = 0; i < idx.length; i++) {
        parts.push(src.slice(idx[i], i + 1 < idx.length ? idx[i + 1] : src.length));
      }
    } else {
      var bs = blocks(src), cur = '';
      for (var j = 0; j < bs.length; j++) {
        if (cur && cur.length + bs[j].length > limit) { parts.push(cur); cur = bs[j]; }
        else cur += bs[j];
      }
      if (cur.trim()) parts.push(cur);
    }

    parts = parts.filter(function (s) { return s.trim(); });
    if (!parts.length) return [];
    return parts.map(function (s, k) {
      var t = titleOf(s);
      return { title: t || ('第 ' + (k + 1) + ' 节'), html: s };
    });
  }

  /* 标题 = 这一块开头的第一个 h1–h3 的文本。取不到就返回空。 */
  function titleOf(block) {
    var m = /<h([1-3])\b[^>]*>([\s\S]*?)<\/h\1>/i.exec(block || '');
    return m ? hText(m[2]) : '';
  }

  function create(opts) {
    opts = opts || {};
    var chapters = [];          // [{title, html, text, chars}]
    var cur = 0;
    var dirty = false;
    var cacheText = null, cacheHtml = null;

    function normalize(list) {
      return (list || []).map(function (c, i) {
        var html = typeof c === 'string' ? c : (c && c.html) || '';
        var text = (c && c.text != null) ? c.text : textOf(html);
        return {
          title: (c && c.title) || titleOf(html) || ('第 ' + (i + 1) + ' 节'),
          html: html,
          text: text,
          chars: text.length
        };
      });
    }

    var doc = {
      get count() { return chapters.length; },
      get index() { return cur; },
      set index(i) {
        var n = Math.max(0, Math.min(chapters.length - 1, i | 0));
        cur = chapters.length ? n : 0;
      },
      get dirty() { return dirty; },
      get chunkChars() { return opts.chunkChars || 30000; },

      load(list) {
        chapters = normalize(list);
        cur = 0;
        dirty = false;
        cacheText = null;
        cacheHtml = null;
        return doc;
      },

      /* 直接把一整篇 html 灌进来（小文档老路也走它，保证两条路同一个模型） */
      loadHtml(html) {
        return doc.load(split(html, opts));
      },

      title(i) { return chapters[i] ? chapters[i].title : ''; },
      chapter(i) { return chapters[i] || null; },
      chapterHtml(i) { return chapters[i] ? chapters[i].html : ''; },

      /* 光标所在的全局偏移：前面各章字数之和 + 章内位置。
         探针的 cursor_offset / doc_chars 吃的是全文坐标，切了窗口也得给全文坐标。 */
      offsetIn(i, localPos) {
        var s = 0, n = Math.min(i, chapters.length);
        /* 每一章后面都跟着 2 个字符的分隔符（章之间用 \n\n 接）——
           是 diff 不是 diff-1：循环只会走到**非最后**的章，它们的后面必然
           还有下一章。漏掉第一个分隔符就会让全局偏移永远差 2
           （单测抓到的就是这个）。 */
        for (var k = 0; k < n; k++) s += chapters[k].chars + 2;
        return s + Math.max(0, localPos | 0);
      },

      /* 编辑区回写**当前章**。只标脏，不重组（见文件头的硬约束 2）。 */
      commit(i, html, text) {
        var c = chapters[i];
        if (!c) return false;
        var h = html == null ? '' : html;
        var t = text == null ? textOf(h) : text;
        /* 内容没变就**什么都不做**。这一句不是微优化：`quillText()` 会在
           导出菜单里被连调三次，每次前面都挂着一次 `commitCurrentChapter()`——
           无条件标脏的话，三次调用会重组三遍全文；40 万字上那是三倍的
           几十毫秒。相等判断让「切章回来没动过」这种情况完全免掉重组。 */
        if (c.html === h && c.text === t) return false;
        c.html = h;
        c.text = t;
        c.chars = t.length;
        dirty = true;
        cacheText = null;
        cacheHtml = null;
        return true;
      },

      /* 全文总字数：各章缓存之和，**不重组**。字数显示走这条，
         所以字数条在 40 万字上也是常数时间。 */
      chars() {
        var s = 0;
        for (var i = 0; i < chapters.length; i++) s += chapters[i].chars + (i ? 2 : 0);
        return s > 0 ? s : 0;
      },

      /* 全文纯文本。脏了才重组一次（探针触发 / 导出 / 复盘时才走到）。 */
      text() {
        if (cacheText != null && !dirty) return cacheText;
        var a = [];
        for (var i = 0; i < chapters.length; i++) a.push(chapters[i].text);
        cacheText = a.join('\n\n');
        dirty = false;
        return cacheText;
      },

      /* 全文 html（导出用）。 */
      html() {
        if (cacheHtml != null) return cacheHtml;
        var a = [];
        for (var i = 0; i < chapters.length; i++) a.push(chapters[i].html);
        cacheHtml = a.join('\n');
        return cacheHtml;
      },

      /* 全文标题（目录用）。每一条带 chapter，点它就切章再滚。
         其他章的标题不在 DOM 里，所以只能从这里来——这是窗口化必须付的代价。 */
      headings() {
        var out = [];
        for (var i = 0; i < chapters.length; i++) {
          var re = /<h([1-3])\b([^>]*)>([\s\S]*?)<\/h\1>/gi, m, k = 0;
          while ((m = re.exec(chapters[i].html))) {
            var idm = /\bid\s*=\s*("([^"]*)"|'([^']*)')/i.exec(m[2]);
            out.push({
              level: +m[1],
              id: idm ? (idm[2] != null ? idm[2] : idm[3]) : '',
              text: hText(m[3]),
              chapter: i,
              /* 章内第几个标题（0 起）。**定位靠它，不靠 id**：
                 Quill 的 formats 白名单里没有 id，所以她一打字，
                 getSemanticHTML() 就把这一章标题上的 id 全丢了——
                 靠 id 找节点的话，当前章改过一个字之后目录就跳不动了。
                 顺序不会变，所以用序号。 */
              k: k++
            });
          }
        }
        return out;
      }
    };

    return doc;
  }

  global.DocModel = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
  /* IIFE 必须自己调一次。漏掉它，DocModel 永远不会挂上 window，
     调用点第一句就抛 TypeError，整份脚本从那行起全不执行——
     editor-core.js 已经栽过一次（语法合法，node --check 查不出来）。 */
})(typeof window !== 'undefined' ? window : globalThis);

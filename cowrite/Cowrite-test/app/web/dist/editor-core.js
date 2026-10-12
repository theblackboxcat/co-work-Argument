/* ============================================================================
   editor-core.js — EditorController（P1 ② 的地基）

   为什么抽它：伴写侧已经有一个「跟 textarea 长得一样」的替身 `ta`（value /
   selectionStart / addEventListener 三个属性接到 Quill 底下，29 处老调用一行没改）。
   它是模块级单例——绑死全局 quill、绑死 #ta。文学视图要迁过来时，复制一份意味着
   caretIndex / setDocText / insertDocText / setRichDoc / 缓冲 / 工具条 各写两遍，
   第三份（目录面板要同时驱动两个编辑器）根本没法写。所以抽成可实例化的控制器。

   返回对象的形状与原替身**逐字段一致**，所以已有调用点一行不用改——
   这是「搬家不改逻辑」，不是重写。

   与旧实现的三处差别（都是有意为之）：
   · 降级缓冲按实例隔离。原来两个视图共享一个 `_taText`，一篇稿子的降级文本
     会被另一篇读到（回归点 T-12）。
   · 字数刷新只有一处（refreshCount），两个视图各配各的计数元素。
   · 创建即建 Quill，不再等 boot：惰性挂载那套 _pending 保留但不再被走到
     （注册语句现在都在实例诞生之后）。留着它，是因为它是替身契约的一部分。
   ========================================================================== */
/* 这个 IIFE **必须自己调一次**（下面的 `})(window)`）。漏了它，EditorController
   永远不会被挂到 window 上，index.html 里 `const ta = EditorController.create()`
   在第一句就抛 TypeError——整份脚本从那一行起全部不执行，表现是"页面能开、
   编辑器是空的、控制台只有一条 Cannot read properties of undefined"。
   node --check 查不出这种错（语法完全合法），只有真跑一遍才现形。 */
(function (global) {
  var api = { create: create, _version: '1.1.0' };
  if (typeof module === 'object' && module.exports) module.exports = api;
  global.EditorController = api;

  function create(opts) {
    opts = opts || {};
    var host = opts.host;
    if (!host) throw new Error('EditorController: 需要 { host }');
    var countEl = opts.countEl || null;
    /* 降级缓冲。必须 var 声明在这一层：漏了声明的话，下面的 `buf = v` 在
       非严格模式下会静默建一个 **全局** buf，于是两个视图共用同一份降级文本——
       正是 T-12（一篇稿子的降级文本被另一篇读到）的原样复发，而且是隐式复发：
       有 Quill 时完全看不出来，只在 Quill 没加载的降级路径上才咬人。 */
    var buf = '';
    /* 光标与选区必须分开记。旧实现把 selectionEnd 也接到 caretIndex，
       Quill 里的 r.length 被整个丢掉，后端永远只看得到 ⟨这里⟩ 一个点。 */
    var memStart = 0, memEnd = 0;
    var toText = opts.toText || function (h) {
      return String(h == null ? '' : h).replace(/<[^>]+>/g, '');
    };

    /* Quill 没加载时退化为纯内存缓冲：探针、通读拿到的仍是纯文本，
       伴写照常，只是没有排版（降级不能变成报错）。 */
    var q = null;
    if (typeof global.Quill === 'function') {
      q = new global.Quill(host, {
        placeholder: opts.placeholder || '',
        formats: (opts.formats || DEFAULT_FORMATS).slice(),
        modules: { clipboard: true, history: { userOnly: opts.userOnly !== false } }
      });
    }

    function text() {
      var t = q ? q.getText() : buf;
      // 末尾那一个换行必须抹掉：Quill 的内容永远以 \n 结尾，
      // 不抹的话 `ed.value = ed.value` 每跑一次多一个空行，字数虚增 1。
      return t.endsWith('\n') ? t.slice(0, -1) : t;
    }
    function refreshCount() {
      if (countEl) countEl.textContent = text().length + ' 字';
      return text().length;
    }

    var ed = {
      /* ---- 替身契约（与 textarea 同形，老调用点零改动）---- */
      get value() { return text(); },
      set value(v) {
        buf = v == null ? '' : String(v);
        memStart = memEnd = 0;
        if (!q) { refreshCount(); return; }
        q.setText(buf);
        memStart = memEnd = 0;
        refreshCount();
      },
      get selectionStart() { return memStart; },
      get selectionEnd() { return memEnd; },
      get length() { return q ? q.getLength() : buf.length; },
      // 惰性挂载：老语句注册在实例诞生之前时先记下来，建好再统一挂上。
      // 现在创建即建 Quill，这条路径正常不会被走到，留着是契约的一部分。
      _pending: [],
      addEventListener(ev, fn) {
        if (!q) { this._pending.push([ev, fn]); return; }
        this._attach(ev, fn);
      },
      _attach(ev, fn) {
        if (!q) return;
        if (ev === 'input') q.on('text-change', fn);
        else q.root.addEventListener(ev, fn);
      },
      _flush() {
        var p = this._pending.slice(); this._pending.length = 0;
        var self = this;
        p.forEach(function (pair) { self._attach(pair[0], pair[1]); });
        return p.length;
      },
      removeEventListener() {},
      focus() { if (q) q.focus(); },
      blur() { if (q) q.blur(); },
      setSelectionRange(start, end, source) {
        if (!q) return;
        var a = Math.max(0, start | 0), b = Math.max(a, (end == null ? a : end) | 0);
        q.setSelection(a, b - a, source || 'api');
        memStart = a; memEnd = b;
      },
      selectionRange() {
        return {start: memStart, end: memEnd, length: Math.max(0, memEnd - memStart)};
      },
      scrollIntoView() {},
      get root() { return q ? q.root : host; },

      /* ---- 富文本能力（旧的全局函数改成了薄封装，逻辑搬到这里）---- */
      get quill() { return q; },
      caretIndex() {
        if (!q) return memStart;
        try {
          var s = q.getSelection(false);
          return s ? s.index : memStart;
        } catch (e) { return memStart; }
      },
      html() {
        if (!q) return '';
        // getSemanticHTML 是 Quill 2 的：干净语义标签，不带 ql-* 排版碎屑
        return typeof q.getSemanticHTML === 'function' ? q.getSemanticHTML() : q.root.innerHTML;
      },
      /* 整篇换成带格式的 HTML：clipboard.convert 会按 formats 清单过滤一遍，
         电子书里那些乱七八糟的类名和内联样式进不来。
         Quill 2.0.3 的坑：convert(字符串) 返回空 ops，必须传 {html}——
         它不报错，就是什么都不来。 */
      setRichDoc(html) {
        if (!q) { buf = toText(html); refreshCount(); return; }
        var delta = null;
        try { delta = q.clipboard.convert({html: html || ''}); } catch (e) { delta = null; }
        if (delta && delta.ops && delta.ops.length) {
          q.setContents(delta, 'api');
        } else {
          try { q.setText(''); q.clipboard.dangerouslyPasteHTML(0, html || '', 'silent'); }
          catch (e2) { q.setText(toText(html)); }
        }
        memStart = memEnd = 0;
        refreshCount();
      },
      /* 末尾追加纯文本（光标位置不丢，不整篇重设） */
      append(v) {
        if (!q) { buf += v || ''; refreshCount(); return; }
        q.insertText(Math.max(0, q.getLength() - 1), v || '');
        refreshCount();
      },
      /* 末尾追加 HTML（「放进左边」用：累加不替换，格式留住） */
      appendHtml(html) {
        if (!q) { buf += toText(html); refreshCount(); return; }
        /* 先补一个换行，把新内容顶到**新的一段**上。
           Quill 的粘贴是就地的：直接 dangerouslyPasteHTML 到末尾，新段落会接在
           最后一段的文字后面粘成一团 —— 实测 `<p>甲</p>` 之后再追加 `<p>乙</p>`
           得到的是 `<p>甲乙</p>`，不是两段。它不报错，只在导出和目录里才现形
           （本该是两段的正文被压成一段）。
           ⚠️ 分隔符别用 <hr>：这份 Quill 没有 divider blot（lib/quill.js 里
              搜不到 divider），<hr> 会被静默吃掉，连它后面那段的断行一起丢。 */
        var at = Math.max(0, q.getLength() - 1);
        if (at > 0) { q.insertText(at, '\n', 'user'); at = Math.max(0, q.getLength() - 1); }
        q.clipboard.dangerouslyPasteHTML(at, html || '', 'user');
        refreshCount();
      },
      getFormat() { return q ? q.getFormat() : {}; },
      format(name, value, source) { if (q) q.format(name, value, source || 'user'); },
      formatLine(i, n, name, value, source) {
        if (q) q.formatLine(i, n, name, value, source || 'user');
      },
      /* 把某一行设成一级标题（目录「猜一下」确认后的落点）。不碰别的字。 */
      applyHeadingToText(s) {
        if (!q) return;
        var i = q.getText().indexOf(s);
        if (i >= 0) q.formatLine(i, 1, 'header', 1, 'user');
      },
      refreshCount: refreshCount
    };

    /* 光标/选区记忆：失焦后仍返回最后位置——语境切片全靠它。
       Quill 在失焦时回调 r=null，这时保留最后一次有效选区，不要把选中范围抹掉。 */
    if (q) {
      q.on('selection-change', function (r) {
        if (r && typeof r.index === 'number') {
          memStart = Math.max(0, r.index);
          memEnd = memStart + Math.max(0, r.length || 0);
        }
      });
      q.on('text-change', function () { refreshCount(); if (opts.onText) opts.onText(); });
    }

    return ed;
  }

  /* 两个实例的 formats 必须一致（P1 护栏 4）：给文学侧一个更窄的白名单，
     目录面板在文学视图会直接死掉——没有 h 标签就没有目录，而且不报错。 */
  var DEFAULT_FORMATS = ['bold', 'italic', 'underline', 'strike', 'header',
                         'blockquote', 'align', 'color', 'size', 'list',
                         'indent', 'link'];
  create.DEFAULT_FORMATS = DEFAULT_FORMATS;
})(typeof window !== 'undefined' ? window : globalThis);

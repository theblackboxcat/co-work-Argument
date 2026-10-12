/* ============================================================================
 * TocPanel v1.0.0 — 目录面板（P1 ③）
 *
 * 按 P1 方案 §3 / §6 落地。三层里的「UI + 适配层」：
 *
 *   heading-core.js   纯函数层：ensureHeadingIds / headingsFromHtml / nestHeadings
 *        ↑
 *   toc-panel.js      ← 本文件：抽屉、树、折叠、当前位置、键盘
 *        ↑
 *   editor-core.js    编辑器层：EditorController（提供 root / html() / onSelect）
 *
 * 对编辑器只要求**三个能力**（root / html() / onSelect），所以③的伴写侧可以在
 * ②（文学模块迁 Quill、抽 EditorController）之前落地，②完成后这里一行不改。
 *
 * 三条不是洁癖、是必须写进实现的护栏：
 *   1. **跳转不动光标**。编辑区把 keyup/click/mouseup/focus 全接到了 touch()，
 *      跳转时若顺手 setSelection，会走 selectionchange → touch() → 8 秒探针重新
 *      计时，她只是点了一下目录，却收到一条伴写建议（方案 §3.4）。
 *   2. **不静默改稿**。空文档没有标题时给的是「设为标题」和「猜一下」两个显式动作，
 *      「猜」也只给建议、逐条确认后才应用。猜错一条就污染一份材料。
 *   3. **长度不一致要说话**。DOM 里的 h 标签数与序列化后提取的标题数不等时，
 *      退回「能跳但不能保证与导出一致」，并在面板上标明——不猜、不静默。
 * ==========================================================================*/
(function (global) {
  'use strict';

  var FOLD_KEY = 'bans_toc_fold';        // 与 bans_mode 同一条理由：长期偏好，不该每次刷新重来
  var DEBOUNCE = 300;                    // getSemanticHTML() 是全文序列化，20 万字上不便宜
  var DEBOUNCE_BIG = 800;                // >10 万字抬一档
  var BIG_CHARS = 100000;
  var FLASH_MS = 1200;                   // 跳转后目标块高亮多久
  var CURRENT_OFFSET = 24;               // 判定「当前标题」的容差

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* 滚动容器**不猜**，从编辑区自己往上找第一个真能滚的祖先。
     为什么必须探测：方案 §6.2 写的是 .ql-container（项目 CSS 确实给它加了
     overflow-y:auto），但 Quill 自带的 .ql-editor{height:100%;overflow-y:auto}
     才是真正滚的那一个——实测里 .ql-container 的 scrollHeight 恒等于
     clientHeight（内容在 1229px 处、它报 615），硬按文档写会得到一个永远不跳的
     目录。所以这里自己找，不依赖任何一边的 CSS 会不会改。 */
  function scrollable(el) {
    return !!el && el.scrollHeight > el.clientHeight + 1;
  }

  function findScroller(el) {
    var n = el, first = null;
    while (n && n.nodeType === 1 && n !== document.documentElement) {
      var ov = 'visible';
      try { ov = getComputedStyle(n).overflowY; } catch (e) { break; }
      if (ov === 'auto' || ov === 'scroll') {
        if (!first) first = n;
        // 声明了能滚 ≠ 真能滚。窄屏时 main 走 height:auto，编辑区被撑开、
        // 自己一像素都不滚，真正滚的是整页；认错了容器，"当前一节"就永远停
        // 在第一条上，跳转也测不出位移。所以要求它此刻确实有富余可滚。
        if (scrollable(n)) return n;
      }
      n = n.parentElement;
    }
    var doc = document.scrollingElement || document.documentElement;
    if (scrollable(doc)) return doc;
    return first || doc;
  }

  function loadFold() {
    try {
      var raw = localStorage.getItem(FOLD_KEY);
      var arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }
  function saveFold(list) {
    try { localStorage.setItem(FOLD_KEY, JSON.stringify(list)); } catch (e) {}
  }

  /* ============================== 主体 ============================== */

  /**
   * @param {Object} opts
   *   editor   {root, html(), onSelect?()}   —— 只要求这三个能力
   *   mount    抽屉容器元素（本文件往里塞内容，不自己造容器）
   *   scroller 滚动容器（默认从 root 往上找 .ql-container）
   *   badge    计数徽标元素（可选，显示「目录 · N」里的 N）
   *   flag     小红点元素（可选，关闭期间内容变了就亮）
   *   onJump   跳转后的回调（可选）
   */
  function createTocPanel(opts) {
    opts = opts || {};
    var ed = opts.editor;
    if (!ed || !ed.root || typeof ed.html !== 'function') {
      throw new Error('TocPanel: 需要 { editor:{root, html()} }');
    }
    /* 根元素不缓存：ed.root 允许是 getter（伴写/文学两个编辑器按当前视图换人），
       缓存一次就会把跳转永远指到某一个编辑器上——那个视图还可能正藏着。 */
    function rootEl() { return ed.root; }
    var mount = opts.mount;
    if (!mount) throw new Error('TocPanel: 需要 { mount }');
    var scroller = opts.scroller || null;
    // 断点一换（窄屏 main 变 height:auto），滚动容器就从编辑区变成整页。
    // 所以不一次性认死：每次要算位置时先问一句"你现在还能滚吗"。
    function resolveScroller() {
      if (!scroller || !scrollable(scroller)) scroller = findScroller(rootEl());
      return scroller;
    }
    var badge = opts.badge || null;
    var flag = opts.flag || null;
    var onJump = opts.onJump || null;

    var items = [];               // [{level, text, id, el, folded}]
    var synced = true;            // DOM 与序列化是否等长（见护栏 3）
    var opened = false;
    var dirty = true;
    var timer = 0, rafId = 0, flashTimer = 0;
    var flashEl = null, flashTarget = null;
    var curIdx = -1;
    var folded = loadFold();      // 按标题文字存：id 会随重算变，文字最稳

    /* ---------- 计算 ---------- */

    function compute() {
      /* 编辑器自己出标题。窗口化（大书按章开窗口）必须走这条：
         那时 DOM 里只有**一章**，走下面"DOM 与序列化比长度"必然判成不同步，
         结果是退化成只列当前章，还弹一条「锚点未同步」——那句话在窗口化下
         是**误导**：不是没同步，是设计上就只装了一章。 */
      var ext = (typeof ed.headings === 'function') ? ed.headings() : null;
      if (ext && ext.length) { computeExternal(ext); return; }

      var html = '';
      try { html = ed.html() || ''; } catch (e) { html = ''; }
      var hs = [];
      try {
        var res = global.HeadingCore && global.HeadingCore.ensureHeadingIds
          ? global.HeadingCore.ensureHeadingIds(html) : null;
        hs = (res && res.headings) || [];
      } catch (e) { hs = []; }

      var dom = rootEl().querySelectorAll('h1,h2,h3,h4,h5,h6');
      // 护栏 3：两边长度必须相等。不等就退化——**有层级有跳转、无 id**，并明说。
      // 比的是长度，所以它兜不住「幽灵 id」（两边都不变长）；那类缺陷只能靠
      // heading-core 自己在 P0 修掉，不能指望运行时发现（方案 §3.3 已记）。
      synced = dom.length === hs.length;

      var minLevel = 99;
      for (var i = 0; i < hs.length; i++) minLevel = Math.min(minLevel, hs[i].level);
      if (hs.length && minLevel === 99) minLevel = 1;
      // 长度不等时以 DOM 为准（跳转必须能跳），层级从标签名读
      var src = synced ? hs : domList(dom);
      var next = [];
      for (var j = 0; j < src.length; j++) {
        var s = src[j];
        var el = (synced ? dom[j] : s.el) || null;
        next.push({
          level: s.level, text: s.text || '',
          id: s.id || '',
          el: el,
          folded: folded.indexOf(s.text) >= 0
        });
      }
      items = next;
      if (badge) badge.textContent = items.length ? String(items.length) : '0';
      dirty = false;
      if (flag) flag.style.display = 'none';
      render();
      markCurrent(true);
    }

    /* 外部标题（窗口化）。清单来自编辑器（全文），但 DOM 里只有当前章——
       所以只有**本章**的条目能拿到 el，别的章点了要先切章（见 jump）。
       这一点必须在界面上看得出来，否则她点一条就直接被送到另一章，
       会以为自己点错了。带 chapter 的条目在渲染时会有个淡色标记。 */
    function computeExternal(ext) {
      var cur = (typeof ed.chapterAt === 'function') ? ed.chapterAt() : -1;
      var dom = rootEl().querySelectorAll('h1,h2,h3,h4,h5,h6');

      items = ext.map(function (s) {
        var mine = (s.chapter === cur);
        /* 当前章的标题能在 DOM 里拿到，**按章内序号取，不按 id**：
           Quill 的白名单里没有 id，她一动笔，这一章标题上的 id 就没了
           （见 doc-core.headings 的注释）。序号不会变。 */
        var el = (mine && s.k != null) ? (dom[s.k] || null) : null;
        return {
          level: s.level, text: s.text || '', id: s.id || '',
          chapter: s.chapter, k: s.k,
          el: el,
          folded: folded.indexOf(s.text) >= 0
        };
      });
      synced = true;
      dirty = false;
      if (badge) badge.textContent = items.length ? String(items.length) : '0';
      if (flag) flag.style.display = 'none';
      render();
      markCurrent(true);
    }

    // 退化路径：直接从活 DOM 读层级与文字
    function domList(dom) {
      var out = [];
      for (var i = 0; i < dom.length; i++) {
        out.push({
          level: parseInt(dom[i].tagName.slice(1), 10) || 1,
          text: (dom[i].textContent || '').trim(),
          id: '', el: dom[i]
        });
      }
      return out;
    }

    /* ---------- 渲染 ---------- */

    /* 抽屉自己带一个「收起」。为什么必须有：抽屉是覆盖在写作区上的，展开后会把
       左下角那个「目录」按钮压在底下——第一次发现时点了半天点不掉，只能刷新。
       三条退路都给上：按钮、抽屉里的「收起」、Esc。任意一条都能关。 */
    function headHtml(n) {
      return '<div class="toc-head"><span>目录</span>'
           + '<span class="toc-hn">' + (n == null ? items.length : n) + ' 条</span>'
           + '<button class="toc-close" id="toc-close" title="收起目录（Esc）">收起</button>'
           + '</div>';
    }

    function bindHead() {
      var b = mount.querySelector('#toc-close');
      if (b) b.onclick = function (e) { e.preventDefault(); close(); };
    }

    function render() {
      if (!items.length) { renderEmpty(); return; }
      var minLevel = 99;
      items.forEach(function (it) { minLevel = Math.min(minLevel, it.level); });
      var html = headHtml();
      if (!synced) {
        html += '<div class="toc-note">锚点未同步：正文标题数与导出时会算的不一样，'
             +  '能跳，但不保证与导出的目录一致。</div>';
      }
      html += '<ul class="toc-list">';
      var curCh = (typeof ed.chapterAt === 'function') ? ed.chapterAt() : -1;
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        // 缩进按「相对最浅的那一级」——不能假定从 h1 开始，也不能假定最深 h3
        var pad = (it.level - minLevel) * 14;
        var kids = childCount(i);
        // 不在当前章的条目：点它会先切章。这件事必须看得见（见 computeExternal）
        var other = (it.chapter != null && curCh >= 0 && it.chapter !== curCh);
        var foldBtn = kids > 0
          ? '<button class="toc-fold" data-i="' + i + '" aria-expanded="'
            + (it.folded ? 'false' : 'true') + '" title="折叠子标题">'
            + (it.folded ? '▸' : '▾') + '</button>'
          : '<span class="toc-fold toc-fold-none"></span>';
        html += '<li class="toc-item' + (other ? ' toc-other' : '') + '" data-i="' + i + '"'
             +  (hiddenUnder(i) ? ' hidden' : '') + '>'
             +  foldBtn
             +  '<a class="toc-link" href="#" data-i="' + i + '"'
             +  ' style="padding-left:' + pad + 'px" title="'
             +  esc(it.text) + (other ? '（在第 ' + (it.chapter + 1) + ' 章，点了会翻过去）' : '')
             +  '">' + esc(it.text || '(无标题)') + '</a>'
             +  '</li>';
      }
      html += '</ul>';
      mount.innerHTML = html;
      bindList();
      bindHead();
    }

    // 第 i 项之后、层级比它深的，算它的子项
    function childCount(i) {
      var n = 0;
      for (var j = i + 1; j < items.length && items[j].level > items[i].level; j++) n++;
      return n;
    }
    // 任一层祖先被折叠 → 自己也藏着
    function hiddenUnder(i) {
      var lv = items[i].level;
      for (var j = i - 1; j >= 0; j--) {
        if (items[j].level < lv) {
          if (items[j].folded) return true;
          lv = items[j].level;
        }
      }
      return false;
    }

    function renderEmpty() {
      mount.innerHTML =
        headHtml(0)
        + '<div class="toc-empty">这份文档里没有标题层级。</div>'
        + '<div class="toc-acts">'
        +   '<button id="toc-mk1">把选中文字设为一级标题</button>'
        +   '<button id="toc-guess">猜一下标题</button>'
        + '</div>'
        + '<div class="toc-guess" id="toc-gbox" hidden></div>';
      var b1 = mount.querySelector('#toc-mk1');
      var b2 = mount.querySelector('#toc-guess');
      if (b1) b1.onclick = function () { ed.formatHeader && ed.formatHeader(1); };
      if (b2) b2.onclick = guess;
      bindHead();
    }

    // 「猜一下」只给建议、逐条确认。**不静默改稿**（护栏 2）。
    function guess() {
      var box = mount.querySelector('#toc-gbox');
      if (!box) return;
      var cands = [];
      var text = '';
      try { var re = rootEl(); text = re.innerText || re.textContent || ''; } catch (e) { text = ''; }
      var lines = text.split(/\n+/);
      for (var i = 0; i < lines.length; i++) {
        var s = lines[i].trim();
        if (!s || s.length > 30) continue;                 // 太长不像标题
        if (/[。！？，、；：）】」』]$/.test(s)) continue;   // 以标点收尾的多半不是
        var prev = i > 0 ? lines[i - 1].trim() : '';       // 前面得是空行
        if (prev) continue;
        cands.push(s);
      }
      if (!cands.length) { box.hidden = false; box.textContent = '没猜出来——也许这篇确实没有标题。'; return; }
      var h = '<div class="toc-guess-h">猜到 ' + cands.length + ' 条，逐条确认后才应用：</div>';
      cands.forEach(function (s, k) {
        h += '<div class="toc-guess-row"><span>' + esc(s) + '</span>'
           + '<button data-g="' + k + '">设为标题</button></div>';
      });
      box.hidden = false;
      box.innerHTML = h;
      box.querySelectorAll('button[data-g]').forEach(function (b) {
        b.onclick = function () {
          var s = cands[+b.dataset.g];
          ed.applyHeadingToText && ed.applyHeadingToText(s);
          schedule();
        };
      });
    }

    function bindList() {
      mount.querySelectorAll('.toc-link').forEach(function (a) {
        a.onclick = function (e) { e.preventDefault(); jump(+a.dataset.i); };
      });
      mount.querySelectorAll('.toc-fold').forEach(function (b) {
        b.onclick = function (e) {
          e.preventDefault(); e.stopPropagation();
          var i = +b.dataset.i, it = items[i]; if (!it) return;
          it.folded = !it.folded;
          var k = folded.indexOf(it.text);
          if (it.folded && k < 0) folded.push(it.text);
          if (!it.folded && k >= 0) folded.splice(k, 1);
          saveFold(folded);
          render();
        };
      });
    }

    /* ---------- 跳转（护栏 1：不动光标） ---------- */

    function jump(i) {
      var it = items[i]; if (!it) return;
      /* 跨章：窗口化时别的章的标题不在 DOM 里，先让编辑器切过去，
         再重算一次 items（这时 el 才会指到新章的节点上）。
         重算后下标仍然对齐——headings() 给的是**全文**顺序，切章不改顺序。 */
      if (it.chapter != null && typeof ed.chapterAt === 'function'
          && typeof ed.goChapter === 'function' && it.chapter !== ed.chapterAt()) {
        ed.goChapter(it.chapter);
        compute();
        it = items[i] || it;
      }
      if (!it.el) return;
      // 系统在「减少动态效果」时走 instant：平滑滚动对前庭敏感的人是真不适，
      // 而目录跳转是她会高频点的动作，不该每次都强制一段动画。
      var smooth = !(global.matchMedia
        && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
      try {
        it.el.scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: 'start'});
      } catch (e) {
        try { it.el.scrollIntoView(); } catch (e2) {}
      }
      flash(it.el);
      markCurrent(true);
      if (onJump) onJump(it, i);
    }

    /* 高亮用浮层，**一个字节都不改正文**。
       早期版本是给标题本身加 .toc-flash：实测这会触发 Quill 的变更观察器，
       它顺势同步一次选区 → document 的 selectionchange → 页面把它读成
       "她动了一下"，8 秒探针重启，跳一次目录就多一次莫名的伴写。
       而且加在可编辑节点上的 class 还有被存进稿子的风险。改成浮层，两样都躲开。 */
    function flash(el) {
      clearTimeout(flashTimer);
      clearFlash();
      var d = mount.ownerDocument;
      var ov = d.createElement('div');
      ov.className = 'toc-flash';
      d.body.appendChild(ov);
      flashEl = ov;
      flashTarget = el;
      placeFlash();
      flashTimer = setTimeout(clearFlash, FLASH_MS);
    }

    function placeFlash() {
      if (!flashEl || !flashTarget) return;
      var r = flashTarget.getBoundingClientRect();
      // 滚出可视区就让位：留一块悬在半空的高亮比没有更糟
      var vh = global.innerHeight || 0;
      if (r.bottom < 0 || r.top > vh) { clearFlash(); return; }
      flashEl.style.left = r.left + 'px';
      flashEl.style.top = r.top + 'px';
      flashEl.style.width = r.width + 'px';
      flashEl.style.height = r.height + 'px';
    }

    function clearFlash() {
      clearTimeout(flashTimer);
      if (flashEl && flashEl.parentNode) flashEl.parentNode.removeChild(flashEl);
      flashEl = null; flashTarget = null;
    }

    /* ---------- 当前位置 ---------- */

    // 为什么不用 offsetTop：给 .write 加 position:relative 之后它成了 offsetParent，
    // 而 scrollTop 是相对 .ql-container 的，两者基准不同，直接比会整片偏移。
    // 所以统一换算成「相对滚动容器内容顶端」的距离。
    function markCurrent(force) {
      if (!items.length) return;
      var idx = 0;
      scroller = resolveScroller();
      if (scroller) {
        // 拿「视口里容器顶边在哪」当判定线，不再拿 scrollTop 做基准换算是
        // 因为整页滚的时候 documentElement 的 rect.top 本身就是 -scrollTop，
        // 再减一遍就翻一倍，判定线跑到内容下面去，"当前一节"永远停在第一条。
        var isDoc = (scroller === document.scrollingElement
                  || scroller === document.documentElement || scroller === document.body);
        var line = (isDoc ? 0 : scroller.getBoundingClientRect().top) + CURRENT_OFFSET;
        for (var i = 0; i < items.length; i++) {
          var el = items[i].el; if (!el) continue;
          if (el.getBoundingClientRect().top <= line) idx = i; else break;
        }
      }
      if (!force && idx === curIdx) return;
      curIdx = idx;
      var links = mount.querySelectorAll('.toc-item');
      for (var j = 0; j < links.length; j++) {
        var isCur = (+links[j].dataset.i) === idx;
        if (isCur) links[j].setAttribute('aria-current', 'location');
        else links[j].removeAttribute('aria-current');
      }
    }

    function onScroll() {
      if (rafId) return;
      rafId = requestAnimationFrame(function () {
        rafId = 0; placeFlash(); markCurrent(false);
      });
    }

    /* ---------- 节流 ---------- */

    function schedule() {
      if (!opened) { dirty = true; if (flag) flag.style.display = ''; return; }
      clearTimeout(timer);
      var t = ((rootEl().textContent || '').length > BIG_CHARS) ? DEBOUNCE_BIG : DEBOUNCE;
      timer = setTimeout(compute, t);
    }

    /* ---------- 开合 ---------- */

    /* scroll 事件不冒泡，所以挂在 window 的捕获阶段——这样不管这一刻真正滚的
       是编辑区还是整页，都收得到；不用跟着断点反复摘挂监听。 */
    var bound = false;
    function bindScroll() {
      if (bound) return;
      global.addEventListener('scroll', onScroll, {passive: true, capture: true});
      bound = true;
    }
    function unbindScroll() {
      if (!bound) return;
      global.removeEventListener('scroll', onScroll, {capture: true});
      bound = false;
    }

    function onKey(e) {
      if (e.key === 'Escape' || e.key === 'Esc') { e.preventDefault(); close(); }
    }

    function open() {
      opened = true;
      mount.classList.add('on');
      if (dirty) compute();
      bindScroll();
      mount.ownerDocument.addEventListener('keydown', onKey);
      markCurrent(true);
    }
    function close() {
      opened = false;
      mount.classList.remove('on');
      unbindScroll();
      mount.ownerDocument.removeEventListener('keydown', onKey);
      clearFlash();
    }
    function toggle() { opened ? close() : open(); }

    function destroy() {
      clearTimeout(timer);
      clearFlash();
      if (rafId) cancelAnimationFrame(rafId);
      unbindScroll();
      mount.ownerDocument.removeEventListener('keydown', onKey);
    }

    return {
      open: open, close: close, toggle: toggle, refresh: schedule,
      recompute: compute, destroy: destroy,
      // 把探测结果露出来：布局是 CSS 决定的，一旦哪天 CSS 改了、容器换人了，
      // 排查的人第一件事就是想知道"它到底认了谁"。留个口子比每次打断点强。
      get scroller() { return scroller; },
      get count() { return items.length; },
      get opened() { return opened; },
      get synced() { return synced; },
      items: function () { return items.slice(); }
    };
  }

  var api = { create: createTocPanel, _version: '1.0.0' };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.TocPanel = api;
})(typeof window !== 'undefined' ? window : globalThis);

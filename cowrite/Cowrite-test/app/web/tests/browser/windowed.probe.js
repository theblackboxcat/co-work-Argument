/* 窗口化（大书按章开窗口）的验收。
   跑法：node tests/browser/run.js windowed
   注意：这里测的是**功能与不变式**，不是耗时。耗时要用真实时钟，
   跑 node tests/browser/cdp.js tests/browser/windowed-perf.cdp.js。 */
try {
  var R = [];
  function t(n, f) {
    // 字符串返回＝**失败诊断**，不是 INFO（见 工程路径与技术回顾 §六·22）。
    try { var v = f(); R.push((v === true ? 'PASS' : (v === false || (typeof v === 'string' && v) ? 'FAIL' : 'INFO')) + ' | ' + n + (v === true || v === false ? '' : ' :: ' + v)); }
    catch (e) { R.push('ERR  | ' + n + ' :: ' + (e && e.message)); }
  }
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending';
  document.body.appendChild(o);
  function dump() { o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n'; }

  /* 造一本"大书"：300 章，每章 1 个 h1 + 8 段，约 15 万字（超过 12 万阈值） */
  function bigBook(nCh) {
    var list = [], chars = 0;
    for (var i = 0; i < nCh; i++) {
      var ps = [];
      for (var j = 0; j < 8; j++) {
        ps.push('<p>第' + i + '章第' + j + '段，她站在走廊尽头，没打伞。我想喊她，' +
                '可是那一年我只会写，不会开口说话。</p>');
      }
      var html = '<h1>第' + (i + 1) + '章</h1>' + ps.join('');
      list.push({title: '第' + (i + 1) + '章', html: html});
      chars += html.replace(/<[^>]+>/g, '').length;
    }
    return {list: list, chars: chars};
  }

  (function () {
    var bk = bigBook(300);

    /* ── 1. 老路不受影响（先行：窗口化之前） ── */
    t('初始是非窗口化（老路）', function () { return WINDOWED === false; });
    document.querySelector('#viewsw .vs[data-view="write"]').click();
    ta.setRichDoc('<h1>小</h1><p>一篇五万字以内的小说走的就是这条路</p>');
    t('老路：quillText() 就是编辑区', function () { return quillText() === ta.value; });
    t('老路：docHtml() 就是编辑区', function () { return docHtml() === ta.html(); });
    t('老路：tocEd.headings() 返回 null（面板该自己抽）', function () { return tocEd.headings() === null; });
    t('老路：tocEd.chapterAt() 返回 -1', function () { return tocEd.chapterAt() === -1; });
    t('老路：切章条藏着', function () { return document.getElementById('chapbar').style.display === 'none'; });

    /* ── 2. 进窗口化 ── */
    var ok = enterWindowed({list: bk.list, text: ''});
    t('★ enterWindowed 成功', function () { return ok === true; });
    t('★ 认出了 300 章', function () { return DOC.count === 300 ? true : 'count=' + DOC.count; });
    t('★ 编辑区只装一章（不是整本）', function () {
      var one = ta.value.length, all = DOC.chars();
      return one < all / 200 ? true : '一章 ' + one + ' / 全文 ' + all;
    });
    t('★ 字数条显示的是全文', function () {
      return document.getElementById('count').textContent === DOC.chars() + ' 字'
        ? true : document.getElementById('count').textContent + ' vs ' + DOC.chars();
    });
    /* 她真的敲字时，字数条也必须还是全文。这条专门盯 Quill 的 text-change
       监听顺序：onText 先跑（写全文），后注册的那条 `input` 监听若照着
       ta.value.length 再写一次，字数条就退回**本章**字数——打字才现形。 */
    t('★ 敲字之后字数条仍是全文', function () {
      ta.quill.insertText(0, '她', 'user');
      var want = DOC.chars();      // 基准要在插入之后取
      var got = document.getElementById('count').textContent;
      return got === want + ' 字' ? true : got + ' vs ' + want + ' 字';
    });
    t('切章条出现了', function () { return document.getElementById('chapbar').style.display !== 'none'; });
    t('切章条写对章号', function () { return document.getElementById('chapinfo').textContent === '第 1/300 章'; });
    t('首页的上章按钮禁用', function () { return document.getElementById('chapprev').disabled === true; });

    /* ── 3. 两个出口给的仍是全文 ── */
    // ⚠️ 标记要按 bigBook() 的实际文本：<h1> 是「第(i+1)章」，但**段落正文**是「第 i 章第 j 段」。
    //    这里原来写的是 '第1章第0段' / '第300章第7段'——两个都差一位，条件恒假，
    //    于是这条断言长期只打印不判定（被 §六·22 那个 INFO 退化掩盖了）。现按实际文本取首末两段。
    t('★ quillText() 给全文（不是当前章）', function () {
      var s = quillText();
      var first = s.indexOf('第0章第0段') >= 0, last = s.indexOf('第299章第7段') >= 0;
      return first && last ? true : '首段' + (first ? '在' : '缺') + ' / 末段' + (last ? '在' : '缺') + '，长度 ' + s.length;
    });
    t('★ docHtml() 给全文（含所有章标题）', function () {
      var h = docHtml();
      return h.indexOf('第1章') >= 0 && h.indexOf('第300章') >= 0 ? true : '长度 ' + h.length;
    });
    t('全文纯文字数与 DOC.chars() 一致', function () {
      var s = quillText();
      // DOC.chars() 含章之间的 \\n\\n（每处 2 个），text() 也是，所以应当严格相等
      return s.length === DOC.chars() ? true : s.length + ' vs ' + DOC.chars();
    });

    /* ── 4. 探针拿到的是全文坐标 ── */
    ta.quill.setSelection(10, 0);
    var sig = attentionSignals();
    t('★ attentionSignals().doc_chars 是全文', function () {
      return sig.doc_chars === DOC.chars() ? true : sig.doc_chars + ' vs ' + DOC.chars();
    });
    t('★ cursor_offset 是全文偏移（第 1 章里就是章内位置）', function () {
      return sig.cursor_offset === DOC.offsetIn(DOC.index, ta.selectionStart) ? true
        : sig.cursor_offset + ' vs ' + DOC.offsetIn(DOC.index, ta.selectionStart);
    });

    /* ── 5. 回写不串章 ── */
    var ch0Before = DOC.chapterHtml(0);
    showChapter(5);
    t('★ 切到第 6 章', function () { return DOC.index === 5 && document.getElementById('chapinfo').textContent === '第 6/300 章'; });
    t('★ 编辑区换成了第 6 章', function () { return ta.value.indexOf('第5章第0段') >= 0 ? true : ta.value.slice(0, 60); });
    // 用 setRichDoc 而不是 ta.value=：value 那条是**纯文本**（setText），
    // 会把 <h1> 压成普通段落——测"回写"要模拟的是编辑后的富文本。
    ta.setRichDoc('<h1>第6章</h1><p>我把这一章改过了</p>');
    t('★ 改动落到第 6 章', function () { return DOC.chapterHtml(5).indexOf('我把这一章改过了') >= 0; });
    t('★ 第 1 章没被牵连', function () { return DOC.chapterHtml(0) === ch0Before; });
    showChapter(0);
    t('★ 切回第 1 章：内容还在', function () { return ta.value.indexOf('第0章第0段') >= 0; });
    t('★ 第 6 章的改动仍在', function () { return DOC.chapterHtml(5).indexOf('我把这一章改过了') >= 0; });
    t('切换回来之后切章条同步', function () { return document.getElementById('chapinfo').textContent === '第 1/300 章'; });
    t('首页章：上章禁用、下章可用', function () {
      return document.getElementById('chapprev').disabled === true
          && document.getElementById('chapnext').disabled === false;
    });
    document.getElementById('chapnext').click();
    t('点「下一章」真的翻了', function () { return DOC.index === 1; });
    document.getElementById('chapprev').click();
    t('点「上一章」翻回来', function () { return DOC.index === 0; });

    /* ── 6. 换章不重启探针，也不伪造信号 ──
       翻页把整块内容换掉，Quill 会连带惊动三条通路：text-change（同步，就在
       setRichDoc 里面）、focus（同步，setSelection 拉回焦点）、selectionchange
       （异步）。三条都不是"她动了一下"。判据在 flippingPage() 一处。 */
    paused = false; if (timer) clearTimeout(timer); timer = null;
    var jumpOf = function () {
      return TRACK.events.filter(function (e) { return e.type === 'jump'; }).length;
    };
    var jumpsBefore = jumpOf();
    showChapter(3);
    t('★ 换章不拉起伴写探针（那不是她动了一下）', function () {
      return timer === null ? true
        : 'timer 被拉起了（switching=' + switching + '，Δchap=' + (Date.now() - chapSwitchedAt) + '）';
    });
    /* 异步那条通路（selectionchange）要等一拍才看得到；150ms 的短窗也要等它过去。
       所以这一段分两层：先看异步通路有没有伪造信号，等短窗过期再看门宽不宽。 */
    setTimeout(function () {
      t('★ 翻页之后也没有凭空多出一条「跳」', function () {
        var now = jumpOf();
        return now === jumpsBefore ? true : '多出 ' + (now - jumpsBefore) + ' 条';
      });
      t('★ 翻页把光标基准挪到了新章（否则她下次轻挪会被记成横跨全篇）', function () {
        return TRACK.lastOffset === ta.selectionStart ? true
          : TRACK.lastOffset + ' vs ' + ta.selectionStart;
      });
      /* 门不能开太大：她翻到新章、真的开始敲字，探针必须照常起来。
         只测"翻页不起探针"的话，把 touch() 整个注释掉也一样过。
         这里不等 150ms 走完（无头 dump 的虚拟时间跑不到），
         直接把"翻页时刻"推回一秒前——测的是判据，不是时钟。 */
      chapSwitchedAt = Date.now() - 1000;
      ta.quill.insertText(0, '她', 'user');
      t('★ 翻页之后她真敲字，探针照常起来（门没开太大）', function () {
        return timer !== null ? true : '探针没起来';
      });
      paused = true; if (timer) clearTimeout(timer); timer = null;  // 别让它真去请求
    }, 0);

    /* ── 7. 目录：全文标题 + 跨章跳转 ── */
    var hs = tocEd.headings();
    t('★ 目录拿到全文标题（300 条）', function () {
      return hs && hs.length === 300 ? true : (hs === null ? '返回了 null' : '条数=' + hs.length);
    });
    t('★ 每条带 chapter 与章内序号 k', function () {
      if (!hs || hs.length < 300) return '条数不足：' + (hs ? hs.length : 'null');
      return hs[0].chapter === 0 && hs[0].k === 0 && hs[299].chapter === 299 && hs[299].k === 0
        ? true : JSON.stringify(hs[299]);
    });
    t('目录面板建着', function () { return !!TOC; });
    TOC.refresh();
    TOC.toggle();          // 打开：open() 里若 dirty 会**同步** compute 一次
    setTimeout(function () {
      var items = document.querySelectorAll('#tocdrawer .toc-item');
      t('★ 面板列出了全文的条目（不是只有当前章）', function () {
        return items.length === 300 ? true : '条目数=' + items.length;
      });
      t('★ 别的章的条目有可见标记（点了会翻章）', function () {
        return document.querySelectorAll('#tocdrawer .toc-other').length > 0;
      });
      var link = document.querySelector('#tocdrawer .toc-link[data-i="120"]');
      t('能拿到第 121 条的链', function () { return !!link; });
      if (link) {
        var before = DOC.index;
        link.click();
        t('★ 点别章的条目会翻过去', function () {
          return DOC.index === 120 ? true : 'before=' + before + ' after=' + DOC.index;
        });
        t('★ 翻章之后当前章标记不在了', function () {
          var li = document.querySelector('#tocdrawer .toc-item[data-i="120"]');
          return li && !li.classList.contains('toc-other');
        });
      }
      /* ── 8. 导出交全文 ── */
      var p = expPayload('doc');
      t('★ 导出 payload 是全文（不是当前章）', function () {
        return p && p.html && p.html.indexOf('第300章') >= 0 ? true : (p ? p.html.length : 'null');
      });
      t('导出字数按全文算', function () {
        return p && /\d+ 字/.test(p.n) ? true : (p && p.n);
      });
      /* ── 9. 收尾：回到老路 ── */
      leaveWindowed();
      t('★ leaveWindowed 之后回到老路', function () {
        return WINDOWED === false && tocEd.headings() === null
          && document.getElementById('chapbar').style.display === 'none';
      });
      dump();
    }, 60);
  })();
} catch (e) {
  var o2 = document.createElement('pre'); o2.id = 'VR';
  o2.textContent = '\n===VR-START===\nFATAL ' + (e && e.message) + '\n===VR-END===\n';
  document.body.appendChild(o2);
}

/* 窗口化的性能对照：**同一本书，老路 vs 窗口化**，一次跑出来。
   必须用真实时钟（node tests/browser/cdp.js tests/browser/windowed-perf.cdp.js）——
   --virtual-time-budget 会伪造时钟，任何耗时结论在那里都不可信。

   这本书就是她真正会导入的那种：四十万字级的 epub。想回答的问题只有一个——
   "整本进 Quill" 的那笔账（导入瞬间硬阻塞 + 每敲一个字卡一下）在窗口化之后
   还剩多少。所以两边量同一组数：setRichDoc / 每字 / DOM 节点 /
   全文出口（quillText、docHtml）/ attentionSignals。

   依赖 web/_perf.epub。没有这个文件时退化成构造样本（结论同量级，
   但少了真实 epub 的标签碎片——导入那一刻的解析成本会偏乐观）。 */
try {
  var R = [];
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending';
  document.body.appendChild(o);
  function ms(f) { var t = performance.now(); var v = f(); return {v: v, t: performance.now() - t}; }
  function r1(x) { return Math.round(x * 10) / 10; }
  function mem() { return performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : -1; }
  function nodes() { return document.querySelectorAll('#ta .ql-editor *').length; }

  /* 逐字敲：真正要问的是"她打字时每一击花多久"。
     20 击看均值，更要看**最坏**那一击——手感是被最坏值毁掉的，不是均值。 */
  function typing(n) {
    var q = ta.quill, at = Math.max(0, q.getLength() - 1), ts = [];
    for (var i = 0; i < n; i++) {
      var t = performance.now();
      q.insertText(at + i, '。', 'user');
      ts.push(performance.now() - t);
    }
    ts.sort(function (a, b) { return a - b; });
    var sum = 0; for (var j = 0; j < ts.length; j++) sum += ts[j];
    return {avg: r1(sum / ts.length), max: r1(ts[ts.length - 1]), first: r1(ts[0])};
  }
  function line(tag, x) {
    R.push(tag + ': ' + r1(x) + 'ms');
  }

  (async function () {
    /* ── 0. 拿书 ── */
    var bk = null, tRead = 0;
    try {
      var tF = performance.now();
      var buf = await fetch('_perf.epub').then(function (r) { return r.arrayBuffer(); });
      R.push('[真实 epub] 取文件 ' + r1(performance.now() - tF) + 'ms, '
        + r1(buf.byteLength / 1048576) + 'MB');
      var file = new File([buf], 'x.epub', {type: 'application/epub+zip'});
      bk = await (function () {
        var t = performance.now();
        return readEpub(file).then(function (b) { tRead = performance.now() - t; return b; });
      })();
    } catch (e) {
      R.push('[没有 _perf.epub，退化成构造样本] ' + e.message);
      var seg = '她站在走廊尽头，没打伞。我想喊她，可是那一年我只会写，不会开口。';
      var parts = [];
      for (var q = 0; q < 17000; q++) parts.push('<p>' + seg + '</p>');
      bk = {html: parts.join(''), text: seg.repeat(17000), chapters: 1, title: '构造样本', list: null};
    }
    var chars = (bk.text || '').length;
    R.push('readEpub: ' + r1(tRead) + 'ms | spine 章 ' + bk.chapters
      + ' | 正文 ' + chars + ' 字 | html ' + Math.round((bk.html || '').length / 1024) + 'KB');
    R.push('分块数: ' + (bk.list ? bk.list.length : '（无 spine，按标题/字数切）'));
    R.push('');

    /* ── 1. 窗口化（现在这条路） ── */
    R.push('══ 窗口化（合并前这条路）══');
    var m0 = mem();
    var tW = ms(function () { return enterWindowed({list: bk.list, text: bk.text}); });
    line('enterWindowed（导入那一刻的阻塞）', tW.t);
    R.push('  → ' + tW.v + ' | heap ' + m0 + '→' + mem() + 'MB');
    R.push('  编辑区字数: ' + ta.value.length + ' / 全文 ' + DOC.chars());
    R.push('  DOM 节点数: ' + nodes());
    line('首屏渲染后的第一击', typing(1).first);
    /* 别在第一块上量"每字"——epub 的 spine 第一块常是版权页（这本只有 28 字），
       在那儿量出来的成本是假的。挑**最大的一章**量，那才是她打字时的上界。 */
    var big = 0, bigChars = 0;
    for (var ci = 0; ci < DOC.count; ci++) {
      var cc = DOC.chapter(ci).chars;
      if (cc > bigChars) { bigChars = cc; big = ci; }
    }
    showChapter(big);
    R.push('  最大的一章: 第 ' + (big + 1) + ' 块，' + bigChars + ' 字（每字在这上面量）');
    R.push('  DOM 节点数（大章）: ' + nodes());
    var tp = typing(20);
    R.push('  打 20 个字（大章）: 均 ' + tp.avg + 'ms / 最坏 ' + tp.max + 'ms');
    /* 大章是上界，中位章才是她平常敲字的手感 */
    var order = [];
    for (var cj = 0; cj < DOC.count; cj++) order.push({i: cj, c: DOC.chapter(cj).chars});
    order.sort(function (a, b) { return a.c - b.c; });
    var mid = order[Math.floor(order.length / 2)];
    showChapter(mid.i);
    var tpm = typing(20);
    R.push('  打 20 个字（中位章 ' + mid.c + ' 字）: 均 ' + tpm.avg + 'ms / 最坏 ' + tpm.max + 'ms');
    /* 冷读：她打字刚把模型标脏，此刻的 docHtml/quillText 才是导出那一刻的真账 */
    line('docHtml() 冷读（刚改过、缓存已清）', ms(function () { return docHtml().length; }).t);
    line('quillText()（全文，喂后端/导出）', ms(function () { return quillText().length; }).t);
    line('docHtml()（全文 getSemanticHTML）', ms(function () { return docHtml().length; }).t);
    line('attentionSignals()', ms(function () { return attentionSignals(); }).t);
    line('目录 重算（全文标题）', ms(function () { TOC.refresh(); TOC.recompute(); }).t);
    R.push('  目录条目: ' + DOC.headings().length + ' 条');
    line('切到下一章（翻页）', ms(function () { showChapter(1); }).t);
    R.push('  翻页后 DOM 节点数: ' + nodes() + '（不随章数增长）');
    R.push('heap: ' + mem() + 'MB');
    R.push('');

    /* ── 2. 老路（把整本塞回 Quill，即合并前的行为） ── */
    R.push('══ 老路（整本进 Quill，合并前）══');
    leaveWindowed();
    var m1 = mem();
    var tO = ms(function () { setRichDoc(bk.html); });
    line('setRichDoc(整本 html)（导入那一刻的阻塞）', tO.t);
    R.push('  heap ' + m1 + '→' + mem() + 'MB');
    R.push('  DOM 节点数: ' + nodes());
    var tp2 = typing(20);
    R.push('  打 20 个字: 均 ' + tp2.avg + 'ms / 最坏 ' + tp2.max + 'ms');
    line('quillText()（全文）', ms(function () { return quillText().length; }).t);
    line('docHtml()（全文）', ms(function () { return docHtml().length; }).t);
    line('attentionSignals()', ms(function () { return attentionSignals(); }).t);
    R.push('heap: ' + mem() + 'MB');
    R.push('');

    /* ── 3. 材料框（文学视图）──
       这一轮窗口化只做了写作区。材料框还是老老实实整本进 Quill，
       所以它该跟上面的"老路"同一量级。量出来是为了别嘴上说没事。 */
    R.push('══ 材料框（文学视图；这一轮**没有**窗口化）══');
    setRichDoc('');                       // 先把写作区清掉，免得两份万级节点叠在一起
    var tL = ms(function () { lta.setRichDoc(bk.html); });
    line('lta.setRichDoc(整本)', tL.t);
    R.push('  材料框 DOM 节点数: ' + document.querySelectorAll('#lta .ql-editor *').length);
    R.push('  heap: ' + mem() + 'MB');
    R.push('');
    R.push('结论看两行：导入阻塞（enterWindowed vs setRichDoc）和每字成本。');

    o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n';
  })().catch(function (e) {
    o.textContent = '\n===VR-START===\nERR ' + (e && e.message) + '\n' + R.join('\n') + '\n===VR-END===\n';
  });
} catch (e) {
  var o2 = document.createElement('pre'); o2.id = 'VR';
  o2.textContent = '\n===VR-START===\nFATAL ' + e.message + '\n===VR-END===\n';
  document.body.appendChild(o2);
}

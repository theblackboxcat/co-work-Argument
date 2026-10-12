/* 大文档性能基线。**必须用真实时钟跑**（node tests/browser/cdp.js 本文件）——
   --virtual-time-budget 会把 JSZip 内部的 yield 当成时间流逝，
   同一个 readEpub 能量出 9836ms，真实值是 93ms，差 100 倍。
   依赖：web/ 下放一个测试用 epub，文件名 _perf.epub。没有就退化成构造的
   80 万字 html（结论同量级，但少了真实 epub 的标签碎片）。 */
try {
  var R = [];
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending'; document.body.appendChild(o);
  function ms(f) { var t = performance.now(); var v = f(); return {v: v, t: Math.round(performance.now() - t)}; }
  function mem() { return performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : -1; }
  function msa(f) { return f().then(function () { }); }
  (async function () {
    var m0 = mem();
    var bk = null, r1 = {t: 0};
    try {
      var t_fetch = performance.now();
      var buf = await fetch('_perf.epub').then(function (r) { return r.arrayBuffer(); });
      R.push('[真实 epub] 取文件 ' + Math.round(performance.now() - t_fetch) + 'ms, ' + Math.round(buf.byteLength / 1048576) + 'MB');
      var file = new File([buf], 'x.epub', {type: 'application/epub+zip'});
      r1 = await (function () { var t = performance.now(); return readEpub(file).then(function (b) { return {bk: b, t: Math.round(performance.now() - t)}; }); })();
      bk = r1.bk;
    } catch (e) {
      R.push('[没有 _perf.epub，退化成构造样本] ' + e.message);
      var seg = '她站在走廊尽头，没打伞。我想喊她，可是那一年我只会写，不会开口。';
      var parts = [];
      for (var q = 0; q < 17000; q++) parts.push('<p>' + seg + '</p>');
      bk = {html: parts.join(''), text: seg.repeat(17000), chapters: 1, title: '构造样本'};
      r1.t = 0;
    }
    var chars = (bk.text || '').length;
    R.push('readEpub: ' + r1.t + 'ms | 章节 ' + bk.chapters + ' | 正文 ' + chars + ' 字 | html ' + Math.round((bk.html || '').length / 1024) + 'KB');
    var m1 = mem();

    var t2 = ms(function () { setRichDoc(bk.html); });
    var m2 = mem();
    R.push('setRichDoc(html): ' + t2.t + 'ms | heap ' + m1 + '→' + m2 + 'MB');

    var t3 = ms(function () { return quillText().length; });
    R.push('quillText(): ' + t3.t + 'ms → ' + t3.v + ' 字');

    var t4 = ms(function () { return docHtml().length; });
    R.push('docHtml()(getSemanticHTML): ' + t4.t + 'ms');

    var nodes = document.querySelectorAll('#ta .ql-editor *').length;
    R.push('DOM 节点数: ' + nodes);

    var t5 = ms(function () { ta.quill.insertText(Math.max(0, ta.quill.getLength() - 1), '。', 'user'); });
    R.push('打一个字（含 text-change 链）: ' + t5.t + 'ms');

    var t6 = ms(function () { return attentionSignals(); });
    R.push('attentionSignals(): ' + t6.t + 'ms');

    var t7 = ms(function () { var s = quillText(); return JSON.stringify({name: 'x', text: s}).length; });
    R.push('quillText + JSON.stringify（喂后端那一步）: ' + t7.t + 'ms → ' + Math.round(t7.v / 1048576) + 'MB');

    var t8 = ms(function () { TOC.refresh(); });
    R.push('TOC.refresh(): ' + t8.t + 'ms');

    R.push('heap 终值: ' + mem() + 'MB');
    o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n';
  })().catch(function (e) {
    o.textContent = '\n===VR-START===\nERR ' + (e && e.message) + '\n' + R.join('\n') + '\n===VR-END===\n';
  });
} catch (e) {
  var o2 = document.createElement('pre'); o2.id = 'VR';
  o2.textContent = '\n===VR-START===\nFATAL ' + e.message + '\n===VR-END===\n'; document.body.appendChild(o2);
}

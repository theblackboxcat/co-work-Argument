/* 回归探针：目录面板交互（toc-panel 改过 root 取法）+ epub 端到端打包 */
try {
  var R = [];
  function t(n, f) {
    // 字符串返回＝**失败诊断**，不是 INFO（见 工程路径与技术回顾 §六·22）。
    try { var v = f(); R.push((v === true ? 'PASS' : (v === false || (typeof v === 'string' && v) ? 'FAIL' : 'INFO')) + ' | ' + n + (v === true || v === false ? '' : ' :: ' + v)); }
    catch (e) { R.push('ERR  | ' + n + ' :: ' + (e && e.message)); }
  }
  (function () {
    /* ---------- 目录面板：写作视图 ---------- */
    document.querySelector('#viewsw .vs[data-view="write"]').click();
    ta.setRichDoc('<h1>第一章</h1><p>正文一</p><h2>一节</h2><p>正文二</p><h1>第二章</h1><p>正文三</p>');
    t('写作视图 TOC 已建', function () { return !!TOC; });
    TOC.refresh();
    TOC.open ? TOC.open() : TOC.toggle();
    t('抽屉已打开', function () {
      var d = document.getElementById('tocdrawer');
      return d && (d.classList.contains('on') || d.style.display !== 'none') ? true : 'drawer state=' + d.className + '/' + d.style.display;
    });
    var items = document.querySelectorAll('#tocdrawer [data-idx], #tocdrawer .tocitem, #tocdrawer a');
    t('抽屉里列出了标题', function () { return items.length > 0 ? true : '条目数=0'; });
    t('抽屉自带「收起」按钮', function () {
      return Array.prototype.some.call(document.querySelectorAll('#tocdrawer button'),
        function (b) { return /收起|关闭/.test(b.textContent); });
    });

    /* 跳转不动光标（护栏） */
    var before = ta.value;
    ta.quill.setSelection(ta.value.length, 0);
    var caret0 = ta.caretIndex();
    try { TOC.jump && TOC.jump(0); } catch (e) { }
    t('跳转后正文一个字没变', function () { return ta.value === before; });
    t('跳转后光标未被搬走', function () { return ta.caretIndex() === caret0; });

    /* Esc 关闭 */
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    t('Esc 能关掉抽屉', function () {
      var d = document.getElementById('tocdrawer');
      return !(d.classList.contains('on')) ? true : 'still on';
    });

    /* ---------- 目录面板：文学视图（root 是 getter） ---------- */
    document.querySelector('#viewsw .vs[data-view="lit"]').click();
    lta.setRichDoc('<h1>材料一</h1><p>甲</p><h2>小节</h2><p>乙</p>');
    TOC.refresh();
    t('文学视图后 tocEd.root 指向 lta', function () { return tocEd.root === lta.root; });
    t('文学视图目录有 h1/h2 可列', function () { return /<h1|<h2/.test(tocEd.html()); });
    document.querySelector('#viewsw .vs[data-view="write"]').click();
    t('切回写作后 tocEd.root 指向 ta', function () { return tocEd.root === ta.root; });

  })();

  /* ---------- epub 端到端：拿文学侧的真实 html（异步，dump 会等） ---------- */
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending';
  document.body.appendChild(o);
  function dump() {
    o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n';
  }
  (function () {
    document.querySelector('#viewsw .vs[data-view="lit"]').click();
    lta.setRichDoc('<h1>材料一</h1><p>甲</p><h2>小节</h2><p>乙</p><h1>材料二</h1><p>丙</p>');
    var html = lta.html();
    ExportCore.buildEpub({ html: html, title: '回归测试', author: '猫猫', language: 'zh' })
      .then(function (res) {
        t('buildEpub 出 blob', function () { return !!(res && res.blob && res.blob.size > 0); });
        t('按 h1 分成 2 章', function () { return res.chapters === 2 ? true : 'chapters=' + res.chapters; });
        t('标题层级数 >= 3', function () { return res.headings >= 3 ? true : 'headings=' + res.headings; });
        t('uid 非空（N2）', function () { return !!(res.uid && String(res.uid).length > 0); });
        return JSZip.loadAsync(res.blob);
      })
      .then(function (zip) {
        var names = Object.keys(zip.files);
        t('含 mimetype', function () { return names.some(function (n) { return /mimetype$/.test(n); }); });
        t('含 container.xml', function () { return names.some(function (n) { return /container\.xml$/.test(n); }); });
        t('含 nav 文档', function () { return names.some(function (n) { return /nav/.test(n); }); });
        var opfN = names.filter(function (n) { return /\.opf$/.test(n); })[0];
        return zip.file(opfN).async('string').then(function (opf) {
          t('OPF uid 非空', function () { return !/dtb:uid=""/.test(opf) && /<dc:identifier[^>]*>[^<]+/.test(opf); });
          t('OPF 标题正确', function () { return opf.indexOf('回归测试') >= 0; });
          var navN = names.filter(function (n) { return /nav/.test(n); })[0];
          return zip.file(navN).async('string').then(function (nav) {
            t('nav 里列到了材料一/材料二', function () { return nav.indexOf('材料一') >= 0 && nav.indexOf('材料二') >= 0; });
          });
        });
      })
      .catch(function (e) { R.push('ERR  | epub 端到端 :: ' + (e && e.message)); })
      .then(dump);
  })();
} catch (e) {
  var o2 = document.createElement('pre'); o2.id = 'VR';
  o2.textContent = '\n===VR-START===\nFATAL ' + (e && e.message) + '\n===VR-END===\n';
  document.body.appendChild(o2);
}

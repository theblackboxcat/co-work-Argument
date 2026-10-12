/* 文学材料分章窗口 + 选区坐标的浏览器回归。 */
try {
  var R = [];
  function t(n, f) {
    try {
      var v = f();
      R.push((v === true ? 'PASS' : (v === false ? 'FAIL' : 'INFO')) + ' | ' + n +
             (v === true || v === false ? '' : ' :: ' + v));
    } catch (e) { R.push('ERR  | ' + n + ' :: ' + (e && e.message)); }
  }
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending';
  document.body.appendChild(o);
  function dump() { o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n'; }

  document.querySelector('#viewsw .vs[data-view="lit"]').click();
  t('Markdown 标题转成富文本标题', function () {
    var h = textToHtml('# 第一章\n\n正文。\n\n## 小节\n\n继续。');
    return h.indexOf('<h1>第一章</h1>') >= 0 && h.indexOf('<h2>小节</h2>') >= 0;
  });
  var list = [
    {title: '第一章', html: '<h1>第一章</h1><p>甲一。</p><p>甲二。</p>'},
    {title: '第二章', html: '<h1>第二章</h1><p>乙一。</p>'},
    {title: '第三章', html: '<h1>第三章</h1><p>丙一。</p>'}
  ];
  t('进入文学分章窗口', function () { return enterLitWindowed({list: list}) === true; });
  t('文学窗口状态独立为真', function () { return LIT_WINDOWED === true && LIT_DOC.count === 3; });
  t('章导航出现', function () {
    var b = document.querySelector('#litchapbar');
    return b && b.style.display !== 'none';
  });
  t('编辑区只装第一章', function () { return /第一章/.test(lta.html()) && !/第二章/.test(lta.html()); });
  t('当前章节信息会随请求发送', function () {
    var c = litChapterInfo();
    return c && c.index === 1 && c.count === 3 && c.title === '第一章';
  });
  t('全文阅读状态有可见入口', function () { return !!document.querySelector('#lread'); });

  lta.quill.setSelection(2, 0);
  t('文学光标起点保留', function () { return lta.selectionStart === 2 && lta.selectionEnd === 2; });
  lta.quill.setSelection(2, 2);
  t('文学选区终点保留', function () { return lta.selectionStart === 2 && lta.selectionEnd === 4; });
  var sel = selectionPayload(lta);
  t('选区原文送给后端', function () { return sel.start === 2 && sel.end === 4 && sel.text.length === 2; });

  showLitChapter(1);
  t('切到第二章', function () {
    return LIT_DOC.index === 1 && /第二章/.test(lta.html()) && !/第一章/.test(lta.html());
  });
  t('窗口化目录指向全文', function () {
    TOC.refresh();
    var hs = tocEd.headings() || [];
    return hs.length === 3 && hs[1].chapter === 1 && hs[2].text === '第三章';
  });
  t('导出拿全文而不是当前章', function () {
    var p = expPayload('doc');
    return p && p.text.indexOf('甲一') >= 0 && p.text.indexOf('丙一') >= 0 && p.html.indexOf('第三章') >= 0;
  });

  document.querySelector('#viewsw .vs[data-view="write"]').click();
  t('切回写作不串文学文档', function () { return LIT_DOC.index === 1; });
  dump();
} catch (e) {
  var x = document.createElement('pre'); x.id = 'VR';
  x.textContent = '\n===VR-START===\nFATAL ' + (e && e.message) + '\n===VR-END===\n';
  document.body.appendChild(x);
}

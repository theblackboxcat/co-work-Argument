/* ② 文学视图富文本统一 —— 一次性验收探针。跑完把结果写进 #VR，headless 抓 --dump-dom 读。 */
(function () {
  var R = [];
  function pre(id) { var e = document.getElementById(id); return e ? e.textContent.trim() : '<missing>'; }
  function t(name, fn) {
    try {
      var v = fn();
      // 字符串返回＝**失败诊断**（老写法 `return cond ? true : '诊断'`），不是 INFO。
      // 之前记成 INFO 且不计失败，于是这类断言**永远不会红**。见 工程路径与技术回顾 §六·22。
      R.push((v === true ? 'PASS' : (v === false || (typeof v === 'string' && v) ? 'FAIL' : 'INFO')) + ' | ' + name + (v === true || v === false ? '' : ' :: ' + v));
    } catch (e) { R.push('ERR  | ' + name + ' :: ' + (e && e.message)); }
  }
  function click(sel) { var e = document.querySelector(sel); if (!e) throw new Error('no ' + sel); e.click(); return e; }

  try { (function () {
    /* ---- 1. 地基 ---- */
    t('EditorController 已加载', function () { return typeof EditorController === 'object' && typeof EditorController.create === 'function'; });
    t('两个编辑器都起了 Quill', function () { return !!(ta.quill && lta.quill); });
    t('两个编辑器根元素不同', function () { return ta.root !== lta.root && !!ta.root && !!lta.root; });
    t('两个根元素都是 contenteditable', function () {
      return ta.root.getAttribute('contenteditable') === 'true' && lta.root.getAttribute('contenteditable') === 'true';
    });
    t('文学材料框已挂 .ql-editor', function () { return !!document.querySelector('#lta .ql-editor'); });
    t('文学工具条 #lfmtbar 存在且有按钮', function () { return document.querySelectorAll('#lfmtbar button').length >= 5; });
    t('文学工具条含块样式 h1-h3', function () {
      var s = document.querySelector('#lfmtbar select[data-block]');
      if (!s) return 'no select[data-block]';
      var vs = Array.prototype.map.call(s.options, function (o) { return o.value; }).join(',');
      return vs.indexOf('h1') >= 0 && vs.indexOf('h2') >= 0 && vs.indexOf('h3') >= 0 ? true : 'options=' + vs;
    });
    t('伴写工具条未被隐藏', function () { return document.getElementById('fmtbar').style.display !== 'none'; });

    /* ---- 2. 切到文学视图 ---- */
    click('#viewsw .vs[data-view="lit"]');
    t('切到文学视图后 VIEW==="lit"', function () { return VIEW === 'lit'; });
    t('文学视图面板可见', function () { return document.getElementById('litmain').style.display !== 'none'; });
    t('tocEd 路由到 lta', function () { return tocEd.ed === lta; });

    /* ---- 3. E3：lput 保格式 + expPayload 交 html ---- */
    lta.value = '';
    lput('', null, { html: '<h2>小标题</h2><p><strong>粗体</strong>与<em>斜体</em></p>' });
    var h1 = lta.html();
    t('lput(html) 保住 h2', function () { return h1.indexOf('<h2') >= 0; });
    t('lput(html) 保住 strong/em', function () { return h1.indexOf('<strong') >= 0 && h1.indexOf('<em') >= 0; });
    t('lput 仍给纯文本 value', function () { return lta.value.indexOf('粗体') >= 0; });

    lput('', null, { html: '<p>第二段</p>' });
    var h2 = lta.html();
    t('lput 累加：旧内容还在（不覆盖）', function () { return h2.indexOf('小标题') >= 0 && h2.indexOf('第二段') >= 0; });
    t('lput 累加：新内容另起一段（不粘连）', function () {
      var blocks = (h2.match(/<(p|h1|h2|h3)\b/g) || []).length;
      return blocks >= 3 ? true : '块数=' + blocks + ' html=' + h2;
    });
    t('lput 累加：不再依赖 <hr>（这份 Quill 无 divider）', function () {
      return h2.indexOf('hr') < 0;
    });

    var pl = expPayload('doc');
    t('E3 文学侧 expPayload 交出 html', function () { return !!(pl && pl.html && pl.html.indexOf('<') >= 0); });
    t('E3 文学侧 expPayload 仍有 text', function () { return !!(pl && pl.text && pl.text.indexOf('第二段') >= 0); });
    t('expPayload 名带「材料」', function () { return pl && pl.name ? pl.name.indexOf('材料') >= 0 : 'no name'; });

    /* ---- 4. E3 连带：epub 按钮在文学视图亮起 ---- */
    t('epub 门控在文学侧放行（needs: p.html）', function () { return expCapable('epub', pl) === null; });
    t('docx/md/txt 门控同样放行', function () {
      return expCapable('docx', pl) === null && expCapable('md', pl) === null && expCapable('txt', pl) === null;
    });
    t('纯文本材料仍会被 epub 拦下', function () {
      return typeof expCapable('epub', { html: null, text: 'x' }) === 'string';
    });
    t('expAvail().doc 在文学侧为真', function () { return expAvail().doc === true; });
    try {
      expRefresh();
      var eb = EXPM.querySelector('button[data-fmt="epub"]');
      t('导出菜单 epub 按钮未置灰', function () { return eb && eb.disabled === false; });
    } catch (e) { R.push('ERR  | expRefresh :: ' + e.message); }

    /* ---- 5. 目录按视图路由 ---- */
    t('TOC 面板已建', function () { return !!TOC && typeof TOC.refresh === 'function'; });
    t('tocEd.html() 拿的是文学侧', function () { return tocEd.html().indexOf('小标题') >= 0; });

    /* ---- 6. E10 / R16：暂停指示器 ---- */
    paused = false; syncPause();
    t('未暂停：按钮写「暂停」', function () { return pre('pause') === '暂停'; });
    t('未暂停：pstate 写「待命」', function () { return pre('pstate') === '待命'; });
    t('未暂停：dot 带 live', function () { return document.getElementById('dot').classList.contains('live'); });
    t('未暂停：hint 写明停止输入后的触发规则', function () {
      return /停止输入 \d+ 秒后(?:触发|，把这一处交给它看一眼)/.test(pre('hint'));
    });

    click('#pause');
    t('暂停后：按钮写「已暂停」', function () { return pre('pause') === '已暂停'; });
    t('暂停后：pstate 写「已暂停」', function () { return pre('pstate') === '已暂停'; });
    t('暂停后：hint 写「已暂停」', function () { return pre('hint') === '已暂停'; });
    t('暂停后：dot 不带 live', function () { return !document.getElementById('dot').classList.contains('live'); });

    click('#viewsw .vs[data-view="write"]');
    t('R16 切视图不改 paused', function () { return paused === true; });
    t('R16 切视图后指示器一致', function () { return pre('pause') === '已暂停' && pre('pstate') === '已暂停'; });
    click('#viewsw .vs[data-view="lit"]');
    t('R16 切回文学仍一致', function () { return paused === true && pre('pause') === '已暂停'; });
    click('#pause');
    t('取消暂停后回「待命」', function () { return paused === false && pre('pstate') === '待命'; });

    /* ---- 7. touch() 的 VIEW 门 ---- */
    paused = false;
    if (timer) clearTimeout(timer);
    timer = null; syncPause();
    var hint0 = pre('hint');
    touch();
    t('文学视图里 touch() 不拉起探针（timer 仍空）', function () { return timer === null; });
    t('文学视图里 touch() 不改 hint', function () { return pre('hint') === hint0; });
    click('#viewsw .vs[data-view="write"]');
    if (timer) clearTimeout(timer);
    timer = null;
    touch();
    t('伴写视图里 touch() 照常拉起（timer 已挂）', function () { return timer !== null; });
    if (timer) clearTimeout(timer);

    /* ---- 8. 写作侧回归 ---- */
    ta.value = '回归测试一句话';
    t('写作侧 value 读写正常', function () { return ta.value.indexOf('回归测试') >= 0; });
    t('quillText() 拿得到', function () { return quillText().indexOf('回归测试') >= 0; });
    t('docHtml() 有标签', function () { return docHtml().indexOf('<') >= 0; });
    t('写作侧 #count 有值', function () { return /\d/.test(pre('count')) ? true : pre('count'); });
    t('写作侧 expPayload 仍交 html', function () { var p = expPayload('doc'); return !!(p && p.html); });
    t('写作侧 tocEd 路由回 ta', function () { return tocEd.ed === ta; });

    /* ---- 9. 富文本写操作 ---- */
    try {
      ta.quill.setText('加粗这一段');
      ta.quill.setSelection(0, 3);
      ta.format('bold', true);
      t('写作侧加粗生效', function () { return ta.html().indexOf('<strong') >= 0; });
      ta.quill.setSelection(ta.value.length, 0);
      ta.format('bold', false);
    } catch (e) { R.push('ERR  | 加粗 :: ' + e.message); }
    try {
      lta.setRichDoc('<h1>一级</h1><h2>二级</h2><p>正文</p>');
      t('文学侧 setRichDoc 保住标题层级', function () {
        var h = lta.html(); return h.indexOf('<h1') >= 0 && h.indexOf('<h2') >= 0;
      });
      t('文学侧 applyHeadingToText 可用', function () {
        lta.applyHeadingToText('正文');
        return lta.html().indexOf('<h') >= 0;
      });
    } catch (e) { R.push('ERR  | setRichDoc :: ' + e.message); }

    /* ---- 10. 错误收集 ---- */
    t('页面无 JS 运行时错误', function () { return (window.__errs || []).length === 0 ? true : (window.__errs || []).join(' / '); });

    var out = document.createElement('pre');
    out.id = 'VR';
    out.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n';
    document.body.appendChild(out);
  })(); } catch (e) {
    var o2 = document.createElement('pre'); o2.id = 'VR';
    o2.textContent = '\n===VR-START===\nFATAL :: ' + (e && e.message) + '\n' + R.join('\n') + '\n===VR-END===\n';
    document.body.appendChild(o2);
  }
})();

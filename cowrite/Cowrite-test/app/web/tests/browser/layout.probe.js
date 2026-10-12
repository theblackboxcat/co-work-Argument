/* 布局探针（异步：等 CSS 过渡走完再测命中，否则量到的是抽屉飞行中的 rect） */
try {
  var R = [];
  function t(n, f) {
    // 字符串返回＝**失败诊断**，不是 INFO（见 工程路径与技术回顾 §六·22）。
    try { var v = f(); R.push((v === true ? 'PASS' : (v === false || (typeof v === 'string' && v) ? 'FAIL' : 'INFO')) + ' | ' + n + (v === true || v === false ? '' : ' :: ' + v)); }
    catch (e) { R.push('ERR  | ' + n + ' :: ' + (e && e.message)); }
  }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function rect(el) { var r = el.getBoundingClientRect(); return { t: Math.round(r.top), l: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) }; }
  function inView(el) {
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.top >= 0 && r.bottom <= (window.innerHeight + 1) && r.left >= 0 && r.right <= (window.innerWidth + 1);
  }
  function hitIs(el) {
    var r = el.getBoundingClientRect();
    var e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (e === el || el.contains(e) || (e && e.contains(el))) return true;
    return (e ? e.tagName + '#' + e.id + '.' + e.className : 'null') + ' @' + JSON.stringify(rect(el));
  }
  function closeBtn() {
    return Array.prototype.filter.call(document.querySelectorAll('#tocdrawer button'),
      function (b) { return /收起|关闭/.test(b.textContent); })[0];
  }
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending';
  document.body.appendChild(o);

  (function () {
    var vw = window.innerWidth;
    document.querySelector('#viewsw .vs[data-view="write"]').click();
    ta.setRichDoc('<h1>第一章</h1><p>正文一</p><h2>一节</h2><p>正文二</p><h1>第二章</h1><p>正文三</p>');
    /* headless 的虚拟时间不推进 CSS transition，抽屉会一直停在飞行中的 rect 上；
       关掉过渡，量到的就是终态。这只是测量手段，不碰产品样式。 */
    document.getElementById('tocdrawer').style.transition = 'none';
    var tb = document.getElementById('tocbtn');

    t('[' + vw + '] 目录按钮在视口内', function () { return inView(tb) ? true : JSON.stringify(rect(tb)); });
    t('[' + vw + '] 目录按钮可点（未遮挡）', function () { return hitIs(tb); });

    TOC.toggle();
    return wait(400).then(function () {
      t('[' + vw + '] 抽屉打开后目录按钮仍可点', function () { return hitIs(tb); });
      var cb = closeBtn();
      t('[' + vw + '] 抽屉「收起」按钮在视口内且可点', function () {
        return cb ? (inView(cb) ? hitIs(cb) : 'off-view ' + JSON.stringify(rect(cb))) : 'no close btn';
      });
      t('[' + vw + '] 抽屉已滑进视口', function () { var r = rect(document.getElementById('tocdrawer')); return r.l >= 0 ? true : JSON.stringify(r); });
      if (cb) cb.click();
      return wait(400).then(function () {
        t('[' + vw + '] 点「收起」后抽屉关闭', function () { return !document.getElementById('tocdrawer').classList.contains('on'); });
        t('[' + vw + '] 写作区底栏在视口内', function () { var b = document.querySelector('#writemain .write .bar'); return inView(b) ? true : JSON.stringify(rect(b)); });

        /* ---- 文学视图 ---- */
        document.querySelector('#viewsw .vs[data-view="lit"]').click();
        lta.setRichDoc('<h1>材料一</h1><p>甲</p><h2>小节</h2><p>乙</p>');
        return wait(400).then(function () {
          t('[' + vw + '] 文学视图：目录按钮已搬进当前视图', function () {
            return document.querySelector('#litmain .bar') && document.querySelector('#litmain .bar').contains(tb) ? true : 'parent=' + (tb.parentNode && tb.parentNode.className);
          });
          t('[' + vw + '] 文学视图：目录按钮在视口内', function () { return inView(tb) ? true : JSON.stringify(rect(tb)); });
          t('[' + vw + '] 文学视图：目录按钮可点', function () { return hitIs(tb); });
          t('[' + vw + '] 文学视图：抽屉已搬进文学区', function () {
            return document.querySelector('#litmain > .write').contains(document.getElementById('tocdrawer'));
          });
          TOC.toggle();
          return wait(400).then(function () {
            t('[' + vw + '] 文学视图：抽屉打开后按钮仍可点', function () { return hitIs(tb); });
            var cb2 = closeBtn();
            t('[' + vw + '] 文学视图：「收起」可点', function () {
              if (!cb2) return 'no close btn';
              if (!inView(cb2)) return 'off-view btn=' + JSON.stringify(rect(cb2)) + ' drawer=' + JSON.stringify(rect(document.getElementById('tocdrawer'))) + ' host=' + JSON.stringify(rect(document.querySelector('#litmain > .write'))) + ' vh=' + window.innerHeight;
              return hitIs(cb2);
            });
            t('[' + vw + '] 文学视图：目录列出了材料里的标题', function () {
              var txt = document.getElementById('tocdrawer').textContent;
              return /材料一/.test(txt) ? true : 'drawer text=' + txt.slice(0, 60);
            });
            if (cb2) cb2.click();
            return wait(300).then(function () {
              var lb = document.getElementById('lfmtbar');
              t('[' + vw + '] 文学工具条在视口内', function () { return inView(lb) ? true : JSON.stringify(rect(lb)); });
              t('[' + vw + '] 文学编辑区有高度', function () { var r = rect(document.getElementById('lta')); return r.h > 60 ? true : JSON.stringify(r); });
              t('[' + vw + '] 文学区底栏在视口内', function () { var b = document.querySelector('#litmain .write .bar'); return b && inView(b) ? true : 'no'; });

              /* 切回伴写，确认搬回去了 */
              document.querySelector('#viewsw .vs[data-view="write"]').click();
              return wait(300).then(function () {
                t('[' + vw + '] 切回伴写：目录按钮搬回写作区', function () {
                  return document.querySelector('#writemain .bar').contains(tb);
                });
                t('[' + vw + '] 切回伴写：抽屉搬回写作区', function () {
                  return document.querySelector('#writemain > .write').contains(document.getElementById('tocdrawer'));
                });
                /* 纸张尺寸 */
                try { pageDialog(); } catch (e) { R.push('ERR  | pageDialog :: ' + e.message); }
                t('纸张尺寸下拉无 %s/%d 残留', function () {
                  var sel = document.getElementById('pg-size');
                  if (!sel) return 'no #pg-size';
                  var txt = Array.prototype.map.call(sel.options, function (x) { return x.textContent; }).join(' | ');
                  return /%[sd]/.test(txt) ? '残留：' + txt : true;
                });
                t('纸张尺寸选项带 mm', function () {
                  var sel = document.getElementById('pg-size');
                  if (!sel) return 'no select';
                  var txt = Array.prototype.map.call(sel.options, function (x) { return x.textContent; }).join(' | ');
                  return /210.*297/.test(txt) ? true : txt;
                });
              });
            });
          });
        });
      });
    });
  })().catch(function (e) { R.push('FATAL ' + (e && e.message)); })
    .then(function () { o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n'; });
} catch (e) {
  var o2 = document.createElement('pre'); o2.id = 'VR';
  o2.textContent = '\n===VR-START===\nFATAL ' + (e && e.message) + '\n===VR-END===\n';
  document.body.appendChild(o2);
}

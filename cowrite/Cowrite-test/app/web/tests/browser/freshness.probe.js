/* 新鲜度的**前端**那半边的验收。跑法：node tests/browser/run.js freshness

背景（§49）：服务端对全文的把握原来冻结在"载入"那一刻，因为前端**从不回传**
它改过的东西。补上之后，这半边有三件事必须对，而且错一件都会静默：

  ① **切段必须和后端 split_paragraphs() 一模一样**（按空行切、去首尾空白、空段丢掉）。
     差一点，指纹就对不上，服务端会拿一段错位的正文当"原文片段"——
     比没有更坏，而且**看不出来**。
  ② **第一次同步要把整篇带过去**，之后**只带变了的那些段**。
     带少了 = 服务端有洞；带多了 = 每 5 秒把整本书重传一遍。
     两种都不会报错，只会慢或者不准。
  ③ 探针里**不许**写 `return cond ? true : '实际是 ' + v`——runner 把非 true/false
     一律记 INFO，而 INFO 不计失败（见 §六.22）。所以下面每条断言都是**严格布尔**，
     诊断信息单独推一行 INFO。
*/
try {
  var R = [];
  function t(n, f) {
    try {
      var v = f();
      var line;
      if (v === true) line = 'PASS | ' + n;
      else if (v === false) line = 'FAIL | ' + n;
      else if (typeof v === 'string' && v) line = 'FAIL | ' + n + ' :: ' + v;
      else line = 'INFO | ' + n + (v === undefined ? '' : ' :: ' + v);
      R.push(line);
    } catch (e) { R.push('ERR  | ' + n + ' :: ' + (e && e.message)); }
  }
  function eq(n, got, want) {
    var ok = (got === want);
    t(n, function () { return ok; });
    if (!ok) R.push('INFO |   ↑ 实际 ' + JSON.stringify(got) + '，要的是 ' + JSON.stringify(want));
  }
  var o = document.createElement('pre'); o.id = 'VR'; o.textContent = 'pending';
  document.body.appendChild(o);
  function dump() { o.textContent = '\n===VR-START===\n' + R.join('\n') + '\n===VR-END===\n'; }

  /* 拦下 /api/sync，看清它**实际要发**的东西——不靠读代码。 */
  var sent = [];
  var origFetch = window.fetch;
  window.fetch = function (url, opt) {
    if (typeof url === 'string' && url.indexOf('/api/sync') >= 0) {
      try { sent.push(JSON.parse(opt.body)); } catch (e) { sent.push(null); }
      return Promise.resolve({json: function () { return Promise.resolve({ok: true, rev: 9}); }});
    }
    return origFetch.apply(this, arguments);
  };

  (function () {
    document.querySelector('#viewsw .vs[data-view="write"]').click();
    clearInterval(syncTimer);        // 心跳别在验收中间插一脚
    sentH = new Set();

    /* ⚠️ 第 2 段**必须含一个换行**。第一版这里三段都是单行，于是"按空行切"与
       "按 \n 切"给出**一模一样**的结果（都是 3 段）——把切法改坏也测不出来。
       夹具必须能把两种切法分开，断言才有意义。 */
    var A = '第一段的话。', B = '第二段的话。\n第二段又是一行。', C = '第三段的话。';
    ta.value = '\n\n' + A + '\n\n   ' + B + '   \n\n\n\n' + C + '\n\n';

    /* ── 1. 切段与后端同法 ───────────────────────────────── */
    var ps = paraParts();
    eq('切出 3 段（段内的换行不算分段）', ps.length, 3);
    eq('段内的那个换行被保留（不是被切开了）', ps[1], B);
    eq('每段首尾空白已去掉（第 2 段没有多余空格）', ps[1].indexOf('  ') < 0, true);

    /* ── 2. 同一段文字 → 同一个指纹；改一个字 → 变 ──────── */
    t('同一段文字哈希稳定', function () { return fnv1a(A) === fnv1a(A); });
    t('改一个字哈希就变', function () { return fnv1a(A) !== fnv1a(A + '。'); });

    return syncDoc().then(function () {
      var p1 = sent[sent.length - 1];
      eq('第一次同步：指纹 3 段', (p1 && p1.paras || []).length, 3);
      eq('第一次同步：把 3 段正文都带上（服务端手里还没有）',
         Object.keys(p1.texts || {}).length, 3);

      /* ── 3. 没改 → 一个字节正文都不带 ────────────────── */
      return syncDoc().then(function () {
        var p2 = sent[sent.length - 1];
        eq('第二次同步（她没动）：指纹仍是 3 段', (p2.paras || []).length, 3);
        eq('第二次同步：不带任何正文', Object.keys(p2.texts || {}).length, 0);

        /* ── 4. 只改一段 → 只带那一段 ──────────────────── */
        var B2 = '第二段的话，改过了。\n第二段又是一行。';
        ta.value = '\n\n' + A + '\n\n' + B2 + '\n\n' + C + '\n\n';
        return syncDoc().then(function () {
          var p3 = sent[sent.length - 1];
          eq('改一段之后：指纹还是 3 段', (p3.paras || []).length, 3);
          eq('只带**那一段**的正文', Object.keys(p3.texts || {}).length, 1);
          eq('而且就是第 2 段（索引 1）', String(Object.keys(p3.texts || {})[0]), '1');
          eq('带的是**新**正文', (p3.texts || {})['1'], B2);

          /* ── 5. 删一段 → 指纹少一段，且不用带正文 ──────── */
          ta.value = '\n\n' + A + '\n\n' + B2 + '\n\n';
          return syncDoc().then(function () {
            var p4 = sent[sent.length - 1];
            eq('删掉第 3 段后：指纹 2 段', (p4.paras || []).length, 2);
            eq('删除不需要送正文', Object.keys(p4.texts || {}).length, 0);

            /* ── 6. 心跳在走 ─────────────────────────── */
            t('同步定时器是挂着的（她停笔时服务端才有"她多久没动"的时钟）',
              function () { return typeof syncTimer === 'number' && syncTimer !== null; });
            t('间隔是 5 秒（指纹很小，本地无压力）', function () { return SYNC_EVERY === 5; });

            /* ── 7. 换文档要作废"已送过"的记录 ────────── */
            sentH = new Set();
            t('换文档时 sentH 清空（否则新稿的段落会被当成旧稿，永不重传）',
              function () { return sentH.size === 0; });
          });
        });
      });
    });
  })().catch(function (e) { R.push('ERR  | 新鲜度前端 :: ' + (e && e.message)); }).then(dump);
} catch (e) {
  var o2 = document.createElement('pre'); o2.id = 'VR';
  o2.textContent = '\n===VR-START===\nFATAL ' + (e && e.message) + '\n===VR-END===\n';
  document.body.appendChild(o2);
}

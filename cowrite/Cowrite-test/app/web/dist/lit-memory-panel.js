/* ============================================================================
 * LitMemoryPanel v1.0.0
 * 记忆管理面板：记忆库（分组/编辑/作废/删除）、章节记录、召回预览、JSON 导入导出。
 * 依赖 LitMemoryCore。作用域前缀 .lm-，不污染宿主页面。
 * ==========================================================================*/
(function (global) {
  'use strict';

  var KIND_LABELS = { world: '世界观', character: '角色', plot: '剧情', foreshadow: '伏笔', style: '风格', reflection: '复盘规则' };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var CSS = [
    '.lm-root{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#23272f;font-size:13px;line-height:1.6;display:flex;flex-direction:column;height:100%;min-height:320px;background:#fff;}',
    '.lm-head{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #e3e8ef;flex-wrap:wrap;}',
    '.lm-title{font-weight:700;font-size:14px;}',
    '.lm-stats{color:#8a94a6;font-size:12px;flex:1;}',
    '.lm-btn{appearance:none;border:1px solid #d5dbe5;background:#fff;border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer;color:#23272f;}',
    '.lm-btn:hover{background:#f0f4fa;}',
    '.lm-btn.primary{background:#1664ff;border-color:#1664ff;color:#fff;}',
    '.lm-btn.primary:hover{background:#0f55e8;}',
    '.lm-btn.small{padding:2px 7px;font-size:11px;}',
    '.lm-tabs{display:flex;gap:4px;padding:0 14px;border-bottom:1px solid #e3e8ef;background:#fafbfc;}',
    '.lm-tab{padding:8px 12px;cursor:pointer;color:#5b6472;border-bottom:2px solid transparent;font-size:13px;}',
    '.lm-tab.active{color:#1664ff;border-bottom-color:#1664ff;font-weight:600;}',
    '.lm-body{flex:1;overflow:auto;padding:12px 14px;}',
    '.lm-empty{color:#8a94a6;text-align:center;padding:36px 0;font-size:12px;}',
    '.lm-group{margin-bottom:16px;}',
    '.lm-group-title{font-size:12px;font-weight:700;color:#5b6472;margin:10px 0 6px;display:flex;align-items:center;gap:6px;}',
    '.lm-count{color:#aab2c0;font-weight:400;}',
    '.lm-card{border:1px solid #e6eaf0;border-radius:10px;padding:9px 11px;margin-bottom:8px;background:#fff;}',
    '.lm-card.superseded{opacity:.5;background:#f6f7f9;}',
    '.lm-card-tag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;margin-right:6px;vertical-align:1px;font-weight:600;}',
    '.lm-card-content{white-space:pre-wrap;word-break:break-word;}',
    '.lm-card-meta{color:#8a94a6;font-size:11px;margin-top:4px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;}',
    '.lm-chip{display:inline-block;background:#eef2f8;color:#5b6472;border-radius:4px;padding:0 6px;font-size:11px;margin:2px 2px 0 0;}',
    '.lm-imp{color:#d9480f;font-weight:600;}',
    '.lm-user{color:#1664ff;font-size:11px;}',
    '.lm-actions{margin-left:auto;display:flex;gap:4px;}',
    '.lm-chapter{border-left:3px solid #1664ff;background:#f7faff;border-radius:6px;padding:8px 10px;margin-bottom:10px;}',
    '.lm-chapter h4{margin:0 0 4px;font-size:13px;}',
    '.lm-chapter .sum{color:#5b6472;font-size:12px;margin-bottom:6px;}',
    '.lm-chapter details{margin-top:6px;font-size:12px;}',
    '.lm-chapter summary{cursor:pointer;color:#1664ff;}',
    '.lm-chapter pre{background:#0f172a;color:#e2e8f0;border-radius:6px;padding:8px;font-size:11px;overflow:auto;white-space:pre-wrap;word-break:break-word;}',
    '.lm-recall-intent{width:100%;border:1px solid #d5dbe5;border-radius:8px;padding:8px;font-size:12px;resize:vertical;min-height:52px;box-sizing:border-box;font-family:inherit;}',
    '.lm-recall-block{background:#0f172a;color:#e2e8f0;border-radius:8px;padding:10px;font-size:12px;white-space:pre-wrap;word-break:break-word;margin-top:10px;max-height:300px;overflow:auto;}',
    '.lm-recall-meta{color:#8a94a6;font-size:11px;margin-top:6px;}',
    '.lm-copy{position:relative;}',
    '.lm-toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:rgba(15,23,42,.92);color:#fff;border-radius:8px;padding:8px 14px;font-size:12px;z-index:9999;max-width:80vw;}',
    '.lm-inline-edit{width:100%;border:1px solid #1664ff;border-radius:6px;padding:6px;font-size:12px;font-family:inherit;box-sizing:border-box;min-height:56px;resize:vertical;}'
  ].join('\n');

  function injectCSS() {
    if (document.getElementById('lm-panel-css')) return;
    var style = document.createElement('style');
    style.id = 'lm-panel-css';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function toast(msg) {
    var el = document.createElement('div');
    el.className = 'lm-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function () {
      el.remove();
    }, 2400);
  }

  function createPanel(container, opts) {
    opts = opts || {};
    var core = opts.core;
    if (!core) throw new Error('LitMemoryPanel: 需要 { core }');
    var onError = opts.onError || function (e) { console.error(e); toast('出错了：' + e.message); };
    var root = document.createElement('div');
    root.className = 'lm-root';
    container.appendChild(root);

    /* ------- 头部 ------- */
    var head = document.createElement('div');
    head.className = 'lm-head';
    var title = document.createElement('div');
    title.className = 'lm-title';
    title.textContent = '文学记忆';
    var stats = document.createElement('div');
    stats.className = 'lm-stats';
    var btnExport = document.createElement('button');
    btnExport.className = 'lm-btn';
    btnExport.textContent = '导出JSON';
    var btnImport = document.createElement('button');
    btnImport.className = 'lm-btn';
    btnImport.textContent = '导入JSON';
    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.json,application/json';
    fileInput.style.display = 'none';
    head.appendChild(title);
    head.appendChild(stats);
    head.appendChild(btnExport);
    head.appendChild(btnImport);
    head.appendChild(fileInput);
    root.appendChild(head);

    /* ------- 标签页 ------- */
    var tabs = document.createElement('div');
    tabs.className = 'lm-tabs';
    var defs = [
      { key: 'cards', label: '记忆库' },
      { key: 'chapters', label: '章节记录' },
      { key: 'recall', label: '召回预览' }
    ];
    var views = {};
    defs.forEach(function (d) {
      var tab = document.createElement('div');
      tab.className = 'lm-tab' + (d.key === 'cards' ? ' active' : '');
      tab.textContent = d.label;
      tab.addEventListener('click', function () {
        Object.keys(views).forEach(function (k) { views[k].style.display = 'none'; });
        document.querySelectorAll('.lm-tab').forEach(function (t) { t.classList.remove('active'); });
        tab.classList.add('active');
        views[d.key].style.display = 'block';
      });
      tabs.appendChild(tab);
      var view = document.createElement('div');
      view.className = 'lm-body';
      view.style.display = d.key === 'cards' ? 'block' : 'none';
      root.appendChild(view);
      views[d.key] = view;
    });
    root.insertBefore(tabs, views.cards);

    /* ------- 导出 / 导入 ------- */
    btnExport.addEventListener('click', function () {
      core.exportJSON().then(function (json) {
        var blob = new Blob([json], { type: 'application/json' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'lit-memory-' + Date.now() + '.json';
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 200);
      }).catch(onError);
    });
    btnImport.addEventListener('click', function () { fileInput.click(); });
    fileInput.addEventListener('change', function () {
      var f = fileInput.files && fileInput.files[0];
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () {
        core.importJSON(String(reader.result)).then(function () {
          toast('导入成功');
          refresh();
        }).catch(onError);
      };
      reader.readAsText(f);
      fileInput.value = '';
    });

    /* ------- 渲染函数 ------- */
    function renderStats(s) {
      stats.textContent = (s ? '卡片 ' + s.cards + ' · 活跃 ' + s.active + ' · 未兑现伏笔 ' + s.foreshadowOpen +
        ' · 章节 ' + s.chapters + ' · 用户修订 ' + s.userEdited : '加载中……');
    }

    function renderCards() {
      var v = views.cards;
      v.innerHTML = '';
      core.getState().then(function (state) {
        var cards = state.cards.slice().sort(function (a, b) {
          if (a.status !== b.status) return a.status === 'active' ? -1 : 1;
          if (a.kind !== b.kind) return kindOrder(a.kind) - kindOrder(b.kind);
          return b.importance - a.importance;
        });
        if (!cards.length) {
          var e = document.createElement('div');
          e.className = 'lm-empty';
          e.textContent = '还没有记忆。写完一章点「运行复盘」，或手动添加设定卡。';
          v.appendChild(e);
          return;
        }
        var groups = {};
        cards.forEach(function (c) { (groups[c.kind] = groups[c.kind] || []).push(c); });
        Object.keys(groups).sort(function (a, b) { return kindOrder(a) - kindOrder(b); }).forEach(function (kind) {
          var g = document.createElement('div');
          g.className = 'lm-group';
          var gt = document.createElement('div');
          gt.className = 'lm-group-title';
          gt.innerHTML = esc(KIND_LABELS[kind] || kind) + ' <span class="lm-count">' + groups[kind].length + '</span>';
          g.appendChild(gt);
          groups[kind].forEach(function (c) { g.appendChild(cardEl(c)); });
          v.appendChild(g);
        });
      }).catch(onError);
    }

    function kindOrder(k) { return ['world', 'character', 'plot', 'foreshadow', 'style', 'reflection'].indexOf(k); }

    function cardEl(c) {
      var el = document.createElement('div');
      el.className = 'lm-card' + (c.status === 'superseded' ? ' superseded' : '');
      var tags = [];
      var tagColor = { world: '#e3f0ff', character: '#e6f7ee', plot: '#fef3e2', foreshadow: '#fdeaea', style: '#f0edff', reflection: '#eef2f8' };
      var tagText = { world: '#0b66c3', character: '#0f8a5f', plot: '#b45a0a', foreshadow: '#c0392b', style: '#5f4bd8', reflection: '#5b6472' };
      var bg = tagColor[c.kind] || '#eef2f8', fg = tagText[c.kind] || '#5b6472';
      tags.push('<span class="lm-card-tag" style="background:' + bg + ';color:' + fg + ';">' + esc(KIND_LABELS[c.kind] || c.kind) + '</span>');
      if (c.userEdited) tags.push('<span class="lm-user">已修订</span>');
      if (c.status === 'superseded') tags.push('<span class="lm-card-tag" style="background:#eceff3;color:#8a94a6;">已作废</span>');

      var contentDiv = document.createElement('div');
      contentDiv.className = 'lm-card-content';
      contentDiv.textContent = c.content;

      var meta = document.createElement('div');
      meta.className = 'lm-card-meta';
      meta.innerHTML = '<span class="lm-imp">重要度 ' + c.importance + '</span>' +
        '<span>章节 ' + (c.chapter || '-') + '</span>' +
        '<span>v' + (c.version || 1) + '</span>' +
        c.keywords.map(function (k) { return '<span class="lm-chip">' + esc(k) + '</span>'; }).join('') +
        (c.note ? '<span style="color:#8a94a6;">' + esc(c.note) + '</span>' : '');

      var actions = document.createElement('div');
      actions.className = 'lm-actions';
      var btnEdit = mkBtn('编辑', 'small');
      var btnStatus = mkBtn(c.status === 'active' ? '作废' : '恢复', 'small');
      var btnDel = mkBtn('删除', 'small');
      actions.appendChild(btnEdit);
      actions.appendChild(btnStatus);
      actions.appendChild(btnDel);

      btnEdit.addEventListener('click', function () {
        var ta = document.createElement('textarea');
        ta.className = 'lm-inline-edit';
        ta.value = c.content;
        var saveBtn = mkBtn('保存', 'small');
        var cancelBtn = mkBtn('取消', 'small');
        contentDiv.replaceWith(ta);
        var bar = document.createElement('div');
        bar.style.marginTop = '6px';
        bar.appendChild(saveBtn);
        bar.appendChild(cancelBtn);
        actions.replaceWith(bar);
        ta.focus();
        saveBtn.addEventListener('click', function () {
          core.editCard(c.id, { content: ta.value }).then(function () { refresh(); toast('已保存（标记为你的修订）'); }).catch(onError);
        });
        cancelBtn.addEventListener('click', function () { refresh(); });
      });
      btnStatus.addEventListener('click', function () {
        core.setStatus(c.id, c.status === 'active' ? 'superseded' : 'active').then(refresh).catch(onError);
      });
      btnDel.addEventListener('click', function () {
        if (!confirm('删除这条记忆？')) return;
        core.deleteCard(c.id).then(function () { refresh(); }).catch(onError);
      });

      el.appendChild(divFromHTML(tags.join('')));
      el.appendChild(contentDiv);
      el.appendChild(meta);
      el.appendChild(actions);
      return el;
    }

    function renderChapters() {
      var v = views.chapters;
      v.innerHTML = '';
      core.getState().then(function (state) {
        if (!state.chapters.length) {
          var e = document.createElement('div');
          e.className = 'lm-empty';
          e.textContent = '还没有章节记录。';
          v.appendChild(e);
          return;
        }
        state.chapters.slice().reverse().forEach(function (c) {
          var el = document.createElement('div');
          el.className = 'lm-chapter';
          var h = document.createElement('h4');
          h.textContent = '第 ' + c.number + ' 章 · ' + c.title + '（记忆 ' + (c.cardCount || 0) + ' 条）';
          var sum = document.createElement('div');
          sum.className = 'sum';
          sum.textContent = c.summary;
          var det = document.createElement('details');
          var s = document.createElement('summary');
          s.textContent = '查看复盘 JSON';
          var pre = document.createElement('pre');
          pre.textContent = JSON.stringify(c.review, null, 2);
          det.appendChild(s);
          det.appendChild(pre);
          el.appendChild(h);
          el.appendChild(sum);
          el.appendChild(det);
          v.appendChild(el);
        });
      }).catch(onError);
    }

    function renderRecall() {
      var v = views.recall;
      v.innerHTML = '';
      var label = document.createElement('div');
      label.style.cssText = 'font-size:12px;color:#5b6472;margin-bottom:6px;';
      label.textContent = '输入接下来要写的内容意图，生成「开写前召回」注入块（可直接前置到大模型提示词）：';
      var ta = document.createElement('textarea');
      ta.className = 'lm-recall-intent';
      ta.placeholder = '例如：沈砚决定夜探藏经阁，发现残页与铜铃有关……';
      var btnRow = document.createElement('div');
      btnRow.style.marginTop = '8px';
      var genBtn = mkBtn('生成召回', 'primary');
      genBtn.className += ' lm-gen';
      var copyBtn = mkBtn('复制注入块', '');
      var meta = document.createElement('div');
      meta.className = 'lm-recall-meta';
      var block = document.createElement('div');
      block.className = 'lm-recall-block';
      block.style.display = 'none';
      btnRow.appendChild(genBtn);
      btnRow.appendChild(copyBtn);
      v.appendChild(label);
      v.appendChild(ta);
      v.appendChild(btnRow);
      v.appendChild(meta);
      v.appendChild(block);

      genBtn.addEventListener('click', function () {
        var r = core.prepareRecall({ intent: ta.value });
        block.textContent = r.block;
        block.style.display = 'block';
        meta.textContent = '约 ' + r.chars + ' 字符 / 约 ' + r.tokenEstimate + ' token · 命中 ' + r.usedCards.length +
          ' 条记忆' + (r.droppedParts.length ? ' · 预算裁剪了 ' + r.droppedParts.join('/') : '');
        copyBtn.classList.add('primary');
      });
      copyBtn.addEventListener('click', function () {
        var text = block.textContent;
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () { toast('已复制注入块'); });
        } else {
          var ta2 = document.createElement('textarea');
          ta2.value = text;
          document.body.appendChild(ta2);
          ta2.select();
          try { document.execCommand('copy'); toast('已复制注入块'); } catch (e) { toast('复制失败，请手动选择'); }
          ta2.remove();
        }
      });
    }

    function refresh() {
      core.getStats().then(function (s) {
        renderStats(s);
        if (views.cards.style.display !== 'none') renderCards();
        if (views.chapters.style.display !== 'none') renderChapters();
      }).catch(onError);
    }

    /* ------- 对外 API ------- */
    var panel = {
      refresh: refresh,
      getRoot: function () { return root; },
      /* 运行章节复盘并刷新；text 为章节正文 */
      runChapterReview: function (text, title) {
        return core.runChapterReview({ text: text, title: title }).then(function (res) {
          refresh();
          var msg = '第 ' + res.chapterLog.number + ' 章复盘完成：新增/更新记忆 ' + res.cardResults.filter(function (r) { return r.action !== 'skip'; }).length +
            ' 条' + (res.resolvedIds.length ? '，兑现伏笔 ' + res.resolvedIds.length + ' 条' : '') +
            (res.reflection ? '，触发反思归纳' : '');
          toast(msg);
          return res;
        });
      },
      previewRecall: function (intent) {
        Object.keys(views).forEach(function (k) { views[k].style.display = 'none'; });
        views.recall.style.display = 'block';
        document.querySelectorAll('.lm-tab').forEach(function (t) { t.classList.remove('active'); });
        tabs.children[2].classList.add('active');
        var ta = views.recall.querySelector('textarea');
        if (ta) { ta.value = intent || ''; }
        var gen = views.recall.querySelector('.lm-gen');
        if (gen) gen.click();
      },
      destroy: function () { root.remove(); }
    };

    function mkBtn(text, cls) {
      var b = document.createElement('button');
      b.className = 'lm-btn' + (cls ? ' ' + cls : '');
      b.textContent = text;
      return b;
    }
    function divFromHTML(html) {
      var d = document.createElement('div');
      d.innerHTML = html;
      return d;
    }

    /* 首次渲染 */
    core.getStats().then(function (s) {
      renderStats(s);
      renderCards();
      renderChapters();
      renderRecall();
    }).catch(onError);

    return panel;
  }

  var api = { create: createPanel, _version: '1.0.0' };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.LitMemoryPanel = api;

  injectCSS();
})(typeof window !== 'undefined' ? window : globalThis);

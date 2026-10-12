/* ============================================================================
 * LitMemoryCore v1.0.0
 * 「文学随写随进化」核心：章节复盘提炼 → 记忆去重/合并/冲突处理 → 定期反思
 * → 开写前召回组装。零外部依赖，浏览器与 node 均可运行。
 *
 * 三层对接：模型（OpenAI 兼容 / 演示启发式）+ 存储（LocalStorage / VikingDB /
 * OpenViking，通过统一 Store 接口可插拔）+ 你的网站（导出 LitMemoryCore / LitMemoryPanel）。
 * ==========================================================================*/
(function (global) {
  'use strict';

  var VERSION = '1.0.0';

  /* ============================== 基础工具 ============================== */
  function uid(prefix) {
    return (prefix || 'id') + '_' + Date.now().toString(36) + '_' +
      Math.random().toString(36).slice(2, 8);
  }
  function now() { return new Date().toISOString(); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function arrayUnique(arr) { return arr.filter(function (v, i) { return arr.indexOf(v) === i; }); }
  function norm(s) {
    return String(s || '').replace(/\s+/g, ' ').replace(/[，。！？、；：“”‘’「」『』（）《》【】,.!?;:'"()\[\]<>]/g, '').trim().toLowerCase();
  }
  /* 中文按二元组 + 英文按词切分，用于轻量关键词检索（可替换为向量检索） */
  function cjkTokenize(text) {
    var s = String(text || '');
    var toks = [];
    var en = s.match(/[a-zA-Z0-9_]{2,}/g);
    if (en) toks = toks.concat(en.map(function (w) { return w.toLowerCase(); }));
    var zh = s.replace(/[a-zA-Z0-9_\s]/g, '');
    for (var i = 0; i + 1 < zh.length; i++) toks.push(zh.slice(i, i + 2));
    return arrayUnique(toks);
  }
  /* 粗略 token 估算：中文约 1.6 字符/token */
  function estimateTokens(text) {
    var s = String(text || '');
    var en = (s.match(/[a-zA-Z0-9_]+/g) || []).join(' ').length;
    var zh = s.replace(/[a-zA-Z0-9_\s]/g, '').length;
    return Math.ceil(en / 4 + zh / 1.6);
  }
  function intersect(a, b) {
    return a.filter(function (v) { return b.indexOf(v) >= 0; });
  }
  function truncate(s, n) {
    s = String(s || '');
    return s.length > n ? s.slice(0, n) + '……' : s;
  }

  /* ============================== 常量 ============================== */
  var KINDS = ['world', 'character', 'plot', 'foreshadow', 'style', 'reflection'];
  var KIND_LABELS = {
    world: '世界观', character: '角色', plot: '剧情',
    foreshadow: '伏笔', style: '风格', reflection: '复盘规则'
  };
  function isKind(k) { return KINDS.indexOf(k) >= 0; }

  function defaultConfig() {
    return {
      reflectEvery: 3,                 // 每 N 章自动反思归纳一次；0 = 关闭
      maxRulesPerReflection: 6,
      maxCards: 240,                   // 超出后按重要性淘汰非必要卡片
      chapterExcerptMax: 3000,         // 章节记录只存摘要截断
      recall: {
        maxChars: 3600,                // 召回注入块总预算（字符）
        cardLimit: 8,
        foreshadowLimit: 6,
        styleLimit: 6,
        summaryLimit: 2
      },
      dedup: { minKeywordOverlap: 2 },
      model: { temperature: 0.3 }
    };
  }

  /* ============================== 空项目 ============================== */
  function emptyProject(title) {
    return {
      schema: 'lit-memory/v1',
      id: uid('prj'),
      title: title || '未命名文学项目',
      createdAt: now(),
      updatedAt: now(),
      world: { title: '', premise: '', settings: [] },  // 人工维护的固定世界观总纲
      characters: [],                                   // ['名字|一句话简介', ...]
      cards: [],                                        // MemoryCard[]
      chapters: [],                                     // ChapterLog[]
      nextChapterNumber: 1,
      lastReflection: null
    };
  }

  function normalizeCard(card, chapterNo) {
    var c = card || {};
    var content = String(c.content || '').trim();
    if (!content) return null;
    var kind = isKind(c.kind) ? c.kind : 'plot';
    var keywords = Array.isArray(c.keywords) ? c.keywords.map(String).filter(Boolean) : [];
    if (!keywords.length) keywords = cjkTokenize(content).slice(0, 6);
    return {
      id: c.id || uid('mc'),
      kind: kind,
      content: content,
      keywords: arrayUnique(keywords),
      importance: clamp(parseInt(c.importance, 10) || 5, 1, 10),
      chapter: c.chapter != null ? c.chapter : (chapterNo || 0),
      status: c.status || 'active',                    // active | superseded
      supersededBy: c.supersededBy || null,
      supersedes: Array.isArray(c.supersedes) ? c.supersedes : [],
      userEdited: !!c.userEdited,
      version: c.version || 1,
      note: c.note || '',
      createdAt: c.createdAt || now(),
      updatedAt: now()
    };
  }

  function mergeCard(oldCard, newCard) {
    return {
      id: oldCard.id,
      kind: newCard.kind || oldCard.kind,
      content: newCard.content,
      keywords: arrayUnique((oldCard.keywords || []).concat(newCard.keywords || [])),
      importance: Math.max(oldCard.importance, newCard.importance),
      chapter: newCard.chapter != null ? newCard.chapter : oldCard.chapter,
      status: 'active',
      supersededBy: null,
      supersedes: oldCard.supersedes || [],
      userEdited: oldCard.userEdited,
      version: (oldCard.version || 1) + 1,
      note: oldCard.note || newCard.note || '',
      createdAt: oldCard.createdAt,
      updatedAt: now()
    };
  }

  /* ============================== 去重 / 合并 / 冲突 ==============================
   * 规则（确定性、可解释、测试覆盖）：
   *  1) 与已有记忆内容完全一致 → 合并更新（版本 +1，关键词取并集，重要性取大）
   *  2) 同类别且关键词重叠 ≥ minKeywordOverlap → 合并更新
   *  3) 同类别且新记忆重要性 ≥ 旧记忆 + 3 → 旧记忆作废（superseded），保留新记忆
   *  4) 被用户编辑过的记忆永不自动覆盖/作废（用户反馈回路优先）
   */
  function dedupInsert(state, card, config) {
    var cfg = (config || defaultConfig());
    var c = normalizeCard(card);
    if (!c) return { action: 'skip', card: null, supersededIds: [], note: '空内容' };
    var cards = state.cards;

    /* 规则 1：内容完全相同 */
    for (var i = 0; i < cards.length; i++) {
      var old = cards[i];
      if (norm(old.content) === norm(c.content)) {
        if (old.userEdited) {
          return { action: 'skip', card: old, supersededIds: [], note: '已有用户编辑的同内容记忆，保留用户版本' };
        }
        var m1 = mergeCard(old, c);
        cards[i] = m1;
        return { action: 'update', card: m1, supersededIds: [], note: '内容相同，合并更新' };
      }
    }
    /* 规则 2：同类别 + 关键词重叠 */
    var ck = c.keywords || [];
    for (var j = 0; j < cards.length; j++) {
      var o2 = cards[j];
      if (o2.status !== 'active' || o2.kind !== c.kind) continue;
      var overlap = intersect(o2.keywords || [], ck).length;
      if (overlap >= cfg.dedup.minKeywordOverlap) {
        if (o2.userEdited) {
          return { action: 'skip', card: o2, supersededIds: [], note: '旧记忆已被用户编辑，保留' };
        }
        var m2 = mergeCard(o2, c);
        cards[j] = m2;
        return { action: 'update', card: m2, supersededIds: [], note: '关键词重叠，合并更新' };
      }
    }
    /* 规则 3：重要性冲突 → 作废旧记忆 */
    for (var k = 0; k < cards.length; k++) {
      var o3 = cards[k];
      if (o3.status !== 'active' || o3.userEdited || o3.kind !== c.kind) continue;
      if (c.importance - o3.importance >= 3) {
        o3.status = 'superseded';
        o3.supersededBy = c.id;
        o3.updatedAt = now();
        c.supersedes = (c.supersedes || []).concat(o3.id);
        cards.push(c);
        return { action: 'supersede', card: c, supersededIds: [o3.id], note: '新记忆重要性更高，旧记忆作废' };
      }
    }
    /* 规则 4：新建 */
    cards.push(c);
    return { action: 'create', card: c, supersededIds: [], note: '新建记忆' };
  }

  /* 兑现伏笔：把 matching 的内容与 active 伏笔卡片匹配，标记作废 */
  function markResolved(state, resolvedItems, chapterNo) {
    var ids = [];
    if (!Array.isArray(resolvedItems) || !resolvedItems.length) return ids;
    var items = resolvedItems.map(function (r) {
      return String((r && r.content) || r || '').trim();
    }).filter(Boolean);
    state.cards.forEach(function (c) {
      if (c.kind !== 'foreshadow' || c.status !== 'active') return;
      var hit = items.some(function (it) {
        var a = norm(it), b = norm(c.content);
        if (!a || !b) return false;
        return a.length >= 4 && (a.indexOf(b) >= 0 || b.indexOf(a) >= 0) ||
          (a.length < 4 && a === b.slice(0, a.length));
      });
      if (hit) {
        c.status = 'superseded';
        c.supersededBy = 'resolved:ch' + chapterNo;
        c.updatedAt = now();
        ids.push(c.id);
      }
    });
    return ids;
  }

  /* 容量管理：超出上限按重要性淘汰最低的非反思类卡片 */
  function enforceCardCap(state, config) {
    var cap = config.maxCards;
    if (state.cards.length <= cap) return 0;
    var evicted = 0;
    var idx = state.cards.map(function (c, i) {
      return { c: c, i: i, sort: (c.status === 'active' ? 0 : 1), imp: c.importance, t: c.createdAt };
    }).sort(function (a, b) {
      if (a.sort !== b.sort) return a.sort - b.sort;
      if (a.imp !== b.imp) return a.imp - b.imp;
      return a.t < b.t ? -1 : 1;
    });
    while (state.cards.length > cap && evicted < idx.length) {
      var cand = idx[evicted];
      if (cand.c.kind === 'reflection' || cand.c.userEdited || cand.c.status === 'superseded') { evicted++; continue; }
      state.cards.splice(cand.i, 1);
      evicted++;
      idx = state.cards.map(function (c, i) { return { c: c, i: i, sort: (c.status === 'active' ? 0 : 1), imp: c.importance, t: c.createdAt }; })
        .sort(function (a, b) { if (a.sort !== b.sort) return a.sort - b.sort; if (a.imp !== b.imp) return a.imp - b.imp; return a.t < b.t ? -1 : 1; });
    }
    return evicted;
  }

  /* ============================== 检索（关键词打分） ============================== */
  function keywordSearch(cards, query, k) {
    var q = cjkTokenize(query || '');
    if (!q.length) return [];
    var scored = cards.map(function (c) {
      if (c.status === 'deleted') return null;
      var ck = c.keywords || [];
      var overlap = intersect(ck, q).length;
      var hit = ck.some(function (x) { return q.indexOf(x) >= 0; });
      var score = overlap * 3 + (hit ? 1 : 0) + (norm(c.content).indexOf(norm(query)) >= 0 ? 2 : 0);
      return { card: c, score: score };
    }).filter(function (x) { return x && x.score > 0; })
      .sort(function (a, b) { return b.score - a.score; });
    return scored.slice(0, k || 8).map(function (x) { return x.card; });
  }

  /* ============================== 提示词 ============================== */
  function buildWorldBrief(state) {
    var lines = [];
    if (state.world.title) lines.push('书名/篇名：' + state.world.title);
    if (state.world.premise) lines.push('总纲：' + state.world.premise);
    if (state.world.settings && state.world.settings.length) {
      lines.push('固定设定：');
      state.world.settings.forEach(function (s, i) { lines.push('  ' + (i + 1) + '. ' + s); });
    }
    if (state.characters && state.characters.length) {
      lines.push('主要角色：' + state.characters.join('；'));
    }
    var chars = state.cards.filter(function (c) { return c.kind === 'character' && c.status === 'active'; })
      .slice(0, 8).map(function (c) { return '  - ' + c.content; });
    if (chars.length) { lines.push('角色动态：'); lines = lines.concat(chars); }
    var fh = state.cards.filter(function (c) { return c.kind === 'foreshadow' && c.status === 'active'; })
      .slice(0, 8).map(function (c) { return '  - ' + c.content; });
    if (fh.length) { lines.push('未兑现伏笔：'); lines = lines.concat(fh); }
    return lines.join('\n');
  }

  var PROMPTS = {
    chapterReview: function (state, chapterText) {
      return {
        system: '你是一位资深文学编辑与记忆管理员。你的任务是从刚写完的章节中，提炼出对后续写作有用的' +
          '记忆条目，输出严格 JSON。你只输出事实与观察，不评价文笔好坏；不编造章节里没有的内容。',
        user: [
          '【项目上下文】',
          buildWorldBrief(state),
          '',
          '【本章正文】',
          truncate(chapterText || '', 12000),
          '',
          '请输出 JSON（不要 markdown 代码块，不要额外文字），结构如下：',
          '{',
          '  "summary": "本章一句话梗概（60字内）",',
          '  "newFacts": [{"content":"新设定/新事实（完整句）","kind":"world|character|plot","keywords":["关键词2-6个"],"importance":1-10}],',
          '  "characterStates": [{"content":"角色当前状态/情感/立场变化","importance":1-10}],',
          '  "foreshadow": [{"content":"本章埋下的新伏笔","importance":1-10}],',
          '  "resolvedForeshadow": ["本章兑现的旧伏笔（若兑现，写其内容关键词；没有则空数组）"],',
          '  "styleNotes": ["本章风格/节奏/语气上的可复用要点"],',
          '  "issues": ["一致性问题或写作建议（可选）"]',
          '}'
        ].join('\n')
      };
    },
    reflection: function (state, summaries) {
      return {
        system: '你是一位资深文学编辑。请从已完成章节的梗概与既有记忆中，归纳出对整本书写作有长期指导意义' +
          '的规律性规则。规则要具体、可执行、与项目相关，不要空话。输出严格 JSON。',
        user: [
          '【项目】' + state.title + '｜' + state.world.premise,
          '',
          '【近期章节梗概】',
          (summaries && summaries.length ? summaries.map(function (s, i) { return (i + 1) + '. ' + s; }).join('\n') : '（暂无）'),
          '',
          '【既有活跃记忆（节选）】',
          state.cards.filter(function (c) { return c.status === 'active'; })
            .sort(function (a, b) { return b.importance - a.importance; })
            .slice(0, 12).map(function (c) { return '  - [' + KIND_LABELS[c.kind] + '] ' + c.content; }).join('\n'),
          '',
          '请输出 JSON：{"rules":["规则1（40字内）","规则2","规则3",...]}，3-6 条'
        ].join('\n')
      };
    }
  };

  /* 解析模型输出：剥代码块，取第一个平衡 JSON 对象 */
  function parseJsonStrict(text) {
    var s = String(text || '').trim();
    s = s.replace(/^```(?:json)?/i, '').replace(/```\s*$/, '');
    var start = s.indexOf('{');
    var end = s.lastIndexOf('}');
    if (start < 0 || end <= start) throw new Error('模型输出中未找到 JSON 对象');
    var body = s.slice(start, end + 1);
    try { return JSON.parse(body); } catch (e) {
      /* 尝试修复尾逗号 */
      try { return JSON.parse(body.replace(/,\s*([}\]])/g, '$1')); } catch (e2) {
        throw new Error('模型 JSON 解析失败：' + e.message);
      }
    }
  }

  /* ============================== 核心 ============================== */
  function createCore(opts) {
    opts = opts || {};
    if (!opts.store) throw new Error('LitMemoryCore: 需要 { store }（createLocalStorageStore / createVikingDBStore / 自定义）');
    if (!opts.model) throw new Error('LitMemoryCore: 需要 { model }（createModelClient / createMockModel / 自定义）');
    var store = opts.store;
    var model = opts.model;
    var config = Object.assign(defaultConfig(), opts.config || {});
    var state = null;
    var loaded = false;

    function msgs(p) {
      return [{ role: 'system', content: p.system }, { role: 'user', content: p.user }];
    }

    async function ensureLoaded() {
      if (loaded && state) return;
      state = await store.load();
      if (!state) { state = emptyProject('未命名文学项目'); await save(); }
      if (!state.world) state.world = { title: '', premise: '', settings: [] };
      if (!state.characters) state.characters = [];
      if (!state.cards) state.cards = [];
      if (!state.chapters) state.chapters = [];
      if (!state.nextChapterNumber) state.nextChapterNumber = state.chapters.length + 1;
      loaded = true;
    }
    async function save() {
      if (state) { state.updatedAt = now(); await store.save(state); }
    }

    function normalizeReview(review) {
      var r = review || {};
      function items(list) { return Array.isArray(list) ? list : []; }
      var newFacts = items(r.newFacts).map(function (f) {
        return normalizeCard({
          content: String((f && f.content) || '').trim(),
          kind: (f && isKind(f.kind)) ? f.kind : undefined,
          keywords: f && f.keywords,
          importance: f && f.importance
        });
      }).filter(Boolean);
      var characterStates = items(r.characterStates).map(function (f) {
        return normalizeCard({
          content: String((f && f.content) || '').trim(),
          kind: 'character',
          keywords: f && f.keywords,
          importance: (f && f.importance) != null ? f.importance : 5
        });
      }).filter(Boolean);
      var foreshadow = items(r.foreshadow).map(function (f) {
        return normalizeCard({
          content: String((f && f.content) || '').trim(),
          kind: 'foreshadow',
          keywords: f && f.keywords,
          importance: (f && f.importance) != null ? f.importance : 6
        });
      }).filter(Boolean);
      var styleNotes = items(r.styleNotes).map(function (s) {
        return normalizeCard({ content: String((s && s.content) || s || '').trim(), kind: 'style', importance: 4 });
      }).filter(Boolean);
      return {
        summary: String(r.summary || '').trim(),
        newFacts: newFacts,
        characterStates: characterStates,
        foreshadow: foreshadow,
        resolvedForeshadow: items(r.resolvedForeshadow).map(function (x) { return String((x && x.content) || x || ''); }).filter(Boolean),
        styleNotes: styleNotes,
        issues: items(r.issues).map(String)
      };
    }

    async function runChapterReview(input) {
      await ensureLoaded();
      input = input || {};
      var text = String(input.text || '');
      if (!text.trim()) throw new Error('章节正文为空');
      var number = input.number || state.nextChapterNumber;
      var warnings = [];
      var review, raw;
      try {
        raw = await model.chat(msgs(PROMPTS.chapterReview(state, text)), { json: true });
        review = normalizeReview(parseJsonStrict(raw));
      } catch (e) {
        warnings.push('复盘模型调用失败，回退为空提取：' + e.message);
        review = normalizeReview({ summary: '', newFacts: [], characterStates: [], foreshadow: [], resolvedForeshadow: [], styleNotes: [], issues: [] });
      }
      if (!review.summary) review.summary = truncate(text.replace(/\s+/g, ' '), 60) + '……';

      /* 生成候选卡片并逐条去重入库 */
      var candidates = review.newFacts.concat(review.characterStates, review.foreshadow, review.styleNotes);
      candidates.forEach(function (c) { c.chapter = number; });
      var cardResults = candidates.map(function (c) {
        return dedupInsert(state, c, config);
      });
      var createdCount = cardResults.filter(function (r) { return r.action !== 'skip'; }).length;

      /* 兑现伏笔 */
      var resolvedIds = markResolved(state, review.resolvedForeshadow, number);

      /* 章节记录 */
      var log = {
        id: uid('ch'),
        number: number,
        title: String(input.title || '').trim() || ('第 ' + number + ' 章'),
        excerpt: truncate(text, config.chapterExcerptMax),
        summary: review.summary,
        review: review,
        cardCount: createdCount,
        resolvedIds: resolvedIds,
        createdAt: now()
      };
      state.chapters.push(log);
      state.nextChapterNumber = number + 1;

      /* 自动反思 */
      var reflection = null;
      if (config.reflectEvery > 0 && state.chapters.length % config.reflectEvery === 0) {
        try { reflection = await runReflection({ force: false, silent: true }); }
        catch (e) { warnings.push('反思归纳失败：' + e.message); }
      }

      var evicted = enforceCardCap(state, config);
      if (evicted > 0) warnings.push('记忆库已满，按重要性淘汰 ' + evicted + ' 条记忆');
      await save();
      return { chapterLog: log, cardResults: cardResults, resolvedIds: resolvedIds, reflection: reflection, warnings: warnings };
    }

    async function runReflection(input) {
      await ensureLoaded();
      input = input || {};
      var due = input.force || (config.reflectEvery > 0 && state.chapters.length > 0 &&
        state.chapters.length % config.reflectEvery === 0);
      if (!due) return null;
      var summaries = state.chapters.slice(-config.recall.summaryLimit * 2).map(function (c) {
        return '第' + c.number + '章 ' + c.summary;
      });
      var rules = [];
      try {
        var raw = await model.chat(msgs(PROMPTS.reflection(state, summaries)), { json: true });
        var parsed = parseJsonStrict(raw);
        rules = Array.isArray(parsed.rules) ? parsed.rules.map(String).filter(Boolean).slice(0, config.maxRulesPerReflection) : [];
      } catch (e) {
        if (!input.silent) throw e;
        rules = [];
      }
      var cardResults = rules.map(function (rule) {
        return dedupInsert(state, {
          content: rule, kind: 'reflection', importance: 7,
          keywords: cjkTokenize(rule).slice(0, 6)
        }, config);
      });
      var reflection = { number: state.chapters.length, rules: rules, cardResults: cardResults, at: now() };
      state.lastReflection = reflection;
      enforceCardCap(state, config);
      await save();
      return reflection;
    }

    function activeCards() {
      return state.cards.filter(function (c) { return c.status === 'active'; });
    }

    /* 开写前召回：按优先级组装注入块 */
    function prepareRecall(input) {
      if (!state) throw new Error('请先 load() 或执行一次复盘');
      input = input || {};
      var intent = String(input.intent || '').trim();
      var budget = input.maxChars || config.recall.maxChars;
      var cards = activeCards().slice().sort(function (a, b) { return b.importance - a.importance; });
      var used = [];

      var parts = [];
      var worldText = ['【项目】' + (state.world.title || state.title || '未命名')];
      if (state.world.premise) worldText.push('【总纲】' + state.world.premise);
      if (state.world.settings && state.world.settings.length) {
        worldText.push('【固定设定】');
        state.world.settings.forEach(function (s, i) { worldText.push((i + 1) + '. ' + s); });
      }
      parts.push({ key: 'world', text: worldText.join('\n'), priority: 100 });

      var topCards = cards.slice(0, config.recall.cardLimit);
      if (topCards.length) {
        used = used.concat(topCards);
        parts.push({
          key: 'cards',
          text: '【关键记忆】\n' + topCards.map(function (c) {
            return '- [' + KIND_LABELS[c.kind] + '] ' + c.content;
          }).join('\n'),
          priority: 60
        });
      }
      var fh = cards.filter(function (c) { return c.kind === 'foreshadow'; }).slice(0, config.recall.foreshadowLimit);
      if (fh.length) {
        used = used.concat(fh);
        parts.push({ key: 'fh', text: '【未兑现伏笔】\n' + fh.map(function (c) { return '- ' + c.content; }).join('\n'), priority: 50 });
      }
      var style = cards.filter(function (c) { return c.kind === 'style' || c.kind === 'reflection'; }).slice(0, config.recall.styleLimit);
      if (style.length) {
        used = used.concat(style);
        parts.push({ key: 'style', text: '【风格与复盘规则】\n' + style.map(function (c) { return '- ' + c.content; }).join('\n'), priority: 40 });
      }
      var sum = state.chapters.slice(-config.recall.summaryLimit);
      if (sum.length) {
        parts.push({
          key: 'recent',
          text: '【近期章节梗概】\n' + sum.map(function (c) { return '- 第' + c.number + '章：' + c.summary; }).join('\n'),
          priority: 30
        });
      }
      if (intent) parts.push({ key: 'intent', text: '【本次写作意图】' + intent, priority: 90 });

      parts.sort(function (a, b) { return b.priority - a.priority; });
      /* 预算裁剪：从低优先级开始丢弃，world 与 intent 必留 */
      var keep = [];
      var total = 0;
      parts.forEach(function (p) {
        var add = p.text.length + 2;
        if (p.key === 'world' || p.key === 'intent') { keep.push(p); total += add; return; }
        if (total + add <= budget) { keep.push(p); total += add; }
      });
      var block = keep.map(function (p) { return p.text; }).join('\n\n');
      var ids = [];
      used.forEach(function (c) { if (ids.indexOf(c.id) < 0) ids.push(c.id); });
      return {
        block: block,
        chars: block.length,
        tokenEstimate: estimateTokens(block),
        usedCards: state.cards.filter(function (c) { return ids.indexOf(c.id) >= 0; }),
        droppedParts: parts.map(function (p) { return p.key; }).filter(function (k) {
          return keep.map(function (p) { return p.key; }).indexOf(k) < 0;
        })
      };
    }

    async function search(query, k) {
      await ensureLoaded();
      return keywordSearch(state.cards, query, k);
    }

    async function editCard(id, patch) {
      await ensureLoaded();
      var card = state.cards.filter(function (c) { return c.id === id; })[0];
      if (!card) throw new Error('记忆不存在：' + id);
      patch = patch || {};
      if ('content' in patch) card.content = String(patch.content).trim();
      if ('importance' in patch) card.importance = clamp(parseInt(patch.importance, 10) || card.importance, 1, 10);
      if ('kind' in patch && isKind(patch.kind)) card.kind = patch.kind;
      if ('keywords' in patch && Array.isArray(patch.keywords)) card.keywords = patch.keywords.map(String).filter(Boolean);
      card.userEdited = true;
      card.version = (card.version || 1) + 1;
      card.updatedAt = now();
      await save();
      return card;
    }
    async function deleteCard(id) {
      await ensureLoaded();
      state.cards = state.cards.filter(function (c) { return c.id !== id; });
      await save();
    }
    async function setStatus(id, status) {
      await ensureLoaded();
      var card = state.cards.filter(function (c) { return c.id === id; })[0];
      if (!card) throw new Error('记忆不存在：' + id);
      card.status = status === 'superseded' ? 'superseded' : 'active';
      card.updatedAt = now();
      await save();
      return card;
    }
    async function addManualCard(input) {
      await ensureLoaded();
      var card = normalizeCard(Object.assign({ importance: 5 }, input || {}));
      var result = dedupInsert(state, card, config);
      enforceCardCap(state, config);
      await save();
      return result;
    }
    async function setWorld(input) {
      await ensureLoaded();
      input = input || {};
      state.world.title = String(input.title != null ? input.title : state.world.title);
      state.world.premise = String(input.premise != null ? input.premise : state.world.premise);
      if (Array.isArray(input.settings)) state.world.settings = input.settings.map(String);
      if (Array.isArray(input.characters)) state.characters = input.characters.map(String);
      if (input.projectTitle) state.title = String(input.projectTitle);
      await save();
      return state;
    }
    async function exportJSON() { await ensureLoaded(); return JSON.stringify(state, null, 2); }
    async function importJSON(text) {
      var data = typeof text === 'string' ? JSON.parse(text) : text;
      if (!data || !data.cards || !data.chapters) throw new Error('不是合法的记忆项目 JSON');
      data.schema = 'lit-memory/v1';
      data.updatedAt = now();
      state = data;
      loaded = true;
      await save();
      return state;
    }
    async function clearProject(title) {
      state = emptyProject(title || '未命名文学项目');
      loaded = true;
      await save();
      return state;
    }
    async function getState() { await ensureLoaded(); return state; }
    async function getStats() {
      await ensureLoaded();
      var by = {};
      KINDS.forEach(function (k) { by[k] = 0; });
      state.cards.forEach(function (c) { by[c.kind] = (by[c.kind] || 0) + 1; });
      var active = state.cards.filter(function (c) { return c.status === 'active'; });
      return {
        cards: state.cards.length,
        active: active.length,
        byKind: by,
        chapters: state.chapters.length,
        foreshadowOpen: active.filter(function (c) { return c.kind === 'foreshadow'; }).length,
        userEdited: state.cards.filter(function (c) { return c.userEdited; }).length,
        title: state.title
      };
    }

    return {
      config: config,
      load: ensureLoaded,
      getState: getState,
      runChapterReview: runChapterReview,
      runReflection: runReflection,
      prepareRecall: prepareRecall,
      search: search,
      editCard: editCard,
      deleteCard: deleteCard,
      setStatus: setStatus,
      addManualCard: addManualCard,
      setWorld: setWorld,
      exportJSON: exportJSON,
      importJSON: importJSON,
      clearProject: clearProject,
      getStats: getStats
    };
  }

  /* ============================== 模型客户端 ============================== */
  function createModelClient(cfg) {
    cfg = cfg || {};
    var baseURL = String(cfg.baseURL || '').replace(/\/+$/, '');
    if (!baseURL) throw new Error('createModelClient: 需要 baseURL（OpenAI 兼容 /chat/completions）');
    var fetchImpl = cfg.fetchImpl || (typeof fetch === 'function' ? fetch.bind(global) : null);
    if (!fetchImpl) throw new Error('createModelClient: 环境无 fetch，请注入 fetchImpl');
    var key = cfg.apiKey || '';
    var model = cfg.model || 'default';
    async function chat(messages, opts) {
      opts = opts || {};
      var body = {
        model: model,
        messages: messages,
        temperature: cfg.temperature != null ? cfg.temperature : 0.3,
        stream: false
      };
      if (opts.json && cfg.jsonMode !== false) body.response_format = { type: 'json_object' };
      var res = await fetchImpl(baseURL + '/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        var t = '';
        try { t = await res.text(); } catch (e) { /* noop */ }
        throw new Error('模型接口 HTTP ' + res.status + ': ' + t.slice(0, 200));
      }
      var data = await res.json();
      var content = data && data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content;
      if (!content) throw new Error('模型接口返回空内容');
      return content;
    }
    return { chat: chat };
  }

  /* 演示模型：从章节正文启发式抽取，让 Demo 无需密钥即可跑通全链路。
   * 仅用于演示/测试，正式接入请使用 createModelClient 接真实模型。 */
  function createMockModel(opts) {
    opts = opts || {};
    var names = (opts.names || []).map(String);
    var FORESHADOW_WORDS = ['伏笔', '预言', '钥匙', '秘密', '信物', '传闻', '契约', '残页', '铜铃', '暗号'];
    var SPLIT = /[。！？；\n]+/;
    function kindOf(sentence) {
      var hasName = names.some(function (n) { return n && sentence.indexOf(n) >= 0; });
      if (hasName) return 'character';
      if (/城|阁|楼|谷|山|寺|宫|殿|派|帮|岛/.test(sentence)) return 'world';
      return 'plot';
    }
    function chat(messages) {
      var last = messages[messages.length - 1];
      var text = String(last && last.content || '');
      /* 反思归纳提示词：输出规则列表 */
      if (text.indexOf('{"rules"') >= 0) {
        var rules = [];
        names.forEach(function (n) {
          if (n && text.split(n).length - 1 >= 2) rules.push('注意「' + n + '」主线持续推进与状态一致性');
        });
        rules = rules.concat([
          '伏笔应在后续章节适时兑现，避免遗忘',
          '保持章节间的语气与节奏连贯',
          '人物出场时重申其当前立场与关系'
        ]).slice(0, 5);
        return Promise.resolve(JSON.stringify({ rules: rules }));
      }
      var bodyIdx = text.indexOf('【本章正文】');
      var body = bodyIdx >= 0 ? text.slice(bodyIdx + '【本章正文】'.length) : text;
      var sentences = body.split(SPLIT).map(function (s) { return s.trim(); }).filter(function (s) { return s.length > 6; });
      var newFacts = [], foreshadow = [], charStates = [];
      sentences.slice(0, 10).forEach(function (s) {
        var hasName = names.some(function (n) { return n && s.indexOf(n) >= 0; });
        var hasFh = FORESHADOW_WORDS.some(function (w) { return s.indexOf(w) >= 0; });
        if (hasFh) {
          foreshadow.push({ content: s.slice(0, 60), importance: 7 });
        } else if (hasName) {
          var who = names.filter(function (n) { return n && s.indexOf(n) >= 0; })[0];
          charStates.push({ content: who + '：' + s.slice(0, 48), importance: 5 });
        } else {
          newFacts.push({ content: s.slice(0, 48), kind: kindOf(s), importance: 4 });
        }
      });
      var avg = sentences.length ? sentences.reduce(function (a, s) { return a + s.length; }, 0) / sentences.length : 0;
      var styleNotes = [];
      if (avg > 40) styleNotes.push('本章句式偏长，节奏偏缓');
      else if (avg > 0) styleNotes.push('本章句式短促，节奏偏快');
      var resolved = [];
      var dialogRatio = (body.match(/[“"』」]/g) || []).length;
      if (dialogRatio > 4) styleNotes.push('本章对白占比高，注意以动作穿插');
      var reply = {
        summary: truncate(sentences[0] || body.trim(), 60),
        newFacts: newFacts.slice(0, 6),
        characterStates: charStates.slice(0, 5),
        foreshadow: foreshadow.slice(0, 3),
        resolvedForeshadow: resolved,
        styleNotes: styleNotes.slice(0, 2),
        issues: []
      };
      return Promise.resolve(JSON.stringify(reply));
    }
    return { chat: chat, _kind: 'mock' };
  }

  /* ============================== 存储适配器 ============================== */
  /* ---- LocalStorage（默认，浏览器即用） ---- */
  function createLocalStorageStore(key, opts) {
    opts = opts || {};
    var storage = opts.storage || (typeof localStorage !== 'undefined' ? localStorage : null);
    if (!storage) throw new Error('createLocalStorageStore: 环境无 localStorage，请注入 { storage }');
    var K = 'lit-memory:' + key;
    return {
      async load() {
        var raw = storage.getItem(K);
        if (!raw) return null;
        try { return JSON.parse(raw); } catch (e) { return null; }
      },
      async save(state) {
        try { storage.setItem(K, JSON.stringify(state)); }
        catch (e) { throw new Error('本地存储写入失败（容量或隐私模式）：' + e.message); }
      },
      async clear() { storage.removeItem(K); },
      _key: K
    };
  }

  /* ---- VikingDB 载荷构造（纯函数，可测） ---- */
  function buildVikingdbUpsertPayload(collection, docs) {
    return { collection_name: collection, data: docs };
  }
  function buildVikingdbSearchPayload(collection, opts) {
    opts = opts || {};
    var search = {};
    if (opts.vector) search.order_by_vector = { vectors: [opts.vector] };
    if (opts.filter) search.filter = opts.filter;
    search.limit = opts.limit || 10;
    var payload = { collection_name: collection, search: search };
    if (opts.indexName) payload.index_name = opts.indexName;
    return payload;
  }
  function buildVikingdbFetchPayload(collection, primaryKeys) {
    return { collection_name: collection, primary_keys: primaryKeys };
  }

  /* ---- VikingDB 适配器（尽力而为：端点/鉴权/索引以你的火山实例为准） ----
   * 数据面两种形态：V1 /collection/upsert_data（API Key 或 AK/SK 签名）；
   * V2 /api/vikingdb/data/upsert_in_collection 等。domain 默认 api-vikingdb.volces.com。
   * 本项目把整份 ProjectState 存为 '__project__' 文档，卡片逐条存储以便检索。
   */
  function createVikingDBStore(cfg) {
    cfg = cfg || {};
    var domain = cfg.domain || 'api-vikingdb.volces.com';
    var collection = cfg.collection;
    if (!collection) throw new Error('createVikingDBStore: 需要 collection（控制台创建）');
    var apiKey = cfg.apiKey || '';
    var paths = Object.assign({
      upsert: '/collection/upsert_data',          // V1；V2 数据面请改为你的实际路径
      search: '/api/index/search',
      fetch: '/api/collection/fetch_data'
    }, cfg.paths || {});
    var fetchImpl = cfg.fetchImpl || (typeof fetch === 'function' ? fetch.bind(global) : null);
    if (!fetchImpl) throw new Error('createVikingDBStore: 环境无 fetch');
    function authHeaders() {
      var h = { 'Content-Type': 'application/json' };
      if (apiKey) h['Authorization'] = 'Bearer ' + apiKey;
      return h;
    }
    async function post(path, body) {
      var res = await fetchImpl('https://' + domain + path, {
        method: 'POST', headers: authHeaders(), body: JSON.stringify(body)
      });
      if (!res.ok) {
        var t = ''; try { t = await res.text(); } catch (e) { /* noop */ }
        throw new Error('VikingDB HTTP ' + res.status + ' @ ' + path + ': ' + t.slice(0, 200));
      }
      return res.json();
    }
    var cache = { cards: [], state: null };
    return {
      async load() {
        /* 尽力而为：拉 '__project__' 文档重组状态；卡片另存可检索副本。
         * 注意：完整实现需要按你的 collection 字段结构（id/kind/content/keywords/...）对齐。 */
        try {
          var resp = await post(paths.fetch, buildVikingdbFetchPayload(collection, ['__project__']));
          var data = resp && resp.data;
          var doc = Array.isArray(data) ? data[0] : (data && data[0]) || null;
          if (doc && doc.fields && doc.fields.project_json) {
            var parsed = JSON.parse(doc.fields.project_json);
            cache.state = parsed;
            cache.cards = parsed.cards || [];
            return parsed;
          }
        } catch (e) {
          throw new Error('VikingDB load 失败（请核对 collection/索引/鉴权）：' + e.message);
        }
        return null;
      },
      async save(state) {
        var projectDoc = { id: '__project__', fields: { project_json: JSON.stringify(state) } };
        await post(paths.upsert, buildVikingdbUpsertPayload(collection, [projectDoc]));
        /* 逐条卡片 upsert（差分：仅新增/更新的），字段名按你的 collection 结构对齐 */
        var docs = (state.cards || []).map(function (c) {
          return { id: c.id, fields: { kind: c.kind, content: c.content, keywords: JSON.stringify(c.keywords || []), importance: c.importance, status: c.status, chapter: c.chapter, updated_at: c.updatedAt } };
        });
        for (var i = 0; i < docs.length; i += 20) {
          await post(paths.upsert, buildVikingdbUpsertPayload(collection, docs.slice(i, i + 20)));
        }
        cache.state = state;
        cache.cards = state.cards || [];
      },
      async search(query, k) {
        /* 若配置了 embedding 函数则走向量检索，否则用本地关键词兜底 */
        if (typeof cfg.embedding === 'function') {
          var vec = await cfg.embedding(query);
          var resp = await post(paths.search, buildVikingdbSearchPayload(collection, { vector: vec, limit: k || 8, indexName: cfg.indexName }));
          var hits = (resp.data || []).map(function (d) { return d.fields || {}; });
          return hits.map(function (f) {
            return { id: f.id || '', kind: f.kind, content: f.content, keywords: (function () { try { return JSON.parse(f.keywords || '[]'); } catch (e) { return []; } })(), importance: parseInt(f.importance, 10) || 5, status: f.status || 'active', chapter: parseInt(f.chapter, 10) || 0 };
          });
        }
        return keywordSearch(cache.cards || [], query, k || 8);
      },
      async clear() {
        /* 按你的 collection 提供删除能力；此处留空实现占位 */
      }
    };
  }

  /* ---- OpenViking（火山方舟 Agent 上下文数据库）适配器 ----
   * OpenViking 采用 viking:// 文件系统范式 + 分层上下文 + 目录递归检索，
   * 鉴权 Bearer APIKey + X-OpenViking-Agent。开放接入方式为 MCP / CLI / API。
   * 本包提供两种用法：
   *   ① 提供 adapter 对象（你按自己的接入方式实现 load/save/search）
   *   ② 不提供则方法抛错并给出指引——保证核心管线不受影响。
   * 参考文档：
   *   https://docs.volcengine.com/docs/82379/2373745 （OpenViking 概览）
   *   https://docs.volcengine.com/docs/84313/2381937 （数据库访问使用说明）
   *   https://docs.volcengine.com/docs/84313/2487454 （上下文感知搜索 search）
   */
  function createOpenVikingStore(cfg) {
    cfg = cfg || {};
    if (cfg.adapter && typeof cfg.adapter.load === 'function') {
      return {
        load: cfg.adapter.load,
        save: cfg.adapter.save,
        search: typeof cfg.adapter.search === 'function' ? cfg.adapter.search : function () { return Promise.resolve([]); },
        clear: typeof cfg.adapter.clear === 'function' ? cfg.adapter.clear : function () { return Promise.resolve(); }
      };
    }
    var guide = 'OpenViking 适配器需按你的火山实例实现（viking:// 分层上下文：把 ProjectState 写入记忆目录，' +
      '召回走上下文感知搜索）。可先在本机跑通 OpenViking 开源内核或火山方舟 OpenViking Context 后，' +
      '给 createOpenVikingStore 传入 { adapter: { load, save, search } }。参考文档见源码注释。';
    return {
      async load() { throw new Error(guide); },
      async save() { throw new Error(guide); },
      async search() { throw new Error(guide); },
      async clear() { throw new Error(guide); }
    };
  }

  /* ============================== 导出 ============================== */
  var api = {
    VERSION: VERSION,
    KINDS: KINDS,
    KIND_LABELS: KIND_LABELS,
    defaultConfig: defaultConfig,
    emptyProject: emptyProject,
    normalizeCard: normalizeCard,
    dedupInsert: dedupInsert,
    markResolved: markResolved,
    enforceCardCap: enforceCardCap,
    keywordSearch: keywordSearch,
    cjkTokenize: cjkTokenize,
    estimateTokens: estimateTokens,
    parseJsonStrict: parseJsonStrict,
    PROMPTS: PROMPTS,
    createCore: createCore,
    createModelClient: createModelClient,
    createMockModel: createMockModel,
    createLocalStorageStore: createLocalStorageStore,
    createVikingDBStore: createVikingDBStore,
    createOpenVikingStore: createOpenVikingStore,
    buildVikingdbUpsertPayload: buildVikingdbUpsertPayload,
    buildVikingdbSearchPayload: buildVikingdbSearchPayload,
    buildVikingdbFetchPayload: buildVikingdbFetchPayload
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.LitMemoryCore = api;
})(typeof window !== 'undefined' ? window : globalThis);

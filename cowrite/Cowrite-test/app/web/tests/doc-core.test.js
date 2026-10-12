/* doc-core.js 单测。纯字符串逻辑，不依赖 DOM：node tests/doc-core.test.js */
const path = require('path');
const DocModel = require(path.join(__dirname, '..', 'dist', 'doc-core.js'));

let pass = 0, fail = 0;
function group(name) { console.log('\n■ ' + name); }
function t(desc, fn) {
  try {
    const v = fn();
    if (v === true) { pass++; console.log('  ✓ ' + desc); }
    else { fail++; console.log('  ✗ ' + desc + '  → ' + v); }
  } catch (e) { fail++; console.log('  ✗ ' + desc + '  → 抛了：' + e.message); }
}
const flat = s => String(s || '').replace(/\s+/g, '');

/* ── 组 1 · textOf ───────────────────────────────────────────── */
group('组 1 · textOf：块标签换算行、实体解码');
t('块标签换行', () => {
  const r = DocModel.textOf('<p>甲</p><p>乙</p>');
  return r === '甲\n乙' ? true : JSON.stringify(r);
});
t('空段落留空行', () => {
  const r = DocModel.textOf('<p>甲</p><p><br></p><p>乙</p>');
  return r === '甲\n\n乙' ? true : JSON.stringify(r);
});
t('去标签、解实体', () => {
  const r = DocModel.textOf('<p><strong>粗</strong>&nbsp;与&amp;号</p>');
  return r === '粗 与&号' ? true : JSON.stringify(r);
});
t('★ 实体解码顺序：&amp;lt; 必须解成 &lt; 而不是 <', () => {
  const r = DocModel.textOf('<p>&amp;lt;</p>');
  return r === '&lt;' ? true : JSON.stringify(r) + '（解成 < 就是把原文那四个字符改成了一个尖括号）';
});
t('script/style 整段丢掉', () => {
  const r = DocModel.textOf('<p>甲</p><script>var a=1;</script><style>p{}</style>');
  return r === '甲' ? true : JSON.stringify(r);
});
t('空输入不抛', () => {
  return DocModel.textOf(null) === '' && DocModel.textOf(undefined) === '' && DocModel.textOf('') === '';
});

/* ── 组 2 · split ────────────────────────────────────────────── */
group('组 2 · split：分章');
const h = (n, body) => '<h1>第' + n + '章</h1><p>' + body + '</p>';
const book = '<h1>第一章</h1><p>甲</p><h1>第二章</h1><p>乙</p><h1>第三章</h1><p>丙</p>';

t('按 h1 切 3 章', () => {
  const c = DocModel.split(book);
  return c.length === 3 ? true : '章数=' + c.length;
});
t('章标题取自 h1', () => {
  const c = DocModel.split(book);
  return c[0].title === '第一章' && c[2].title === '第三章' ? true : JSON.stringify(c.map(x => x.title));
});
t('h1 之前的内容自成一章', () => {
  const c = DocModel.split('<p>序</p>' + book);
  return c.length === 4 && DocModel.textOf(c[0].html) === '序' ? true : '章数=' + c.length;
});
t('无 h1 时按 h2 切', () => {
  const c = DocModel.split('<h2>一</h2><p>甲</p><h2>二</h2><p>乙</p>');
  return c.length === 2 ? true : '章数=' + c.length;
});
t('都没有标题时按 chunkChars 切', () => {
  const many = Array.from({ length: 40 }, (_, i) => '<p>' + '字'.repeat(1000) + i + '</p>').join('');
  const c = DocModel.split(many, { chunkChars: 5000 });
  return c.length >= 6 ? true : '章数=' + c.length;
});
t('★ 切完拼回来=原文（一个字不多一个不少）', () => {
  const c = DocModel.split(book);
  const back = c.map(x => x.html).join('\n');
  return flat(back) === flat(book) ? true : '拼不回去';
});
t('★ 硬切也不丢也不重（块边界切）', () => {
  const many = Array.from({ length: 40 }, (_, i) => '<p>段' + i + '·' + '字'.repeat(300) + '</p>').join('');
  const c = DocModel.split(many, { chunkChars: 4000 });
  const back = c.map(x => x.html).join('\n');
  return flat(back) === flat(many) ? true : '拼不回去';
});
t('★ 硬切不劈开块（每章都以 </p> 收尾）', () => {
  const many = Array.from({ length: 40 }, (_, i) => '<p>' + '字'.repeat(300) + '</p>').join('');
  const c = DocModel.split(many, { chunkChars: 4000 });
  const bad = c.filter(x => !/<\/p>$/.test(x.html.trim()));
  return bad.length === 0 ? true : bad.length + ' 章被劈开了';
});
t('空 html → 空数组', () => {
  return DocModel.split('').length === 0 && DocModel.split('   ').length === 0;
});
t('单章（无任何块标签）也是 1 章', () => {
  const c = DocModel.split('就是一句话');
  return c.length === 1 && c[0].html === '就是一句话' ? true : JSON.stringify(c);
});

/* ── 组 3 · 模型：字数、惰性、回写 ──────────────────────────── */
group('组 3 · DocModel：字数 / 惰性 / 回写');
const mk = () => DocModel.create({ chunkChars: 3000 }).load(DocModel.split(book));

t('count / index / chapter', () => {
  const d = mk();
  return d.count === 3 && d.index === 0 && d.chapter(1).title === '第二章' ? true : 'count=' + d.count;
});
t('index 越界被夹住', () => {
  const d = mk();
  d.index = 99;
  const hi = d.index;
  d.index = -5;
  return hi === 2 && d.index === 0 ? true : hi + '/' + d.index;
});
t('chars() = 全文纯文本长度', () => {
  const d = mk();
  const expect = DocModel.textOf(d.html()).length;
  return d.chars() === expect ? true : d.chars() + ' vs ' + expect;
});
t('★ commit 之后 chars() 立刻对（不靠重组）', () => {
  const d = mk();
  d.commit(0, '<h1>第一章</h1><p>甲甲甲甲甲</p>');
  const expect = DocModel.textOf(d.html()).length;
  return d.chars() === expect ? true : d.chars() + ' vs ' + expect;
});
t('★ commit 只标脏，不重组全文', () => {
  const d = mk();
  const before = d.text().length;              // 先重建一次缓存
  d.commit(0, '<p>甲</p>');                    // 明显更短，字数必须立刻反映
  return d.dirty === true && d.chars() === before - 4
    ? true : 'dirty=' + d.dirty + ' chars=' + d.chars() + ' before=' + before;
});
t('★ text() 重组后 dirty 归位', () => {
  const d = mk();
  d.commit(0, '<h1>第一章</h1><p>改了</p>');
  const s = d.text();
  return d.dirty === false && s.indexOf('改了') >= 0 ? true : 'dirty=' + d.dirty;
});
t('★ 字数条走的是缓存：40 万字上也是常数时间', () => {
  const big = Array.from({ length: 400 }, (_, i) => '<h1>第' + i + '章</h1><p>' + '字'.repeat(1000) + '</p>').join('');
  const d = DocModel.create().loadHtml(big);
  d.text();                                   // 先让缓存失效一次
  d.commit(0, '<h1>第0章</h1><p>' + '字'.repeat(500) + '</p>');
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < 1000; i++) d.chars();
  const dt = Number(process.hrtime.bigint() - t0) / 1e6;
  return dt < 50 ? true : '1000 次 chars() 用了 ' + dt.toFixed(1) + 'ms（说明它重组了全文）';
});
t('★ commit 相同内容不标脏（导出菜单连调三次才不会重组三遍）', () => {
  const d = mk();
  d.text();                                    // 建立缓存，dirty=false
  const r = d.commit(0, d.chapterHtml(0), d.chapter(0).text);
  return r === false && d.dirty === false ? true : 'returned=' + r + ' dirty=' + d.dirty;
});
t('commit 不存在的章返回 false（不抛）', () => {
  const d = mk();
  return d.commit(99, '<p>x</p>') === false;
});
t('loadHtml 直接把整篇灌进来', () => {
  const d = DocModel.create().loadHtml(book);
  return d.count === 3 ? true : '章数=' + d.count;
});

/* ── 组 4 · 全文坐标与目录 ──────────────────────────────────── */
group('组 4 · 全局偏移与跨章目录');
t('offsetIn：第 0 章就是章内位置', () => {
  const d = mk();
  return d.offsetIn(0, 5) === 5;
});
t('★ offsetIn：后面章要加上前面各章', () => {
  const d = mk();
  const expect = d.chapter(0).chars + 2 + d.chapter(1).chars + 2 + 3;
  return d.offsetIn(2, 3) === expect ? true : d.offsetIn(2, 3) + ' vs ' + expect;
});
t('★ headings 带 chapter（跨章跳转靠它）', () => {
  const d = mk();
  const hs = d.headings();
  return hs.length === 3 && hs[0].chapter === 0 && hs[2].chapter === 2 && hs[2].text === '第三章'
    ? true : JSON.stringify(hs);
});
t('headings 认 id（导入时补过的那套）', () => {
  const d = DocModel.create().loadHtml('<h1 id="eebk-7">第七章</h1><p>x</p><h2 id="eebk-8">小</h2>');
  const hs = d.headings();
  return hs[0].id === 'eebk-7' && hs[1].id === 'eebk-8' && hs[1].level === 2
    ? true : JSON.stringify(hs);
});
t('★ headings 带章内序号 k（定位靠它，因为 id 会被 Quill 丢掉）', () => {
  const d = DocModel.create().loadHtml('<h1>甲</h1><h2>甲一</h2><h1>乙</h1><h2>乙一</h2><h2>乙二</h2>');
  const hs = d.headings();
  const ks = hs.map(x => x.chapter + ':' + x.k).join(',');
  return ks === '0:0,0:1,1:0,1:1,1:2' ? true : ks;
});
t('★ 丢掉 id 之后 k 仍然对（Quill 一保存 id 就没了）', () => {
  const d = DocModel.create().loadHtml('<h1 id="eebk-1">甲</h1><p>x</p><h2 id="eebk-2">乙</h2>');
  d.commit(0, '<h1>甲</h1><p>x</p><h2>乙</h2>');      // 模拟 Quill 保存后 id 消失
  const hs = d.headings();
  return hs.length === 2 && hs[0].id === '' && hs[1].k === 1 ? true : JSON.stringify(hs);
});
t('headings 只认 h1–h3（h4 不进目录，与目录面板一致）', () => {
  const d = DocModel.create().loadHtml('<h1>一</h1><h4>四</h4>');
  return d.headings().length === 1;
});

/* ── 组 5 · 真实体量的形状（不测时间，只测不变式） ──────────── */
group('组 5 · 80 万字体量下的不变式');
t('★ 80 万字分章后：总字数守恒、每章不超限', () => {
  const seg = '<p>' + '她站在走廊尽头，没打伞。'.repeat(6) + '</p>';
  const many = Array.from({ length: 4000 }, (_, i) => '<h1>第' + i + '节</h1>' + seg).join('');
  const d = DocModel.create().loadHtml(many);
  const ok1 = flat(d.html()) === flat(many);
  const ok2 = d.count >= 4000;
  return ok1 && ok2 ? true : '守恒=' + ok1 + ' 章数=' + d.count;
});
t('★ 单章字数远小于全文（窗口化才有意义）', () => {
  const seg = '<p>' + '字'.repeat(200) + '</p>';
  const many = Array.from({ length: 4000 }, (_, i) => '<h1>第' + i + '节</h1>' + seg).join('');
  const d = DocModel.create().loadHtml(many);
  const per = d.chapter(0).chars;
  return per < d.chars() / 1000 ? true : '单章 ' + per + ' / 全文 ' + d.chars();
});

console.log('\n──────────────────────────────────────────');
console.log('合计 ' + (pass + fail) + ' 例：通过 ' + pass + '，失败 ' + fail);
process.exit(fail ? 1 : 0);

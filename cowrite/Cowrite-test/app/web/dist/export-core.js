/* ============================================================================
   export-core.js — 从零 EPUB 打包器（P2 甲档）

   为什么单独一个文件、不并进 epub-core.js：依赖方向必须是单向的。
   epub-core 的 UMD 工厂硬要求 JSZip，而这一层还要用 HeadingCore（零依赖）。
   塞进去就把「读 epub」和「写 epub」两件事绑成一个依赖球。

       heading-core  ←  export-core  ←  index.html(expDo)
                             ↑
                        epub-core（只用它已导出的 exportEpub / buildNavXhtml / MIME）

   它自己不写 zip 组装：那是 EpubCore.exportEpub 的活（mimetype 首位 + STORE 已实测）。
   本文件只负责「合成一个 book 形状」+ 生成 epub-core 里没有的三件东西：
   container.xml、content.opf、章节 xhtml 壳。
   ========================================================================== */
(function (global, factory) {
  var api = factory(global.HeadingCore, global.EpubCore, global.JSZip);
  if (typeof module === 'object' && module.exports) module.exports = api;
  global.ExportCore = api;
})(typeof window !== 'undefined' ? window : globalThis, function (HeadingCore, EpubCore, JSZip) {

  var MAX_CHAPTERS = 200;          // 章数上限：h1 极多时别产出几百个文件拖慢阅读器
  var DEFAULT_TITLE = '文稿';
  var OPF = 'OEBPS/content.opf';
  var NAV = 'OEBPS/nav.xhtml';
  var NCX = 'OEBPS/toc.ncx';
  var CSS = 'OEBPS/style.css';

  /* ---------- 工具 ---------- */

  /* XML 1.0 不收的控制字符（N5）。从别处粘贴来的正文常带 U+200B 之类的零宽字符，
     严格阅读器会因此拒收整本书。docx 那条路在服务端专门做了过滤，epub 侧原本没有。
     制表/换行/回车是合法的，留着。 */
  function stripCtrl(s) {
    return String(s == null ? '' : s)
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\uFFFE\uFFFF]/g, '');
  }

  function xmlEscape(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* XHTML 里 <br> 必须写成 <br />。Quill 的空行是 <p><br></p>，直接进 xhtml 会被
     严格解析器判为未闭合标签 —— 整章打不开。空元素统一补斜杠。 */
  var VOID_TAGS = /<(br|hr|img|input|meta|link|source|col|area|base|wbr)(\s[^<>]*)?>/gi;
  function closeVoid(s) {
    return String(s).replace(VOID_TAGS, function (whole, tag, attrs) {
      if (/\/\s*>$/.test(whole)) return whole;                 // 已经自闭合
      var a = attrs || '';
      if (/\/\s*$/.test(a)) return '<' + tag + a + '>';        // <br/> 少了个空格
      return '<' + tag + (a ? a : ' ') + '/>';
    });
  }

  function uuid() {
    try {
      if (global.crypto && typeof global.crypto.randomUUID === 'function') {
        return global.crypto.randomUUID();
      }
    } catch (e) { /* 非安全上下文里没有 randomUUID，走下面 */ }
    var s = '';
    for (var i = 0; i < 32; i++) s += '0123456789abcdef'.charAt(Math.floor(Math.random() * 16));
    return s.replace(/^(.{8})(.{4})(.{4})(.{4})(.{12})$/, '$1-$2-$3-$4-$5');
  }

  function stamp() {
    try { return new Date().toISOString().replace(/\.\d+Z$/, 'Z'); }
    catch (e) { return '2026-01-01T00:00:00Z'; }
  }

  /* ---------- 按 h1 切章（§12.4） ---------- */

  /* 在 <h1 开标签的**起点**切，切点不在标签内部 —— 不可能切出半个标签。
     h1 之前的内容（序言/扉页）自成一章；全文没有 h1 就退化成单章。 */
  function splitByH1(html) {
    var src = String(html || '');
    var idx = [], re = /<h1\b/gi, m;
    while ((m = re.exec(src))) idx.push(m.index);
    if (!idx.length) return [src];
    var parts = [];
    if (idx[0] > 0) parts.push(src.slice(0, idx[0]));
    for (var i = 0; i < idx.length; i++) {
      parts.push(src.slice(idx[i], i + 1 < idx.length ? idx[i + 1] : src.length));
    }
    parts = parts.filter(function (s) { return s.trim(); });
    return parts.length ? parts : [src];
  }

  /* 超过上限就均匀合并相邻章，不是砍掉后面的内容 —— 少一章内容比多一个文件严重得多。 */
  function capChapters(parts) {
    if (parts.length <= MAX_CHAPTERS) return parts;
    var n = MAX_CHAPTERS, out = [], per = Math.ceil(parts.length / n);
    for (var i = 0; i < parts.length; i += per) out.push(parts.slice(i, i + per).join('\n'));
    return out;
  }

  /* ---------- 三个 epub-core 里没有的新增件 ---------- */

  function containerXml() {
    return '<?xml version="1.0" encoding="utf-8"?>\n'
      + '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">\n'
      + '  <rootfiles>\n'
      + '    <rootfile full-path="' + OPF + '" media-type="application/oebps-package+xml"/>\n'
      + '  </rootfiles>\n'
      + '</container>\n';
  }

  function chapterXhtml(title, body) {
    return '<?xml version="1.0" encoding="utf-8"?>\n'
      + '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
      + '<head><title>' + xmlEscape(title) + '</title>'
      + '<link rel="stylesheet" type="text/css" href="../style.css"/></head>\n'
      + '<body>\n' + body + '\n</body>\n</html>\n';
  }

  /* 章标题取本章第一个标题的文字；没有标题的章用书名兜着，不留空 <title>。 */
  function firstHeadingText(headings, fallback) {
    for (var i = 0; i < headings.length; i++) {
      var t = (headings[i] && headings[i].text || '').trim();
      if (t) return t;
    }
    return fallback;
  }

  function styleCss() {
    return 'body{line-height:1.75;margin:0 3%}\n'
      + 'h1,h2,h3,h4,h5,h6{line-height:1.35;margin:1.4em 0 .6em;font-weight:600}\n'
      + 'h1{font-size:1.5em}h2{font-size:1.25em}h3{font-size:1.1em}\n'
      + 'p{margin:0 0 .7em;text-indent:0;text-align:justify}\n'
      + 'blockquote{margin:.8em 0;padding:0 0 0 1em;color:#555;border-left:2px solid #ccc}\n'
      + 'img{max-width:100%;height:auto}\n';
  }

  /* ---------- 主入口 ---------- */

  /* opts: { html, title, author, language }
     返回 Blob（application/epub+zip）。 */
  async function buildEpub(opts) {
    opts = opts || {};
    if (!JSZip) throw new Error('JSZip 没加载，打不了 epub');
    if (!EpubCore || typeof EpubCore.exportEpub !== 'function') {
      throw new Error('EpubCore 没加载，打不了 epub');
    }
    if (!HeadingCore || typeof HeadingCore.ensureHeadingIds !== 'function') {
      throw new Error('HeadingCore 没加载，打不了 epub');
    }

    var title = stripCtrl(opts.title || '').trim() || DEFAULT_TITLE;
    var author = stripCtrl(opts.author || '').trim();
    var lang = (opts.language || 'zh-CN').trim() || 'zh-CN';
    var body = closeVoid(stripCtrl(opts.html || ''));
    if (!body.trim()) throw new Error('没有正文，没什么可打包的');

    var chunks = capChapters(splitByH1(body));
    var zip = new JSZip();
    zip.file('mimetype', EpubCore.MIME_EPUB || 'application/epub+zip', {compression: 'STORE'});

    // N6：exportEpub 只枚举 book.zip 里已存在的条目，不在里面的会被**静默跳过**
    // （不报错，产出「空书」）。所以每个条目都必须先写进这个合成 zip。
    zip.file('META-INF/container.xml', containerXml(), {compression: 'DEFLATE'});
    zip.file(CSS, styleCss(), {compression: 'DEFLATE'});
    // nav / ncx 先放占位，目录生成成功会被 exportEpub 覆盖；
    // 一篇没有标题的稿子也不会因此缺文件（OPF 里引用了就必须在）。
    zip.file(NAV, '<?xml version="1.0" encoding="utf-8"?>\n'
      + '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
      + '<head><title>Table of Contents</title></head>\n'
      + '<body><nav epub:type="toc" id="toc"><ol></ol></nav></body>\n</html>\n',
      {compression: 'DEFLATE'});
    zip.file(NCX, '<?xml version="1.0" encoding="utf-8"?>\n'
      + '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
      + '<head><meta name="dtb:uid" content=""/></head>\n'
      + '<docTitle><text>' + xmlEscape(title) + '</text></docTitle>\n'
      + '<navMap></navMap>\n</ncx>\n', {compression: 'DEFLATE'});

    var spine = [], cache = {}, manifestItems = [], next = 1, total = 0;
    for (var i = 0; i < chunks.length; i++) {
      // id 生成器只认 heading-core 一家（§12.3）：不自己数、不自己拼前缀，
      // 目录面板、导出、将来的回写式三处才不会漂。
      var r = HeadingCore.ensureHeadingIds(chunks[i], {startIndex: next});
      next = r.nextIndex;
      var n = i + 1;
      var href = 'text/c' + n + '.xhtml';
      var path = 'OEBPS/' + href;
      cache[path] = r.headings;
      total += r.headings.length;
      zip.file(path, chapterXhtml(firstHeadingText(r.headings, title), r.html),
               {compression: 'DEFLATE'});
      manifestItems.push('<item id="c' + n + '" href="' + href
        + '" media-type="application/xhtml+xml"/>');
      spine.push({idref: 'c' + n, path: path, href: href, title: ''});
    }

    var uid = 'urn:uuid:' + uuid();
    var manifest = ''
      + '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n    '
      // properties="nav" 不能省：parseBook 靠它认 nav（epub-core.js:274）
      + '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>\n    '
      + '<item id="css" href="style.css" media-type="text/css"/>\n    '
      + manifestItems.join('\n    ');
    var spineXml = spine.map(function (s) { return '<itemref idref="' + s.idref + '"/>'; }).join('\n    ');

    zip.file(OPF, '<?xml version="1.0" encoding="utf-8"?>\n'
      + '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">\n'
      + '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
      + '    <dc:identifier id="pub-id">' + xmlEscape(uid) + '</dc:identifier>\n'
      + '    <dc:title>' + xmlEscape(title) + '</dc:title>\n'
      + (author ? '    <dc:creator>' + xmlEscape(author) + '</dc:creator>\n' : '')
      + '    <dc:language>' + xmlEscape(lang) + '</dc:language>\n'
      + '    <meta property="dcterms:modified">' + stamp() + '</meta>\n'
      + '  </metadata>\n'
      + '  <manifest>\n    ' + manifest + '\n  </manifest>\n'
      + '  <spine toc="ncx">\n    ' + spineXml + '\n  </spine>\n'
      + '</package>\n', {compression: 'DEFLATE'});

    // 合成 book：只填 exportEpub 与 collectHeadingsForNav 会读的那几个字段。
    // _headingCache 直接给 ensureHeadingIds 的返回值，不再二次提取 ——
    // 二次提取会丢掉刚补上的 id（N9 的成因：zip 里的正文与 nav 缓存不同源）。
    var book = {
      zip: zip,
      changes: {},
      spine: spine,
      manifest: {},
      opfPath: OPF,
      opfDir: 'OEBPS',
      navPath: NAV,
      ncxPath: NCX,
      identifier: uid,
      title: title,
      creator: author,
      language: lang,
      _headingCache: cache,
      originalNav: null
    };
    for (var k = 0; k < spine.length; k++) {
      book.manifest[spine[k].idref] = {id: spine[k].idref, href: spine[k].href,
                                       path: spine[k].path, mediaType: 'application/xhtml+xml'};
    }

    var blob = await EpubCore.exportEpub(book, {autoToc: true});
    return {blob: blob, chapters: spine.length, headings: total, uid: uid};
  }

  return {
    buildEpub: buildEpub,
    splitByH1: splitByH1,
    stripCtrl: stripCtrl,
    closeVoid: closeVoid,
    MAX_CHAPTERS: MAX_CHAPTERS,
    _version: '1.0.0'
  };
});

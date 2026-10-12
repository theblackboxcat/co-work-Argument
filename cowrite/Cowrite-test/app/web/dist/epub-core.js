/*!
 * epub-core.js — 浏览器端 EPUB 导入 / 目录解析 / 编辑 / 重新打包核心逻辑（无 DOM 依赖）
 * License: MIT
 * 依赖：JSZip（UMD 全局 `JSZip`，或 CommonJS require('jszip')）
 *       heading-core.js（UMD 全局 `HeadingCore`，或 require('./heading-core.js')）
 *       —— 依赖方向单向（TC-4）：heading-core ← epub-core，反过来不行
 */
(function (global, factory) {
  if (typeof module === 'object' && typeof module.exports === 'object') {
    module.exports = factory(require('jszip'), require('./heading-core.js'));
  } else {
    global.EpubCore = factory(global.JSZip, global.HeadingCore);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function (JSZip, HeadingCore) {
  'use strict';

  /* 缺 heading-core 就在【加载时】抛，不静默降级 —— 静默降级正是 E3 的成因。
     浏览器侧要求 index.html 里 heading-core.js 的 <script> 排在本文件之前。 */
  if (!HeadingCore || typeof HeadingCore.ensureHeadingIds !== 'function') {
    throw new Error('epub-core: 没拿到 heading-core（它必须在本文件之前加载）');
  }

  var MIME_EPUB = 'application/epub+zip';

  /* ============================ 微型 XML 解析 ============================ */
  function localName(name) {
    var i = name.indexOf(':');
    return i > -1 ? name.slice(i + 1) : name;
  }
  function parseXml(src) {
    var root = null, stack = [];
    var re = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|<!DOCTYPE[^>]*>|<\/?[^>]*>|[^<]+/g;
    var m, textBuf = '';
    function flushText() {
      if (textBuf && stack.length) {
        stack[stack.length - 1].text += textBuf;
      }
      textBuf = '';
    }
    while ((m = re.exec(src))) {
      var t = m[0];
      if (!t.trim()) continue;
      if (t.charAt(0) !== '<') { textBuf += t; continue; }
      if (t.indexOf('<!--') === 0 || t.indexOf('<![CDATA[') === 0 ||
          t.indexOf('<?') === 0 || t.indexOf('<!DOCTYPE') === 0) {
        if (t.indexOf('<![CDATA[') === 0) {
          textBuf += t.slice(9, -3);
        }
        continue;
      }
      flushText();
      if (t.indexOf('</') === 0) {
        stack.pop();
      } else {
        var inner = t.slice(1, -1).trim();
        var selfClose = inner.charAt(inner.length - 1) === '/';
        var body = selfClose ? inner.slice(0, -1) : inner;
        var mm = body.match(/^([^\s/>]+)([\s\S]*)$/);
        if (!mm) continue;
        var node = { name: localName(mm[1]), rawName: mm[1], attrs: {}, children: [], text: '' };
        var attrRe = /([^\s=]+)\s*=\s*("([^"]*)"|'([^']*)')/g;
        var a;
        while ((a = attrRe.exec(mm[2]))) {
          node.attrs[a[1]] = a[3] !== undefined ? a[3] : a[4];
        }
        if (stack.length) stack[stack.length - 1].children.push(node);
        else if (!root) root = node;
        if (!selfClose) stack.push(node);
      }
    }
    flushText();
    return root;
  }
  function findChildren(node, local) {
    var out = [];
    if (!node || !node.children) return out;
    for (var i = 0; i < node.children.length; i++) {
      if (node.children[i].name === local) out.push(node.children[i]);
    }
    return out;
  }
  function findDescendant(node, local) {
    if (!node) return null;
    var queue = node.children ? node.children.slice() : [];
    while (queue.length) {
      var cur = queue.shift();
      if (cur.name === local) return cur;
      if (cur.children) queue = queue.concat(cur.children);
    }
    return null;
  }
  function findDescendants(node, local, out) {
    out = out || [];
    if (!node || !node.children) return out;
    for (var i = 0; i < node.children.length; i++) {
      var c = node.children[i];
      if (c.name === local) out.push(c);
      findDescendants(c, local, out);
    }
    return out;
  }
  function attr(node, name) {
    if (!node || !node.attrs) return undefined;
    for (var k in node.attrs) {
      if (localName(k) === name) return node.attrs[k];
    }
    return undefined;
  }
  function textContent(node) {
    if (!node) return '';
    var s = node.text || '';
    for (var i = 0; i < node.children.length; i++) s += textContent(node.children[i]);
    return s;
  }
  function decodeEntities(s) {
    return String(s)
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&#x([0-9a-fA-F]+);/g, function (_, h) { return String.fromCodePoint(parseInt(h, 16)); })
      .replace(/&#(\d+);/g, function (_, d) { return String.fromCodePoint(parseInt(d, 10)); });
  }

  /* ============================ 路径工具 ============================ */
  function dirname(p) {
    var i = p.lastIndexOf('/');
    return i === -1 ? '' : p.slice(0, i);
  }
  function normPath(p) {
    if (!p) return p;
    p = String(p).replace(/\\/g, '/').replace(/^\.\//, '');
    while (p.charAt(0) === '/') p = p.slice(1);
    return p;
  }
  function resolvePath(baseDir, href) {
    var parts = (normPath(baseDir) + '/' + normPath(href)).split('/');
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var seg = parts[i];
      if (!seg || seg === '.') continue;
      if (seg === '..') { out.pop(); continue; }
      out.push(seg);
    }
    return out.join('/');
  }

  /* ============================ ZIP 工具 ============================ */
  function entryPaths(zip) {
    return Object.keys(zip.files || {});
  }
  function findZipEntry(zip, path) {
    path = normPath(path);
    if (!path) return null;
    if (zip.files[path]) return zip.files[path];
    if (zip.files['./' + path]) return zip.files['./' + path];
    var lower = path.toLowerCase();
    var keys = entryPaths(zip);
    for (var i = 0; i < keys.length; i++) {
      if (keys[i].toLowerCase() === lower) return zip.files[keys[i]];
    }
    return null;
  }
  async function entryBytes(zip, path) {
    var entry = findZipEntry(zip, path);
    if (!entry) return null;
    return new Uint8Array(await entry.async('arraybuffer'));
  }
  async function entryText(zip, path) {
    var buf = await entryBytes(zip, path);
    if (buf === null) return null;
    try {
      return new TextDecoder('utf-8', { fatal: false }).decode(buf);
    } catch (e) {
      return new TextDecoder('utf-8').decode(buf);
    }
  }

  /* ============================ 安全清洗 ============================ */
  function sanitizeHtml(html) {
    html = String(html || '')
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
      .replace(/<object[\s\S]*?<\/object>/gi, '')
      .replace(/<embed[\s\S]*?>/gi, '')
      .replace(/\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
      .replace(/\s(href|src)\s*=\s*("javascript:[^"]*"|'javascript:[^']*')/gi, ' $1="#"')
      .replace(/\s(href|src)\s*=\s*(javascript:[^\s>]+)/gi, ' $1="#"')
      .replace(/<link\b[^>]*>/gi, '');
    return html;
  }

  /* ============================ 头部标题扫描 ============================ */
  /* B5(E)：整段迁到 heading-core（R23-b / R32 / R40），这里只剩 re-export。
     原来本函数自带一份属性取值语法：一条以 id 开头、后接可选空白与等号、再取引号内值的
     正则 —— 它没有属性名左边界，于是把 data-id="x" 里的 x 当成了 id（`\b` 在 `-` 之后
     也成立），nav 就此指向文档里不存在的 #x：点了不跳、全程无报错。
     「属性取值语法只许有一份」，那一份在 HeadingCore.attrMap，检测与提取共享同一次解析（R40）。
     ⚠️ 这条注释故意不把那条正则的字面串写出来 —— 测试里有一条 grep 门禁断言
     「本文件里 id 正则命中数 = 0」，注释里留字面串会让门禁自相矛盾（与 heading-core
     里「连注释都不许出现禁用串」是同一条纪律）。
     等价性已实跑对过 16 个用例：13 例输出逐字相同，3 例不同，而**不同的正是 B5 裁掉的三例**
     （`data-id="x"` 不再被当成 id / 无引号的 id=aa 现在读得到 / `id=""` 的 id 键
      从缺失变成空串 —— 后者所有消费点都写 `h.id || ''` 或 `hs[j].id ? …`，下游无差别）。 */
  var headingsFromHtml = HeadingCore.headingsFromHtml;
  /* ============================ 书籍解析 ============================ */
  async function parseBook(zip) {
    var book = {
      zip: zip,
      title: '',
      creator: '',
      language: '',
      version: '',
      opfDir: '',
      manifest: [],        // [{id, href, path, mediaType, properties}]
      spine: [],           // [{idref, path, title, href}]
      toc: [],             // 嵌套目录 [{label, href, children}]
      tocFlat: [],
      navPath: null,       // EPUB3 nav.xhtml
      ncxPath: null,       // EPUB2 toc.ncx
      opfPath: null,
      coverPath: null,
      drm: false,
      changes: {},         // path -> Uint8Array（编辑后的文件）
      originalNav: null
    };

    // 1. container.xml -> rootfile
    var containerXml = await entryText(zip, 'META-INF/container.xml');
    if (containerXml === null) throw new Error('不是有效的 EPUB：缺少 META-INF/container.xml');
    var container = parseXml(containerXml);
    var rootfile = findDescendant(container, 'rootfile');
    if (!rootfile) throw new Error('container.xml 中未找到 rootfile');
    book.opfPath = normPath(attr(rootfile, 'full-path'));
    if (!book.opfPath) throw new Error('container.xml 中 rootfile 缺少 full-path');
    book.opfDir = dirname(book.opfPath);

    // 2. OPF
    var opfXml = await entryText(zip, book.opfPath);
    if (opfXml === null) throw new Error('缺少 OPF 文件：' + book.opfPath);
    var opf = parseXml(opfXml);
    book.version = attr(opf, 'version') || '';
    var metadata = findChildren(opf, 'metadata')[0] || { children: [] };
    var dcTitle = findDescendant(metadata, 'title');
    var dcCreator = findDescendant(metadata, 'creator');
    var dcLang = findDescendant(metadata, 'language');
    if (dcTitle) book.title = decodeEntities(textContent(dcTitle)).trim();
    if (dcCreator) book.creator = decodeEntities(textContent(dcCreator)).trim();
    if (dcLang) book.language = decodeEntities(textContent(dcLang)).trim();

    // cover（meta name="cover" -> manifest id）
    var metaCover = null, metas = findDescendants(metadata, 'meta');
    for (var i = 0; i < metas.length; i++) {
      if (attr(metas[i], 'name') === 'cover') metaCover = attr(metas[i], 'content');
    }

    // manifest
    var manifestEl = findChildren(opf, 'manifest')[0];
    var itemEls = manifestEl ? findChildren(manifestEl, 'item') : [];
    var byId = {};
    for (var j = 0; j < itemEls.length; j++) {
      var id = attr(itemEls[j], 'id');
      var href = attr(itemEls[j], 'href');
      var mediaType = attr(itemEls[j], 'media-type') || '';
      var properties = attr(itemEls[j], 'properties') || '';
      if (!href) continue;
      var path = resolvePath(book.opfDir, href);
      var rec = { id: id, href: href, path: path, mediaType: mediaType, properties: properties };
      book.manifest.push(rec);
      if (id) byId[id] = rec;
      if (/\bcover-image\b/.test(properties)) book.coverPath = path;
      if (/\bnav\b/.test(properties)) book.navPath = path;
      if (mediaType === 'application/x-dtbncx+xml') book.ncxPath = path;
    }
    if (!book.coverPath && metaCover && byId[metaCover]) book.coverPath = byId[metaCover].path;

    // spine
    var spineEl = findChildren(opf, 'spine')[0];
    var spineTocId = spineEl ? attr(spineEl, 'toc') : '';
    var itemrefs = spineEl ? findChildren(spineEl, 'itemref') : [];
    for (var s = 0; s < itemrefs.length; s++) {
      var idref = attr(itemrefs[s], 'idref');
      var rec2 = byId[idref];
      if (rec2 && rec2.mediaType.indexOf('html') !== -1) {
        book.spine.push({ idref: idref, path: rec2.path, href: rec2.href, title: '' });
      }
    }
    if (!book.spine.length) {
      // 兜底：任何 html 文件都收进来
      for (var k = 0; k < book.manifest.length; k++) {
        if (book.manifest[k].mediaType.indexOf('html') !== -1) {
          book.spine.push({ idref: book.manifest[k].id, path: book.manifest[k].path, href: book.manifest[k].href, title: '' });
        }
      }
    }

    // nav 兜底：EPUB2 用 spine toc 指向的 ncx
    if (!book.navPath && spineTocId && byId[spineTocId]) {
      if (byId[spineTocId].mediaType === 'application/x-dtbncx+xml') book.ncxPath = byId[spineTocId].path;
    }
    if (!book.navPath) {
      var navGuess = resolvePath(book.opfDir, 'nav.xhtml');
      if (findZipEntry(zip, navGuess)) book.navPath = navGuess;
    }

    // 3. 目录
    if (book.navPath) {
      var navText = await entryText(zip, book.navPath);
      if (navText) {
        book.originalNav = navText;
        book.toc = parseNavToc(navText, dirname(book.navPath));
      }
    }
    if (!book.toc.length && book.ncxPath) {
      var ncxText = await entryText(zip, book.ncxPath);
      if (ncxText) book.toc = parseNcxToc(ncxText, dirname(book.ncxPath));
    }
    book.tocFlat = flattenToc(book.toc);

    // 4. DRM 检测
    book.drm = !!findZipEntry(zip, 'META-INF/encryption.xml') || !!findZipEntry(zip, 'META-INF/rights.xml');

    return book;
  }

  /* ============================ 目录解析 ============================ */
  function parseNavToc(navXmlText, base) {
    var root = parseXml(navXmlText);
    if (!root) return [];
    // 找 epub:type="toc" 或 role="doc-toc" 的 nav，否则第一个 nav
    var navs = findDescendants(root, 'nav');
    var target = null;
    for (var i = 0; i < navs.length; i++) {
      var et = attr(navs[i], 'type') || attr(navs[i], 'epub:type') || '';
      var role = attr(navs[i], 'role') || '';
      if (et.indexOf('toc') !== -1 || role.indexOf('doc-toc') !== -1) { target = navs[i]; break; }
    }
    if (!target && navs.length) target = navs[0];
    if (!target) return [];
    return parseNavList(findChildren(target, 'ol')[0], base);
  }
  function parseNavList(ol, base) {
    var out = [];
    if (!ol) return out;
    var lis = findChildren(ol, 'li');
    for (var i = 0; i < lis.length; i++) {
      var li = lis[i];
      var a = findDescendant(li, 'a');
      var label = '', href = '';
      if (a) {
        label = decodeEntities(textContent(a)).replace(/\s+/g, ' ').trim();
        href = attr(a, 'href') || '';
      } else {
        var span = findDescendant(li, 'span');
        if (span) label = decodeEntities(textContent(span)).replace(/\s+/g, ' ').trim();
      }
      if (!label) {
        // 直接文本
        var direct = li.text || '';
        if (direct) label = decodeEntities(direct).replace(/\s+/g, ' ').trim();
      }
      var children = [];
      var ols = findChildren(li, 'ol');
      for (var j = 0; j < ols.length; j++) {
        children = children.concat(parseNavList(ols[j], base));
      }
      out.push({ label: label, href: href, path: href ? resolvePath(base, href.split('#')[0]) : null, children: children });
    }
    return out;
  }
  function parseNcxToc(ncxText, base) {
    var root = parseXml(ncxText);
    if (!root) return [];
    var navMap = findDescendant(root, 'navMap');
    if (!navMap) return [];
    return parseNavPoints(findChildren(navMap, 'navPoint'), base);
  }
  function parseNavPoints(navPoints, base) {
    var out = [];
    for (var i = 0; i < navPoints.length; i++) {
      var np = navPoints[i];
      var labelEl = findDescendant(np, 'text');
      var contentEl = findDescendant(np, 'content');
      var label = labelEl ? decodeEntities(textContent(labelEl)).replace(/\s+/g, ' ').trim() : '';
      var href = contentEl ? attr(contentEl, 'src') || '' : '';
      var children = parseNavPoints(findChildren(np, 'navPoint'), base);
      out.push({ label: label, href: href, path: href ? resolvePath(base, href.split('#')[0]) : null, children: children });
    }
    return out;
  }
  function flattenToc(toc) {
    var out = [];
    (function walk(list) {
      for (var i = 0; i < list.length; i++) {
        out.push(list[i]);
        if (list[i].children) walk(list[i].children);
      }
    })(toc);
    return out;
  }

  /* ============================ 章节读取 / 还原 ============================ */
  async function loadChapter(book, index, opts) {
    opts = opts || {};
    var item = book.spine[index];
    if (!item) throw new Error('章节不存在：' + index);
    var raw = await entryText(book.zip, item.path);
    if (raw === null) throw new Error('无法读取章节文件：' + item.path);

    var bodyMatch = raw.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
    var beforeBody = raw.slice(0, bodyMatch ? raw.indexOf(bodyMatch[0]) + bodyMatch[0].indexOf('>') + 1 : 0);
    // beforeBody 定位到 <body ...> 结束
    if (!bodyMatch) {
      beforeBody = '';
    } else {
      var openTagEnd = raw.indexOf(bodyMatch[0]) + bodyMatch[0].indexOf('>') + 1;
      beforeBody = raw.slice(0, openTagEnd);
    }
    var afterBody = '';
    if (bodyMatch) {
      var closeIdx = raw.indexOf('</body>', raw.indexOf(bodyMatch[0]) + 1);
      afterBody = closeIdx === -1 ? '' : raw.slice(closeIdx);
    }
    var bodyHtml = bodyMatch ? bodyMatch[1] : raw;

    // 重写内部资源引用为可显示 URL
    var refs = []; // {objectUrl, path}
    var rewritten = await rewriteResources(bodyHtml, book.zip, dirname(item.path), refs, opts);

    // 记录章节骨架与标题缓存，供还原/目录重生成使用
    if (!book._skel) book._skel = {};
    if (!book._headingCache) book._headingCache = {};
    book._skel[item.path] = { beforeBody: beforeBody, afterBody: afterBody };

    // 清洗 + 补标题 id + 收集标题
    var clean = sanitizeHtml(rewritten);
    /* 🔴 T-9 / KL-1 断言（nat L9：写成断言而不是说明 —— 说明会被后来的人当 bug 顺手"修好"）：
       这里的 startIndex **恒为 1**。回写式导出是【逐章】调用本函数的，每章编号都从 eebk-1
       重新开始，所以它的锚点【不会】与目录面板（全文一次编号得 eebk-1…N）对齐。
       **这是范围边界，不是缺陷。** 跨章的全局连续性由甲档的 nextIndex 累加器保证
       （T-9a，tom 与 lucy 双签：c1→1,2 / c2→3,4,5 / c3→6）。
       唯一的"修法"是把这个 1 换成累计值 —— 那会【静默改变回写式产物】，禁止。 */
    var ensured = HeadingCore.ensureHeadingIds(clean, { startIndex: 1 });
    clean = ensured.html;
    var headings = ensured.headings.map(function (h) {
      return { level: h.level, id: h.id || '', text: h.text };
    });
    book._headingCache[item.path] = headings;

    return {
      index: index, item: item, path: item.path,
      beforeBody: beforeBody, afterBody: afterBody,
      html: clean, headings: headings, refs: refs
    };
  }

  async function rewriteResources(html, zip, base, refs, opts) {
    var mode = (opts && opts.rewriteMode) || 'objectUrl';
    async function toUrl(t) {
      var buf = await entryBytes(zip, t.path);
      if (!buf) return null;
      if (mode === 'dataUri') {
        var mime = mimeOf(t.path);
        var b64 = toBase64(buf);
        return 'data:' + mime + ';base64,' + b64;
      }
      var url = URL.createObjectURL(new Blob([buf], { type: mimeOf(t.path) }));
      refs.push({ objectUrl: url, path: t.path, href: t.href });
      return url;
    }
    var tasks = [];
    var salt = Math.random().toString(36).slice(2, 8);
    function token(i) { return '__EEREF_' + i + '_' + salt + '__'; }
    // srcset（逗号分隔候选，如 "a.jpg 320w, b.jpg 640w"）
    html = html.replace(/\bsrcset\s*=\s*("([^"]*)"|'([^']*)')/gi, function (whole, q, val) {
      if (/^(https?:|data:|blob:)/i.test(val.trim())) return whole;
      var rebuilt = val.split(',').map(function (p) {
        var sp = p.trim().split(/\s+/);
        var ref = sp[0];
        if (!ref || /^(https?:|data:|blob:)/i.test(ref)) return p.trim();
        var path = resolvePath(base, ref);
        var tk = token(tasks.length);
        tasks.push({ path: path, token: tk, href: ref });
        sp[0] = tk;
        return sp.join(' ');
      }).join(', ');
      return whole.replace(val, rebuilt);
    });
    // src / href / poster
    html = html.replace(/\b(src|href|poster)\s*=\s*("([^"]*)"|'([^']*)')/gi, function (whole, name, q, val) {
      if (!val || /^(https?:|data:|blob:|#|javascript:|mailto:)/i.test(val)) return whole;
      var path = resolvePath(base, val);
      var tk = token(tasks.length);
      tasks.push({ path: path, token: tk, href: val });
      return whole.replace(val, tk);
    });
    for (var i = 0; i < tasks.length; i++) {
      var url = await toUrl(tasks[i]);
      if (url) html = html.split(tasks[i].token).join(url);
    }
    return html;
  }
  function toBase64(u8) {
    var s = '';
    var CHUNK = 0x8000;
    for (var i = 0; i < u8.length; i += CHUNK) {
      s += String.fromCharCode.apply(null, u8.subarray(i, i + CHUNK));
    }
    return btoa(s);
  }
  function mimeOf(path) {
    var ext = (path.split('.').pop() || '').toLowerCase();
    var map = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif',
      webp: 'image/webp', svg: 'image/svg+xml', css: 'text/css', mp3: 'audio/mpeg',
      mp4: 'video/mp4', ogg: 'audio/ogg', wav: 'audio/wav', woff: 'font/woff',
      woff2: 'font/woff2', ttf: 'font/ttf', otf: 'font/otf' };
    return map[ext] || 'application/octet-stream';
  }

  function restoreChapter(book, index, editedHtml, refs) {
    var item = book.spine[index];
    if (!item) throw new Error('章节不存在：' + index);
    var content = String(editedHtml || '');
    // 资源 URL 还原为原始相对路径（保持 xhtml 内部引用自洽）
    for (var i = 0; i < refs.length; i++) {
      var ref = refs[i];
      if (ref.objectUrl) {
        content = content.split(ref.objectUrl).join(ref.href || ref.path);
      }
    }
    // 生成完整 xhtml：保留原始前后骨架
    var src = (book._skel && book._skel[item.path]) ? book._skel[item.path] : null;
    var out;
    if (src && src.beforeBody && src.afterBody) {
      out = src.beforeBody + content + src.afterBody;
    } else {
      out = '<?xml version="1.0" encoding="utf-8"?>\n' +
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n' +
        '<head><title></title></head>\n<body>\n' + content + '\n</body>\n</html>';
    }
    return new TextEncoder().encode(out);
  }

  /* ============================ 导出 EPUB ============================ */
  async function exportEpub(book, opts) {
    opts = opts || {};
    var zip = new JSZip();
    // 关键：mimetype 必须第一个写入且不压缩（STORE）
    zip.file('mimetype', MIME_EPUB, { compression: 'STORE' });

    var names = entryPaths(book.zip).filter(function (n) { return !book.zip.files[n].dir; });
    // 原样保留所有文件（含未修改的二进制），修改过的章节用新内容
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      if (name === 'mimetype') continue;
      var data;
      if (Object.prototype.hasOwnProperty.call(book.changes, name)) {
        data = book.changes[name];
      } else {
        data = await book.zip.files[name].async('uint8array');
      }
      zip.file(name, data, { compression: 'DEFLATE' });
    }
    // 目录重新生成（编辑后标题变化时保证目录正确）
    if (opts.autoToc !== false && (book.navPath || book.ncxPath)) {
      try {
        if (book.navPath) {
          var navHtml = buildNavXhtml(book);
          if (navHtml) zip.file(book.navPath, navHtml, { compression: 'DEFLATE' });
        }
        if (book.ncxPath) {
          var ncx = buildNcx(book);
          if (ncx) zip.file(book.ncxPath, ncx, { compression: 'DEFLATE' });
        }
      } catch (e) {
        // 目录生成失败不阻塞导出
      }
    }
    var blob = await zip.generateAsync({
      type: 'blob', mimeType: MIME_EPUB,
      compression: 'DEFLATE', compressionOptions: { level: 6 }
    });
    return blob;
  }

  /* ============================ 目录重新生成 ============================ */
  function collectHeadingsForNav(book) {
    // 返回 [{href, level, id, text}]，href 相对 nav 所在目录
    var out = [];
    var navDir = book.navPath ? dirname(book.navPath) : book.opfDir;
    for (var i = 0; i < book.spine.length; i++) {
      var item = book.spine[i];
      var html = null;
      if (Object.prototype.hasOwnProperty.call(book.changes, item.path)) {
        html = new TextDecoder('utf-8').decode(book.changes[item.path]);
      } else {
        // 同步读不到：从 book 缓存取（loadChapter 时写入 book._headingCache）
        if (book._headingCache && book._headingCache[item.path]) {
          out = out.concat(book._headingCache[item.path].map(function (h) {
            return { href: relPath(navDir, item.path) + (h.id ? '#' + h.id : ''), level: h.level, id: h.id, text: h.text };
          }));
          continue;
        }
      }
      if (html === null) continue;
      var hs = headingsFromHtml(html);
      for (var j = 0; j < hs.length; j++) {
        out.push({ href: relPath(navDir, item.path) + (hs[j].id ? '#' + hs[j].id : ''), level: hs[j].level, id: hs[j].id, text: hs[j].text });
      }
    }
    return out;
  }
  function relPath(fromDir, to) {
    var from = normPath(fromDir).split('/').filter(Boolean);
    var toParts = normPath(to).split('/').filter(Boolean);
    var i = 0;
    while (i < from.length && i < toParts.length && from[i] === toParts[i]) i++;
    var up = [];
    for (var k = i; k < from.length; k++) up.push('..');
    return up.concat(toParts.slice(i)).join('/') || '';
  }
  /* B5 迁移的第二半：本函数与 heading-core 里那份【逐字节相同】（实测两边各 452 字节），
     所以改成 re-export 是**零行为变更**。目录面板要用同一套嵌套规则 —— 留两份必然漂移
     （P-SINGLE）。它不进导出清单：全仓没有外部消费者，公开面越小越稳。 */
  var nestHeadings = HeadingCore.nestHeadings;
  function renderNestedOl(nodes, indent) {
    indent = indent || '';
    if (!nodes.length) return '';
    var s = indent + '<ol>\n';
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      var label = escapeXml(n.text || '');
      s += indent + '  <li>' + (n.href ? '<a href="' + escapeXml(n.href) + '">' + label + '</a>' : label);
      s += renderNestedOl(n.children, indent + '    ');
      s += indent + '  </li>\n';
    }
    s += indent + '</ol>';
    return s;
  }
  function escapeXml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function buildNavXhtml(book) {
    var list = collectHeadingsForNav(book);
    if (!list.length) return null;
    var nested = nestHeadings(list);
    var body = renderNestedOl(nested, '      ');
    var ns = 'xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"';
    // N3：原来 originalNav 为空时 head 取 '' → 产出 <head></head>，XHTML 缺 <title>
    // 不合法。从零打包的那条路必然踩到（它没有 originalNav），所以兜底给个 title。
    var head = book.originalNav
      ? extractOriginalNavHead(book.originalNav) : '<title>Table of Contents</title>';
    return '<?xml version="1.0" encoding="utf-8"?>\n' +
      '<html ' + ns + '>\n<head>' + head + '</head>\n<body>\n' +
      '  <nav epub:type="toc" id="toc">\n' + body + '\n  </nav>\n</body>\n</html>\n';
  }
  function extractOriginalNavHead(nav) {
    var m = nav.match(/<head[^>]*>([\s\S]*?)<\/head>/i);
    return m ? m[1] : '<title>Table of Contents</title>';
  }
  function buildNcx(book) {
    var list = collectHeadingsForNav(book);
    if (!list.length) return null;
    var s = '';
    var playOrder = 0;
    (function walk(nodes) {
      for (var i = 0; i < nodes.length; i++) {
        playOrder++;
        s += '<navPoint id="np-' + playOrder + '" playOrder="' + playOrder + '">' +
          '<navLabel><text>' + escapeXml(nodes[i].text) + '</text></navLabel>' +
          '<content src="' + escapeXml(nodes[i].href) + '"/>';
        // N1：子级直接嵌 navPoint。原来用 <navMap> 包一层，而 NCX 2005-1 里 navMap
        // 只能是 ncx 的唯一根子元素 —— 嵌套 navMap 是非法结构，EPUB2 老阅读器
        // 会整本目录失效。
        if (nodes[i].children && nodes[i].children.length) walk(nodes[i].children);
        s += '</navPoint>';
      }
    })(nestHeadings(list));
    // N2：dtb:uid 原来写死空串，应与 OPF 的 unique-identifier 同值，否则 epubcheck 报错。
    var uid = book.identifier || book.uid || '';
    return '<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n' +
      '<head><meta name="dtb:uid" content="' + escapeXml(uid) + '"/></head>\n' +
      '<docTitle><text>' + escapeXml(book.title || '') + '</text></docTitle>\n' +
      '<navMap>\n' + s + '\n</navMap>\n</ncx>\n';
  }

  /* ============================ 导出单文件 HTML ============================ */
  async function exportHtml(book, opts) {
    opts = opts || {};
    var sections = [];
    for (var i = 0; i < book.spine.length; i++) {
      var item = book.spine[i];
      var content = '';
      if (Object.prototype.hasOwnProperty.call(book.changes, item.path)) {
        content = new TextDecoder('utf-8').decode(book.changes[item.path]);
      } else {
        content = await entryText(book.zip, item.path);
      }
      if (content === null) continue;
      var bm = content.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
      var html = bm ? bm[1] : content;
      html = sanitizeHtml(html);
      // 内部资源转 data URI
      var refs = [];
      html = await rewriteResources(html, book.zip, dirname(item.path), refs, { rewriteMode: 'dataUri' });
      if (!/^<h[1-6][\s>]/i.test(html.trim())) {
        html = '<h2>' + escapeHtmlForBody((book._headingCache && book._headingCache[item.path] && book._headingCache[item.path][0] ? book._headingCache[item.path][0].text : '第 ' + (i + 1) + ' 章')) + '</h2>' + html;
      }
      sections.push('<section>\n' + html + '\n</section>');
    }
    var css = 'body{max-width:44em;margin:0 auto;padding:2em 1.2em;line-height:1.75;color:#222;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;}' +
      'img{max-width:100%;height:auto;}h1,h2,h3{line-height:1.3;}section{margin-bottom:2.5em;}blockquote{border-left:3px solid #ccc;margin:1em 0;padding:.3em 1em;color:#555;}';
    var doc = '<!DOCTYPE html>\n<html lang="' + escapeHtmlForBody(book.language || 'zh') + '">\n<head>\n<meta charset="utf-8">\n' +
      '<title>' + escapeHtmlForBody(book.title || '导出的书') + '</title>\n' +
      '<style>' + css + '</style>\n</head>\n<body>\n' +
      '<h1>' + escapeHtmlForBody(book.title || '') + '</h1>' +
      (book.creator ? '<p style="color:#777">' + escapeHtmlForBody(book.creator) + '</p>' : '') +
      sections.join('\n') + '\n</body>\n</html>';
    return new Blob([doc], { type: 'text/html;charset=utf-8' });
  }
  function escapeHtmlForBody(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  return {
    MIME_EPUB: MIME_EPUB,
    parseXml: parseXml,
    parseBook: parseBook,
    loadChapter: loadChapter,
    restoreChapter: restoreChapter,
    exportEpub: exportEpub,
    exportHtml: exportHtml,
    buildNavXhtml: buildNavXhtml,
    buildNcx: buildNcx,
    headingsFromHtml: headingsFromHtml,
    sanitizeHtml: sanitizeHtml,
    resolvePath: resolvePath,
    normPath: normPath,
    findZipEntry: findZipEntry,
    entryText: entryText,
    entryBytes: entryBytes,
    flattenToc: flattenToc,
    decodeEntities: decodeEntities,
    /* N4（lucy seq=47 §1）：这两个原先在清单外，甲档打包器要用 ——
       escapeXml 转义 OPF/nav 里的 title 与 creator，mimeOf 给乙档的图片资源。
       是【加】不是【缩】，与 A4「导出清单不得缩水」相容：18 键 → 20 键。 */
    escapeXml: escapeXml,
    mimeOf: mimeOf
  };
});

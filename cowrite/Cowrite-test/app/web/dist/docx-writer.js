/*!
 * docx-writer.js — 浏览器端「HTML + 页面设置 → Word(.docx)」生成器（OOXML，纯逻辑，无 DOM 依赖）
 * License: MIT
 * 依赖：JSZip（UMD 全局 JSZip / CommonJS require('jszip')）
 *
 * 能力：段落/标题/对齐/字号/颜色/加粗斜体下划线删除线/列表(项目符号与编号，可嵌套)/
 *       引用/代码块/分割线/超链接/图片(内嵌 data URI)/页面大小/页边距/栏数/行距
 */
(function (global, factory) {
  if (typeof module === 'object' && typeof module.exports === 'object') {
    module.exports = factory(require('jszip'));
  } else {
    global.DocWriter = factory(global.JSZip);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function (JSZip) {
  'use strict';

  var NS_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
  var NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
  var NS_REL = 'http://schemas.openxmlformats.org/package/2006/relationships';
  var NS_CT = 'http://schemas.openxmlformats.org/package/2006/content-types';
  var NS_WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing';
  var NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main';
  var NS_PIC = 'http://schemas.openxmlformats.org/drawingml/2006/picture';
  var REL_DOC = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument';
  var REL_STYLES = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles';
  var REL_NUM = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering';
  var REL_IMAGE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image';
  var REL_HLINK = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink';

  var MM_TO_TWIPS = 1440 / 25.4;      // 1mm = 56.6929 twips
  var EMU_PER_MM = 36000;

  /* ================= 工具 ================= */
  function mmTwips(mm) { return Math.round(mm * MM_TO_TWIPS); }
  function mmEmu(mm) { return Math.round(mm * EMU_PER_MM); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function colorHex(c) {
    if (!c) return null;
    c = String(c).trim();
    if (/^#[0-9a-fA-F]{3}$/.test(c)) {
      return c.slice(1).split('').map(function (x) { return x + x; }).join('').toUpperCase();
    }
    if (/^#[0-9a-fA-F]{6}$/.test(c)) return c.slice(1).toUpperCase();
    var m = c.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
    if (m) {
      return [m[1], m[2], m[3]].map(function (v) {
        var h = parseInt(v, 10).toString(16);
        return h.length === 1 ? '0' + h : h;
      }).join('').toUpperCase();
    }
    return c.toUpperCase(); // 颜色名（OOXML 支持部分命名色）
  }
  function ptFromSize(s) {
    if (!s) return null;
    s = String(s).trim();
    var m = s.match(/^([\d.]+)\s*(pt|px)$/i);
    if (!m) return null;
    var v = parseFloat(m[1]);
    if (/px/i.test(m[2])) v = v * 0.75; // 96dpi 换算
    return Math.max(4, Math.round(v * 2) / 2); // 半步取整
  }

  /* ================= 图片尺寸（从字节解析，同步、可测） ================= */
  function imageMeta(bytes) {
    if (!bytes || bytes.length < 24) return null;
    var b = bytes;
    // PNG: 8B 签名 + IHDR(4 len + 'IHDR')，宽高在偏移 16/20
    if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) {
      return { width: b.readUInt32BE ? b.readUInt32BE(16) : (b[16] << 24 | b[17] << 16 | b[18] << 8 | b[19]),
               height: b.readUInt32BE ? b.readUInt32BE(20) : (b[20] << 24 | b[21] << 16 | b[22] << 8 | b[23]) };
    }
    // GIF: 'GIF8' + 宽高 LE(6/8)
    if (b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46) {
      return { width: b[6] | b[7] << 8, height: b[8] | b[9] << 8 };
    }
    // JPEG: 扫 SOF0/1/2 段
    if (b[0] === 0xff && b[1] === 0xd8) {
      var i = 2;
      while (i + 9 < b.length) {
        if (b[i] !== 0xff) { i++; continue; }
        var marker = b[i + 1];
        var len = (b[i + 2] << 8) | b[i + 3];
        if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
          var h = (b[i + 5] << 8) | b[i + 6];
          var w = (b[i + 7] << 8) | b[i + 8];
          return { width: w, height: h };
        }
        i += len + 2;
      }
    }
    return null;
  }
  function dataUriToBytes(uri) {
    var m = String(uri || '').match(/^data:([^;,]+)?(;base64)?,(.*)$/i);
    if (!m) return null;
    var raw = m[3];
    if (m[2]) {
      if (typeof atob === 'function') {
        var bin = atob(raw);
        var u8 = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
        return u8;
      }
      return Buffer.from(raw, 'base64');
    }
    // 未编码数据：尝试 UTF-8
    var s = decodeURIComponent(raw);
    var out = new Uint8Array(s.length);
    for (var j = 0; j < s.length; j++) out[j] = s.charCodeAt(j) & 0xff;
    return out;
  }
  function mimeOfDataUri(uri) {
    var m = String(uri || '').match(/^data:([^;,]+)/i);
    return m ? m[1].toLowerCase() : 'image/png';
  }
  function extOfMime(mime) {
    return { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/gif': 'gif',
      'image/bmp': 'bmp', 'image/webp': 'webp', 'image/svg+xml': 'svg' }[mime] || 'png';
  }

  /* ================= HTML 解析（浏览器端，返回块节点） ================= */
  // 节点结构：
  // { type:'p'|'h1'..'h6'|'blockquote'|'pre'|'hr'|'img'|'list',
  //   inlines:[{text,bold,italic,underline,strike,color,sizePt,href}],
  //   align, ordered, items:[ [inline..] ], src, widthMm, heightMm }
  function parseHtml(html, page, doc) {
    doc = doc || new DOMParser().parseFromString(String(html || ''), 'text/html');
    var blocks = [];
    var body = doc.body || doc;
    var contentWidthMm = (page.size.width_mm - page.margin.left_mm - page.margin.right_mm) /
      Math.max(1, page.columns || 1);
    parseChildren(body, blocks, contentWidthMm, 0);
    if (!blocks.length) blocks.push({ type: 'p', inlines: [] });
    return blocks;
  }

  function parseChildren(parentEl, out, contentWidthMm, listLevel) {
    var nodes = parentEl.childNodes;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.nodeType === 3) { // 文本
        var txt = n.nodeValue.replace(/\u200b/g, '');
        if (txt.trim()) out.push({ type: 'p', inlines: [{ text: txt }], align: 'left' });
        continue;
      }
      if (n.nodeType !== 1) continue;
      var tag = n.tagName.toLowerCase();
      if (tag === 'script' || tag === 'style' || tag === 'iframe') continue;
      if (tag === 'p' || tag === 'div' || tag === 'section' || tag === 'article') {
        out.push(blockWithInlines(n, tag));
      } else if (/^h[1-6]$/.test(tag)) {
        out.push(blockWithInlines(n, tag));
      } else if (tag === 'blockquote') {
        out.push(blockWithInlines(n, 'blockquote'));
      } else if (tag === 'pre') {
        out.push({ type: 'pre', inlines: [{ text: n.textContent.replace(/\u200b/g, '') }] });
      } else if (tag === 'ul' || tag === 'ol') {
        out.push(parseList(n, tag === 'ol', contentWidthMm));
      } else if (tag === 'img') {
        out.push(parseImage(n, contentWidthMm));
      } else if (tag === 'hr') {
        out.push({ type: 'hr' });
      } else if (tag === 'br') {
        out.push({ type: 'p', inlines: [], align: 'left' });
      } else if (tag === 'table') {
        out.push({ type: 'p', inlines: [{ text: '[表格：请在 Word 中插入表格]' }], align: 'left' });
      } else {
        // 其余容器递归
        parseChildren(n, out, contentWidthMm, listLevel);
      }
    }
  }

  function blockWithInlines(el, tag) {
    var type = /^h[1-6]$/.test(tag) ? tag : (tag === 'blockquote' ? 'blockquote' : 'p');
    return {
      type: type,
      inlines: collectInlines(el),
      align: blockAlign(el)
    };
  }

  function blockAlign(el) {
    var cls = (el.getAttribute && el.getAttribute('class')) || '';
    var m = cls.match(/ql-align-(left|center|right|justify)/);
    if (m) return m[1];
    var st = (el.getAttribute && el.getAttribute('style')) || '';
    var sm = st.match(/text-align\s*:\s*(left|center|right|justify)/i);
    if (sm) return sm[1].toLowerCase();
    return 'left';
  }

  function collectInlines(el) {
    var runs = [];
    walk(el, {});
    return runs;
    function walk(node, fmt) {
      if (node.nodeType === 3) {
        var txt = node.nodeValue.replace(/\u200b/g, '');
        if (txt) runs.push({ text: txt, bold: fmt.bold, italic: fmt.italic,
          underline: fmt.underline, strike: fmt.strike, color: fmt.color, sizePt: fmt.sizePt, href: fmt.href });
        return;
      }
      if (node.nodeType !== 1) return;
      var tag = node.tagName.toLowerCase();
      if (tag === 'script' || tag === 'style' || tag === 'iframe') return;
      var f = shallow(fmt);
      var style = (node.getAttribute && node.getAttribute('style')) || '';
      if (tag === 'b' || tag === 'strong') f.bold = true;
      if (tag === 'i' || tag === 'em') f.italic = true;
      if (tag === 'u') f.underline = true;
      if (tag === 's' || tag === 'del' || tag === 'strike') f.strike = true;
      if (tag === 'a') f.href = node.getAttribute('href') || f.href;
      if (/font-weight\s*:\s*(bold|600|700|800|900)/i.test(style)) f.bold = true;
      if (/font-style\s*:\s*italic/i.test(style)) f.italic = true;
      if (/text-decoration\s*:\s*underline/i.test(style)) f.underline = true;
      if (/text-decoration\s*:\s*line-through/i.test(style)) f.strike = true;
      var cm = style.match(/color\s*:\s*([^;]+)/i);
      if (cm) f.color = cm[1].trim();
      var sm = style.match(/font-size\s*:\s*([^;]+)/i);
      if (sm) {
        var pt = ptFromSize(sm[1]);
        if (pt) f.sizePt = pt;
      }
      if (tag === 'br') { if (runs.length) runs.push({ text: '\n', bold: f.bold, italic: f.italic, underline: f.underline, strike: f.strike, color: f.color, sizePt: f.sizePt, href: f.href }); return; }
      for (var i = 0; i < node.childNodes.length; i++) walk(node.childNodes[i], f);
    }
    function shallow(o) { var r = {}; for (var k in o) r[k] = o[k]; return r; }
  }

  function parseList(ulEl, ordered, contentWidthMm) {
    var items = [];
    var lis = ulEl.children;
    for (var i = 0; i < lis.length; i++) {
      var li = lis[i];
      if (li.tagName.toLowerCase() !== 'li') continue;
      var inlines = collectInlines(li);
      items.push(inlines);
      // 嵌套列表并入同一 items（用 _sub 标记层级）
      for (var j = 0; j < li.children.length; j++) {
        var sub = li.children[j];
        var t = sub.tagName.toLowerCase();
        if (t === 'ul' || t === 'ol') {
          var subList = parseList(sub, t === 'ol', contentWidthMm);
          subList._sub = true;
          items.push(subList);
        }
      }
    }
    return { type: 'list', ordered: ordered, items: items, align: blockAlign(ulEl) };
  }

  function parseImage(imgEl, contentWidthMm) {
    var src = imgEl.getAttribute('src') || '';
    var out = { type: 'img', src: src, widthMm: 0, heightMm: 0 };
    var bytes = /^data:/i.test(src) ? dataUriToBytes(src) : null;
    if (bytes) {
      var meta = imageMeta(bytes);
      if (meta) {
        var maxW = Math.max(20, contentWidthMm - 4);
        var scale = Math.min(1, maxW / meta.width);
        out.widthMm = Math.round(meta.width * scale);
        out.heightMm = Math.round(meta.height * scale);
      }
      out.mime = mimeOfDataUri(src);
      out.bytes = bytes;
    } else if (imgEl.getAttribute('width')) {
      out.widthMm = parseFloat(imgEl.getAttribute('width')) * 0.75;
      out.heightMm = parseFloat(imgEl.getAttribute('height') || '0') * 0.75;
    }
    return out;
  }

  /* ================= OOXML 组装 ================= */
  function buildDocx(blocks, page, opts) {
    opts = opts || {};
    var media = [];        // {rid, ext, bytes}
    var hyperlinks = [];   // {rid, target}
    var needNumbering = blocks.some(function (b) { return b.type === 'list'; });
    var ridCounter = 0;
    function nextRid() { ridCounter++; return 'rId' + ridCounter; }

    var bodyXml = blocks.map(function (b) { return blockToXml(b, page, media, hyperlinks, nextRid, opts); }).join('\n');
    if (!bodyXml.trim()) bodyXml = '<w:p/>';

    var sect = sectPr(page);

    var docXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<w:document xmlns:w="' + NS_W + '" xmlns:r="' + NS_R + '" xmlns:wp="' + NS_WP + '" ' +
      'xmlns:a="' + NS_A + '" xmlns:pic="' + NS_PIC + '">\n<w:body>\n' + bodyXml + '\n' + sect + '\n</w:body>\n</w:document>';

    var rels = [];
    rels.push(relXml('rId-styles', REL_STYLES, 'styles.xml'));
    if (needNumbering) rels.push(relXml('rId-numbering', REL_NUM, 'numbering.xml'));
    media.forEach(function (m) { rels.push(relXml(m.rid, REL_IMAGE, 'media/' + m.file)); });
    hyperlinks.forEach(function (h) { rels.push(relXml(h.rid, REL_HLINK, h.target, true)); });

    var docRelsXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<Relationships xmlns="' + NS_REL + '">\n' + rels.join('\n') + '\n</Relationships>';

    var rootRelsXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<Relationships xmlns="' + NS_REL + '">\n' +
      '<Relationship Id="rId1" Type="' + REL_DOC + '" Target="word/document.xml"/>\n' +
      '</Relationships>';

    var stylesXml = buildStyles(opts);
    var numberingXml = needNumbering ? buildNumbering() : null;

    var contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<Types xmlns="' + NS_CT + '">\n' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n' +
      '<Default Extension="xml" ContentType="application/xml"/>\n' +
      media.map(function (m) { return '<Default Extension="' + m.ext + '" ContentType="' + m.ct + '"/>'; }).join('\n') + '\n' +
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n' +
      '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>\n' +
      (needNumbering ? '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>\n' : '') +
      '</Types>';

    var coreXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ' +
      'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" ' +
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n' +
      '<dc:title>' + esc(opts.title || '') + '</dc:title>\n' +
      '<dc:creator>' + esc(opts.author || '') + '</dc:creator>\n' +
      '<dcterms:created xsi:type="dcterms:W3CDTF">' + isoNow() + '</dcterms:created>\n' +
      '<dcterms:modified xsi:type="dcterms:W3CDTF">' + isoNow() + '</dcterms:modified>\n' +
      '</cp:coreProperties>';

    var appXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" ' +
      'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">\n' +
      '<Application>DocWriter</Application>\n<DocSecurity>0</DocSecurity>\n</Properties>';

    var zip = new JSZip();
    zip.file('[Content_Types].xml', contentTypes);
    zip.file('_rels/.rels', rootRelsXml);
    zip.file('word/document.xml', docXml);
    zip.file('word/_rels/document.xml.rels', docRelsXml);
    zip.file('word/styles.xml', stylesXml);
    if (numberingXml) zip.file('word/numbering.xml', numberingXml);
    media.forEach(function (m) { zip.file('word/media/' + m.file, m.bytes); });
    zip.file('docProps/core.xml', coreXml);
    zip.file('docProps/app.xml', appXml);
    return zip;
  }

  function isoNow() {
    var d = new Date();
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return d.getUTCFullYear() + '-' + p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate()) +
      'T' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()) + ':' + p(d.getUTCSeconds()) + 'Z';
  }

  function relXml(id, type, target, external) {
    return '<Relationship Id="' + id + '" Type="' + type + '" Target="' + esc(target) + '"' +
      (external ? ' TargetMode="External"' : '') + '/>';
  }

  function sectPr(page) {
    var w = mmTwips(page.size.width_mm), h = mmTwips(page.size.height_mm);
    var m = page.margin;
    var cols = Math.max(1, page.columns || 1);
    var colsXml = cols > 1
      ? '<w:cols w:num="' + cols + '" w:space="' + mmTwips(page.columnGap_mm || 12) + '"/>'
      : '<w:cols w:num="1" w:space="0"/>';
    return '<w:sectPr>\n' +
      '<w:pgSz w:w="' + w + '" w:h="' + h + '" w:orient="' + (page.size.landscape ? 'landscape' : 'portrait') + '"/>\n' +
      '<w:pgMar w:top="' + mmTwips(m.top_mm) + '" w:right="' + mmTwips(m.right_mm) + '" ' +
      'w:bottom="' + mmTwips(m.bottom_mm) + '" w:left="' + mmTwips(m.left_mm) + '" ' +
      'w:header="' + mmTwips(m.header_mm || 12.5) + '" w:footer="' + mmTwips(m.footer_mm || 12.5) + '" w:gutter="0"/>\n' +
      colsXml + '\n</w:sectPr>';
  }

  function blockToXml(b, page, media, hyperlinks, nextRid, opts) {
    switch (b.type) {
      case 'h1': case 'h2': case 'h3': case 'h4': case 'h5': case 'h6':
        return paragraphXml(b.inlines, { style: 'Heading' + b.type.slice(1), align: b.align }, media, hyperlinks, nextRid, opts);
      case 'blockquote':
        return paragraphXml(b.inlines, { indentLeft: 720, italic: true, color: '595959', align: b.align }, media, hyperlinks, nextRid, opts);
      case 'pre':
        return paragraphXml(b.inlines, { mono: true, shade: 'F2F2F2', align: 'left' }, media, hyperlinks, nextRid, opts);
      case 'hr':
        return '<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="8" w:space="1" w:color="808080"/></w:pBdr><w:spacing w:after="120"/></w:pPr></w:p>';
      case 'img':
        return imageParagraphXml(b, media, nextRid, page);
      case 'list':
        return listXml(b, media, hyperlinks, nextRid, opts);
      default:
        return paragraphXml(b.inlines, { align: b.align, spacing: opts.lineSpacing }, media, hyperlinks, nextRid, opts);
    }
  }

  function paragraphXml(inlines, fmt, media, hyperlinks, nextRid, opts) {
    fmt = fmt || {};
    var pPr = '<w:pPr>';
    if (fmt.style) pPr += '<w:pStyle w:val="' + fmt.style + '"/>';
    if (fmt.align && fmt.align !== 'left') {
      pPr += '<w:jc w:val="' + (fmt.align === 'justify' ? 'both' : fmt.align) + '"/>';
    }
    if (fmt.indentLeft) pPr += '<w:ind w:left="' + fmt.indentLeft + '"/>';
    var line = lineTwips(opts.lineSpacing);
    pPr += '<w:spacing w:before="0" w:after="' + (fmt.style ? 120 : 100) + '"' +
      (line ? ' w:line="' + line + '" w:lineRule="auto"' : '') + '/>';
    if (fmt.shade) pPr += '<w:shd w:val="clear" w:color="auto" w:fill="' + fmt.shade + '"/>';
    if (fmt.mono) pPr += '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="SimSun"/><w:sz w:val="20"/></w:rPr>';
    if (fmt.italic && !fmt.mono) pPr += '<w:rPr><w:i/></w:rPr>';
    pPr += '</w:pPr>';

    var runs = '';
    (inlines || []).forEach(function (run) {
      runs += runXml(run, fmt, media, hyperlinks, nextRid);
    });
    if (!runs && fmt.style) {
      // 空标题也保留样式标记
      runs = '<w:r><w:t xml:space="preserve"></w:t></w:r>';
    }
    return '<w:p>' + pPr + runs + '</w:p>';
  }

  function runXml(run, blockFmt, media, hyperlinks, nextRid) {
    if (!run) return '';
    var text = String(run.text == null ? '' : run.text);
    // 换行拆分为多个 w:t + w:br
    var parts = text.split('\n');
    var rPr = '<w:rPr>';
    if (run.bold || blockFmt.bold) rPr += '<w:b/><w:bCs/>';
    if (run.italic || blockFmt.italic) rPr += '<w:i/><w:iCs/>';
    if (run.underline) rPr += '<w:u w:val="single"/>';
    if (run.strike) rPr += '<w:strike/>';
    if (blockFmt.mono) rPr += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="SimSun"/>';
    if (run.color) {
      var hex = colorHex(run.color);
      if (hex) rPr += '<w:color w:val="' + hex + '"/>';
    }
    if (blockFmt.color) {
      var hex2 = colorHex(blockFmt.color);
      if (hex2 && !run.color) rPr += '<w:color w:val="' + hex2 + '"/>';
    }
    var pt = run.sizePt || (blockFmt.sizePt);
    if (pt) rPr += '<w:sz w:val="' + Math.round(pt * 2) + '"/><w:szCs w:val="' + Math.round(pt * 2) + '"/>';
    rPr += '</w:rPr>';

    var inner = '';
    for (var i = 0; i < parts.length; i++) {
      if (i > 0) inner += '<w:br/>';
      inner += '<w:t xml:space="preserve">' + esc(parts[i]) + '</w:t>';
    }
    var r = '<w:r>' + rPr + inner + '</w:r>';
    if (run.href && /^https?:/i.test(run.href)) {
      var rid = nextRid();
      hyperlinks.push({ rid: rid, target: run.href });
      return '<w:hyperlink r:id="' + rid + '" w:history="1">' + r + '</w:hyperlink>';
    }
    return r;
  }

  function imageParagraphXml(b, media, nextRid, page) {
    if (!b.bytes || !b.widthMm) {
      return '<w:p><w:r><w:t>' + esc('[图片无法嵌入]') + '</w:t></w:r></w:p>';
    }
    var mime = b.mime || 'image/png';
    var ext = extOfMime(mime);
    var ct = { 'image/png': 'image/png', 'image/jpeg': 'image/jpeg', 'image/gif': 'image/gif',
      'image/bmp': 'image/bmp', 'image/webp': 'image/webp' }[mime] || 'image/png';
    var rid = nextRid();
    var file = 'image' + (media.length + 1) + '.' + ext;
    media.push({ rid: rid, ext: ext, file: file, bytes: b.bytes, ct: ct });
    var cx = mmEmu(b.widthMm), cy = mmEmu(b.heightMm);
    return '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="120"/></w:pPr>' +
      '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">' +
      '<wp:extent cx="' + cx + '" cy="' + cy + '"/>' +
      '<wp:effectExtent l="0" t="0" r="0" b="0"/>' +
      '<wp:docPr id="' + (media.length) + '" name="Picture ' + (media.length) + '"/>' +
      '<a:graphic><a:graphicData uri="' + NS_PIC + '">' +
      '<pic:pic><pic:nvPicPr><pic:cNvPr id="' + media.length + '" name="Picture ' + media.length + '"/>' +
      '<pic:cNvPicPr/></pic:nvPicPr>' +
      '<pic:blipFill><a:blip r:embed="' + rid + '"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>' +
      '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="' + cx + '" cy="' + cy + '"/></a:xfrm>' +
      '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>' +
      '</pic:pic></a:graphicData></a:graphic>' +
      '</wp:inline></w:drawing></w:r></w:p>';
  }

  function listXml(b, media, hyperlinks, nextRid, opts) {
    var xml = '';
    var numId = b.ordered ? 2 : 1;
    (function walkItems(items, level) {
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        if (it && it.type === 'list') { walkItems(it.items, level + 1); continue; }
        var inlines = it || [];
        var pPr = '<w:pPr>';
        pPr += '<w:numPr><w:ilvl w:val="' + level + '"/><w:numId w:val="' + numId + '"/></w:numPr>';
        pPr += '<w:spacing w:after="60"' + (lineTwips(opts.lineSpacing) ? ' w:line="' + lineTwips(opts.lineSpacing) + '" w:lineRule="auto"' : '') + '/>';
        pPr += '</w:pPr>';
        var runs = '';
        inlines.forEach(function (r) { runs += runXml(r, {}, media, hyperlinks, nextRid); });
        xml += '<w:p>' + pPr + runs + '</w:p>';
      }
    })(b.items, 0);
    return xml;
  }

  function lineTwips(ls) {
    var map = { 1: 240, 1.15: 276, 1.5: 360, 2: 480, 2.5: 600, 3: 720 };
    if (ls == null) return null;
    var key = String(ls);
    if (map[key]) return map[key];
    var v = parseFloat(ls);
    if (v && v > 0) return Math.round(v * 240);
    return null;
  }

  function buildStyles(opts) {
    var headingSizes = { 1: 32, 2: 28, 3: 24, 4: 22, 5: 20, 6: 18 };
    var headingColors = { 1: '1F3864', 2: '2E5395', 3: '2F5496', 4: '404040', 5: '404040', 6: '404040' };
    var hs = '';
    for (var i = 1; i <= 6; i++) {
      hs += '<w:style w:type="paragraph" w:styleId="Heading' + i + '">' +
        '<w:name w:val="heading ' + i + '"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>' +
        '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="' + (i - 1) + '"/></w:pPr>' +
        '<w:rPr><w:b/><w:color w:val="' + headingColors[i] + '"/><w:sz w:val="' + headingSizes[i] + '"/></w:rPr>' +
        '</w:style>';
    }
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<w:styles xmlns:w="' + NS_W + '">\n' +
      '<w:docDefaults><w:rPrDefault><w:rPr>' +
      '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="宋体"/><w:sz w:val="24"/><w:szCs w:val="24"/>' +
      '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>\n' +
      '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>\n' +
      hs +
      '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/></w:style>\n' +
      '</w:styles>';
  }

  function buildNumbering() {
    function lvl(ilvl, fmt, txt, indent, hang) {
      return '<w:lvl w:ilvl="' + ilvl + '"><w:start w:val="1"/><w:numFmt w:val="' + fmt + '"/>' +
        '<w:lvlText w:val="' + txt + '"/><w:lvlJc w:val="left"/>' +
        '<w:pPr><w:ind w:left="' + (indent) + '" w:hanging="' + (hang) + '"/></w:pPr></w:lvl>';
    }
    // abstractNum 1：项目符号（每级用不同符号）
    var bulletLevels = '';
    var bullets = ['\u2022', '\u25CB', '\u25A0'];
    for (var i = 0; i < 3; i++) {
      bulletLevels += lvl(i, 'bullet', bullets[i % 3], 720 * (i + 1), 360);
    }
    // abstractNum 2：十进制编号（多级）
    var numLevels = '';
    var fmts = ['decimal', 'lowerLetter', 'lowerRoman'];
    for (var j = 0; j < 3; j++) {
      numLevels += lvl(j, fmts[j % 3], '%' + (j + 1) + '.', 720 * (j + 1), 360);
    }
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<w:numbering xmlns:w="' + NS_W + '">\n' +
      '<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>' + bulletLevels + '</w:abstractNum>\n' +
      '<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>' + numLevels + '</w:abstractNum>\n' +
      '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>\n' +
      '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>\n' +
      '</w:numbering>';
  }

  /* ================= 公共 API ================= */
  function defaultPage() {
    return {
      size: { width_mm: 210, height_mm: 297, landscape: false },   // A4 纵向
      margin: { top_mm: 25.4, right_mm: 31.8, bottom_mm: 25.4, left_mm: 31.8, header_mm: 12.5, footer_mm: 12.5 },
      columns: 1,
      columnGap_mm: 12
    };
  }

  // 浏览器入口：HTML 字符串 + 页面设置 → Blob
  function htmlToDocxBlob(html, page, opts) {
    return htmlToDocx(html, page, opts).then(function (zip) {
      return zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', compression: 'DEFLATE' });
    });
  }

  // 通用入口：HTML → JSZip（浏览器内需要 DOMParser）
  function htmlToDocx(html, page, opts) {
    opts = opts || {};
    var p = merge(defaultPage(), page || {});
    var blocks = parseHtml(html, p, null);
    return Promise.resolve(buildDocx(blocks, p, opts));
  }

  // 纯逻辑入口：块节点数组（node 测试用，不依赖 DOM）
  function blocksToDocx(blocks, page, opts) {
    opts = opts || {};
    var p = merge(defaultPage(), page || {});
    return Promise.resolve(buildDocx(blocks || [], p, opts));
  }

  function merge(base, extra) {
    var out = JSON.parse(JSON.stringify(base));
    if (!extra) return out;
    if (extra.size) { out.size = merge(out.size, extra.size); }
    if (extra.margin) { out.margin = merge(out.margin, extra.margin); }
    for (var k in extra) {
      if (k !== 'size' && k !== 'margin' && extra[k] !== undefined) out[k] = extra[k];
    }
    return out;
  }

  return {
    defaultPage: defaultPage,
    htmlToDocx: htmlToDocx,
    htmlToDocxBlob: htmlToDocxBlob,
    blocksToDocx: blocksToDocx,
    parseHtml: parseHtml,
    imageMeta: imageMeta,
    dataUriToBytes: dataUriToBytes,
    ptFromSize: ptFromSize
  };
});

"""
md2pdf.py — 把修订稿Markdown 渲染成 PDF（WeasyPrint，中文字体 Noto Serif CJK）。

表格较多，单独设置列宽策略；行内代码用等宽字体并加浅底色。
数学记号Δ、α′、τ 等在正文中以 Unicode 直接出现，无需 MathJax。
"""
import os
import re
import sys

import markdown
from weasyprint import HTML

HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
@page {
  size: A4;
  margin: 20mm 18mm 20mm 18mm;
  @bottom-center {
    content: counter(page) " / " counter(pages);
    font-family: "Noto Serif CJK SC";
    font-size: 8pt;
    color: #888;
  }
}
body {
  font-family: "Noto Serif CJK SC", serif;
  font-size: 10.2pt;
  line-height: 1.68;
  color: #1a1a1a;
  text-align: justify;
  hyphens: auto;
}
h1 {
  font-size: 17pt;
  margin: 0 0 4mm 0;
  padding-bottom: 2mm;
  border-bottom: 1.6pt solid #222;
  page-break-after: avoid;
}
h2 {
  font-size: 13pt;
  margin: 7mm 0 2.5mm 0;
  padding-left: 2.5mm;
  border-left: 3pt solid #333;
  page-break-after: avoid;
}
h3 {
  font-size: 11pt;
  margin: 4.5mm 0 2mm 0;
  color: #2a2a2a;
  page-break-after: avoid;
}
p { margin: 0 0 2.4mm 0; orphans: 2; widows: 2; }
blockquote {
  margin: 2.5mm 0 2.5mm 4mm;
  padding: 1.5mm 3mm;
  border-left: 2.5pt solid #bbb;
  background: #f7f7f7;
  color: #333;
}
blockquote p { margin: 1mm 0; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 3mm 0 4mm 0;
  font-size: 8.8pt;
  page-break-inside: avoid;
}
th {
  background: #f0f0f0;
  font-weight: 600;
  padding: 1.4mm 1.2mm;
  border: 0.5pt solid #bbb;
  text-align: left;
}
td {
  padding: 1.3mm 1.2mm;
  border: 0.5pt solid #ccc;
  vertical-align: top;
}
tbody tr:nth-child(even) { background: #fafafa; }
code {
  font-family: "DejaVu Sans Mono", monospace;
  font-size: 8.8pt;
  background: #f2f2f2;
  padding: 0.3mm 1mm;
  border-radius: 1.5pt;
}
pre {
  background: #f5f5f5;
  border-left: 2.5pt solid #ccc;
  padding: 2.2mm 3mm;
  margin: 2.5mm 0;
  font-size: 8.4pt;
  line-height: 1.45;
  overflow-wrap: break-word;
  white-space: pre-wrap;
  page-break-inside: avoid;
}
pre code { background: none; padding: 0; font-size: 8.4pt; }
hr {
  border: none;
  border-top: 0.5pt solid #ddd;
  margin: 5mm 0;
}
strong { color: #000; }
a { color: #24518a; text-decoration: none; }
ul, ol { margin: 1.5mm 0 2.5mm 6mm; padding-left: 4mm; }
li { margin: 0.8mm 0; }
"""


def convert(md_path, pdf_path, title=None):
    src = open(md_path, encoding="utf-8").read()
    html = markdown.markdown(
        src,
        extensions=["tables", "fenced_code", "sane_lists",
                    "attr_list", "md_in_html"],
        output_format="html5",
    )
    t = title or os.path.splitext(os.path.basename(md_path))[0]
    doc = ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
           "<title>%s</title><style>%s</style></head><body>%s</body></html>"
           % (t, CSS, html))
    HTML(string=doc, base_url=HERE).write_pdf(pdf_path)
    return pdf_path


if __name__ == "__main__":
    jobs = [("REVISION.md", "符号置换未产生可检出的代价_修订稿.pdf"),
            ("REVISION_LEDGER.md", "修订证据台账.pdf")]
    for src, dst in jobs:
        sp, dp = os.path.join(HERE, src), os.path.join(HERE, dst)
        convert(sp, dp, title=dst[:-4])
        print("%-26s -> %-42s %8.1f KB"
              % (src, dst, os.path.getsize(dp) / 1024.0))
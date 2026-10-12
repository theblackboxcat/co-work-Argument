"""
build_docs.py — render PAPER.md into camera-ready .docx and .pdf.

No pandoc / LaTeX in this environment, so both paths are built directly:
  * DOCX via python-docx (native Word styles, real tables, embedded PNGs)
  * PDF  via weasyprint (single-column, print CSS, embedded PNGs)

Both consume the SAME markdown source so the two deliverables cannot drift.
"""

import html
import os
import re
import base64
from pathlib import Path

ROOT = Path(__file__).parent
# 可用环境变量覆盖，便于同时渲染多个版本做对比（默认仍是主文件）
import os
SRC = ROOT / os.environ.get("PAPER_SRC", "PAPER.md")
DOCX_OUT = ROOT / os.environ.get("PAPER_DOCX", "符号置换未产生可检出的代价_论文.docx")
PDF_OUT = ROOT / os.environ.get("PAPER_PDF", "符号置换未产生可检出的代价_论文.pdf")
FIGDIR = ROOT / "paper_figs"


# ----------------------------------------------------------------- markdown
STRUCT_PREFIX = ("#", "|", ">", "$", "![", "- ", "* ", "---")

RE_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
RE_IMG = re.compile(r"^!\[(.*)\]\((\S+?)\)$")
RE_MATH = re.compile(r"^\$\$(.+)\$\$$")
RE_LIST = re.compile(r"^\s*([-*]|\d+\.)\s+(.*)$")
RE_TBLSEP = re.compile(r"^\|[\s:|-]+\|$")


def resolve_img(rel: str) -> Path:
    """Markdown may use ../paper_figs/x.png (repo-root relative). Try both."""
    for cand in ((ROOT / rel).resolve(), (ROOT.parent / rel).resolve(),
                 (ROOT / Path(rel).name).resolve(),
                 (ROOT / FIGDIR / Path(rel).name).resolve()):
        if cand.exists():
            return cand
    return (ROOT / rel).resolve()


def parse(md: str):
    """-> list of blocks. ('h',lvl,txt) ('p',txt) ('tbl',rows,cap)
    ('fig',path,cap) ('math',tex) ('list',items) ('quote',txt)"""
    lines = md.split("\n")
    blocks, i, n = [], 0, len(lines)

    def is_struct(s):
        return (s.startswith(STRUCT_PREFIX)
                or RE_LIST.match(s) is not None
                or s.startswith("|") or s.startswith("$$"))

    while i < n:
        raw = lines[i]
        st = raw.strip()

        if not st:
            i += 1
            continue

        if set(st) == {"-"}:
            i += 1
            continue

        # ---- fenced code block: consume verbatim, never re-parse
        if st.startswith("```"):
            j, buf = i + 1, []
            while j < n and not lines[j].strip().startswith("```"):
                buf.append(lines[j].rstrip())
                j += 1
            blocks.append(("code", buf))
            i = j + 1
            continue

        m = RE_HEAD.match(st)
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        # ---- table (header, separator, >=0 body rows)
        if st.startswith("|") and i + 1 < n and RE_TBLSEP.match(lines[i + 1].strip()):
            cap = None
            # caption sits on the immediately preceding non-blank line
            k = i - 1
            while k >= 0 and not lines[k].strip():
                k -= 1
            if k >= 0 and lines[k].strip().startswith("**"):
                cap = lines[k].strip().strip("*").strip()
            rows = [[c.strip() for c in st.strip("|").split("|")]]
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip()
                             for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(("tbl", rows, cap))
            continue

        # ---- figure: whole line is ![alt](path)
        m = RE_IMG.match(st)
        if m:
            blocks.append(("fig", resolve_img(m.group(2)), m.group(1)))
            i += 1
            continue

        # ---- inline display math $$ ... $$ (single line)
        m = RE_MATH.match(st)
        if m:
            blocks.append(("math", m.group(1).strip()))
            i += 1
            continue

        # ---- multi-line display math
        if st.startswith("$$"):
            j, buf = i + 1, []
            while j < n and lines[j].strip() != "$$":
                buf.append(lines[j])
                j += 1
            blocks.append(("math", " ".join(x.strip() for x in buf if x.strip())))
            i = j + 1
            continue

        # ---- block quote (consume the whole run, keep it as one paragraph)
        if st.startswith(">"):
            j, buf = i, []
            while j < n and lines[j].strip().startswith(">"):
                buf.append(lines[j].strip().lstrip(">").strip())
                j += 1
            blocks.append(("quote", " ".join(x for x in buf if x)))
            i = j
            continue

        # ---- list run
        if RE_LIST.match(raw):
            j, items = i, []
            while j < n and RE_LIST.match(lines[j]):
                items.append(RE_LIST.match(lines[j]).group(2).strip())
                j += 1
            blocks.append(("list", items))
            i = j
            continue

        # ---- paragraph: merge until blank line or any structural line
        j, buf = i, []
        while j < n:
            nx = lines[j].strip()
            if not nx:
                break
            if j > i and is_struct(nx):
                break
            buf.append(nx)
            j += 1
        if buf:
            blocks.append(("p", " ".join(buf)))
        i = j if j > i else i + 1

    return blocks


# ------------------------------------------------- inline LaTeX -> unicode
GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ",
    "Psi": "Ψ", "Omega": "Ω",
}
SUP = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵",
       "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻",
       "n": "ⁿ", "i": "ⁱ", "*": "＊", "(": "⁽", ")": "⁾"}
SUB = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅",
       "6": "₆", "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋",
       "n": "ₙ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "l": "ₗ",
       "m": "ₘ", "e": "ₑ", "a": "ₐ", "r": "ᵣ", "eff": "ₑff",
       "*": "₍", "(": "₍", ")": "₎", "=": "₌", "R": "ᵣ"}

SUBSCRIPTS = ["mathrm", "mathbf", "mathbb", "text", "mathit", "mathsf",
              "operatorname", "texttt", "textsf", "rm", "bf", "it", "cal"]


def _scripts(body: str) -> str:
    """Convert a LaTeX group body with _{..} / ^{..} into unicode."""
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c in "_^" and i + 1 < len(body):
            kind = SUB if c == "_" else SUP
            i += 1
            if body[i] == "{":
                depth, j = 1, i + 1
                while j < len(body) and depth:
                    if body[j] == "{":
                        depth += 1
                    elif body[j] == "}":
                        depth -= 1
                    j += 1
                grp = body[i + 1:j - 1]
                i = j
            else:
                grp, i = body[i], i + 1
            # try the whole group as one subscript, else char by char
            if grp in kind:
                out.append(kind[grp])
            elif grp in SUBSCRIPTS:
                pass                      # \mathrm{REL} -> REL, no marker
            elif len(grp) > 1 and any(ch.isupper() for ch in grp):
                out.append(grp)            # acronym like REL: keep upright
            else:
                for ch in grp:
                    out.append(kind.get(ch, ch))
        else:
            out.append(c)
            i += 1
    return "".join(out)


def tex_unicode(tex: str) -> str:
    """LaTeX fragment -> plain unicode. Handles the subset used in this paper."""
    s = tex.strip()
    # symbol macros that must win before generic control-word stripping
    SYMS = [
        (r"\\approx", "≈"), (r"\\times", "×"), (r"\\cdot", "·"),
        (r"\\pm", "±"), (r"\\ge\b|\\geq", "≥"), (r"\\leq|\\le\b", "≤"),
        (r"\\neq|\\ne\b", "≠"), (r"\\in\b", "∈"), (r"\\notin", "∉"),
        (r"\\rightarrow|\\to\b", "→"), (r"\\leftarrow", "←"),
        (r"\\ldots|\\dots", "…"), (r"\\infty", "∞"),
        (r"\\star", "★"), (r"\\ast", "∗"), (r"\\sim", "∼"),
        (r"\\mid", "|"), (r"\\left", ""), (r"\\right", ""),
        (r"\\,", " "), (r"\\;", " "), (r"\\!", ""), (r"\\ ", " "),
        (r"\\quad", "  "), (r"\\qquad", "    "),
        (r"\\sqrt\{([^}]*)\}", r"√(\1)"),
        (r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)"),
        (r"\\#", "#"), (r"\\%", "%"), (r"\\_", "_"),
        (r"\\{", "{"), (r"\\}", "}"),
    ]
    for a, b in SYMS:
        s = re.sub(a, b, s)
    # \mathrm{...} etc: unwrap, contents may carry _ ^
    for cmd in SUBSCRIPTS:
        while True:
            m = re.search(r"\\" + cmd + r"\{", s)
            if not m:
                break
            depth, j = 1, m.end()
            while j < len(s) and depth:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                j += 1
            s = s[:m.start()] + s[m.end():j - 1] + s[j:]
    # greek
    s = re.sub(r"\\([a-zA-Z]+)",
               lambda m: GREEK.get(m.group(1), " "), s)
    # remaining control words -> space
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    return _scripts(s).strip()


RE_TEX = re.compile(r"\$([^$\n]{1,160})\$")


def _sub_inline_tex(s: str):
    """Replace $...$ with (unicode, True) markers inside a markdown string.
    Returns list of (text, is_math)."""
    out, pos = [], 0
    for m in RE_TEX.finditer(s):
        if m.start() > pos:
            out.append((s[pos:m.start()], False))
        out.append((tex_unicode(m.group(1)), True))
        pos = m.end()
    if pos < len(s):
        out.append((s[pos:], False))
    return out


RE_MD = re.compile(
    r"\*\*(?P<b>[^*]+?)\*\*"        # bold first: **x**
    r"|`(?P<c>.+?)`"                     # then code: `x`
    r"|(?<!\*)\*(?P<i>[^*\n]+?)\*(?!\*)"  # then italic: *x*
)
RE_LINK = re.compile(r"\[(.+?)\]\((.+?)\)")


def inline(s: str) -> str:
    """markdown -> HTML, with $...$ rendered to unicode <i>."""
    s = html.escape(s)
    keep = []

    def stash(m):
        keep.append(tex_unicode(m.group(1)))
        return f"\x00M{len(keep)-1}\x00"

    s = RE_TEX.sub(stash, s)

    def md_sub(m):
        if m.group("b") is not None:
            return f"<b>{m.group('b')}</b>"
        if m.group("c") is not None:
            return f"<code>{m.group('c')}</code>"
        return f"<i>{m.group('i')}</i>"

    s = RE_MD.sub(md_sub, s)
    s = RE_LINK.sub(r'<span class="lnk">\1</span>', s)
    for i, t in enumerate(keep):
        s = s.replace(f"\x00M{i}\x00", f"<i class='m'>{t}</i>")
    s = re.sub(r"\\[a-zA-Z]+\s*", " ", s)
    return s.replace("**", "").replace("__", "")


def _scrub(s: str) -> str:
    """Last-resort cleanup so no raw markup can reach the output."""
    s = re.sub(r"\\[a-zA-Z]+\s*", " ", s)
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r"\$([^$\n]{1,160})\$",
               lambda m: tex_unicode(m.group(1)), s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def inline_md(s: str):
    """markdown -> [(text, bold, italic, code, math)] for python-docx."""
    segs = _sub_inline_tex(s)
    out = []
    for text, is_math in segs:
        if is_math:
            out.append((_scrub(text), False, True, False, True))
            continue
        pos = 0
        for m in RE_MD.finditer(text):
            if m.start() > pos:
                out.append((_scrub(text[pos:m.start()]),
                            False, False, False, False))
            if m.group("b") is not None:
                out.append((_scrub(m.group("b")), True, False, False, False))
            elif m.group("c") is not None:
                out.append((_scrub(m.group("c")), False, False, True, False))
            else:
                out.append((_scrub(m.group("i")), False, True, False, False))
            pos = m.end()
        if pos < len(text):
            out.append((_scrub(text[pos:]), False, False, False, False))
    return out or [("", False, False, False, False)]


# ----------------------------------------------------------------- Mermaid-ish
def extract_abstract(blocks):
    """-> (abstract_text, first_body_index).

    The abstract / keywords / category lines are pulled out of the body so the
    renderers emit them exactly once, in the title block."""
    out, collecting, stop = [], False, 2
    for i, b in enumerate(blocks):
        if b[0] == "h":
            if collecting:
                stop = i
                break
            continue
        if b[0] != "p":
            continue
        t = b[1]
        if t.startswith("**摘要.**"):
            collecting = True
            out.append(t.replace("**摘要.**", "").strip())
            stop = i + 1
        elif t.startswith("**关键词:**"):
            out.append(t.replace("**关键词:**", "关键词：").strip())
            stop = i + 1
        elif t.startswith("**分类:**"):
            out.append(t.replace("**分类:**", "分类：").strip())
            stop = i + 1
            break
        elif collecting:
            out.append(t)
            stop = i + 1
    return " ".join(x for x in out if x), stop


# ----------------------------------------------------------------- DOCX
def build_docx(blocks):
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor, Emu
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.section import WD_SECTION
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    doc = Document()

    # ---- base styles
    n = doc.styles["Normal"]
    n.font.name = "Times New Roman"
    n.font.size = Pt(10.5)
    n._element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Serif CJK SC")
    pf = n.paragraph_format
    pf.line_spacing = 1.28
    pf.space_after = Pt(5)
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def setfont(run, name="Times New Roman", ea="Noto Serif CJK SC",
                size=None, bold=None, italic=None, color=None):
        run.font.name = name
        run._element.rPr.rFonts.set(qn("w:eastAsia"), ea)
        if size:
            run.font.size = Pt(size)
        if bold is not None:
            run.font.bold = bold
        if italic is not None:
            run.font.italic = italic
        if color:
            run.font.color.rgb = RGBColor.from_string(color)

    SEC = doc.sections[0]
    SEC.page_width, SEC.page_height = Inches(8.5), Inches(11)
    for m, v in (("top", 1.0), ("bottom", 1.0), ("left", 1.1), ("right", 1.1)):
        setattr(SEC, f"{m}_margin", Inches(v))

    def hrule(p):
        pPr = p._p.get_or_add_pPr()
        bd = OxmlElement("w:pBdr")
        b = OxmlElement("w:bottom")
        b.set(qn("w:val"), "single"); b.set(qn("w:sz"), "6")
        b.set(qn("w:space"), "1"); b.set(qn("w:color"), "999999")
        bd.append(b); pPr.append(bd)

    def emit(text, size=10.5, bold=False, italic=False, align=None,
             space_before=0, space_after=5, indent=0, color=None,
             font="Times New Roman"):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.left_indent = Inches(indent)
        if indent:
            p.paragraph_format.first_line_indent = Inches(-0.18)
        if align:
            p.paragraph_format.alignment = align
        for t, b, it, cd, mt in inline_md(text):
            r = p.add_run(t)
            if cd:
                setfont(r, "DejaVu Sans Mono", "Noto Sans Mono CJK SC",
                        size - 1.5, bold=False, italic=False,
                        color="A03000")
                continue
            if mt:
                setfont(r, "Cambria Math", "Noto Serif CJK SC", size,
                        False, True, "1A3A6B")
                continue
            setfont(r, font, "Noto Serif CJK SC", size,
                    bold or b, italic or it, color)
        return p

    def math(tex):
        p = doc.add_paragraph()
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(7)
        p.paragraph_format.space_after = Pt(7)
        r = p.add_run(tex_unicode(tex))
        setfont(r, "Cambria Math", "Cambria Math", 11, italic=False)
        return p

    def table(rows, cap):
        t = doc.add_table(rows=len(rows), cols=len(rows[0]))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                c = t.cell(ri, ci)
                c.text = ""
                p = c.paragraphs[0]
                p.paragraph_format.alignment = (
                    WD_ALIGN_PARAGRAPH.LEFT if ci == 0
                    else WD_ALIGN_PARAGRAPH.CENTER)
                p.paragraph_format.space_before = Pt(2.5)
                p.paragraph_format.space_after = Pt(2.5)
                p.paragraph_format.line_spacing = 1.05
                for t_, b, it, cd, mt in inline_md(cell):
                    r = p.add_run(t_)
                    if cd:
                        setfont(r, "DejaVu Sans Mono",
                                "Noto Sans Mono CJK SC", 8.2, False, False,
                                "A03000")
                    elif mt:
                        setfont(r, "Cambria Math", "Noto Serif CJK SC", 8.8,
                                False, True, "1A3A6B")
                    else:
                        setfont(r, "Times New Roman", "Noto Serif CJK SC",
                                8.8, b, it, None)
                if ri == 0:
                    sh = OxmlElement("w:shd")
                    sh.set(qn("w:val"), "clear")
                    sh.set(qn("w:fill"), "EFEFEF")
                    c._tc.get_or_add_tcPr().append(sh)
        if cap:
            emit(cap, 9, italic=True, align=WD_ALIGN_PARAGRAPH.LEFT,
                 space_before=3, space_after=9)
        else:
            doc.add_paragraph().paragraph_format.space_after = Pt(4)

    def code(lines):
        """Verbatim monospace block with a light frame; never re-parsed."""
        if not lines:
            return
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Inches(0.16)
        pf.right_indent = Inches(0.06)
        pf.space_before = Pt(4)
        pf.space_after = Pt(8)
        pf.line_spacing = 1.06
        pPr = p._p.get_or_add_pPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear"); sh.set(qn("w:fill"), "F4F5F7")
        pPr.append(sh)
        for k, ln in enumerate(lines):
            if k:
                p.add_run().add_break()
            r = p.add_run(ln if ln.strip() else " ")
            setfont(r, "DejaVu Sans Mono", "Noto Sans Mono CJK SC", 8.6)

    def figure(path, cap):
        if not path.exists():
            emit(f"[missing figure: {path}]", 9, italic=True,
                 color="B00000")
            return
        p = doc.add_paragraph()
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(3)
        p.add_run().add_picture(str(path), width=Inches(6.3))
        if cap:
            emit(cap, 8.8, italic=True, align=WD_ALIGN_PARAGRAPH.LEFT,
                 space_before=0, space_after=11)

    # ---- title block
    title = blocks[0][2]
    p = emit(title, 19, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
             space_after=4, font="Noto Serif CJK SC")
    sub = blocks[1][2]
    emit(sub, 13.5, bold=False, align=WD_ALIGN_PARAGRAPH.CENTER,
         space_after=10, color="333333", font="Noto Serif CJK SC")

    abs_txt, body0 = extract_abstract(blocks)
    if abs_txt:
        emit(abs_txt, 9.6, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
             space_before=4, space_after=3)
    p = emit("", 6, space_after=2); hrule(p)

    for b in blocks[body0:]:
        k = b[0]
        if k == "h":
            lvl, txt = b[1], b[2]
            if lvl == 2:
                p = emit(txt, 14, bold=True, space_before=15,
                         space_after=6, font="Noto Serif CJK SC")
                hrule(p)
            elif lvl == 3:
                emit(txt, 11.6, bold=True, space_before=11, space_after=4,
                     font="Noto Serif CJK SC")
            else:
                emit(txt, 10.8, bold=True, italic=True, space_before=8,
                     space_after=3, font="Noto Serif CJK SC")
        elif k == "p":
            emit(b[1], 10.5)
        elif k == "math":
            math(b[1])
        elif k == "tbl":
            table(b[1], b[2])
        elif k == "fig":
            figure(b[1], b[2])
        elif k == "code":
            code(b[1])
        elif k == "list":
            for it in b[1]:
                emit("• " + it, 10.3, indent=0.22, space_after=2.5)
        elif k == "quote":
            p = emit(b[1], 10, italic=True, indent=0.24,
                     space_before=5, space_after=7, color="204060")
            p.paragraph_format.right_indent = Inches(0.24)
            pPr = p._p.get_or_add_pPr()
            bd = OxmlElement("w:pBdr")
            lf = OxmlElement("w:left")
            lf.set(qn("w:val"), "single"); lf.set(qn("w:sz"), "18")
            lf.set(qn("w:space"), "8"); lf.set(qn("w:color"), "9CB4C8")
            bd.append(lf); pPr.append(bd)

    # ---- footer page numbers
    for sec in doc.sections:
        fp = sec.footer.paragraphs[0]
        fp.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = fp.add_run()
        setfont(r, "Times New Roman", "Noto Serif CJK SC", 8.5,
                color="666666")
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), "PAGE")
        r._r.addnext(fld)

    doc.save(str(DOCX_OUT))
    print(f"docx -> {DOCX_OUT}")


# ----------------------------------------------------------------- PDF
CSS = """
@page { size: A4; margin: 22mm 20mm 20mm 20mm;
  @bottom-center { content: counter(page); font-size: 8.5pt; color:#666; } }
body { font-family: "Noto Serif CJK SC","Noto Serif",serif;
  font-size: 10.2pt; line-height: 1.5; color:#111; text-align: justify; }
h1 { font-size: 19pt; text-align:center; margin: 0 0 4pt; line-height:1.28; }
.sub { font-size: 13pt; text-align:center; color:#333; margin: 0 0 14pt; }
h2 { font-size: 13.5pt; margin: 17pt 0 6pt; padding-bottom:3pt;
  border-bottom: 0.6pt solid #999; page-break-after: avoid; }
h3 { font-size: 11.2pt; margin: 12pt 0 4pt; page-break-after: avoid; }
h4 { font-size: 10.4pt; margin: 9pt 0 3pt; font-style: italic;
  page-break-after: avoid; }
p { margin: 0 0 6pt; }
.abs { font-size: 9.6pt; text-align: justify; }
.rule { border-bottom: 0.6pt solid #999; margin: 9pt 0 12pt; }
.math { text-align:center; margin: 9pt 0; font-family:"DejaVu Serif",serif;
  font-size: 11pt; }
table { border-collapse: collapse; margin: 10pt auto 4pt; font-size: 8.6pt;
  width: auto; page-break-inside: avoid; }
th,td { border: 0.5pt solid #666; padding: 3pt 6pt; text-align: center; }
th:first-child, td:first-child { text-align: left; }
thead { background: #eee; } tr:first-child td { font-weight: 700; }
figcaption { font-size: 8.6pt; color:#333; margin: 3pt 0 13pt;
  text-align:left; }
figure { margin: 12pt 0 0; text-align:center; page-break-inside: avoid; }
img { width: 100%; max-width: 168mm; }
code { font-family:"DejaVu Sans Mono",monospace; font-size:9pt;
  color:#A03000; }
pre.code { font-family:"DejaVu Sans Mono",monospace; font-size:8.8pt;
  line-height:1.42; color:#1A1A1A; background:#F4F5F7;
  border-left: 2.2pt solid #C8CCD2; padding: 6pt 10pt; margin: 6pt 0 10pt;
  white-space: pre-wrap; page-break-inside: avoid; }
.lnk { color:#204060; }
blockquote { margin: 7pt 0; padding: 5pt 0 5pt 12pt;
  border-left: 2.2pt solid #9CB4C8; color:#204060; font-size:9.8pt;
  font-style: italic; }
ul { margin: 4pt 0 8pt; padding-left: 20pt; } li { margin-bottom: 3pt; }
.refs p { font-size: 9.2pt; margin-bottom: 6pt; padding-left: 22pt;
  text-indent: -22pt; }
"""


def build_pdf(blocks):
    o = []
    title = blocks[0][2]
    o.append(f"<h1>{inline(title)}</h1>")
    o.append(f"<div class='sub'>{inline(blocks[1][2])}</div>")
    abs_txt, body0 = extract_abstract(blocks)
    if abs_txt:
        o.append(f"<p class='abs'>{inline(abs_txt)}</p>")
    o.append("<div class='rule'></div>")

    for b in blocks[body0:]:
        k = b[0]
        if k == "h":
            o.append(f"<h{b[1]}>{inline(b[2])}</h{b[1]}>")
        elif k == "p":
            o.append(f"<p>{inline(b[1])}</p>")
        elif k == "math":
            o.append(f"<div class='math'>{html.escape(tex_unicode(b[1]))}</div>")
        elif k == "tbl":
            rows = b[1]
            th = "".join(f"<td>{inline(c)}</td>" for c in rows[0])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>"
                                            for c in r) + "</tr>"
                           for r in rows[1:])
            o.append(f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")
            if b[2]:
                o.append(f"<figcaption>{inline(b[2])}</figcaption>")
        elif k == "fig":
            p = b[1]
            if p.exists():
                data = base64.b64encode(p.read_bytes()).decode()
                o.append(f"<figure><img src='data:image/png;base64,{data}'/>"
                         f"<figcaption>{inline(b[2])}</figcaption></figure>")
            else:
                o.append(f"<p><i>[missing figure]</i></p>")
        elif k == "list":
            o.append("<ul>" + "".join(f"<li>{inline(x)}</li>"
                                      for x in b[1]) + "</ul>")
        elif k == "quote":
            o.append(f"<blockquote>{inline(b[1])}</blockquote>")
        elif k == "code":
            o.append("<pre class='code'>"
                     + html.escape("\n".join(b[1])) + "</pre>")

    body = "".join(o)
    # references get a hanging indent
    body = body.replace("<h2>参考文献</h2>", "<h2>参考文献</h2>")
    idx = body.find("<h2>参考文献</h2>")
    if idx > 0:
        head, tail = body[:idx], body[idx:]
        tail = tail.replace("<h2>参考文献</h2>",
                            "<h2>参考文献</h2><div class='refs'>", 1)
        tail = tail.rsplit("</body>", 1)
        body = head + tail[0] + "</div>"

    # Edge/Chrome do not implement weasyprint's @page margin boxes, so we
    # inline a print-friendly @page rule and drop the @bottom-center counter.
    css_for_browser = re.sub(r"@bottom-center\s*\{[^}]*\}", "", CSS)
    doc = (f"<html><head><meta charset='utf-8'>"
           f"<style>{css_for_browser}</style></head>"
           f"<body>{body}</body></html>")
    tmp = ROOT / "_paper_tmp.html"
    tmp.write_text(doc, encoding="utf-8")
    pdf_done = False
    try:
        from weasyprint import HTML, CSS as WCSS
        HTML(string=doc, base_url=str(ROOT)).write_pdf(
            str(PDF_OUT), stylesheets=[WCSS(string=CSS)])
        pdf_done = True
    except Exception as e:
        print(f"weasyprint unavailable ({type(e).__name__}); using headless browser")
    if not pdf_done:
        _pdf_via_browser(tmp, PDF_OUT)
    tmp.unlink(missing_ok=True)
    print(f"pdf  -> {PDF_OUT}")


def _pdf_via_browser(html_path, pdf_path):
    """Render a self-contained HTML file to PDF with headless Edge/Chrome.

    The HTML embeds all figures as base64 data URIs, so no network or local
    file access is needed at print time.
    """
    import subprocess, shutil
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    exe = next((c for c in cands if os.path.exists(c)), None)
    if exe is None:
        exe = shutil.which("msedge") or shutil.which("chrome")
    if exe is None:
        raise RuntimeError("no headless browser found for PDF rendering")
    url = html_path.resolve().as_uri()
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--no-pdf-header-footer",
           f"--print-to-pdf={pdf_path.resolve()}", url]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)


if __name__ == "__main__":
    md = SRC.read_text(encoding="utf-8")
    blocks = parse(md)
    print(f"{len(blocks)} blocks parsed")
    from collections import Counter
    print(Counter(b[0] for b in blocks))
    build_docx(blocks)
    build_pdf(blocks)

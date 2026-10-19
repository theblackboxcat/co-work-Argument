# -*- coding: utf-8 -*-
"""
伴写 demo · 本地服务（纯标准库，无需 pip install）

启动：
    python server.py
然后浏览器打开 http://127.0.0.1:8790

两种模式：
  1) 离线演示（默认）—— 未配置 api_key 时走本地规则引擎，演示机制，不发任何网络请求
  2) 真实模型   —— 在 config.json 里填好 base_url / api_key / model，走 OpenAI 兼容端点

策略来源：同目录 SKILL.md（作为 system prompt 注入）。改 SKILL.md 不需要重启，
          每次请求都会重新读取。
"""

import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import providers          # 模型后端适配层：协议差异只在这一处
import lit_tools          # 文学工作台的工具层（上网 / GitHub / 找本地 skill）

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, 'web')
SKILL_PATH = os.path.join(BASE, 'SKILL.md')
WORKFLOW_PATH = os.path.join(BASE, 'WORKFLOW.md')
CONFIG_PATH = os.path.join(BASE, 'config.json')
CORPUS_PATH = os.path.join(BASE, '语料', '示例语料.json')
PORT = 8792   # 测试版专用端口。发行版 8790；jev 文档里写的 8791 也让开——
                # 那个端口在 params.json 里被当作 jev 判定层的地址，虽然它默认关着，
                # 但两个用途撞在同一个号上迟早出事。

# v3 开关：默认关闭（跑基线）。打开＝侧边用「模式+禁令」的那套策略。
#   方式一：在 dsh-伴写/ 下建一个名为 USE_V3 的空文件
#   方式二：环境变量 COWRITE_V3=1
V3_DIR = os.path.join(BASE, 'v3')
USE_V3 = (os.environ.get('COWRITE_V3', '') == '1'
          or os.path.exists(os.path.join(BASE, 'USE_V3')))
_v3 = None
_jev = None          # 外部判定层（local-jev）。装不上就是 None，调用点一律判空。
_probe = None         # 测试版采集外挂。装不上就是 None，调用点一律判空。
if USE_V3:
    try:
        import sys as _sys
        _sys.path.insert(0, V3_DIR)
        import policy as _policy_mod      # noqa: E402
        import telemetry as _telemetry    # noqa: E402
        import attention as _attention    # noqa: E402
        _v3 = (_policy_mod, _telemetry, _attention)
    except Exception as _e:               # 装不上就老老实实跑基线，不许静默出错
        print('[v3] 载入失败，回退到当前 skill：%s' % _e)
        USE_V3 = False
    # jev **单独一个 try，绝不能并进上面那个**：它是可选的外部判定层，失败开放
    # 是它的硬规矩（服务不在、包没带、文件坏了，都只该等于"没有它"）。
    # 并在一起的话，jev_gate 一旦装不上就会连带把 policy/telemetry/attention 判死，
    # 整个 v3 退回基线 —— 一个可选项拖垮主链路，正好是它最不该有的行为。
    try:
        import sys as _sys2
        if V3_DIR not in _sys2.path:
            _sys2.path.insert(0, V3_DIR)
        import jev_gate as _jev           # noqa: E402  可选·失败开放·默认关
    except Exception as _e2:
        print('[jev] 判定层未载入（可选，不影响写作）：%s' % _e2)
        _jev = None

    # ---- 测试版采集外挂（**不属于伴写本体**）----
    # 它只旁挂、不介入：探针失败最多丢采集数据，不许影响写作。
    # 发行版里这个模块不存在，所以这一段只在 Cowrite-test 上跑。
    try:
        import sys as _sys3
        if V3_DIR not in _sys3.path:
            _sys3.path.insert(0, V3_DIR)
        import probe as _probe             # noqa: E402
    except Exception as _e3:
        print('[probe] 采集外挂未载入（写作不受影响）：%s' % _e3)
        _probe = None

STATIC_NO_CACHE = {'.html', '.js', '.css'}

# ── DS 网页端朗读桥（tts_read.py）─────────────────────────────
# 把文学编辑框的文本路由到 chat.deepseek.com 的 TTS 朗读。
# 自动化是独立进程（tts_read.py），用 Playwright 驱动系统 Edge；
# 本服务只负责：接收文本 → 起子进程 → 回状态。**不把 Playwright
# 依赖进主进程**，装不上也不影响伴写本体。
TTS_READ_SCRIPT = os.path.join(BASE, 'tts_read.py')
_TTS_PROC = None
_TTS_LOCK = threading.Lock()


def _tts_python():
    """找能跑 tts_read.py 的 python：优先本进程的（若已装 playwright），
    否则在 PATH 里找一个。找不到返回 None。"""
    import sys as _sys
    candidates = [_sys.executable] if _sys.executable else []
    for p in candidates:
        try:
            import importlib.util as _iu
            if _iu.find_spec('playwright'):
                return p
        except Exception:
            pass
    # 兜底：PATH 里的 python
    try:
        for probe in ('python', 'python3'):
            found = shutil.which(probe)
            if found:
                return found
    except Exception:
        pass
    return None


# 实时会话里的跨轮开头形状史。模板只在序列里显形，单条看不出来，
# 而模型自己也看不出——只能由管道记、管道拦。
_OPEN_HISTORY = []
_OPEN_HISTORY_MAX = 40


# ---------------------------------------------------------------- 载入

def load_skill():
    try:
        with open(SKILL_PATH, encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def _maybe_skillv(info, signals, mode=None, text_len=None):
    """Skill-V-lite 旁路。SKILLV_LITE 不是 1 时原样返回，主路径不变。

    失败也原样返回：这一层是试点，不许把注意力推断拖垮。
    不往系统提示词加条款。默认 gate 只拦住契约判为沉默的回合。
    """
    if os.environ.get('SKILLV_LITE', '') != '1' or not isinstance(info, dict):
        return info
    try:
        import sys as _sv_sys
        root = os.path.abspath(os.path.join(BASE, '..', '..', 'skillv_lite'))
        if root not in _sv_sys.path:
            _sv_sys.path.insert(0, root)
        from skillv.runtime import maybe_apply
        return maybe_apply(info, signals, mode=mode, text_len=text_len)
    except Exception as _sv_e:
        print('[skillv] 未介入（主路径保持原样）：%s' % _sv_e)
        return info


def initiative_mode():
    """主导权档位：jia（甲·规则）/ yi（乙·半放权）/ bing（丙·放权）。

    - jia  甲：规则决定说不说，上下文仍是字面挑片段
    - yi   乙：规则决定说不说，但上下文换成连续窗口 + 整篇
    - bing 丙：**说不说也交给模型**（2026-09-20 要试的就是它）

    默认 bing。想回退只改 config.json 里这一个词，不用动代码——
    "先试体感、再决定回退还是采纳"得真的能一键完成才算数。
    """
    try:
        m = (load_config().get('initiative') or 'bing')
    except Exception:
        m = 'bing'
    m = str(m).strip().lower()
    return m if m in ('jia', 'yi', 'bing') else 'bing'


def load_config():
    cfg = {'base_url': 'https://api.deepseek.com', 'api_key': '', 'model': 'deepseek-chat'}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def load_corpus():
    if not os.path.exists(CORPUS_PATH):
        return {'sections': [], 'anchors': [], 'conflicts': []}
    try:
        with open(CORPUS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'sections': [], 'anchors': [], 'conflicts': []}


def online(cfg):
    return bool(cfg.get('api_key'))


def _safe_int(v, default=0, lo=None, hi=None):
    """把外面送进来的东西变成 int，坏值退回默认。

    为什么不用 `int(req.get('x') or default)`：那写法只在"缺字段"时安全，
    一旦字段存在但内容不是数字（面板传了 '—'、URL 里带了 'abc'、
    前端某次改动把数字变成了字符串），就在**请求线程里**抛 ValueError。
    没有 try 接着的那些 handler 会让连接直接被关，客户端看到的是
    "点击没反应"，错误只留在 stderr —— 2026-10-07 实测 /api/probe/list
    的 limit 就是这样：`{"limit":"abc"}` ⇒ 连接断开、零响应。
    """
    try:
        n = int(float(v))
    except Exception:
        return default
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


# ---------------------------------------------------------------- 文档
# 文档由作者现场载入（不是任何硬编码语料）。载入后成为伴写的唯一依据。

DOC_STORE = {'name': '', 'text': '', 'paragraphs': [], 'chapters': [],
             'para_fp': [], 'rev': 0}

# ---------------------------------------------------------------- 全文剖面
# 为什么需要它：只给"和当前段落最相关的那几段"，模型就是在盲人摸象——
# 它读不出整篇的调性、读不出反复出现的东西、读不出已经建立的呼应。
# 所以载入文档之后**先让模型通读一遍**，把全局判断记成一份剖面，
# 之后每一次局部伴写都带着它（局部相关片段 + 全局剖面，两者都要）。
#
# 剖面是**异步生成**的：载入文档不阻塞，前台先能用，好了就显示在面板上。
PROFILE = {'status': 'none', 'text': '', 'built_at': 0, 'err': '', 'doc_chars': 0,
           'rev': 0}      # 这份剖面读的是**哪一版**正文（§49）。对不上就不许当结论用。
_PROFILE_LOCK = threading.Lock()

# ---------------------------------------------------------------- 全文阅读记忆
# 与 PROFILE 分开：PROFILE 是写作调性剖面，最多抽 9000 字；这份必须逐章覆盖全文。
# 它是“模型已经读过全文”的可验证依据：覆盖字数/章数、逐片笔记、归并后的全书记忆。
FULLREAD = {
    'status': 'empty', 'err': '', 'memory': '', 'chapter_notes': [],
    'doc_key': '', 'doc_chars': 0, 'chapters': 0,
    'covered_chars': 0, 'total_chars': 0,
    'covered_parts': 0, 'total_parts': 0,
    'built_at': 0, 'rev': 0, 'started_at': 0,
}
_FULLREAD_LOCK = threading.Lock()
_FULLREAD_CACHE = {}
_FULLREAD_CACHE_LOCK = threading.Lock()
FULLREAD_MEMORY_MAX = 4200
FULLREAD_PART_MAX = 1800
_state_root = os.environ.get('LOCALAPPDATA') or os.path.join(
    os.path.expanduser('~'), '.local', 'share')
FULLREAD_CACHE_PATH = os.path.join(_state_root, 'Cowrite', 'fullread_cache.json')

PROFILE_PROMPT = """你刚刚通读了一个人写的一整篇东西。现在**不要评价、不要总结剧情**，
只做完下面五件事，用最省的字：

1. **调性（整体氛围）**：整篇的语气是什么（冷／暖／快／慢／滞／紧／亮／闷……），
   用 2–3 个词，每个词后面跟一句依据——依据里要写明它出在**哪一章**。
2. **她反复用的词／说法**：**只属于她的**用词习惯、口头禅、特有的说法
   （不是通用词）。每个后面写明出在**哪一章**。**只写真的出现两次以上的。**
   **标点、括号、单个语气符号、表情符号都不算"词"——不要写进这一栏。**
3. **反复出现的东西**：反复出现的物象、动作、场景。每个后面写明出在**哪一章**。
   **不许把只出现过一次的东西写进这一栏。**
4. **已经成形的一组概念**：这篇里被她反复触碰的那几个**念头／主题**
   （不是事件、不是情节动作，是念头；用她自己的说法，不要替她概括成学术词）。
   最多 5 个，每个注明它在哪一章。**这一栏宁可空着**——整篇还没聚出概念，就写"暂无"。
5. **已经建立的关系与写法**：哪两处构成呼应／重复／顺序上的矛盾
   （最多 3 条，各注明在哪一章）；再加一两句写法特征
   （人称、句子长短、断句习惯、有没有对话）。

**引用位置只说章名，不报段号／行号。** 我给的「章目录」里有章名，
写「第 3 章 雨」这种就行。**她的界面上只显示章名、不显示段号**——
`§1308` 这种行标她读不出来，只会对不上自己看到的位置。
认不出章（稿子没有标题）就直接引**原文字句**，别报段号。
**别自己编章名、别自己编章号**——只能引用我给的那份目录。

硬要求：
- **不许出现文中没有的东西。** 感受不到就不写，宁可这一栏空着。
- **不要写情节梗概。** 不要写"这是一个关于……的故事"。
- 用词一律用**她自己的词**，不要替换成更"文学"的同义词。
- 不要评价好坏，不要给建议，不要替她想接下来。
- 总长 320 字以内。
- 直接输出这份剖面（用 1/2/3/4/5 编号），不要开场白，不要结语。

这份剖面会被你**自己在后面每一次局部伴写时读到**，用来自我校正：
她写下某一处时，你要知道整篇的调性、她已经反复用过的词和已经成形的念头，
才不会把一处当成孤立的一句来读。所以写得越准越省，越有用。"""


def sample_doc(limit=9000):
    """给剖面用：长文塞不进上下文，抽样。
    头 25 段 + 尾 12 段 + 中间均匀取样——两头是定调的地方，中间是脉络。
    （这是抽样，不是压缩；全量过模型成本太高，见"复跑手册"。）

    **认出章之后，抽样必须照顾章的完整性**（2026-09-20）：原来纯按段号抽，
    一个章可能只在样本里露半截，模型于是拿不到"这一章叫什么、覆盖哪几段"。
    现在的做法是：章的标题行**一定取样**（它是模型引用位置的唯一凭据），
    其余仍按原节奏抽。这样模型手里始终有一份完整的章目录。"""
    ps = DOC_STORE.get('paragraphs') or []
    if not ps:
        return '', 0
    chs = DOC_STORE.get('chapters') or []
    head, tail = ps[:25], ps[-12:] if len(ps) > 37 else []
    mid = ps[25:len(ps) - 12] if len(ps) > 37 else []
    step = max(1, len(mid) // max(1, (limit // 400)))
    picked = head + mid[::step] + tail
    # 章的标题段一个都不能漏：它们是模型后来引用"第几章"时的锚。
    seen = set(no for no, _t in picked)
    must = [(c['start'], ps_by_no(c['start'])) for c in chs if c['start'] not in seen]
    must = [(no, t) for no, t in must if t]
    if must:
        picked = sorted(picked + must, key=lambda x: x[0])
    out, used = [], 0
    for no, txt in picked:
        c = chapter_of(no)
        mark = '' if not c else ('〔第 %d 章 %s〕' % (c['no'], c['title'])
                                 if c['start'] == no else '')
        # **不带 §N**（理由同 doc_full）：剖面是"通读后留下的印象"，
        # 而它**会被存下来、下次会话还读它**——这里给什么坐标，
        # 模型以后就一直用那个坐标说位置。
        s = ('%s\n%s' % (mark, txt)) if mark else txt
        if used + len(s) > limit:
            # 标题段就算超限也要收（它是引用凭据），其余照旧停。
            if not mark:
                break
        out.append(s)
        used += len(s)
    return '\n\n'.join(out), len(out)


def ps_by_no(no):
    """段号 → 正文。给 sample_doc 补章标题段用。"""
    for n, t in (DOC_STORE.get('paragraphs') or []):
        if n == no:
            return t
    return ''


def chapter_index_text():
    """一份**紧凑的章目录**（章号 / 章名 / 字数）。

    它会被拼进剖面的 prompt，也会拼进伴写的【当前位置】。
    为什么要单独给一份：prompt 里只说"依据要带段号"，模型就只能回 `§1308`——
    那不是她的坐标系。给了这份目录，它才能说"第 3 章 雨"。

    ⚠️ **目录里不写段号区间**（2026-09-20 改，实测逼出来的）：
    原来每行是「第 5 章「2.1 主动性与介入时机」：第 65–66 段，415 字」。
    整篇正文的段号前缀都拆掉之后，**真模型仍然在答复里写「第 157 段」**——
    因为这是它手里仅剩的段号体系，它就照这个坐标推了一个出来。
    **只要还有一处给它段号，它就会用段号报位置。** 所以这里只留章名与字数：
    字数还留着，是为了让它知道哪几章长、哪几章短（认路需要这个，不需要段号）。

    认不出章时返回 ''，上层照旧退回段号，功能不降级。"""
    chs = DOC_STORE.get('chapters') or []
    if not chs:
        return ''
    lines = []
    for c in chs:
        lines.append('  第 %d 章「%s」%d 字' % (c['no'], c['title'], c['chars']))
    return '全篇共 %d 章：\n%s' % (len(chs), '\n'.join(lines))


def strip_lineno_coords(s):
    """把答复里的**行号形态**去掉。出口的最后一道。

    为什么规则之外还要这一道（2026-09-20 真模型实测）：
    把上下文里的段号标注全拆干净、system 与 user 末尾都写了禁令之后，
    三个光标位置里**两个**听话了（改成"这一节最末那句…和下一段开头…"，
    正是要的效果），第三个——**要指相隔几十段的两处时**——仍然写
    「第 157 段末尾那句…」。

    也就是说：规则压得住多数，压不住全部。而这件事对她是
    **"对不对得上自己看到的位置"**，不该留概率。所以最后再过一道。
    这不是不信任模型，是这一条要求的容错是零。

    ⚠️ 只删「…段」与「§…」两种形态，**绝不碰「第 N 章」**——那是她要的坐标。
    删完通常仍然通顺：模型几乎总写成「第 157 段末尾那句」，
    拿掉前半截正好剩「末尾那句」，方位词还留着。
    """
    if not s:
        return s
    s = re.sub(r'§\s*\d+', '', s)
    s = re.sub(r'第\s*\d+\s*段', '', s)
    s = re.sub(r'[（(]\s*[）)]', '', s)          # 删空了的小括号
    s = re.sub(r'[ \t]{2,}', ' ', s)             # 合并空出来的连续空格
    s = re.sub(r'\s+([，。；、！？：）)」』])', r'\1', s)   # 标点前不留空
    # 标点后/行首的孤立空格：删掉编号之后它会留在那儿（"§1308 那句" → " 那句"）。
    # 只在**后面跟中文**时才吃这个空格，免得动到英文行文里的正常空格。
    s = re.sub(r'([，。；、！？：])\s+(?=[\u4e00-\u9fff])', r'\1', s)
    s = re.sub(r'(?m)^[ \t]+', '', s)
    return s


def llm_call(cfg, system, user, temperature=0.3, max_tokens=2048):
    """一次纯文本调用。**格式判断不在这里做。**

    为什么这一层薄成一句话：全文剖面第一版自己写了一份请求代码，直接拼了
    `/chat/completions`，而本项目的 config 是 `anthropic-messages`——
    于是 404。教训是"凡和已有调用长得一样的地方就该复用，别另抄一份"，
    但抽出来还不够：**抄一份就漏一次格式判断，抽成函数也一样漏**。
    现在协议细节全部收进 `providers.chat()`，这一层只剩转发。
    """
    return providers.chat_messages_complete(
        cfg, [{'role': 'user', 'content': user}], system=system,
        temperature=temperature, max_tokens=max_tokens, timeout=300)


def build_profile():
    """通读一遍 → 剖面。在后台线程里跑，失败不影响伴写。"""
    with _PROFILE_LOCK:
        PROFILE['status'] = 'building'
        PROFILE['err'] = ''
    try:
        corpus_txt, n = sample_doc()
        if not corpus_txt:
            with _PROFILE_LOCK:
                PROFILE['status'] = 'empty'
            return
        cfg = load_config()
        chidx = chapter_index_text()
        txt = (llm_call(
            cfg, PROFILE_PROMPT,
            '【全书／全文】共 %d 段，下面是抽样给你的正文（每章开头标着章名）。\n%s\n\n%s'
            % (len(DOC_STORE.get('paragraphs') or []),
               ('\n' + chidx + '\n') if chidx else '',
               corpus_txt)) or '').strip()
        with _PROFILE_LOCK:
            PROFILE.update({'status': 'ready' if txt else 'empty',
                            'text': txt, 'built_at': time.time(),
                            'doc_chars': len(DOC_STORE.get('text') or ''),
                            # 绑上"读的是哪一版"。之后正文一变，这一版就旧了，
                            # prompt 那边会据此**降级**它的身份（§49）。
                            'rev': DOC_STORE.get('rev') or 0})
        print('[profile] 剖面已生成 %d 字（采样 %d 段）' % (len(txt), n), flush=True)
        SYNC['drift'] = 0          # 新剖面对齐了新 rev，之前的漂移一笔勾销
        # 存进记忆层：这样下次开机、重新载入同一份稿子，全篇把握不用重算就有。
        try:
            mem_save_profile(txt)
        except Exception as _me:
            print('[profile] 写记忆层失败：%s' % _me, flush=True)
    except Exception as e:
        with _PROFILE_LOCK:
            PROFILE.update({'status': 'error', 'err': '%s' % e})
        print('[profile] 生成失败：%s' % e, flush=True)


def start_profile():
    set_doc_profile_reset()
    threading.Thread(target=build_profile, daemon=True).start()


def set_doc_profile_reset():
    with _PROFILE_LOCK:
        PROFILE.update({'status': 'pending', 'text': '', 'built_at': 0, 'err': '',
                        'rev': 0})



def fullread_doc_key(text=None, name=None):
    t = DOC_STORE.get('text', '') if text is None else text
    n = DOC_STORE.get('name', '') if name is None else name
    h = hashlib.sha256()
    h.update((n or '').encode('utf-8', 'replace'))
    h.update(b'\0')
    h.update((t or '').encode('utf-8', 'replace'))
    return h.hexdigest()


def _fullread_public():
    with _FULLREAD_LOCK:
        st = dict(FULLREAD)
    st.pop('chapter_notes', None)
    st['memory_chars'] = len(st.get('memory') or '')
    st['coverage_pct'] = (round(100.0 * (st.get('covered_chars') or 0)
                                / max(1, st.get('total_chars') or 0), 1))
    return st


def _fullread_cache_load():
    with _FULLREAD_CACHE_LOCK:
        if _FULLREAD_CACHE:
            return
        try:
            with open(FULLREAD_CACHE_PATH, encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict):
                _FULLREAD_CACHE.update(d)
        except Exception:
            pass


def _fullread_cache_save():
    try:
        os.makedirs(os.path.dirname(FULLREAD_CACHE_PATH), exist_ok=True)
        with _FULLREAD_CACHE_LOCK:
            items = list(_FULLREAD_CACHE.items())[-16:]
            d = dict(items)
        tmp = FULLREAD_CACHE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, FULLREAD_CACHE_PATH)
    except Exception as e:
        print('[fullread] 写缓存失败（不影响本次）：%s' % e, flush=True)


def set_fullread_reset():
    """载入新文档时重置全文阅读状态；命中缓存则直接恢复。"""
    text = DOC_STORE.get('text', '') or ''
    key = fullread_doc_key(text)
    _fullread_cache_load()
    with _FULLREAD_CACHE_LOCK:
        cached = dict(_FULLREAD_CACHE.get(key) or {})
    state = {
        'status': 'empty', 'err': '', 'memory': '', 'chapter_notes': [],
        'doc_key': key, 'doc_chars': len(text),
        'chapters': len(DOC_STORE.get('chapters') or []),
        'covered_chars': 0, 'total_chars': len(text),
        'covered_parts': 0, 'total_parts': 0,
        'built_at': 0, 'rev': DOC_STORE.get('rev') or 0, 'started_at': 0,
    }
    if not text.strip():
        state['status'] = 'empty'
    elif cached.get('memory') and cached.get('doc_chars') == len(text):
        state.update({
            'status': 'ready', 'memory': cached.get('memory') or '',
            'chapter_notes': cached.get('chapter_notes') or [],
            'covered_chars': len(text), 'covered_parts': cached.get('parts') or 0,
            'total_parts': cached.get('parts') or 0,
            'chapters': cached.get('chapters') or state['chapters'],
            'built_at': cached.get('built_at') or time.time(),
            'rev': cached.get('rev') or state['rev'],
        })
    else:
        state['status'] = 'pending'
    with _FULLREAD_LOCK:
        FULLREAD.update(state)


def _probe_prof_snapshot():
    """只读的两个数：剖面状态 + 它的 rev。**给采集埋点用。**

    为什么不用 _fullread_public()：它会取 _FULLREAD_LOCK、算覆盖率、
    还把 memory_chars/coverage_pct 都重算一遍——那是给 UI 看的，
    而埋点在被测路径上，多一把锁就多一个卡住写作的机会。

    这里直接读两个标量，判据与 mark_fullread_stale() 完全一致
    （FULLREAD.rev != DOC_STORE.rev 即过期），不重复实现规则。
    """
    try:
        st = FULLREAD.get('status') or 'empty'
        rev = FULLREAD.get('rev') or 0
        drev = DOC_STORE.get('rev') or 0
        return {'prof_stale': (st == 'stale'), 'prof_ver': rev,
                'prof_status': st, 'doc_rev': drev}
    except Exception:
        return {'prof_stale': None, 'prof_ver': None,
                'prof_status': None, 'doc_rev': None}


def mark_fullread_stale():
    key = fullread_doc_key()
    with _FULLREAD_LOCK:
        if (FULLREAD.get('doc_key') == key and FULLREAD.get('status') == 'ready'
                and (FULLREAD.get('rev') or 0) != (DOC_STORE.get('rev') or 0)):
            FULLREAD['status'] = 'stale'
            FULLREAD['err'] = '正文已改动；当前全书记忆对应旧版本，正在等待安静后重建。'


def fullread_manifest_block():
    st = _fullread_public()
    status = st.get('status')
    if status == 'ready':
        return ('【全文阅读状态 · 已完成】\n'
                '你已经在后台逐片阅读过全文，不是抽样、不是只看了检索片段。\n'
                '覆盖：%d/%d 字；%d/%d 片；%d 章。\n'
                '服务端已持有你阅读全文后建立的全书记忆；当前章节或选区只是用户此刻所在的位置，'
                '不限制你对全篇的认识。'
                % (st.get('covered_chars') or 0, st.get('total_chars') or 0,
                   st.get('covered_parts') or 0, st.get('total_parts') or 0,
                   st.get('chapters') or 0))
    if status == 'building':
        return ('【全文阅读状态 · 进行中】\n'
                '你正在后台阅读全文，目前覆盖 %d/%d 字（%.1f%%），已完成 %d/%d 片。\n'
                '可以基于已覆盖内容回答；未覆盖部分不要假装已经读过。'
                % (st.get('covered_chars') or 0, st.get('total_chars') or 0,
                   st.get('coverage_pct') or 0.0,
                   st.get('covered_parts') or 0, st.get('total_parts') or 0))
    if status == 'stale':
        return ('【全文阅读状态 · 记忆已过期】\n'
                '你以前读过全文，但正文在之后改过；现在不能把旧全书记忆当成当前全文。\n'
                '只依据当前章节、选区和已给出的原文回答，未给出的部分要明确说未提供。')
    if status == 'offline':
        return ('【全文阅读状态 · 未完成】当前没有可调用的模型，无法建立全书记忆。')
    if status == 'error':
        return ('【全文阅读状态 · 建立失败】%s\n未完成全文阅读时，不要声称已经读过全文。'
                % (st.get('err') or '未知错误'))
    return '【全文阅读状态 · 尚未建立】不要声称已经读过全文。'


def fullread_block(max_chars=3600):
    st = _fullread_public()
    manifest = fullread_manifest_block()
    if st.get('status') != 'ready':
        return manifest
    mem = (st.get('memory') or '').strip()
    if not mem:
        return manifest
    if max_chars and len(mem) > max_chars:
        mem = (mem[:max_chars] + '\n…（全书记忆较长，界面只注入一部分；'
               '服务端保留完整阅读笔记。逐章读取时仍以该版全文覆盖记录为准。）')
    return manifest + '\n\n【全书记忆 · 阅读全文所得】\n' + mem


def fullread_notes_for(focus, max_chars=1800):
    """从逐片阅读笔记中取与当前问题/选区最相关的明细。"""
    with _FULLREAD_LOCK:
        st = dict(FULLREAD)
    if st.get('status') != 'ready':
        return ''
    notes = list(st.get('chapter_notes') or [])
    if not notes:
        return ''
    terms = _terms(focus or '')
    scored = []
    for i, note in enumerate(notes):
        score = len(terms & _terms(note)) if terms else 0
        if score:
            scored.append((score, i, note))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked, used = [], 0
    for _score, _i, note in scored:
        if used + len(note) + 2 > max_chars:
            continue
        picked.append(note); used += len(note) + 2
    if not picked:
        picked = [notes[0][:max_chars]]
    return '【全书记忆 · 相关片明细】\n' + '\n\n'.join(picked)


def _fullread_parts(cfg):
    text = DOC_STORE.get('text', '') or ''
    limit = max(3000, providers.input_budget(cfg) - 2600)
    parts = []
    chs = DOC_STORE.get('chapters') or []
    if chs:
        for c in chs:
            chunk = '\n\n'.join((ps_by_no(n) or '')
                                for n in range(c['start'], c['end'] + 1))
            chunk = chunk.strip()
            if not chunk:
                continue
            segs = split_semantic_chunks(chunk, limit)
            for j, seg in enumerate(segs, 1):
                parts.append({
                    'title': '第 %d 章「%s」%s' % (
                        c['no'], c['title'], ('第 %d 片' % j) if len(segs) > 1 else ''),
                    'text': seg['text'],
                })
    else:
        for i, seg in enumerate(split_semantic_chunks(text, limit), 1):
            parts.append({'title': '全文第 %d 片' % i, 'text': seg['text']})
    return parts


def _fullread_extract(cfg, part):
    system = (
        '你是全文阅读器，不是在回答用户，也不是在润色。只记录这一片里已经出现的事实。\n'
        '输出用 markdown，固定包含：\n'
        '## 内容脉络\n## 实体与关系\n## 主题/术语/反复出现的东西\n'
        '## 关键原句（逐字，最多 5 条）\n## 未明确\n'
        '不得补写原文没有的内容；没有就写“无”。')
    user = ('【%s】\n\n%s' % (part.get('title', ''), part.get('text', '')))
    out = providers.chat_messages_complete(
        cfg, [{'role': 'user', 'content': user}], system=system,
        temperature=0.2, max_tokens=min(2048, providers.output_budget(cfg, 2048)),
        timeout=420)
    return (out or '').strip()


def _fullread_pack(items, limit):
    out, cur, used = [], [], 0
    for item in items:
        item = (item or '').strip()
        if not item:
            continue
        if cur and used + len(item) + 5 > limit:
            out.append('\n\n---\n\n'.join(cur)); cur, used = [], 0
        cur.append(item); used += len(item) + 5
    if cur:
        out.append('\n\n---\n\n'.join(cur))
    return out


def _fullread_reduce_once(cfg, block):
    system = (
        '把多片全文阅读笔记合并成一份全书记忆，供后续对话时使用。\n'
        '保留：总体结构、章节脉络、人物/实体关系、反复出现的主题与意象、'
        '重要术语、关键原文锚点、未解决问题。\n'
        '删除重复；不得新增原文没有的事实。输出 markdown，不要开场白。')
    out = providers.chat_messages_complete(
        cfg, [{'role': 'user', 'content': block}], system=system,
        temperature=0.2, max_tokens=min(3000, providers.output_budget(cfg, 3000)),
        timeout=420)
    return (out or '').strip()


def _fullread_reduce(cfg, notes):
    items = [x for x in notes if (x or '').strip()]
    if not items:
        return ''
    limit = max(3000, providers.input_budget(cfg) - 1200)
    for _ in range(4):
        joined = '\n\n---\n\n'.join(items)
        if len(joined) <= limit and len(joined) <= FULLREAD_MEMORY_MAX:
            return joined
        blocks = _fullread_pack(items, limit)
        if len(blocks) == 1 and len(blocks[0]) <= FULLREAD_MEMORY_MAX:
            return blocks[0]
        items = [_fullread_reduce_once(cfg, b) for b in blocks]
    joined = '\n\n---\n\n'.join(items)
    if len(joined) > FULLREAD_MEMORY_MAX:
        joined = joined[:FULLREAD_MEMORY_MAX] + '\n…（全书记忆归并后仍较长，保留摘要部分）'
    return joined


def build_fullread():
    """后台逐片读全文，建立覆盖率可验证的全书记忆。"""
    if not (DOC_STORE.get('text') or '').strip():
        return
    key = fullread_doc_key()
    with _FULLREAD_LOCK:
        FULLREAD.update({
            'status': 'building', 'err': '', 'doc_key': key,
            'doc_chars': len(DOC_STORE.get('text') or ''),
            'total_chars': len(DOC_STORE.get('text') or ''),
            'covered_chars': 0, 'covered_parts': 0, 'total_parts': 0,
            'chapters': len(DOC_STORE.get('chapters') or []),
            'started_at': time.time(), 'rev': DOC_STORE.get('rev') or 0,
            'memory': '', 'chapter_notes': [],
        })
    cfg = load_config()
    if not providers.configured(cfg):
        with _FULLREAD_LOCK:
            FULLREAD.update({'status': 'offline',
                             'err': '未配置可调用的模型'})
        return
    try:
        parts = _fullread_parts(cfg)
        _fullread_cache_load()
        with _FULLREAD_CACHE_LOCK:
            cached = dict(_FULLREAD_CACHE.get(key) or {})
        notes = list(cached.get('partial_notes') or [])
        start_at = min(len(notes), len(parts))
        covered = sum(len((parts[k].get('text') or '')) for k in range(start_at))
        with _FULLREAD_LOCK:
            FULLREAD.update({'total_parts': len(parts), 'chapter_notes': notes,
                             'covered_chars': min(covered, len(DOC_STORE.get('text') or '')),
                             'covered_parts': start_at})
        for i, part in enumerate(parts[start_at:], start_at + 1):
            if fullread_doc_key() != key:
                raise RuntimeError('阅读期间正文发生变化，停止写入旧全书记忆')
            note = _fullread_extract(cfg, part)
            title = part.get('title') or ('第 %d 片' % i)
            notes.append('## %s\n%s' % (title, note or '（这一片未读出内容）'))
            covered += len(part.get('text') or '')
            with _FULLREAD_LOCK:
                FULLREAD.update({
                    'chapter_notes': notes,
                    'covered_chars': min(covered, len(DOC_STORE.get('text') or '')),
                    'covered_parts': i,
                })
            with _FULLREAD_CACHE_LOCK:
                _FULLREAD_CACHE[key] = {
                    'partial_notes': notes, 'parts': len(parts),
                    'doc_chars': len(DOC_STORE.get('text') or ''),
                    'chapters': len(DOC_STORE.get('chapters') or []),
                    'rev': DOC_STORE.get('rev') or 0,
                }
            _fullread_cache_save()
            print('[fullread] %d/%d 片，覆盖 %d 字'
                  % (i, len(parts), covered), flush=True)
        if fullread_doc_key() != key:
            raise RuntimeError('阅读完成前正文已经变化，本次全书记忆作废')
        memory = _fullread_reduce(cfg, notes)
        built = time.time()
        with _FULLREAD_LOCK:
            FULLREAD.update({
                'status': 'ready', 'memory': memory, 'chapter_notes': notes,
                'covered_chars': len(DOC_STORE.get('text') or ''),
                'covered_parts': len(parts), 'total_parts': len(parts),
                'built_at': built, 'rev': DOC_STORE.get('rev') or 0,
            })
        with _FULLREAD_CACHE_LOCK:
            _FULLREAD_CACHE[key] = {
                'memory': memory, 'doc_chars': len(DOC_STORE.get('text') or ''),
                'chapters': len(DOC_STORE.get('chapters') or []),
                'parts': len(parts), 'built_at': built,
                'chapter_notes': notes,
                'rev': DOC_STORE.get('rev') or 0,
            }
        _fullread_cache_save()
        print('[fullread] 全文阅读完成：%d 片 / %d 字'
              % (len(parts), len(DOC_STORE.get('text') or '')), flush=True)
    except Exception as e:
        with _FULLREAD_LOCK:
            FULLREAD.update({'status': 'error', 'err': str(e)})
        print('[fullread] 失败：%s' % e, flush=True)


def start_fullread(force=False):
    text = DOC_STORE.get('text', '') or ''
    if not text.strip():
        set_fullread_reset()
        return False
    key = fullread_doc_key(text)
    if not force:
        _fullread_cache_load()
        with _FULLREAD_CACHE_LOCK:
            cached = _FULLREAD_CACHE.get(key)
        if cached and cached.get('memory'):
            with _FULLREAD_LOCK:
                FULLREAD.update({
                    'status': 'ready', 'err': '', 'doc_key': key,
                    'memory': cached.get('memory') or '',
                    'chapter_notes': cached.get('chapter_notes') or [],
                    'doc_chars': len(text), 'total_chars': len(text),
                    'covered_chars': len(text),
                    'covered_parts': cached.get('parts') or 0,
                    'total_parts': cached.get('parts') or 0,
                    'chapters': len(DOC_STORE.get('chapters') or []),
                    'built_at': cached.get('built_at') or time.time(),
                    'rev': DOC_STORE.get('rev') or 0,
                })
            return True
    with _FULLREAD_LOCK:
        if FULLREAD.get('status') == 'building' and FULLREAD.get('doc_key') == key:
            return False
    threading.Thread(target=build_fullread, daemon=True).start()
    return True


def maybe_rebuild_fullread():
    with _FULLREAD_LOCK:
        st = FULLREAD.get('status')
        key = FULLREAD.get('doc_key')
    if st in ('pending', 'building'):
        return False
    cur = fullread_doc_key()
    if st == 'ready' and key == cur and (FULLREAD.get('rev') or 0) == (DOC_STORE.get('rev') or 0):
        return False
    n = len(DOC_STORE.get('paragraphs') or [])
    need = max(4, min(FRESH_DRIFT_MAX, max(1, n // 8)))
    if (SYNC.get('drift') or 0) < need:
        return False
    last = SYNC.get('last_change') or SYNC.get('at') or 0
    if time.time() - last < FRESH_QUIET_SEC:
        return False
    return start_fullread(force=(key == cur))

def load_workflow():
    try:
        with open(WORKFLOW_PATH, encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def split_paragraphs(text):
    """按空行切段；返回 [(段号, 文本)]，段号从 1 开始。"""
    raw = re.split(r'\n\s*\n', (text or '').replace('\r\n', '\n'))
    return [(i + 1, p.strip()) for i, p in enumerate(raw) if p.strip()]


def normalize_selection(sel):
    """把前端选区收成可安全放进提示词的一张事实。

    选区坐标可能是编辑区坐标，也可能是窗口化后的全文坐标；服务端不擅自
    拿它去切另一份文本，只使用前端同时送来的 `text`，从这里开始所有模型
    看到的选区内容完全一致。
    """
    if not isinstance(sel, dict):
        return None
    try:
        start = max(0, int(sel.get('start') or 0))
        end = max(start, int(sel.get('end') or start))
    except Exception:
        start = end = 0
    text = str(sel.get('text') or '')
    if not text and end <= start:
        return None
    return {'start': start, 'end': end, 'text': text,
            'length': max(end - start, len(text)),
            'truncated': bool(sel.get('truncated'))}


def selection_block(sel, limit=6000):
    """选区原文＋起止位置的模型提示块。没有选区时返回空串。"""
    sel = normalize_selection(sel)
    if not sel:
        return ''
    body = sel['text']
    cut = len(body) > limit
    if cut:
        body = body[:limit]
    pos = ('第 %d–%d 个字符' % (sel['start'] + 1, sel['end'])
           if sel['end'] > sel['start'] + 1 else ('第 %d 个字符' % (sel['start'] + 1)))
    return ('【用户明确选区】%s，共 %d 字%s。\n'
            '她这次说的“这里 / 这一段 / 选中的部分”默认都指下面这段原文；\n'
            '除非她明确说“全文”，回答与改动建议必须优先落在选区内。\n'
            '「%s」%s' %
            (pos, sel['length'], '（显示时截断）' if cut else '', body,
             '\n（选区很长，上面只展示了开头；完整内容另按范围内材料处理。）' if cut else ''))


def split_text_chunks(text, limit, overlap=0):
    """按自然段边界把长文切成互不丢失顺序的片。

    这是分片，不是截断：所有片按顺序处理后再拼回，调用方负责标明这是
    分段结果。单段本身超限时才硬切，且保证前进，不会死循环。
    """
    t = text or ''
    if not t:
        return []
    limit = max(1000, int(limit or 1000))
    out = []
    at = 0
    while at < len(t):
        end = min(len(t), at + limit)
        if end < len(t):
            win = t[at:end]
            cut = max(win.rfind('\n\n'), win.rfind('\n'))
            if cut >= int(limit * 0.55):
                end = at + cut
        if end <= at:
            end = min(len(t), at + limit)
        out.append({'text': t[at:end], 'start': at, 'end': end})
        if end >= len(t):
            break
        at = max(end - max(0, int(overlap or 0)), at + 1)
    return out

def is_full_translate_request(text):
    return bool(re.search(
        r'(?:翻译|译).{0,12}(?:全文|整本|整篇|全部)|'
        r'(?:全文|整本|整篇|全部).{0,12}(?:翻译|译)|'
        r'一口气.{0,8}(?:翻译|译)', text or ''))


def split_semantic_chunks(text, limit):
    """在自然边界上分片；词典/条目文本优先按词条切，避免从释义中间开始。"""
    t = text or ''
    if not t:
        return []
    limit = max(1000, int(limit or 1000))
    paras = [x.strip() for x in re.split(r'\n\s*\n', t) if x.strip()]
    if len(paras) < 2:
        return split_text_chunks(t, limit)
    marks = []
    for i, para in enumerate(paras):
        first = para.split('\n', 1)[0].strip()
        is_head = bool(re.match(
            r'^\s*(?:#{1,6}\s+|第\s*[0-9一二三四五六七八九十百千万]+\s*[章节回卷]|'
            r'\d+(?:\.\d+)+\s+)', first))
        is_dict = (len(first) <= 80 and i + 1 < len(paras)
                   and re.match(r'^(?:n\.|adj\.|adv\.|v\.|vt\.|vi\.|prep\.|pron\.|'
                                r'conj\.|interj\.|phrase)\s*', paras[i + 1]))
        if is_head or is_dict:
            marks.append(i)
    if len(marks) < 2:
        return split_text_chunks(t, limit)
    entries = []
    if marks[0] > 0:
        entries.append('\n\n'.join(paras[:marks[0]]))
    for j, at in enumerate(marks):
        end = marks[j + 1] if j + 1 < len(marks) else len(paras)
        entries.append('\n\n'.join(paras[at:end]))
    out, cur = [], ''
    for entry in entries:
        if len(entry) > limit:
            if cur:
                out.append({'text': cur})
                cur = ''
            out.extend({'text': x['text']} for x in split_text_chunks(entry, limit))
            continue
        if cur and len(cur) + len(entry) + 2 > limit:
            out.append({'text': cur})
            cur = entry
        else:
            cur = (cur + '\n\n' + entry) if cur else entry
    if cur:
        out.append({'text': cur})
    return out


def relevant_excerpt(text, focus, limit):
    """长材料做问答时，用问题/选区检索相关段落，而不是拿“前 N 字”冒充全文。"""
    t = text or ''
    if len(t) <= limit:
        return t, ''
    unit = max(1800, int(limit) // 4)
    chunks = split_semantic_chunks(t, unit)
    terms = _terms(focus or '')
    scored = []
    for i, ch in enumerate(chunks):
        body = ch['text']
        score = 0.0
        if re.match(r'^\s*(#{1,6}\s+|第\s*[0-9一二三四五六七八九十百千万]+\s*[章节回卷]|\d+(?:\.\d+)+\s+)',
                    body):
            score += 2.0
        if terms:
            score += len(terms & _terms(body)) / max(1.0, len(terms))
        scored.append((score, i, body))
    take = set()
    used = 0
    for score, i, body in sorted(scored, key=lambda x: (-x[0], x[1])):
        if score <= 0:
            continue
        if used + len(body) + 2 <= limit:
            take.add(i); used += len(body) + 2
    seeds = [0, len(chunks) - 1, len(chunks) // 2]
    step = max(1, len(chunks) // 8)
    seeds += list(range(0, len(chunks), step))
    for i in seeds:
        if 0 <= i < len(chunks) and i not in take:
            body = chunks[i]['text']
            if used + len(body) + 2 <= limit:
                take.add(i); used += len(body) + 2
    picked = [chunks[i] for i in sorted(take)]
    body = '\n\n'.join(c['text'] for c in picked)
    note = ('（原句检索：材料共 %d 字，下面是围绕问题/选区取出的可核对原句，'
            '不是“只给了前 N 字”。是否已经通读全文，以同时提供的【全文阅读状态】为准；'
            '不要把这块检索片段误认为唯一上下文，也不要因为片段不全就否认已经建立的全书记忆。）'
            % len(t))
    return body, note


# ---------------------------------------------------------------- 章节识别
# 为什么要有这一层（2026-09-20 猫猫报的 bug）：
#   一个现成的 docx / md 载进来，**目录识别是失效的**——右上角那格位置
#   不管光标在哪都显示「一」，而模型回复里引用位置用的是 `§1308` 这种
#   **段号**，界面却从来不显示"现在是第几段"。她的话："会给用户极大的困惑"。
#
# 根因有两层，**两层都要治**：
#   ① 我们从来没有把「章节」这个概念交出去过。epub 之所以正常，是因为
#      spine 天然分章、章标题进了正文；docx / md 的标题只是一个普通段落，
#      剖面的 prompt 也只让它写**段号**（"依据里要带段号"），
#      于是模型手里根本没有章名可用，只能回 `§1308`。
#   ② 前端的目录（TOC）与探针各算各的位置，TOC 认识标题、探针不认识，
#      两者从来没通过气。所以"目录面板里有章名"和"位置框显示一"能同时成立。
#
# 治法是**一处识别、三处复用**：
#   `detect_chapters()` 在载入时认出章（标题行 + 每章的字数区间），
#   存进 DOC_STORE；然后
#     · 剖面 prompt     → 按章抽样，要求它引用时**说章名**
#     · build_user      → 把"她在第几章、章名是什么"放进【当前位置】
#     · /api/doc 回给前端 → 前端拿它算右上角位置框、并转给探针
#   这样"看到的章"和"模型说的章"是**同一份**，不会再各说各话。

# 一行是不是章节标题。顺序有讲究：从最确定的形态往最松的排。
# ⚠️ 不要放宽到"任意短行"——散文里短句太多，会把正文切成碎片，
#    那比没有章还坏（她会拿到一屏莫名其妙的分章）。
# ⚠️ 更不要收「(1)」「（一）」这种——那是**列表项**，不是章。
#    2026-09-20 拿真实论文试过：`(1) 构建同语言对照…` 这种被收进来，
#    结果一篇 6 章的论文被切成 21"章"，其中好几个"章"只有一段。
#    判据是：分章是为了定位，列表项定位不到"地方"，只定位到"第几条"。
_CHAP_PATTERNS = [
    # 1) markdown / 手工的 `# 标题`（1–6 级）。要求 # 后有空格，别把 `#tag` 当标题。
    (3, re.compile(r'^\s{0,3}(#{1,6})\s+(\S.*?)\s*#*\s*$')),
    # 2) 网文式：第X章 / 第X节 / 第X回 / 第X卷；X 可以是中文数字或阿拉伯数字。
    (2, re.compile(r'^\s*第\s*[0-9〇零一二三四五六七八九十百千万两]+\s*[章节回卷幕篇]\s*[·:：\-—]?\s*\S*')),
    # 3) 编号小节：`2.1 主动性与介入时机` / `3.1.2 xxx`（论文最常见的那种）。
    #    要求数字点分且**后面跟标题字**，避免把「1.5 倍」这种正文量给收进来。
    (3, re.compile(r'^\s*\d{1,2}(?:\.\d{1,2}){1,2}\s+[\u4e00-\u9fff（("].{0,60}$')),
    # 3b) 顶层裸编号：`1 引言` / `2 相关工作`（论文的章级标题常不带点）。
    #     比上一条严：**必须**是「数字 + 空格 + 中文/引号开头」且整行短。
    #     不收它的话，`1 引言` 会被漏掉、整篇少一章（实测过）。
    (2, re.compile(r'^\s*\d{1,2}\s+[\u4e00-\u9fff（(“"《].{0,40}$')),
    # 4) 英文章节：Chapter 12 / CHAPTER ONE / Part 3
    (2, re.compile(r'^\s*(?:chapter|part|book|section)\s+'
                   r'(?:[0-9]+|[ivxlcdm]+|one|two|three|four|five|six|seven|'
                   r'eight|nine|ten|eleven|twelve)\b[^\n]*$', re.I)),
    # 5) 附录 / 致谢 / 参考文献这类**结构分界**也算章（论文里它们是大块）。
    (2, re.compile(r'^\s*(?:附录|致谢|参考文献|引用文献|后记|序言|前言|自序|'
                   r'目录|摘要|摘\s*要|附录\s*[A-Za-z0-9一二三四五六七八九十]?)\s*$')),
]


def _chapter_title(para):
    """这一段的**首行**是不是章节标题。是就返回标题文本，不是返回 ''。"""
    first = (para or '').split('\n', 1)[0].strip()
    if not first or len(first) > 60:
        return ''
    for _lv, rx in _CHAPTER_MARKS:
        m = rx.match(first)
        if m:
            # markdown 那种把 `# ` 剥掉，别把井号喂给模型。
            # `lstrip('#')` 只去行首的：`#### 2.6.1 断裂即价值` → `2.6.1 断裂即价值`
            t = first.lstrip('#').strip()
            # 目录行不是章：它后面挂着页码（`… 25`）或者 PAGEREF 那种域代码。
            # 收了它，位置框会把"目录里的第 25 页"当成一章（实测过）。
            if re.search(r'\bPAGEREF\b|HYPERLINK', t):
                return ''
            if re.search(r'[\u4e00-\u9fff）)"]\s+\d{1,3}$', t):
                return ''
            return t
    return ''


# 按"确定性"排过序，给 _chapter_title 用（级别数字只用来标层级粗细）。
_CHAPTER_MARKS = sorted(_CHAP_PATTERNS, key=lambda x: x[0])


def detect_chapters(paras):
    """从 [(段号, 文本)] 里认出章节结构。

    返回 [{'no': 第几章(1起), 'title': 章名, 'start': 起段号, 'end': 止段号,
           'chars': 本章字数}]；认不出就返回 []（**不是**硬凑一章）。
    认不出是**正常结果**：很多散文本来就没有章。这时上层退回段号。
    """
    if not paras:
        return []
    marks = []          # [(段号, 标题)]
    for no, txt in paras:
        t = _chapter_title(txt)
        if t:
            marks.append((no, t))
    # 一个都没有，或者只有一个且在文档最开头——那更像"标题"而不是"分章"。
    # 只有一章的文档不需要"章"这个概念（窗口化那套同理：切不动就别切）。
    if len(marks) < 2:
        return []
    # 第一个章标记之前若还有正文（前言），也算作一章。
    # ⚠️ 但**只剩目录/域代码的那种**不算：真实论文里"目录"那几段全是
    #    `… PAGEREF _Toc… \h 4` 这种域结果，把它当一章，位置框会显示
    #    "第 1 章（开篇）"而那里根本没有正文（实测过）。
    out = []
    if marks[0][0] > 1:
        pre = ' '.join(t for _n, t in paras if _n < marks[0][0])
        if pre.strip() and not re.search(r'\bPAGEREF\b|HYPERLINK', pre):
            out.append({'title': '（开篇）', 'start': 1, 'end': marks[0][0] - 1})
    by_no = dict(paras)
    for i, (pno, title) in enumerate(marks):
        end = marks[i + 1][0] - 1 if i + 1 < len(marks) else paras[-1][0]
        out.append({'title': title, 'start': pno, 'end': end})
    # 章号从 1 连续编（开篇那章若存在，就是第 1 章）
    for i, c in enumerate(out):
        c['no'] = i + 1
        c['chars'] = sum(len(by_no.get(n, '')) for n in range(c['start'], c['end'] + 1))
    return out


def chapter_of(para_no):
    """第 para_no 段落在哪一章。认不出章就返回 None。

    ⚠️ `para_no` 可能是 **None**：她正在写一段**新内容**时，`find_para_no`
    在文档快照里找不到它，返回的就是 None。原来这里直接拿 None 去比大小，
    整条 `/api/cowrite` 会抛 `TypeError: '<=' not supported between
    instances of 'int' and 'NoneType'` 崩掉（2026-09-20 实测）。
    **认不出位置不是故障，是常态**——写新段落本来就还没进快照。
    """
    if not para_no:
        return None
    for c in (DOC_STORE.get('chapters') or []):
        if c['start'] <= para_no <= c['end']:
            return c
    return None


def extract_docx_bytes(data):
    """纯标准库解 docx：docx 是 zip，正文在 word/document.xml。

    **要保住标题**（2026-09-20）：原来这一层把所有标签一律 `<[^>]+>` 抹掉，
    Word 里设成「标题 1 / Heading 1」的那些段落于是变成普通段落——
    标题信号在被任何人看见之前就被销毁了，detect_chapters 再准也无从下手。
    现在碰到标题样式就补一个 `# ` 前缀（markdown 形态），
    让"标题"这件事以**纯文本**的形态活下来（后端其余部分与前端都认这个）。

    中文 Word 的样式名是「标题 1」，英文是「Heading 1」，两种都覆盖；
    另外 outlineLvl 是更底层的判据（很多模板的标题不带 styleId 但带它）。"""
    import zipfile
    import io as _io
    try:
        with zipfile.ZipFile(_io.BytesIO(data)) as z:
            xml = z.read('word/document.xml').decode('utf-8', 'ignore')
    except Exception as e:
        raise ValueError('docx 解析失败：%s' % e)

    # 只取 <w:body> 里的东西：不然 XML 声明和根标签会混进正文，
    # 把整篇变成一个"段"（实测过）。
    bm = re.search(r'<w:body\b[^>]*>([\s\S]*)</w:body>', xml)
    if bm:
        xml = bm.group(1)

    def _para(m):
        """一个 <w:p>…</w:p> → 文本（标题补 # 前缀）。"""
        body = m.group(0)
        # 段落的样式：<w:pStyle w:val="Heading1"/> / <w:pStyle w:val="1"/>
        lv = 0
        sm = re.search(r'<w:pStyle[^>]*w:val\s*=\s*"([^"]*)"', body)
        if sm:
            sid = sm.group(1)
            hm = re.search(r'(?:heading|标题)\s*([1-6])', sid, re.I)
            if hm:
                lv = int(hm.group(1))
            elif re.match(r'^[1-6]$', sid):
                # ⚠️ 只收**恰好一位**数字的 styleId（Word 中文版的「标题 1」常写成 "1"）。
                #    绝不能放宽成 \d+ —— 正文样式常叫 "11"、"21" 这种，
                #    放宽之后一整篇普通段落会被当成"标题 1"（2026-09-20 实测：
                #    一篇 6 章的论文因此变成 21 个"章"，`(4) …` 那种列表项
                #    也跟着成了"章"，因为它的 styleId 正是 "11"）。
                lv = int(sid)
        if not lv:
            # outlineLvl 0 起（0 表示 1 级标题），只有它没 pStyle 时才用
            om = re.search(r'<w:outlineLvl[^>]*w:val\s*=\s*"([0-5])"', body)
            if om:
                lv = int(om.group(1)) + 1
        txt = re.sub(r'<w:tab[^>]*/>', '\t', body)
        # 先把**属性块整个削掉**再取字。只靠 `<[^>]+>` 是不够的：
        # `<w:b w:val="0"/>` 这种自闭合标签在被逐段匹配时会把 `w:val="0"`
        # 之类的残片留在正文里（2026-09-20 在真实 docx 上看到
        # `…这一跨模态命题。\n<w:b` 这样的脏尾）。属性块不是内容，整块去掉最稳。
        txt = re.sub(r'<w:pPr\b[\s\S]*?</w:pPr>|<w:pPr\b[^>]*/>', '', txt)
        txt = re.sub(r'<w:rPr\b[\s\S]*?</w:rPr>|<w:rPr\b[^>]*/>', '', txt)
        txt = re.sub(r'<[^>]+>', '', txt)
        txt = (txt.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                  .replace('&quot;', '"').replace('&apos;', "'")).strip()
        if lv and txt:
            txt = '#' * min(lv, 6) + ' ' + txt
        # ⚠️ 段间**必须**留一个空行：split_paragraphs 是按空行切段的，
        #    只还给一个 '\n' 的话整篇会塌成一段（实测过，不可省）。
        return '\n' + txt + '\n'

    xml = re.sub(r'<w:p\b[^>]*>[\s\S]*?</w:p>|<w:p\b[^>]*/>', _para, xml)
    # —— 兜底：把**任何残留的标签**清掉。
    # 为什么要兜底而不是指望上面的正则：`<w:p>` 的分支匹配不到**表格内部**的
    # 段落结构（表格里是 <w:tr>/<w:tc> 包着 <w:p>，嵌套层级不一样），
    # 于是表格的 XML 会成片漏进正文。2026-09-20 用真实论文实测：
    # 303 段里有 77 段带着 `<w:tbl>` / `</w:tc></w:tr>` 这类脏尾，
    # 而且 8 万字的表格垃圾全被算进了某一"章"。
    # 这一段只做"清场"，不改内容——它是最后一道，宁可保守。
    xml = re.sub(r'<[^>]+>', '', xml)
    # 空段（原本就是 <w:p/> 那种）会留下连续的裸换行，压一压；
    # 但**保留**段与段之间那一个空行。
    xml = re.sub(r'[ \t]+', ' ', xml)
    xml = re.sub(r'\n[ \t]*\n([ \t]*\n)+', '\n\n', xml)
    xml = re.sub(r'[ \t]+\n', '\n', xml)
    return xml.strip()


def docx_bytes(text):
    """用标准库 zipfile **手写**一个最小可用的 .docx（纯文本，一段一行）。

    不引 python-docx：导出只要"Word/WPS 打得开、段落对得上"，
    为这一步引一个第三方库不划算——何况本机的 docx 编辑另有专用通道。

    docx 的最小集合就三件：[Content_Types].xml + _rels/.rels + word/document.xml。
    少了哪一件 Word 都会说文件损坏。
    """
    import zipfile
    import io as _io

    def xesc(s):
        return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    paras = []
    for ln in (text or '').split('\n'):
        # XML 1.0 不接受大部分控制字符，遇到就丢掉（制表符除外）
        ln = ''.join(ch for ch in ln if ch in '\t\r' or ord(ch) >= 32)
        if not ln.strip():
            paras.append('<w:p/>')
        else:
            paras.append('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>'
                         % xesc(ln))

    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>%s<w:sectPr/></w:body></w:document>' % ''.join(paras))

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', doc)
    return buf.getvalue()


def md_plain(text):
    """markdown → 尽量干净的纯文本。**只去掉标记，不做排版**。

    真正的渲染在网页上（`web/index.html` 的 `md()`）。这里是给 .docx 用的：
    Word 里出现一排 `##` 和 `**` 比没有标题更难看。
    所以只处理最显眼的几种：标题井号、引用箭头、列表符号、加粗星号、反引号。
    """
    out = []
    for ln in (text or '').split('\n'):
        ln = re.sub(r'^\s{0,3}#{1,6}\s+', '', ln)
        ln = re.sub(r'^\s*>\s?', '', ln)
        ln = re.sub(r'^\s*[-*+]\s+', '· ', ln)
        ln = ln.replace('**', '').replace('`', '')
        out.append(ln)
    return '\n'.join(out)


def _safe_name(s, ext):
    """文件名里不能有的字符一律换掉；另给一个纯 ASCII 的兜底名，
    免得某些浏览器拿到中文 Content-Disposition 就乱码。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', (s or '').strip()) or '文稿'
    if len(s) > 60:
        s = s[:60]
    ascii_name = re.sub(r'[^A-Za-z0-9._-]', '_', s) or 'export'
    # 全是中文时兜底名会变成一串下划线，那种不如就叫 export
    if not re.search(r'[A-Za-z0-9]', ascii_name):
        ascii_name = 'export'
    return s + '.' + ext, ascii_name + '.' + ext


def set_doc(name, text):
    DOC_STORE['name'] = name or ''
    DOC_STORE['text'] = text or ''
    DOC_STORE['paragraphs'] = split_paragraphs(text)
    # 章节：载入时认一次，之后剖面 / 位置 / 前端都复用它（见上文「章节识别」）。
    DOC_STORE['chapters'] = detect_chapters(DOC_STORE['paragraphs'])
    DOC_STORE['para_fp'] = []
    DOC_STORE['rev'] = 1
    # 换了稿子 → 指纹表与变更集统统作废。**不清就是上一个作品的段落**
    # 冒充这一篇的正文，比"没有"更坏。
    _PARA_BY_HASH.clear()
    SYNC.update({'rev': 1, 'at': 0.0, 'changed': {}, 'gaps': 0, 'gap_no': [],
                 'seeded': False, 'last_change': 0.0, 'drift': 0})
    set_fullread_reset()
    return doc_meta()


def doc_meta():
    ps = DOC_STORE['paragraphs']
    chs = DOC_STORE.get('chapters') or []
    fr = _fullread_public() if 'fullread_doc_key' in globals() else {}
    fr.pop('memory', None)
    return {'name': DOC_STORE['name'],
            'chars': len(DOC_STORE['text']),
            'paragraphs': len(ps),
            'rev': DOC_STORE.get('rev') or 0,
            'synced_at': SYNC.get('at') or 0,
            'gaps': SYNC.get('gaps') or 0,
            # 前端**必须**拿到这份章表：右上角位置框、目录、探针
            # 三处都要靠它说"她在第几章"，不能在 JS 里再认一遍
            # （两端各写一份判定迟早走偏，§四.28 的老教训）。
            'chapters': chs,
            'fullread': fr}


# ---------------------------------------------------------------- 新鲜度（§49）
# 她 2026-09-19 指出的问题：**服务端对全文的把握冻结在"载入"那一刻**。
# `DOC_STORE` 原来只有一个写入口（`set_doc`），只被载入调用；伴写时前端只送
# 【当前段＋前一段】。于是 `pick_context` 会把**她已删掉的段落**当"文档原文"
# 递给模型，`find_para_no` 在**她新写的**段落上定位不到，剖面也继续以
# "你通读所得"的身份说话。
#
# 分工按她的要求定，**别改回去**：
#   · **指纹**只负责**便宜地发现"哪变了"**——段数＋每段 hash，几 KB。
#   · 但送到模型眼前的必须是**变了那些段的正文**。只报"第 47 段变了 23 字"
#     是**结构判断**，那是她明确不要的："那样就失去了系统的特色"。
#     要让她读到的是**信息上处在什么局面**，所以正文必须真到手。
#   · hash 由**前端**算，服务端只当**不透明令牌**。两端各写一份哈希函数迟早走偏
#     （§四.28），而且 JS 的 UTF-16 码元与 Python 的码点在中日韩扩展区并不一致。
SYNC = {'rev': 0, 'at': 0.0, 'changed': {}, 'gaps': 0, 'gap_no': [], 'seeded': False,
        'last_change': 0.0, 'drift': 0}
_PARA_BY_HASH = {}          # 前端 hash → 段落正文（服务端不自己算 hash）
_PARA_BY_HASH_CAP = 4000

# 剖面什么时候值得**重读一遍**：她选的是「降级＋停顿后重建」。
#   先降级（零成本，立刻消掉"旧判断被当成结论"），重建则要挑时候——
#   她**停笔**了才做，否则会在她正写着的时候占一次模型调用、还可能扫兴。
FRESH_QUIET_SEC = 45        # 停笔这么久才算"停下来了"
FRESH_DRIFT_MAX = 12        # 漂移段数的上限（正文越长，阈值按比例，但不超这个）


def apply_sync(paras, texts, total_chars=None):
    """把前端送来的**段落指纹**（＋变了的那些段的正文）并进 `DOC_STORE`。

    paras: [[字数, hash], …]   全文按顺序的指纹（hash 是前端算的）
    texts: {索引: 该段正文}    只带"服务端手里那份是旧的"的段落

    返回本次变更集。定位不到正文的段落记成 **gap** 并打日志——
    **静默降级是最坏的失败方式**（§四.12），宁可留个洞也别装作没洞。
    """
    old_fp = list(DOC_STORE.get('para_fp') or [])
    old_ps = list(DOC_STORE.get('paragraphs') or [])
    new_fp = [str(h) for _ln, h in paras]
    texts = {str(k): v for k, v in (texts or {}).items()}
    # 首次同步：服务端手上是载入那份，与前端这一串指纹**逐位对应**，可以配对。
    # ⚠️ 三个条件缺一不可（补第二个、第三个是 2026-09-19 用真 HTTP 才逼出来的）：
    #   ① 还没配对过（`seeded`）——否则每一趟都会拿"上一趟的自己"去凑；
    #   ② 段数一致；
    #   ③ **旧的那几段全都得有正文**。旧文里带洞时逐位配对＝拿洞去顶真身，
    #      结果正文里凭空少掉一段，而 `gaps` 还报 0——**静默丢内容**。
    seeding = (not SYNC.get('seeded')) and len(old_ps) == len(new_fp) \
        and all(t for _no, t in old_ps)

    new_ps, gaps = [], []
    for i, (_ln, h) in enumerate(paras):
        h = str(h)
        t = texts.get(str(i))
        if t is None:
            t = _PARA_BY_HASH.get(h)
        if t is None and seeding and i < len(old_ps):
            t = old_ps[i][1]
        if t is None:
            gaps.append(i + 1)
            new_ps.append((i + 1, ''))
        else:
            new_ps.append((i + 1, t.strip()))

    # 变更集：前后各剥掉相同的头尾，中间那段就是她动过的地方。
    # 不做 LCS——段落是一维线性文本，头尾对齐足够，而且**看得懂**比精确更要紧。
    #
    # ⚠️ 第一次同步时 `para_fp` 还是空的（`set_doc` 清掉了）：那时**没有可比的前一版**，
    #    若照常算，整篇都会被判成"没了"——载入后第一趟就会报一次假的大变更，
    #    还会把 `drift` 顶过阈值、骗出一次没必要的剖面重建。
    #    所以这时改成**逐位比文本**：段数一致就能认出"哪几段被改过"，
    #    段数都不一致就认不出——那就**不报**，不猜。
    baseline = (not old_fp) or (len(old_fp) != len(old_ps))
    if baseline:
        # 逐位比文本：段数一致就认得出"哪几段被改过"；段数都不一致就**认不出**，
        # 那就不报变更明细——但「内容确实变了」这件事**必须**照样认下来，
        # 否则 rev 不涨、剖面不会被判过期，正文变了而把握还装成新鲜的。
        p = 1
        idx = ([i for i in range(len(new_ps)) if old_ps[i][1] != new_ps[i][1]]
               if len(old_ps) == len(new_ps) else None)
        removed = [old_ps[i] for i in idx] if idx else []
        added = [new_ps[i] for i in idx] if idx else []
        changed = bool(idx) or (len(old_ps) != len(new_ps))
    else:
        p = 0
        while p < len(old_fp) and p < len(new_fp) and old_fp[p] == new_fp[p]:
            p += 1
        s = 0
        while (s < len(old_fp) - p and s < len(new_fp) - p
               and old_fp[len(old_fp) - 1 - s] == new_fp[len(new_fp) - 1 - s]):
            s += 1
        removed = old_ps[p:len(old_ps) - s]
        added = new_ps[p:len(new_ps) - s]
        changed = bool(removed or added)

    DOC_STORE['paragraphs'] = new_ps
    DOC_STORE['para_fp'] = new_fp
    # 章表得跟着正文重算（2026-09-20）。`chapters` 存的是**段号区间**
    # （start / end），而段号是**按当前正文**数的——她删掉一段、或在中间插一段，
    # 后面所有章的区间就整体错位一位，位置框于是报错章。
    # 只在**段数真变了**时重算：逐段改字不动边界，重算纯属浪费
    # （大书每次重扫全文的标题行不便宜，而 /api/sync 每 5 秒来一趟）。
    # ⚠️ 章表变化要**一起**告诉前端（doc_meta 里带出去），否则前端那份也旧了。
    _old_n = len(DOC_STORE.get('chapters') or [])
    if len(new_ps) != len(old_ps):
        DOC_STORE['chapters'] = detect_chapters(new_ps)
        if len(DOC_STORE['chapters']) != _old_n:
            print('[chapter] 段数变了（%d → %d），章表重算：%d 章'
                  % (len(old_ps), len(new_ps), len(DOC_STORE['chapters'])),
                  flush=True)
    # rev ＝ **内容版本**。只有真变了才加一——心跳（她没动）不该让它走。
    # 这一条很要紧：剖面的 rev 就是拿它对账的，心跳每次加一的话，
    # 每次载入之后剖面都会被判成"已经旧了"。
    bumped = changed
    if bumped:
        DOC_STORE['rev'] = (DOC_STORE.get('rev') or 0) + 1
    for i, (_ln, h) in enumerate(paras):
        if new_ps[i][1]:
            _PARA_BY_HASH[str(h)] = new_ps[i][1]
    for no, t in removed:              # 删掉的正文也留着——prompt 里要说清"这些没了"
        if t:
            _PARA_BY_HASH.setdefault('*rm*' + str(no) + ':' + t[:24], t)
    if len(_PARA_BY_HASH) > _PARA_BY_HASH_CAP:
        keep = set(new_fp)
        for k in [k for k in _PARA_BY_HASH if k not in keep]:
            del _PARA_BY_HASH[k]

    # 全文只在**没有洞**的时候才重建——有洞还拼，就会悄悄变短一截。
    if not gaps:
        DOC_STORE['text'] = '\n\n'.join(t for _no, t in new_ps)
    elif total_chars:
        DOC_STORE['chars_synced'] = int(total_chars)

    SYNC.update({'rev': DOC_STORE['rev'], 'at': time.time(), 'gaps': len(gaps),
                 'gap_no': list(gaps), 'seeded': True,
                 'changed': {'at': p,
                             'removed': [{'no': no, 'text': t} for no, t in removed],
                             'added': [{'no': no, 'text': t} for no, t in added]}})
    if bumped:
        SYNC['last_change'] = SYNC['at']
        SYNC['drift'] = (SYNC.get('drift') or 0) + len(removed) + len(added)
        mark_fullread_stale()
    if gaps:
        print('[sync] ⚠️ %d 段没能定位到正文（段号 %s）——不猜，留洞'
              % (len(gaps), gaps[:12]), flush=True)
    return SYNC['changed']


def maybe_rebuild_profile():
    """她停笔、且正文已经漂得够远 → 重读一遍全文。

    **为什么不按漂移直接重建**：她正写着的时候插一次模型调用，既是打断，
    算出来的剖面也是"她写到一半"的样子——不如等她真的停下来。
    **为什么不是"一漂就降级、降级就重建"**：降级是零成本的，重建不是。
    """
    with _PROFILE_LOCK:
        st = PROFILE.get('status')
        prev_rev = PROFILE.get('rev') or 0
    if st in ('pending', 'building'):
        return False
    if prev_rev == (DOC_STORE.get('rev') or 0):
        return False                     # 没漂，不用重读
    n = len(DOC_STORE.get('paragraphs') or [])
    need = max(4, min(FRESH_DRIFT_MAX, max(1, n // 8)))
    if (SYNC.get('drift') or 0) < need:
        return False
    last = SYNC.get('last_change') or SYNC.get('at') or 0
    if time.time() - last < FRESH_QUIET_SEC:
        return False                     # 她还在写，等等
    print('[profile] 正文漂移 %d 段（阈值 %d）且已静 %d 秒 → 重读一遍'
          % (SYNC.get('drift') or 0, need, FRESH_QUIET_SEC), flush=True)
    start_profile()
    return True


def fmt_sync_changes(limit=6):
    """把变更集写成**信息层面**的说法。

    只报"第几段动了几个字"是结构判断——她不要那个。
    所以这里给的是：**哪些文字没了**（那里现在空了）、**哪些文字新写了**
    （她把什么写实了）。读信息的是模型自己，在**下一次伴写那一趟**里读，
    不为它单开一次模型调用。
    """
    ch = SYNC.get('changed') or {}
    rm, ad = ch.get('removed') or [], ch.get('added') or []
    if not rm and not ad:
        return ''
    out = []
    # ⚠️ rm/ad 里装的是 **dict**（{'no','text'}），不是 (no, text) 元组——
    #    写的时候按元组解包过一次，`no` 拿到的是字符串 'no'，`%d` 当场炸。
    for e in rm[:limit]:
        t = e.get('text') or ''
        if t:
            out.append('· 原来第 %d 段的位置上，这段文字**已经不在了**'
                       '（**这是旧稿，不是正文，别当成正文引用**）：%s'
                       % (e.get('no') or 0, t[:120] + ('…' if len(t) > 120 else '')))
    for e in ad[:limit]:
        t = e.get('text') or ''
        if t:
            out.append('· 第 %d 段是**新写的**（你上次通读时还没有）：%s'
                       % (e.get('no') or 0, t[:120] + ('…' if len(t) > 120 else '')))
    extra = max(0, len(rm) - limit) + max(0, len(ad) - limit)
    if extra:
        out.append('· 另外还有 %d 处改动' % extra)
    return '\n'.join(out)


def _terms(s):
    """极简中文切词：取 2-gram，供段落间重叠度比较。无第三方依赖。"""
    s = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', s or '')
    return set(s[i:i + 2] for i in range(len(s) - 1)) or set(s)


CTX_CLIP = 400          # 单个片段最多给多少字


def _clip_para(txt, limit=CTX_CLIP):
    """截到 limit 字，**并如实报出"截了"**。

    为什么必须标记：不标记，模型就把这截片段当成整段，于是"这一段到此为止"
    变成它自己脑补出来的一个事实——它可能据此判断"这里结束了/这里没有下文"，
    而真相只是我们没给它看。这属于**静默降级**（§四.12），是最坏的失败方式：
    出错的人（模型）不知道自己看到的是残缺的。

    反过来，标记出来是有用的：模型知道自己只看到局部，
    才可能在"证据不够"时选择 ⊘，而不是拿半段话凑一个说法。
    参照 scrivener-mcp 的滑窗标记 `[words 0-500/3200]`。
    """
    t = (txt or '').strip()
    if len(t) <= limit:
        return t, len(t), False
    return t[:limit].rstrip() + '…', len(t), True


def pick_context(cur, prev, topk=3):
    """在【已载入文档】中找出与当前段落最相关的几段——这是伴写看得到原文的根据。"""
    ps = DOC_STORE.get('paragraphs') or []
    if not ps:
        return []
    cur_terms = _terms(cur) | _terms(prev)
    if not cur_terms:
        return []
    scored = []
    for no, txt in ps:
        if txt.strip() == (cur or '').strip():
            continue
        t = _terms(txt)
        if not t:
            continue
        ov = len(cur_terms & t) / max(1, len(cur_terms))
        if ov > 0.06:
            scored.append((ov, no, txt))
    scored.sort(reverse=True)
    out = []
    for ov, no, txt in scored[:topk]:
        body, chars, clipped = _clip_para(txt)
        out.append({'no': no, 'text': body, 'score': round(ov, 3),
                    'chars': chars, 'clipped': clipped})
    return out


def fmt_ctx_para(p):
    """把一条上下文渲染进提示词。**章名 + 字数 + 是否截断**都给，
    这样模型手里的是"可回指的位置"，而不是一段不知来历的文字。

    连续窗口里光标所在的那一段会带 `here` 标记——它是锚点的一部分：
    模型得能在这一堆段里一眼看出**她在哪儿**。

    ⚠️ 这里原来写的是「第 12 段」。理由见 `doc_full`：**上下文里给什么坐标，
    模型就用什么坐标报位置**。所以认得出章就报章名；认不出（稿子里没有
    标题）才退回段号——那时候没有别的坐标可用，而它总得能指认某一段。
    """
    mark = '　**← 她就停在这一段**' if p.get('here') else ''
    sc = p.get('score')
    sc_txt = ('相关度 %.2f · ' % sc) if sc is not None else ''
    c = chapter_of(p.get('no'))
    where = ('〔第 %d 章 %s〕' % (c['no'], c['title'])) if c else ('第 %d 段' % p['no'])
    if p.get('clipped'):
        return ('· %s%s（%s本段共 %d 字，'
                '下面只是前 %d 字，**不是整段**）：%s'
                % (where, mark, sc_txt, p.get('chars', 0), CTX_CLIP, p['text']))
    return ('· %s%s（%s全 %d 字）：%s'
            % (where, mark, sc_txt, p.get('chars', 0), p['text']))


# ── 丙：连续上下文（换掉"字面挑片段"）─────────────────────────────
# 换掉 pick_context 的理由是实测出来的：挑片段省下的输入成本 ≈ 0
#   （输入 8 千字 1.0 秒 / 5 万字 4.4 秒 / 12 万字 3.7 秒——**输入长度几乎
#   不影响延迟**，慢的是模型写出来的字），
# 但丢掉的是**语序**，和"哪一段真的相关"这个判断本身。
# 碎片没有前后文，模型读不出"她刚写完什么、前面刚发生了什么"。
CTX_WIN_BEFORE = 8          # 光标前面给几段
CTX_WIN_AFTER = 4           # 光标后面给几段
DOC_INLINE_MAX = 90000      # 整篇直接内联的上限；超了就退回连续窗口


def context_window(cur, before=CTX_WIN_BEFORE, after=CTX_WIN_AFTER):
    """光标**周围连续的**若干段。代替 pick_context 在丙里的位置。

    和 pick_context 的关键差别有两条：
      ① 它是**连续的**——语序、前后因果都在；
      ② 它带着 `here` 标记——模型能一眼看出她在哪一段（锚定）。
    """
    ps = DOC_STORE.get('paragraphs') or []
    if not ps:
        return []
    no = find_para_no(cur)
    i = (no - 1) if no else len(ps)      # 段号从 1 起；定位不到就当"在最后"
    lo = max(0, i - before)
    hi = min(len(ps), i + 1 + after)
    out = []
    for k in range(lo, hi):
        body, chars, clipped = _clip_para(ps[k][1])
        out.append({'no': ps[k][0], 'text': body, 'chars': chars,
                    'clipped': clipped, 'here': (no is not None and ps[k][0] == no)})
    return out


def doc_full(max_chars=None):
    """整篇正文，**按章分段**。超上限返回 ('', 总字数) 让上层退回连续窗口。

    ⚠️ 这里原来给每一段都顶一个 `[12] ……` 的段号，注释说"给模型回指用"。
    2026-09-20 拿真模型验过它的后果：**模型在答复里也报段号**——
    "第 157 段末尾那句…"。而她的界面上根本不显示段号，`§1308` 这种行标
    对她只有困惑。**你在上下文里给什么坐标，它就用什么坐标报位置**；
    user 末尾无论怎么写"不要报行号"，都盖不过几千字正文里的 `[157]`。

    所以这里换掉：**只在章首标章名**，段与段之间空行隔开。
    它要指"章内某处"时，**引用原文字句**比报数字更准——那也是她认得出、
    一搜就能找到的说法（她认得自己写的字，不认得段号）。
    """
    ps = DOC_STORE.get('paragraphs') or []
    if not ps:
        return '', 0
    total = sum(len(t) for _, t in ps)
    try:
        cap = int(max_chars or DOC_INLINE_MAX)
    except Exception:
        cap = DOC_INLINE_MAX
    if total > cap:
        return '', total
    out = []
    for no, t in ps:
        c = chapter_of(no)
        if c and c['start'] == no:
            out.append('〔第 %d 章 %s〕\n%s' % (c['no'], c['title'], t))
        else:
            out.append(t)
    return '\n\n'.join(out), total


def anchor_block(anchor, text):
    """光标锚点块。前端已经把 ⟨这里⟩ 标好了，这里只做**长度保护**：
    她可能在一段几千字的中间停下，不能把那一段整块塞进来把锚点淹掉。"""
    a = (anchor or '').strip()
    if not a:
        # 老前端没送锚点：退回"她停下的那一段"，但**明说**段内位置未知。
        body, _chars, _clipped = _clip_para(text, 800)
        return ('（这一版前端没有送光标位置，我只能给你她停下的那一段，'
                '**段内位置未知**。）\n' + body)
    if len(a) > 2400:
        a = a[:1400] + '\n…（中间略）…\n' + a[-1000:]
    return a


def find_para_no(cur):
    """当前段落是文档里的第几段——给模型一个可回指的锚，避免它编段号。"""
    target = (cur or '').strip()
    if not target:
        return None
    for no, txt in (DOC_STORE.get('paragraphs') or []):
        if txt.strip() == target:
            return no
    # 退而求其次：当前段落是某段的开头（作者正在这一段里继续写）
    for no, txt in (DOC_STORE.get('paragraphs') or []):
        if txt.strip().startswith(target[:12]) and len(target) >= 12:
            return no
    return None


def next_para_info(cur):
    """光标**后面**那一段（已经写好的）＋后面还有几段。没有就返回 None。

    为什么要它：**写作不是线性的**——她可能先把结尾写完，再回头补中间。
    那时候光标后面早就躺着正文了，而原来的上下文只有【前一段】＋【当前段】，
    模型**完全不知道后面有东西**，于是会给出"接下来可以写…"——而那个"接下来"
    已经写好了。位置一旦告诉它，它才会谈"这一处"。
    这和前端送来的 `after_chars` 是同一件事的两面：那边决定**说什么**
    （见 v3/attention.py 的 RECONTEXT），这边决定**能看见什么**。

    ⚠️ 段落表是**载入时**的快照，她新写的段落不在里面。所以定位不到、
    或者后面已经没段了，就什么都不给——**不猜**。
    """
    ps = DOC_STORE.get('paragraphs') or []
    no = find_para_no(cur)
    if not no or no >= len(ps):
        return None
    body, chars, clipped = _clip_para(ps[no][1])   # 段号从 1 开始，ps[no] 即下一段
    return {'no': no + 1, 'text': body, 'chars': chars, 'clipped': clipped,
            'paras_after': len(ps) - no}


def fmt_next_para(np):
    """渲染【后一段】。和 fmt_ctx_para 一样给**章名**＋字数＋是否截断——
    **不许给一段不知来历、不知有多长的文字**。

    ⚠️ 这里原来写「第 N 段」。理由见 `doc_full`：上下文里给什么坐标，
    模型就用什么坐标报位置，而她要的是章名。"""
    c = chapter_of(np.get('no'))
    where = ('〔第 %d 章 %s〕' % (c['no'], c['title'])) if c else ('第 %d 段' % np['no'])
    if np.get('clipped'):
        return ('· %s（本段共 %d 字，下面只是前 %d 字，**不是整段**）：%s'
                % (where, np.get('chars', 0), CTX_CLIP, np['text']))
    return '· %s（全 %d 字）：%s' % (where, np.get('chars', 0), np['text'])


# ---------------------------------------------------------------- 记忆层（v3.8）
# 接这一层的目的只有两个：**调得到历史伴写文本**、**拿得住对全文的把握**，
# 好让这一次的搭话接得上上一次——也就是写作的连续性。
#   时间节点  memories/sessions/YYYY-MM-DD.md        每次伴写追加一条，append-only
#   任务节点  resources/<作品>/<part>/seg-*.md       文档逐段，后台灌
#   长期      resources/<作品>/<part>/.overview.md   全文剖面，**持久化**，跨会话可用
#
# 三条硬约束：
#   ① ov 不在就**整层跳过**，伴写照常。但必须打日志——静默降级是最坏的失败方式。
#   ② 语义召回是**补充不是替换**。`pick_context`（字面）继续决定"文档里有没有相关的东西"，
#      因为对照实验证明语义召回没有下限（60 次查询一次空都没返回），
#      拿它当"该不该沉默"的闸门会把 ⊘ 抹掉。
#   ③ 注入的一切都是"旧观察"，只许当位置事实用，不许念出来。
MEM = {'ok': False, 'work': '', 'part': 'part-01',
       'indexed': 0, 'total': 0, 'status': 'off', 'err': ''}
_MEM_LOCK = threading.Lock()
_MEM_MAX_SEG = 600          # 后台最多灌这么多段（≈0.5 秒/段，别把载入拖垮）
_MEM_MIN_CHARS = 40         # 过短的段不灌


_MEM_STORES = {}        # 工作区名 -> (store, 取到的时刻)。**按区分开缓存**


def _mem_store(ws=None):
    """取一个可用的记忆层；拿不到返回 None（调用方负责跳过）。带 1 小时缓存。

    `ws` 显式给定时用它，否则按 config.json 的 `workspace`（伴写的默认区 novel，
    = 现有的 maomao user，现有记忆原地不动）。**分区做在 OpenViking 的 user 层**，
    不是路径也不是 tag——理由见 workspaces.json。

    两个模式各用各的区，所以缓存必须**按区分开**，不能全局一个：
    否则先开了文学模式、切回伴写，拿到的还是文学区的 store。
    """
    if ws:
        key = ws
    else:
        key = (load_config() or {}).get('workspace') or ''
    now = time.time()
    hit = _MEM_STORES.get(key)
    if hit and now - hit[1] < 3600:
        return hit[0]
    try:
        import ov_memory
        name, user = ov_memory.resolve_workspace(key or None)
        s = ov_memory.OVStore(workspace=name)
        s.login()
    except Exception as e:
        if not ws:      # 只有默认区挂了才算伴写的记忆故障
            with _MEM_LOCK:
                MEM['status'] = 'error'
                MEM['err'] = '%s' % e
        print('[memory] 工作区「%s」不可用，跳过：%s' % (key or '(默认)', e), flush=True)
        return None
    _MEM_STORES[key] = (s, now)
    if not ws:
        with _MEM_LOCK:
            MEM['err'] = ''
            MEM['ws'] = name
            MEM['ws_user'] = user
    return s


def _mem_work_name(name):
    """作品名 → 记忆层目录名：去掉路径与扩展名。"""
    b = (name or '未命名').replace('\\', '/').split('/')[-1]
    b = re.sub(r'\.(md|txt|docx)$', '', b, flags=re.I).strip()
    return b or '未命名'


def mem_index_worker(store, work, part):
    """后台把文档逐段灌进任务节点。慢（≈0.5 秒/段），所以只在后台跑且有上限。"""
    ps = DOC_STORE.get('paragraphs') or []
    cand = [(no, t) for no, t in ps if len(t) >= _MEM_MIN_CHARS][:_MEM_MAX_SEG]
    with _MEM_LOCK:
        MEM['total'] = len(cand)
        MEM['indexed'] = 0
        MEM['status'] = 'indexing'
    for i, (no, t) in enumerate(cand, 1):
        try:
            store.write_segment(work, part, 'seg-%04d' % no, t)
        except Exception as e:
            with _MEM_LOCK:
                MEM['status'] = 'error'
                MEM['err'] = '灌段失败：%s' % e
            print('[memory] 灌段失败，停止：%s' % e, flush=True)
            return
        with _MEM_LOCK:
            MEM['indexed'] = i
        if i % 50 == 0:
            print('[memory] 已灌 %d/%d 段' % (i, len(cand)), flush=True)
    with _MEM_LOCK:
        MEM['status'] = 'ready' if cand else 'empty'
    print('[memory] 灌段完成：%d 段' % len(cand), flush=True)


def _looks_like_dir_overview(t):
    """这份东西是**记忆库自己生成的目录摘要**，不是我们通读出来的剖面。

    实测（2026-09-20）：`resources/<work>/<part>/.overview.md` 这个路径上，
    躺着的是 OpenViking 的 SemanticProcessor 自动生成的一份**占位摘要**——
    开头是 YAML 头（`generated_by:` / `content_write`），正文只有一句
    `[Directory overview is not ready]`，284 字。而 `mem_save_profile()`
    往同一个路径写时被服务端拒过（`400 cannot create generated abstract
    overview directly`），所以它未必已经被我们的剖面覆盖。

    取回来时如果不认，它就会被当成"上次的全篇把握"塞进 prompt 的
    【全文剖面】块——模型拿到的所谓记忆，其实是一句"还没准备好"。
    **宁可不给，也不能给一句假话**：没有剖面不过是少一层背景，
    给一份假的会让它以为自己读过。
    """
    t = (t or '').strip()
    if not t:
        return False
    return ('Directory overview is not ready' in t
            or 'generated_by:' in t
            or 'SemanticProcessor' in t)


def mem_on_doc_load():
    """载入文档后跑（后台）：① 取回上次的全篇把握 ② 后台灌段。"""
    name = _mem_work_name(DOC_STORE.get('name'))
    part = MEM['part']
    store = _mem_store()
    if not store:
        return
    try:
        store.ensure_tree(name)
    except Exception as e:
        print('[memory] 建树失败：%s' % e, flush=True)
        return
    with _MEM_LOCK:
        MEM['ok'] = True
        MEM['work'] = name
        MEM['status'] = 'ready'
        MEM['err'] = ''
    # ① 上次的全篇把握：有的话立刻用上，剖面后台重算好了会替掉它
    try:
        old = (store.read('%s/resources/%s/%s/.overview.md'
                          % (store.root, name, part)) or '').strip()
    except Exception:
        old = ''
    if old and _looks_like_dir_overview(old):
        # 见 _looks_like_dir_overview：那里躺着的是记忆库自己的目录占位摘要。
        # 当真剖面用，等于每轮都告诉模型"你上次的全篇把握是：还没准备好"。
        print('[memory] 那个位置是目录占位摘要（不是剖面），这次不用它', flush=True)
        old = ''
    if old and not (PROFILE.get('text') or '').strip():
        with _PROFILE_LOCK:
            PROFILE.update({'status': 'ready', 'text': old, 'built_at': 0,
                            'err': '', 'from_memory': True,
                            'doc_chars': len(DOC_STORE.get('text') or '')})
        print('[memory] 取回上次的全篇把握 %d 字' % len(old), flush=True)
    # ② 后台灌段
    threading.Thread(target=mem_index_worker, args=(store, name, part),
                     daemon=True).start()


def mem_save_profile(text):
    """剖面算出来后**持久化**——"全文把握"能跨会话连续，靠的就是这一步。"""
    if not (text or '').strip():
        return
    store = _mem_store()
    if not store:
        return
    try:
        store.write_overview(MEM['work'] or _mem_work_name(DOC_STORE.get('name')),
                             MEM['part'], text)
        print('[memory] 全篇把握已存 %d 字' % len(text), flush=True)
    except Exception as e:
        print('[memory] 存剖面失败：%s' % e, flush=True)


def mem_record(text, cards):
    """每次伴写之后追加一条（时间节点，append-only）。**历史伴写文本**由此而来。"""
    store = _mem_store()
    if not store:
        return
    try:
        lines = ['%s ｜ 她停在：「%s…」'
                 % (time.strftime('%H:%M'), (text or '').strip()[:24])]
        for c in (cards or [])[:3]:
            body = (c.get('body') or '').strip().replace('\n', ' ')
            if body:
                lines.append('  · [%s] %s' % (c.get('layer') or '?', body[:120]))
        store.append_session(time.strftime('%Y-%m-%d'), '\n'.join(lines))
    except Exception as e:
        print('[memory] 记一条伴写失败：%s' % e, flush=True)


def mem_recall(text):
    """装配注入块：长期判断 + 最近几次的伴写 + 语义召回（先近后远，封顶 5 条）。"""
    with _MEM_LOCK:
        if not MEM['ok']:
            return ''
    store = _mem_store()
    if not store:
        return ''
    try:
        return store.memory_block(text, work=MEM['work'], part=MEM['part'], limit=5)
    except Exception as e:
        print('[memory] 召回失败：%s' % e, flush=True)
        return ''


# ---------------------------------------------------------------- 离线规则引擎
# 不发网络请求。目的不是"像模型"，而是把 A_adm / 双证门槛 / 四档沉默
# 这些机制用可预期的规则演出来，供界面与交互的验证。

def offline_engine(text, corpus, section):
    """返回伴写卡片列表（可能为空＝⊘₀ 不说话）"""
    cards = []
    t = (text or '').strip()
    if not t:
        return cards

    # 1) 互证：锚点词命中 >=2 处 → 双证成立（实线）；==1 处 → 虚线候选
    for a in corpus.get('anchors', []):
        term = a.get('term', '')
        if not term or term not in t:
            continue
        hits = a.get('hits', [])
        if len(hits) >= 2:
            ev = '；'.join('§%s（%s·L%s）' % (h['sec'], h['part'], h['line']) for h in hits[:3])
            cards.append({
                'type': 'relate',
                'level': 'solid',
                'title': '互证 · 双证成立',
                'body': '你这段写的「%s」，档案里另有 %d 处：%s。要看吗？' % (term, len(hits), ev),
                'evidence': [{'ref': '§%s（%s·L%s）' % (h['sec'], h['part'], h['line']),
                              'text': h.get('text', '')} for h in hits],
            })
        elif len(hits) == 1:
            h = hits[0]
            cards.append({
                'type': 'relate',
                'level': 'dashed',
                'title': '候选 · 证据不足',
                'body': '「%s」另有一处：§%s（%s·L%s）。只有一处证据，尚未成立——'
                        '我不把它算作互证。' % (term, h['sec'], h['part'], h['line']),
                'evidence': [{'ref': '§%s（%s·L%s）' % (h['sec'], h['part'], h['line']),
                              'text': h.get('text', '')}],
            })

    # 2) 冲突：命中冲突词 → 并置，不裁定
    for c in corpus.get('conflicts', []):
        if any(k in t for k in c.get('keys', [])):
            sides = '／'.join('%s（%s 处 · §%s）' % (s['form'], s['count'], s['sec'])
                              for s in c.get('sides', []))
            cards.append({
                'type': 'conflict',
                'level': 'solid',
                'title': '来源冲突 · 不裁定',
                'body': '%s 都出现过：%s。我不裁定哪个是对的——这是你的文本，不是我的。'
                        % (c.get('label', '两种写法'), sides),
                'evidence': [{'ref': '§%s' % s['sec'], 'text': '%s · %s 处'
                              % (s['form'], s['count'])} for s in c.get('sides', [])],
            })

    # 3) 缺口：段落里出现未在语料中登记的专名 → 描述缺口，不猜成因
    unknown = [w for w in re.findall(r'「([^」]{1,12})」', t)
               if w and not any(w == a.get('term') for a in corpus.get('anchors', []))]
    for w in unknown[:2]:
        cards.append({
            'type': 'gap',
            'level': 'dashed',
            'title': '缺口 · 不猜成因',
            'body': '这里提到的「%s」，档案里没有对应记载。'
                    '我不判断它是还没出现，还是你有意不写——这两种我不区分。' % w,
            'evidence': [],
        })

    # 4) 当前节若为空缺节 → 主动声明沉默（⊘₀）
    sec = next((s for s in corpus.get('sections', []) if str(s.get('sec')) == str(section)), None)
    if sec and sec.get('kind') in ('STUB', 'THIN') and not cards:
        cards.append({
            'type': 'withhold',
            'level': 'muted',
            'title': '⊘₀ · 主动沉默',
            'body': '这一节（§%s，%s，%s 字）我没有任何可核的依据，所以我不说话。'
                    '（我没有在思考，我是真的没有。）'
                    % (sec.get('sec'), sec.get('kind'), sec.get('chars')),
            'evidence': [],
        })

    return cards[:4]


LAYER_NAME = {
    'A': '思路性 · 回映不命名',
    'B': '结构性 · 指位置不给方案',
    'C': '情节性 · 核自洽不预测',
    '⊘': '主动沉默',
}

MODE_NAME = {
    'P': '问题驱动 · 给方向不给成品',
    'M': '混合 · 候选段落待接',
    'S': '故事驱动 · 候选段落待接',
}


def split_layer(content):
    """从模型输出里拆出层标记 [A]/[B]/[C]/[⊘] 与正文。
    模型偶尔不写标记 → 退回无标记，正文原样返回。"""
    import re as _re
    s = (content or '').strip()
    m = _re.match(
        r'^\s*[\[【]?\s*([ABC⊘]|SILENT)\s*[₀₁₂₃0-9]?\s*[\]】]?\s*'
        r'[｜|、:：\-\-)）.]?\s*', s)
    if m:
        tag = m.group(1)
        if tag == 'SILENT':
            tag = '⊘'
        return tag, s[m.end():].strip() or s
    return '', s


def split_verdict(content):
    """读丙的第一行判决：`[说]` / `[不说]`。

    返回 ('yes' | 'no' | '', 剩下的正文)。

    一条纪律：**读不出来就返回原文，不许因为格式没写对就把人家的话吞了**。
    模型偶尔会忘了写这一行——那时候它的正文照旧有用，不能丢。
    """
    import re as _re
    s = (content or '').strip()
    # `不说` 必须排在 `说` 前面：alternation 从左往右取，反过来会把
    # 「[不说]」切成 `不说` 的否定被吃掉、只剩一个"不"当正文。
    m = _re.match(r'^\s*[\[【]?\s*(不说|说|NO|YES|no|yes)\s*[\]】]?\s*'
                  r'[·、,，:：\-—]?\s*', s)
    if not m:
        return '', s
    v = 'no' if m.group(1) in ('不说', 'NO', 'no') else 'yes'
    return v, s[m.end():].strip()


def full_doc(text, recall='', whole=True, max_chars=None):
    """甲 / 乙 / 丙共用的上下文块：整篇或**连续窗口** ＋ 剖面 ＋ 记忆。

    `whole=True`（乙/丙）给整篇；`whole=False`（甲）给光标周围连续的一段。

    和原来的做法比，改了三处，逐条对应她提出的那个问题：

      · 预匹配的锚点/冲突清单 —— **不给**。那是"引擎替你找题目"，
        也是模型漂向"全篇缺口"最直接的诱因。要看全篇，它自己看。
      · 字面挑的 3 个片段 —— 换成**连续**窗口 / 整篇。
        实测输入长度几乎不影响延迟（8 千字 1.0 秒、5 万字 4.4 秒、
        12 万字 3.7 秒），挑片段省下的成本约等于零。
      · 剖面 —— **降级**。原来写的是"落在你记下的某一条上，那可以说"；
        现在连这句许可也撤掉，只留"背景"这一层身份。
        理由：模型能自己读整篇，不需要我们先嚼一遍再喂。
        剖面剩下的唯一价值是**跨会话的记忆**（这一篇大致是什么质地）。
    """
    if not DOC_STORE.get('text'):
        return ('【未载入文档】她还没有把稿子载进来，所以你对这一篇一无所知——'
                '除了下面那一处本身。**不要假装你读过全篇。**\n')
    m = doc_meta()
    if whole:
        full, total = doc_full(max_chars=max_chars)
        if full:
            part = ('【整篇（按章分段，`〔第 N 章 标题〕` 是章标记）】%s'
                    '（%d 字 / 共 %d 段）\n%s\n'
                    % (m['name'], m['chars'], m['paragraphs'], full))
        else:
            win = context_window(text)
            body = '\n'.join(fmt_ctx_para(p) for p in win) or '（没定位到段落）'
            part = ('【整篇太长（%d 字），下面给的是**光标周围连续的一段**】'
                    '%s（%d 字 / 共 %d 段）\n%s\n'
                    % (total, m['name'], m['chars'], m['paragraphs'], body))
    else:
        win = context_window(text)
        body = '\n'.join(fmt_ctx_para(p) for p in win) or '（没定位到段落）'
        part = ('【光标周围**连续**的一段（每段前面的 `〔第 N 章 标题〕` 是它所在的章——'
                '**那是给你认路的，别报给她**）】'
                '%s（%d 字 / 共 %d 段）\n%s\n'
                % (m['name'], m['chars'], m['paragraphs'], body))

    _fr = fullread_block(max_chars=1800)
    _notes = fullread_notes_for(text, 1000)
    if _notes:
        _fr += '\n\n' + _notes
    if _fr:
        part = _fr + '\n\n' + part
    if SYNC.get('gaps'):
        part += ('（⚠️ 有 %d 段没能跟上（第 %s 段），你手里**不是完整的**。'
                 '凡是要指具体某处的，一律以眼前这一段为准。）\n'
                 % (SYNC['gaps'],
                    '、'.join(str(x) for x in (SYNC.get('gap_no') or [])[:12])))
    prof = (PROFILE.get('text') or '').strip()
    if prof:
        stale = (PROFILE.get('rev') or 0) != (DOC_STORE.get('rev') or 0)
        head = '【全文剖面 — 你更早时候通读整篇记下的观察】'
        if stale:
            head += '（⚠️ 正文在你记下它之后又变过。）'
        part += ('\n%s\n%s\n'
                 '（这是**你自己过去的观察**。丙之下它只是背景：'
                 '**不许念出来、不许复述、不许拿它当结论、更不许拿它当题目**。'
                 '它唯一的用处是让你读到这一处时，心里知道这一篇大致是什么质地。'
                 '要指任何具体的地方，一律以眼前的正文为准。）\n' % (head, prof))
    mem = mem_recall(text)
    if mem:
        part += ('\n【记忆 — 你上一次留下的观察】\n%s\n'
                 '（同样是旧观察：**不要念出来、不要复述**；只许当位置事实用；'
                 '与眼前这一段冲突时，以眼前这一段为准。）\n' % mem)
    if recall:
        part += ('\n【记忆库 — 前面几个 Part 提炼出来的固定事实】\n%s\n'
                 '（只许当位置事实用来核对前后是否矛盾，**不要复述、不要念出来、'
                 '不要当成这一处的结论**。）\n' % recall[:3000])
    return part


def call_model(cfg, skill, text, section, corpus_ctx, prev='', ctx_paras=None,
               attn_hint='', attn=None, ban_opening='', rewrite='', mode=None,
               recall='', delegate=False, anchor='', attn_desc='',
               full_ctx=False):
    """模型自主伴写：给出原文上下文（作者载入的文档 + 相关片段），
    由模型按 WORKFLOW.md 自己判层、自己决定说什么。
    失败时抛出，由上层降级。

    `recall` 是浏览器侧"文学记忆库"手动召回的那一段（只挂在这一次请求上，
    用完即弃）。它和上面 ov 的 mem_recall 是**两回事**：那边是流水账式的历史，
    这边是从写过的 Part 里提炼出来的固定事实（角色/伏笔/设定）。
    两者的护栏是同一条——都只许当位置事实用，不许念出来。

    **两个轴是分开的**（这一点很容易混，所以单列）：

      · `full_ctx=True`（乙 / 丙）——**上下文形态**：整篇 / 连续窗口，
        替代"字面挑 3 个片段"。理由见 _delegate_doc。
      · `delegate=True`（丙）——**说话权**：说不说交给模型。
        只有丙才开；甲/乙仍是规则拦（在 /api/cowrite 里提前返回）。

    所以乙＝`full_ctx=True, delegate=False`，丙＝两个都 True。
    `anchor` 是前端标好的光标位置图，`attn_desc` 是纯事实的状态说明。
    """
    ctx_paras = ctx_paras or []
    corpus = load_corpus()
    t = (text or '').strip()
    matched_anchors = []
    matched_conflicts = []
    match_info = ''
    # 1) 引擎预计算：作者文本命中了哪些锚点/冲突
    #    **整篇上下文下整块跳过**——这是"预先结构化"最集中的一处，
    #    也是模型漂向"全篇缺口"最强的信号源。
    #    那一类东西只该在**她开口要**的时候才给。
    if not full_ctx:
        for a in corpus.get('anchors', []):
            term = a.get('term', '')
            if term and term in t:
                matched_anchors.append({
                    'term': term,
                    'hits': ['§%s（%s）' % (h['sec'], h['part']) for h in a.get('hits', [])],
                    'hit_count': len(a.get('hits', [])),
                })
        for c in corpus.get('conflicts', []):
            if any(k in t for k in c.get('keys', [])):
                matched_conflicts.append({
                    'label': c.get('label', ''),
                    'sides': ['%s（%s 处）' % (s['form'], s['count']) for s in c.get('sides', [])],
                })

    # 2) 构建给模型的上下文：语料库 + 预计算匹配结果
    match_info = ''
    if matched_anchors:
        match_info += '\n\n【引擎预匹配结果 — 作者文本中出现的锚点】\n' + '\n'.join(
            '· 「%s」命中 %d 处：%s' % (ma['term'], ma['hit_count'], '、'.join(ma['hits']))
            for ma in matched_anchors)
    if matched_conflicts:
        match_info += '\n\n【引擎预匹配结果 — 作者文本中出现的冲突】\n' + '\n'.join(
            '· %s：%s' % (mc['label'], '／'.join(mc['sides']))
            for mc in matched_conflicts)
    if not matched_anchors and not matched_conflicts:
        match_info += '\n\n【引擎预匹配结果 — 作者文本未命中任何锚点或冲突条目】'

    # ---- 文档上下文（作者现场载入的原文；若未载入则退回预置语料，向后兼容）----
    has_doc = bool(DOC_STORE.get('text'))
    if anchor:
        # ---- 甲 / 乙 / 丙：位置前置的那一套，见 full_doc 的说明 ----
        # 有锚点就说明前端是新版；老前端（不送锚点）走下面的原路径。
        doc_part = full_doc(text, recall, whole=full_ctx,
                            max_chars=max(4000, providers.input_budget(cfg) - 4000))
    elif has_doc:
        m = doc_meta()
        doc_part = '【已载入文档】%s（%d 字 / 共 %d 段）\n' % (m['name'], m['chars'], m['paragraphs'])
        # §49：同步没跟上的那些段＝**你手里不是完整的一份**。不喊一声，
        # 模型会照旧凭"我记得全篇"下判断——那正是要治的毛病换了张脸回来。
        if SYNC.get('gaps'):
            doc_part += ('（⚠️ 有 %d 段没能跟上（第 %s 段），你手里**不是完整的**。'
                         '凡是要指具体某处的，一律以眼前这一段为准；'
                         '**不要**凭"我记得全篇"说话。）\n'
                         % (SYNC['gaps'],
                            '、'.join(str(x) for x in (SYNC.get('gap_no') or [])[:12])))
        if ctx_paras:
            doc_part += '\n【文档中与当前段落相关的原文片段】\n' + '\n'.join(
                fmt_ctx_para(p) for p in ctx_paras)
        else:
            doc_part += '\n（文档中暂未找到与当前段落相关的其他片段。）\n'
        # 全文剖面：**这是治「盲人摸象」的那一味药**。
        # 只给相关片段，模型就只看得到眼前这一处；给了剖面，它才知道
        # 整篇的调性是什么、哪些东西在反复出现、哪两处已经构成呼应。
        prof = (PROFILE.get('text') or '').strip()
        if prof:
            # §49：剖面绑着"它读的是哪一版"。正文动过之后，这份判断**不再成立**
            # 到"可以照着说"的程度——但它仍然是**旧观察**，比没有强。
            # 所以不删，**降级**：把许可（"落在某一条上那可以说"）撤掉。
            stale = (PROFILE.get('rev') or 0) != (DOC_STORE.get('rev') or 0)
            if stale:
                doc_part += ('\n【全文剖面 — 你更早时候通读整篇记下的判断】\n%s\n'
                             '（⚠️ **这份判断已经旧了**：你记下它之后，正文又变过。'
                             '它只当**背景**用——用来知道这篇大致是什么质地，'
                             '**不许拿它当结论、不许照它说"你这里呼应了前文"**。'
                             '凡是要具体指某处的，一律**以你眼前这一段和下面的'
                             '「正文变了」为准**。）\n' % prof)
            else:
                doc_part += ('\n【全文剖面 — 你自己通读整篇后记下的判断】\n%s\n'
                             '（这是你自己的旧观察，用来自我校正这一处的读法。'
                             '**不要把它念出来、不要复述、不要拿它当结论**；'
                             '但如果这一处正好落在你记下的某一条上，那可以说。'
                             '没落在上面，就以你眼前这一段为准。）\n' % prof)
        # §49 变更叙事：**自你上次通读以来，正文哪里变了。**
        # 它存在的理由只有一个：让模型自己**在信息上**校准这一处的读法
        # （她把什么写实了、哪里现在空了），**不是**让它去谈"你改了结尾"。
        # 所以她选的是"只用于自我校正"——许可没有跟着一起放大。
        chg = fmt_sync_changes() if DOC_STORE.get('para_fp') else ''
        if chg:
            doc_part += ('\n【正文自你上次通读以来变了（这些是你没读过的新情况）】\n%s\n'
                         '（你自己默读一遍，**只用来判断你接下来那句话还成不成立**：'
                         '有没有哪一条你本来要依据的信息**已经不在了**，'
                         '有没有哪一处现在**已经不空了**。'
                         '**不许把它说出来、不许复述、不许评价她改了什么、'
                         '不许建议她补什么、不许把上面那些旧稿当成正文引用**'
                         '——她从没告诉你她改了东西，你也不该表现出"我一直盯着"。）\n'
                         % chg)
        # 记忆层（v3.8）：历史伴写 + 全篇把握的持久化版本 + 语义召回。
        # 它**不替换**上面的 ctx_paras——字面召回决定"文档里有没有相关的东西"
        # （语义召回没有下限，见对照实验），记忆只负责把字面看不见的回声补进来。
        # ov 不在时 mem_recall 返回空，这里就什么都不加，伴写照常。
        mem = mem_recall(t)
        if mem:
            doc_part += ('\n【记忆 — 你自己上一次留下的观察】\n%s\n'
                         '（同样是旧观察：**不要念出来、不要复述**；只许当位置事实用。'
                         '它和上面的剖面、和眼前这一段冲突时，以眼前这一段为准。）\n'
                         % mem)
    else:
        doc_part = '【未载入文档】当前使用预置语料结构：\n' + (corpus_ctx or '') + match_info

    if has_doc and not anchor:
        _fr = fullread_block(max_chars=1600)
        _notes = fullread_notes_for(t, 800)
        if _notes:
            _fr += '\n\n' + _notes
        if _fr:
            doc_part = _fr + '\n\n' + doc_part

    if recall:
        # 截断放在这里而不是入口：召回块是她按一次按钮才给一次的，
        # 理论上不该超长，但记忆库攒久了会长——宁可砍掉尾巴，别把整段上下文撑爆。
        doc_part += ('\n【记忆库 — 前面几个 Part 提炼出来的固定事实】\n%s\n'
                     '（这些是自己提炼的旧记录：只许当位置事实用来核对前后是否矛盾，'
                     '**不要复述、不要念出来、不要当成这一处的结论**；'
                     '与眼前这一段冲突时，以眼前这一段为准。）\n'
                     % recall[:3000])

    # ── 光标**后面**那一段：**这是"她不在文末"唯一能让模型看见的证据** ──
    # 没有它，模型只知道自己手里这一段和它前面那段，会理所当然地以为"后面还是空的"，
    # 于是拿"接下来写什么"当答案——而她可能是先写完结尾再回头补中间的，
    # 那个"接下来"早就写好了。
    #
    # 为什么**不**并进 doc_part：doc_ctx 末尾有一条"如果你在其中认出了某一处的机关，
    # 那可以说"（那是给**已完成正文**的许可），和这里"不要评价它"正好相反。
    # 两条叠在同一个块里，后一条会盖掉前一条。所以它单独一段、紧接当前段落下。
    nxt = next_para_info(text) if (has_doc and not full_ctx) else None
    if nxt:
        after_ctx = ('【光标**后面**那一段（已经写好的，不是空的）】\n%s\n'
                     '（注意：她在这一篇里**不是顺着往下写的**——上面这一段就在她光标'
                     '后面，早就写好了。**不要建议她写这一段、不要把它接上、'
                     '不要评价它**；它只用来让你知道"这不是第一次写到这里"。'
                     '后面还有 %d 段。）' % (fmt_next_para(nxt), nxt['paras_after']))
    else:
        after_ctx = ''

    wf = load_workflow()
    system = skill + ('\n\n---\n\n' + wf if wf else '')

    cur_no = find_para_no(text)
    pos = '' if section in (None, '', '—') else str(section)
    # 章：这一段落在哪一章。给模型一个**她的坐标系**——
    # 只有段号时它只能回 `§1308`，那是行标不是人话（2026-09-20 她报的）。
    cur_ch = chapter_of(cur_no) if cur_no else None
    if cur_ch:
        pos = (pos + ' / ' if pos else '') + '第 %d 章「%s」' % (cur_ch['no'], cur_ch['title'])
    if cur_no:
        pos = (pos + ' / ' if pos else '') + '文档第 %d 段' % cur_no
    chidx = chapter_index_text()
    # 位置怎么报。**这条规则必须送到每一条路径上**——包括丙走的 v3
    # （system 与 user 末尾各一份：system 是"规矩"，末尾是"提笔前最后一句"）。
    # 2026-09-20 之前它只挂在基线组装里，而丙默认走 v3，于是规则整条丢失：
    # 章目录塞进了事实块，却没有一句要求它用章名，模型就照旧报 §1308。
    # **给了坐标系，不等于要求用坐标系。**
    #
    # 后来又发现一句禁令还不够：把上下文里的段号标注全拆干净之后，它仍然
    # 报「第 157 段」，而且**数得完全准确**——整篇正文摆在那儿，它自己就能数。
    # 所以这里两样一起给：**禁令**＋**替代手段**（引原句）。
    # 只禁不给，它会继续用那个唯一的坐标。
    # ⚠️ 措辞里不举任何具体例子（连反例都不举）：见 v3/policy.py REWRITE 那段
    # 注释——写进去的例子，三次里有两次被当成模板照抄（§四.1 第五次应验）。
    loc_rule = ('【位置怎么报】\n'
                '· 说位置用**章名**。\n'
                '· **答复里不要出现任何编号**——段落编号、行号、数字序号，'
                '一个都不要。她界面上没有这种东西，它不会帮她找到地方，'
                '只会让她对不上自己看到的位置。**别以为报编号更精确**：她读不出来。\n'
                '· 要指**章里的某一处**，就把那处的**原文引出来**——'
                '引原句就是你要的定位方式，不需要再加编号。\n'
                '· 章名只能从上面那份章目录里取，不要自己编章名或章号。\n'
                if chidx else
                '引用位置时只能用上面标注的段号，不要自己编段号。\n')
    user = (
        '【当前位置】%s\n'
        '【作者刚刚停下的段落】\n%s\n'
        '%s'
        '%s'
        '%s\n'
        '---\n'
        '请严格按 WORKFLOW 执行：\n'
        '第 1 步判定作者现在在哪一层（A 思路性 / B 结构性 / C 情节性）；\n'
        '第 2 步走该层对应的分支；第 3 步保持简洁（3 句以内）；\n'
        '第 4 步过三条自检；判不出或无可依据，走第 5 步主动声明沉默。\n'
        '依据只能来自上面给出的文本。文本里没有的，就说你不知道。\n'
        '不要续写正文，不要建议作者接下来写什么，不要预测情节走向。\n'
        '【输出形态】第一行开头写层标记 [A]/[B]/[C]/[⊘]，标记后直接接正文。\n'
        '禁止输出步骤标题、判定过程、自检清单、字数统计，禁止复述原文。\n'
        '%s'
        '**重要：不要使用任何工具调用语法（如 <invoke>、function call 等），'
        '直接用自然语言回答。**'
        % (pos or '未标注', text,
           ('\n' + chidx + '\n') if chidx else '',
           ('\n【前一段（语境）】\n%s\n' % prev) if prev else '',
           ('\n' + after_ctx + '\n') if after_ctx else '',
           '\n' + doc_part + '\n' + loc_rule)
    )
    # ---- v3：用「模式 + 禁令」替换整条策略与 user 组装 ----
    v3_meta = None
    if USE_V3 and _v3:
        try:
            _policy_mod = _v3[0]
            # mode 由**作者在网页上选**（P/M/S 按钮）；为 None 才让分类器猜。
            # 2026-09-16 起默认不再信分类器：两套语料对照下来 AUC 0.523，
            # 等于抛硬币（详见《工程路径与技术回顾》§四.18）。
            _mode = mode if mode in ('P', 'M', 'S') else None
            system, v3_meta = _policy_mod.build_system(text, mode=_mode,
                                                       delegate=delegate,
                                                       coord=loc_rule)
            if v3_meta is not None:
                v3_meta['mode_source'] = '作者指定' if _mode else '分类器猜测'
            user = _policy_mod.build_user(text, prev, doc_part, hint=attn_hint,
                                          ban_opening=ban_opening,
                                          rewrite=rewrite,
                                          after_ctx=after_ctx,
                                          anchor=anchor, facts=attn_desc,
                                          delegate=delegate, coord=loc_rule)
        except Exception as e:
            print('[v3] 组装失败，本次走基线：%s' % e)
            v3_meta = None
    # v3 的 build_user 已经把重写指令放在正确位置；基线才需要自己补在最后
    if rewrite and not v3_meta:
        user = user + '\n\n' + rewrite

    if v3_meta:
        samp = _v3[0].sampling()
    else:
        samp = None

    # 协议细节（拼 URL / 请求头 / 载荷 / 解析）全在 providers 里，
    # 这里只负责把"该用什么参数"算出来，以及把"没有"接成 ⊘。
    try:
        content = providers.chat(
            cfg, system, user,
            temperature=float((samp or {}).get('temperature', 0.3)),
            max_tokens=int((samp or {}).get('max_tokens', 2048)),
            timeout=180,
            thinking=str((samp or {}).get('thinking',
                                          cfg.get('thinking', 'disabled'))))
    except providers.EmptyReplyError as e:
        # 连上了、也回了，只是没有正文：不编造，按工作流第 5 步主动声明沉默
        content = '⊘ 我没能给出可依据的回应（%s）。这是真的没有，不是在思考。' % e

    # 丙：先读第一行的判决（[说] / [不说]），再拆层标记。
    # 顺序不能反——split_layer 会把 `[说]` 当噪音，但 `[不说]` 会被它
    # 认成 ⊘ 那一类标记，于是"沉默"与"层标记"混在一处就分不开了。
    if delegate:
        _v, _rest = split_verdict(content)
        if _v == 'no':
            # 采集：探针到点而判为不出声。原实现直接 return，一个字都不留，
            # 于是论文说的"沉默的精确率与召回一个数都给不出"是**代码事实**。
            # 埋点**只旁挂、不介入**：包在 try 里，采集失败绝不能挡住这张卡。
            _probe_eid = None
            if _probe is not None:
                _snap = _probe_prof_snapshot()
                try:
                    _rec = _probe.silence(
                        _rest, attn=attn, v3_meta=v3_meta, mode=mode, cfg=cfg,
                        prof_stale=_snap.get('prof_stale'),
                        prof_ver=_snap.get('prof_ver'),
                        prof_status=_snap.get('prof_status'),
                        text_len=len(text or ''),
                        text_head=(text or '')[:200],
                    )
                    _probe_eid = (_rec or {}).get('event_id')
                except Exception as _pe:
                    print('[probe] 沉默埋点失败（不影响出卡）：%s' % _pe)
            # P0-1：丙档沉默也要落进 samples.jsonl（arm = v3-delegate-no）。
            # ⚠ 为什么这条与 probe.silence() **不是重复**：
            #   probe.jsonl 记的是"探针到点而判为不出声"这个**时刻**（含理由、
            #   剖面快照、attn信号）；samples.jsonl 记的是**样本**（含 arm、
            #   initial_mode、mode_score），而 diagnose.py 的门槛判定与
            #   形态层检验的因变量构造读的都是 samples.jsonl。
            #   两条通道不通 ⇒ 召回率的分母永远缺一格。
            # 同一条纪律：失败不介入，绝不能挡住出卡。
            if _v3 and _v3[1] is not None:
                try:
                    _rec_no = {
                        'text_id': 'live-%s' % time.strftime('%m%d%H%M%S'),
                        'arm': 'v3-delegate-no',
                        'initial_mode': (v3_meta or {}).get('mode'),
                        'mode_source': (v3_meta or {}).get('mode_source', '?'),
                        'mode_score': (v3_meta or {}).get('score'),
                        'rules_applied': '%s-strict' % ((v3_meta or {}).get('mode')
                                                      or '?'),
                        # output_preview 留空是**刻意的**：它是沉默，没有正文。
                        # 诊断脚本靠这个字段把「出声」与「沉默」分开，
                        # 所以沉默记录必须有这个键、值为空。
                        'output_preview': '',
                        'reason': (_rest or '')[:200],
                        'spoke': False,
                    }
                    if attn:
                        _rec_no['attention_state'] = attn['state']
                        _rec_no['signals'] = attn['signals']
                    _v3[1].record(_rec_no)
                except Exception as _de:
                    print('[p0-1] 丙档沉默埋点失败（不影响出卡）：%s' % _de)
            return [{
                'type': 'withhold', 'level': 'muted', 'layer': '⊘',
                'title': '⊘ · 它看过了，没说话',
                'body': _rest or '（它没写理由。）',
                'evidence': [], 'verdict': 'no',
                # 回放要靠这个 id 指回这次事件；没有它标注就落不到那一行
                'probe_event_id': _probe_eid,
            }]
        if _v == 'yes':
            content = _rest
        # _v == ''（它忘了写这一行）→ 当它说了，正文照旧用，**不吞**。
    layer, body = split_layer(content)

    card = {
        'type': 'model',
        'level': 'solid',
        'title': LAYER_NAME.get(layer, '伴写 · 真实模型'),
        'layer': layer,
        'body': body,
        'evidence': [],
    }
    if v3_meta:
        card['layer'] = v3_meta['mode']          # P / M / S
        card['title'] = MODE_NAME.get(v3_meta['mode'], '伴写')
        card['mode_score'] = v3_meta['score']
        card['rule_set'] = '%s-%s' % (v3_meta['mode'],
                                      'strict' if v3_meta['mode'] == 'P' else 'mixed')
        # 埋点：作者反馈与体验信号先留空，等 UI 与作者补
        try:
            rec = {
                'text_id': 'live-%s' % time.strftime('%m%d%H%M%S'),
                'arm': 'v3',
                'initial_mode': v3_meta['mode'],
                'mode_source': v3_meta.get('mode_source', '?'),
                'mode_score': v3_meta['score'],
                'rules_applied': card['rule_set'],
                'output_preview': content[:200],
            }
            if attn:
                rec['attention_state'] = attn['state']
                rec['signals'] = attn['signals']
                rec['spoke'] = True
            _v3[1].record(rec)
        except Exception:
            pass
    # 采集：出声了。**沉默的分母**——召回率的分母是"探针到点的总次数"，
    # 只记沉默不分母，就仍然算不出召回。与沉默埋点同一条纪律：失败不介入。
    if _probe is not None:
        try:
            _ps = _probe_prof_snapshot()
            _probe.spoke(preview=content, attn=attn, v3_meta=v3_meta,
                         mode=mode, cfg=cfg,
                         prof_stale=_ps.get('prof_stale'),
                         prof_ver=_ps.get('prof_ver'),
                         text_len=len(text or ''),
                         text_head=(text or '')[:200])
        except Exception as _pe:
            print('[probe] 出声埋点失败（不影响出卡）：%s' % _pe)
    return [card]


# ------------------------------------------------- 文学模式的工具调用（标签协议）
# 见 lit_tools.py 开头：为什么没走原生 function calling。
# 这里只做两件事：**从模型输出里认出一次调用**，和**把它从给作者看的正文里去掉**。
# 最多让模型查四回。查不出来就直接答，别绕死循环。
# 为什么从 3 提到 4：读图那条链是 lofter_post（拿图链接）→ read_image（读字）
# → 作答，正好 3 步，一步富余都没有；它要是想再确认一次就被收口打断了。
LIT_MAX_ROUNDS = 4


_LIT_URL_RE = re.compile(r'https?://[^\s<>"）)】\'，。]+')


def _lit_has_url(*chunks):
    """她给的东西里有没有链接（材料框 / 这一句 / 对话历史）。

    为什么要它：工具开关原来**默认勾着**，后来为了拆文、审稿这种纯对着
    眼前材料做功的活不被"要不要上网查一下"拖慢，改成默认**不勾**
    （2026-09-20）。改得对，但代价没被看见——**"贴一个 LOFTER 网址让它读"
    走的正是同一条路**：工具不开，模型根本不知道有 `lofter_post` 这东西，
    只能回一句"我打不开这个网址"，看起来就是"什么网址都没内容"。

    贴链接这件事本身就是明摆着的意图，不该还要她另外去勾一下再来一次。
    所以：**材料里出现链接时，这一次自动把工具挂上**。
    拆文/审稿的材料是正文，一般不含链接，那条快路面不受影响。
    """
    for c in chunks:
        if isinstance(c, str):
            if _LIT_URL_RE.search(c):
                return True
        elif isinstance(c, list):
            for m in c:
                if isinstance(m, dict) and _LIT_URL_RE.search(
                        str(m.get('content') or '')):
                    return True
    return False


# 围栏块的开头。**两个函数必须共用这一个**——各写一份迟早走偏，而且真走过一次：
# 早先只认 ```tool 和 ```json，模型写成「``` tool」（多了个空格）就整个漏掉，
# 结果它跟后端说的话被当成答案直接发给了作者。
#
# 所以宽容的是**tool / json 这几个字怎么写**：大小写、前后空格、干脆不写都认
# （用的时候带 re.I）。但不能宽容到「任意语言名」——那样它正文里的 ```python
# 示例块会被当成工具调用吃掉。边界就画在这儿。
TOOL_FENCE = r'```[ \t]*(?:tool|json)?[ \t]*\r?\n'


def _loads_tool_json(raw):
    """解析工具围栏里的 JSON。

    LongCat（及其他 openai-compat 模型）有时会把花括号写成
    {{"call": ...}} 或整段每个 {{ / }} 都翻倍——那不是合法 JSON，
    json.loads 直接失败。旧实现失败后 strip_tool_blocks 仍把围栏剥掉，
    文学栏就交一张白卷（tools_used 空、text 空）。这里多试几次把成对的
    双花括号收成单层再解析；解不开就返回 None，交给上层当"没用工具"。
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    candidates = [raw]
    fixed = raw
    for _ in range(3):
        if '{{' not in fixed and '}}' not in fixed:
            break
        nxt = fixed.replace('{{', '{').replace('}}', '}')
        if nxt == fixed:
            break
        fixed = nxt
        candidates.append(fixed)
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def parse_tool_call(text):
    """从一段模型输出里认出一次工具调用。认不出来就返回 None——
    那不是错误，是"它这次没打算用工具"。

    认的形状（宽松）：围栏块里一个带 call / tool / name 键的 JSON 对象。
    取**最后一个**——模型偶尔会先写个示例再真的调一次，取最后一个才对得上
    它最终的意图。
    """
    if not text:
        return None
    found = None
    for m in re.finditer(TOOL_FENCE + r'(.*?)```', text, re.S | re.I):
        raw = (m.group(1) or '').strip()
        if not raw.startswith('{'):
            continue
        obj = _loads_tool_json(raw)
        if not isinstance(obj, dict):
            continue
        name = (obj.get('call') or obj.get('tool') or obj.get('name') or '').strip()
        if not name:
            continue
        args = obj.get('args') or obj.get('arguments') or obj.get('params') or {}
        found = {'call': name, 'args': args if isinstance(args, dict) else {},
                 'raw': m.group(0)}
    return found


def strip_tool_blocks(text):
    """把工具调用块从正文里去掉——那是它跟后端说的话，不是要给作者看的答案。

    只剥**内容是 JSON 对象**的块；它正文里自己写的 ```python 之类示例要留着。"""
    if not text:
        return text
    return re.sub(TOOL_FENCE + r'\s*\{.*?\}\s*```', '', text,
                  flags=re.S | re.I).strip()


# ---------------------------------------------------------------- HTTP

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        sys_ok = '  %s - %s' % (self.address_string(), fmt % args)
        try:
            print(sys_ok, flush=True)
        except Exception:
            pass

    def _json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def end_headers(self):
        p = self.path.split('?')[0]
        ext = os.path.splitext(p)[1]
        # 页面本身是从 `/` 给的——**没有扩展名**。只按后缀判断就会把它漏掉，
        # 于是它一直被浏览器缓存着：改完了她刷新看到的还是旧的那份，
        # 会以为东西没接上。目录路径（`/` 之类）一律当成页面。
        if ext in STATIC_NO_CACHE or ext == '':
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    # GET
    def do_GET(self):
        p = self.path.split('?')[0]
        if p == '/api/corpus':
            return self._json(load_corpus())
        if p == '/api/status':
            cfg = load_config()
            return self._json({
                'online': online(cfg),
                'model': cfg.get('model'),
                'base_url': cfg.get('base_url'),
                'skill_chars': len(load_skill()),
                'initiative': initiative_mode(),
            })
        if p == '/api/skill':
            return self._json({'skill': load_skill()})
        if p == '/api/workflow':
            return self._json({'workflow': load_workflow()})
        if p == '/api/doc':
            return self._json({'meta': doc_meta(), 'text': DOC_STORE.get('text', '')})
        if p == '/api/profile':
            with _PROFILE_LOCK:
                return self._json(dict(PROFILE))
        if p == '/api/fullread':
            return self._json(_fullread_public())
        if p == '/api/memory':
            # 记忆层状态：服务在不在、灌了多少段、有没有出错。启动器与面板都看它。
            with _MEM_LOCK:
                return self._json(dict(MEM))
        if p == '/api/lit':
            # 文学模式的动作清单（GET）。顺序即界面上的顺序。
            # 工具清单一起给——**它能干什么必须在界面上看得见**，
            # 不然"它到底有没有去查"只有后端知道，跟记忆区那件事是同一个道理。
            return self._json({'ws': self.LIT_WS, 'actions': [
                {'id': k, 'label': v['label']}
                for k, v in self.LIT_ACTIONS.items()],
                'tools': [{'id': k, 'desc': v['desc']}
                          for k, v in lit_tools.TOOLS.items()]})
        if p == '/api/workspaces':
            # 记忆工作区清单。给启动器与面板看"现在写进的是哪一区"——
            # 记忆混乱多半不是因为存错了，而是因为**不知道自己存到哪儿去了**。
            try:
                import ov_memory
                cur = (load_config() or {}).get('workspace') or ''
                ws, user = ov_memory.resolve_workspace(cur or None)
                return self._json({'workspaces': ov_memory.list_workspaces(),
                                   'current': ws, 'current_user': user})
            except Exception as e:
                return self._json({'workspaces': [], 'current': '', 'error': '%s' % e})
        if p == '/api/providers':
            # 可选后端的清单。**只给元信息，不给任何 key。**
            return self._json({'providers': providers.list_providers(),
                               'default': providers.DEFAULT_ID})
        if p == '/api/config':
            cfg = providers.resolve(load_config())
            return self._json({
                'provider': cfg.get('provider'),
                'base_url': cfg.get('base_url'),
                'model': cfg.get('model'),
                'api': cfg.get('api'),
                # key 只回打码后的样子——别把整串密钥送进浏览器
                'api_key_set': bool(cfg.get('api_key')),
                'api_key_masked': providers.mask_key(cfg.get('api_key')),
                'configured': providers.configured(load_config()),
            })
        return super().do_GET()

    # POST
    def _api_config(self):
        """保存模型配置。

        只认四个字段（provider / base_url / model / api_key）——
        temperature、thinking、max_tokens 一概不收：那些由 v3 的策略参数定，
        是伴写质量与实验可复现的前提，不该在网页上随手改。

        留空 api_key 表示"沿用环境变量里那把"，不会把已有的 key 清掉。
        """
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        old = load_config()
        new = dict(old)
        for k in ('provider', 'base_url', 'model', 'api_key'):
            if k in req:
                new[k] = (req.get(k) or '').strip()
        if not new.get('api_key'):
            new['api_key'] = old.get('api_key', '')   # 留空＝不改
        try:
            if os.path.exists(CONFIG_PATH):
                shutil.copy(CONFIG_PATH, CONFIG_PATH + '.bak')
            tmp = CONFIG_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(new, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_PATH)
        except Exception as e:
            return self._json({'error': '写 config.json 失败：%s' % e}, 500)
        cfg = providers.resolve(load_config())
        # ── 存进去≠能用 ────────────────────────────────────────────
        # 原来这里一律回 ok:true / configured:true，只要 key 非空就算数。
        # 于是出现过这种局面（2026-09-19 猫猫在整包上实测）：她填的是一家的端点，
        # 而下拉停在模板自带的另一家（install.ps1 从 config.example.json 生成时
        # provider 预设成 deepseek），协议因此对不上——保存回的是"已保存"，
        # 真正伴写时却报错或无声降级。存盘成功和"这套配置打得通"是两件事，
        # 既然手上能测（probe 只花一次最小请求），就顺手测一次再说实话。
        warn = ''
        if providers.configured(load_config()):
            try:
                # 探活挂在**保存这条请求里**，超时要压得住手：她点完保存
                # 会盯着面板等结论，20 秒是上限（测试按钮是 25 秒，那是她
                # 自己点的、有预期；保存不一样）。连不上就早说，别挂着。
                ok, msg = providers.probe(load_config(), timeout=15)
                if not ok:
                    warn = ('配置存下来了，但**连不通**：%s'
                            '　（多半是「后端」选的与「端点」填的不是同一家；'
                            '对照一下再存一次。）' % msg)
            except Exception as e:
                warn = '配置存下来了，但连通性没能确认：%s' % e
        with _FULLREAD_LOCK:
            _fr_status = FULLREAD.get('status')
        if (DOC_STORE.get('text') or '').strip() and _fr_status in ('offline', 'error', 'pending'):
            start_fullread(force=True)
        return self._json({'ok': True,
                           'provider': cfg.get('provider'),
                           'configured': providers.configured(load_config()),
                           'api': cfg.get('api'),
                           'base_url': cfg.get('base_url'),
                           'model': cfg.get('model'),
                           'warn': warn,
                           'api_key_masked': providers.mask_key(cfg.get('api_key'))})

    def _api_test(self):
        """测试当前配置通不通。req 可带一份临时配置，先看效果再决定存不存。"""
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        base = load_config()
        trial = dict(base)
        for k in ('provider', 'base_url', 'model', 'api_key'):
            if k in req and (req.get(k) or '').strip():
                trial[k] = req[k].strip()
        ok, msg = providers.probe(trial)
        return self._json({'ok': ok, 'msg': msg})

    def _api_sync(self):
        """前端按**短周期**把段落指纹（＋变了的那些段的正文）送回来。

        为什么不能复用 `/api/doc`：那条路会顺带跑 `start_profile()` 与
        `mem_on_doc_load()`，每次同步都重灌一遍记忆层——那是灾难。
        为什么是**独立定时器**：探针的 8 秒会被她打字不断重置，她连着写的时候
        永不到点，把握就一动不动。她说的正是这个。
        为什么必须送正文：只报"哪一段变了几个字"是**结构判断**，
        模型据此读不出文章在**信息**上处在什么局面。
        """
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        if not (DOC_STORE.get('text') or '').strip():
            return self._json({'ok': False, 'why': '还没有载入文档'})
        try:
            ch = apply_sync(req.get('paras') or [], req.get('texts') or {},
                            req.get('chars'))
        except Exception as e:
            return self._json({'ok': False, 'why': '%s' % e}, 200)
        nr = len(ch.get('removed') or [])
        na = len(ch.get('added') or [])
        if nr or na:
            print('[sync] rev=%d 动了：没了 %d 段 / 新写 %d 段'
                  % (DOC_STORE.get('rev') or 0, nr, na), flush=True)
        m = doc_meta()
        # 同步这一趟顺手看她是不是已经停笔够久、漂得够远——是的话**后台**重读全文。
        # 放在这里而不是单开一个服务端定时器：她停笔时前端仍会发心跳（见 index.html），
        # 所以这里天然有一个"现在几点了、她多久没动"的时钟。
        try:
            maybe_rebuild_profile()
        except Exception as e:
            print('[profile] 重建判定失败：%s' % e, flush=True)
        try:
            maybe_rebuild_fullread()
        except Exception as e:
            print('[fullread] 重建判定失败：%s' % e, flush=True)
        return self._json({'ok': True, 'rev': m['rev'], 'chars': m['chars'],
                           'paragraphs': m['paragraphs'], 'gaps': m['gaps'],
                           'removed': nr, 'added': na,
                           'profile_rev': PROFILE.get('rev') or 0})

    def _api_doc(self):
        """载入文档。支持 {name, text} 或 {name, b64}（docx 走二进制解析）。"""
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        name = req.get('name') or '未命名'
        try:
            if req.get('b64'):
                import base64
                text = extract_docx_bytes(base64.b64decode(req['b64']))
            else:
                text = req.get('text') or ''
        except Exception as e:
            return self._json({'error': str(e)}, 400)
        meta = set_doc(name, text)
        # 载入之后**立刻**在后台通读一遍，不阻塞前台。
        # 剖面好了会在面板上出现一张卡片，之后的每一次伴写都带着它。
        if text.strip():
            # 写作视图仍要调性剖面；文学视图只需要覆盖全文的阅读记忆，
            # 不再为了写小说语气额外抽样调用一次模型。
            if req.get('view') != 'lit':
                start_profile()
            start_fullread()
            # 记忆层：取回上次的全篇把握 + 后台灌段。都不阻塞前台。
            threading.Thread(target=mem_on_doc_load, daemon=True).start()
        return self._json({'ok': True, 'meta': meta, 'text': text})

    def _api_profile(self):
        """GET 取剖面状态；POST 强制重做一次。"""
        if self.command == 'POST':
            if not (DOC_STORE.get('text') or '').strip():
                return self._json({'status': 'empty', 'text': '',
                                   'err': '还没有载入文档'})
            start_profile()
        with _PROFILE_LOCK:
            return self._json(dict(PROFILE))

    def _api_initiative(self):
        """切换主导权档位：jia（甲·规则）/ yi（乙）/ bing（丙·放权）。

        为什么单独做一个端点、而不是让她去改 config.json：
        她的原话是"把本机的改成丙方案，让我试一试体感，然后再由我判断
        回退成甲乙还是采纳丙"。**要能当场切**——否则"试体感"就得重启服务，
        那就不是体感了。写回 config.json 后即时生效，下一次伴写走新档位。
        """
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        want = str(req.get('initiative') or '').strip().lower()
        if want not in ('jia', 'yi', 'bing'):
            return self._json({'error': '只能是 jia / yi / bing'}, 400)
        cfg = load_config()
        cfg['initiative'] = want
        try:
            tmp = CONFIG_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_PATH)
        except Exception as e:
            return self._json({'error': '写 config.json 失败：%s' % e}, 500)
        print('[initiative] 已切到 %s' % want, flush=True)
        return self._json({'ok': True, 'initiative': want})

    def _json_body(self):
        """读请求体并解析成 dict。**空体/坏体一律返回 {}，不抛。**

        本文件原来有 12 处各自写 `n = int(self.headers.get('Content-Length')
        or 0)` + `json.loads(self.rfile.read(n))`，其中 9 处包在 try 里、
        3 处没包。没包的那几处（/api/cowrite、/api/lit、/api/memory/chat …）
        遇到坏体就在请求线程里抛，客户端拿到的是**连接被直接关掉**，
        而不是一个能读的 4xx —— 2026-10-07 实测确认。

        采集侧那套接口本来就有 `_read_json()`（坏体返 {}），这里保持它的语义；
        新代码一律用本方法，老调用点不动（那是本体的行为）。
        """
        try:
            n = _safe_int(self.headers.get('Content-Length'), 0, lo=0,
                          hi=64 * 1024 * 1024)
            if not n:
                return {}
            raw = self.rfile.read(n)
            if not raw:
                return {}
            d = json.loads(raw.decode('utf-8'))
            return d if isinstance(d, dict) else {'_raw': d}
        except Exception:
            return {}

    def _read_json(self):
        """读请求体。**坏体返回 {} 而不是抛**——采集接口拿空 dict 还能走默认值，
        而一个解析异常会把整个 handler 打断，那比"字段缺失"难查得多。
        现有各接口的 body 解析逻辑不动：那是本体的行为，测试版不改它。"""
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if not n:
                return {}
            return json.loads(self.rfile.read(n).decode('utf-8')) or {}
        except Exception:
            return {}

    # ---------------- 测试版采集：读数与回填（§7 其二/ 其一/ 其四） ----------------
    # 这三个接口**只读/只写 probe 自己的文件**，不碰 samples.jsonl，
    # 也不改 /api/cowrite 与 /api/rewrite 的语义。
    def _api_probe_list(self, req):
        """回放：按时间倒序吐出采集事件。前端回放页用。
        支持 ?kind=silence 过滤，以及 ?unlabeled=1 只看未标注的。"""
        if _probe is None:
            return self._json({'error': '采集外挂未载入'}, 503)
        rows, bad = _probe.read_all()
        kind = (req.get('kind') or '').strip()
        unlabeled = str(req.get('unlabeled') or '') in ('1', 'true', 'yes')
        if kind:
            rows = [r for r in rows if r.get('kind') == kind]
        if unlabeled:
            rows = [r for r in rows if not r.get('author_feedback')]
        rows = list(reversed(rows))
        # ⚠️ 这里原来是 `int(req.get('limit') or 500)`：limit 传字符串时
        # 在请求线程里抛 ValueError，没有任何 try 接住 —— 客户端收到的是
        # **连接被直接关掉**（RemoteDisconnected），不是 4xx。
        # 面板那边看到的就是"刷新没反应"，而错误只在 stderr 里。
        # 凡是外面送进来的数，一律走 _safe_int，坏值退回默认。
        limit = _safe_int(req.get('limit'), 500, lo=1, hi=20000)
        return self._json({'total': len(rows), 'bad_lines': bad,
                           'rows': rows[:limit],
                           'log': _probe.LOG_PATH})

    def _api_probe_annotate(self, req):
        """回填标注。**回填不新增**——同一事件只在原行上改。

        这是 §7 其二要的"事后回放由作者标'该沉默／其实想听'"的落点。
        """
        if _probe is None:
            return self._json({'error': '采集外挂未载入'}, 503)
        eid = str(req.get('event_id') or '').strip()
        # 撤回：清掉这一条自己的标注字段。必须走独立分支——
        # 原接口要求 author_feedback 非空，于是"标错了"没有任何 UI 路径可退。
        if req.get('clear'):
            if not eid:
                return self._json({'error': '要 event_id'}, 400)
            try:
                n = _probe.annotate(eid, None, None, clear=True)
            except Exception as e:
                return self._json({'error': '撤回失败：%s' % e}, 500)
            if not n:
                return self._json({'error': '没有这个 event_id：%s' % eid,
                                   'hit': 0}, 404)
            return self._json({'ok': True, 'hit': n, 'cleared': True})
        fb = str(req.get('author_feedback') or '').strip()
        if not eid or not fb:
            return self._json({'error': '要 event_id 与 author_feedback'}, 400)
        extra = {}
        # ⚠️ 'sim' 必须在白名单里：盲评面板把作者填的 s(g,p) 放在这个字段上提交，
        # 而原来它不在名单内 —— 填的每一个 s 都被静默丢掉，
        # probe_analyze 第 4 节于是永远显示"已填 s 的 0 条"，
        # §7 其四的效应差永远算不出来（2026-10-07 用假端点实测抓到）。
        for k in ('note', 'p_text', 'accepted', 'blind_pos', 'flow_signal',
                  'sim'):
            if k in req and req[k] is not None:
                extra[k] = req[k]
        try:
            n = _probe.annotate(eid, fb, extra)
        except ValueError as e:
            # 标注与事件类型不匹配 —— 这是调用方的错，报 400 且把可选项列出来
            return self._json({'error': '%s' % e}, 400)
        except Exception as e:
            return self._json({'error': '回填失败：%s' % e}, 500)
        if not n:
            # 没命中要说出来：静默返回 0 会让"标了但没存"看起来像"没标"
            return self._json({'error': '没有这个 event_id：%s' % eid, 'hit': 0}, 404)
        return self._json({'ok': True, 'hit': n})

    def _api_probe_pick(self, req):
        """记录作者手选 P/M/S—— §7 其一那个从未被测量的东西。

        localStorage 换机器就丢，而重测信度要跨会话，所以必须落盘。
        """
        if _probe is None:
            return self._json({'error': '采集外挂未载入'}, 503)
        m = str(req.get('mode') or '').strip().upper()
        if m not in ('P', 'M', 'S'):
            return self._json({'error': 'mode 只能是 P / M / S'}, 400)
        row = _probe.mode_pick(m, source=req.get('source') or '作者手选',
                               cfg=req.get('cfg'),
                               text_len=req.get('text_len'),
                               text_head=req.get('text_head'))
        return self._json({'ok': True, 'event_id': (row or {}).get('event_id')})

    def _api_probe_trial(self, req):
        """记录一次「伤害」试验的搭话（§7 其四）：扩张型 / 收敛型。"""
        if _probe is None:
            return self._json({'error': '采集外挂未载入'}, 503)
        k = str(req.get('trial_kind') or '').strip()
        try:
            row = _probe.trial(k, req.get('g_text') or '', scene=req.get('scene'),
                               text_len=req.get('text_len'),
                               text_head=req.get('text_head'),
                               note=req.get('note'))
        except ValueError as e:
            return self._json({'error': str(e)}, 400)
        return self._json({'ok': True, 'event_id': (row or {}).get('event_id')})

    def _api_probe_pairs(self, req):
        """把同一场景的两型搭话配成对，按随机序返回，供盲评。

        **只返回已成对的**（两型都在）。落单的列在 `unpaired` 里——
        落单的那一型无法参与组间差，但仍然是有意义的数据（它说明有一型没出）。
        """
        if _probe is None:
            return self._json({'error': '采集外挂未载入'}, 503)
        rows, bad = _probe.read_all()
        tr = [r for r in rows if r.get('kind') == 'probe_trial']
        byscene = {}
        for r in tr:
            byscene.setdefault((r.get('scene') or '').strip(), []).append(r)
        pairs, unpaired = [], []
        for scene, grp in byscene.items():
            bykind = {}
            for r in grp:
                bykind.setdefault(r.get('trial_kind'), r)   # 同型多条取最后一条
            if len(bykind) == 2 and scene:
                a, b = sorted(bykind.values(), key=lambda r: r.get('blind_pos') or 0)
                pairs.append({'scene': scene, 'first': a, 'second': b,
                              'seed': a.get('seed')})
            else:
                unpaired.append({'scene': scene,
                                 'kinds': sorted(bykind)})
        return self._json({'pairs': pairs, 'unpaired': unpaired,
                           'bad_lines': bad, 'seed': _probe.TRIAL_SEED})

    def _api_probe_stats(self, req):
        """当场算沉默的完整 2x2 与两个率。

        **正类= 该沉默。**
            TP = 沉默事件标「该沉默」        FN = 出声事件标「本该沉默」
            FP = 沉默事件标「其实想听」      TN = 出声事件标「该说话」
                     以及标「本来就没什么可说」的沉默（算FP：它确实多闭了嘴）

        精确率 = TP / (TP + FP)  ——它沉默的那些里，该沉默的占多少
        召回率 = TP / (TP + FN)  ——该沉默的那些里，它沉默的占多少

        **分母不足时返回 None，不返回 0。** 两者意义完全不同：
        0 是"算出来是0"，None 是"还标不出来"。后者才是常态。
        """
        if _probe is None:
            return self._json({'error': '采集外挂未载入'}, 503)
        rows, bad = _probe.read_all()
        pp = len([r for r in rows if r.get('kind') == 'probe_to_point'])
        sil = [r for r in rows if r.get('kind') == 'silence']
        spk = [r for r in rows if r.get('kind') == 'spoke']

        cell = {}
        for name, pairs in _probe.CONFUSION.items():
            cell[name] = len([r for r in rows
                              if any(r.get('kind') == k
                                     and r.get('author_feedback') == f
                                     for k, f in pairs)])
        TP, FP, FN, TN = cell['TP'], cell['FP'], cell['FN'], cell['TN']
        labeled = TP + FP + FN + TN
        precision = (round(TP / (TP + FP), 4) if (TP + FP) else None)
        recall = (round(TP / (TP + FN), 4) if (TP + FN) else None)
        return self._json({
            'probe_to_point': pp, 'silence': len(sil), 'spoke': len(spk),
            'labeled': labeled,
            'matrix': {'TP': TP, 'FP': FP, 'FN': FN, 'TN': TN},
            'precision': precision, 'recall': recall,
            # 未标注的沉默数——它决定精确率还差多少样本
            'silence_unlabeled': len([r for r in sil
                                      if not r.get('author_feedback')]),
            'spoke_unlabeled': len([r for r in spk
                                    if not r.get('author_feedback')]),
            'breakdown': {
                k: len([r for r in rows if r.get('author_feedback') == k])
                for k in (_probe.SILENT_KINDS + _probe.SPOKE_KINDS)
            },
            'bad_lines': bad, 'log': _probe.LOG_PATH,
        })

    def _api_probe_reset(self, req):
        """清空采集文件。只在测试版可用，且必须显式确认。"""
        if _probe is None:
            return self._json({'error': '采集外挂未载入'}, 503)
        if not str(req.get('confirm') or '') == 'RESET':
            return self._json({'error': '要confirm=RESET 才清'}, 400)
        _probe.reset()
        return self._json({'ok': True})

    def _api_attention(self):
        """只做注意力推断，不调模型。前端用它决定「几秒后出声 / 干脆不出声」。"""
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        if not (USE_V3 and _v3 and _v3[2]):
            # v3 没开：返回"照常出声"，保持旧行为
            return self._json({'available': False, 'speak': True, 'delay_sec': 8})
        try:
            _, info = _v3[2].infer(req.get('signals') or req)
        except Exception as e:
            # 注意力字段（pause_ms / doc_chars / …）全是裸 int()，前端只要
            # 送来一个非数字（空串、'—'、null 之外的怪值），infer 就会抛。
            # 这里**失败开放**：退回"照常出声"，但要把 reason 带回去，
            # 否则"注意力为什么失灵"在界面上看不出来。
            return self._json({'available': False, 'error': str(e),
                               'reason': 'signals 解析失败，按旧行为照常出声',
                               'speak': True, 'delay_sec': 8})
        info['available'] = True
        # 采集：探针到点（**不论最终说不说**）。分母在这里成立——
        # 探针到点 = 全部机会，之后 silence / spoke 各占其中一份。
        if _probe is not None:
            try:
                _probe.probe_to_point(attn=info, mode=req.get('mode'),
                                      delegate=bool(req.get('delegate')))
            except Exception as _pe:
                print('[probe] 探针埋点失败（不影响推断）：%s' % _pe)
        # 探针先记下规则版 speak。Skill-V 只改返回给前端的那一位，且默认关。
        info = _maybe_skillv(
            info, req.get('signals') or req, mode=req.get('mode'),
            text_len=req.get('text_len'))
        return self._json(info)

    # ---------------------------------------------------------------- 文学模式
    # 与伴写**相反**的两条：伴写不替作者定向、不确定就沉默；
    # 这里要下判断，但每一条判断都必须举证到原文。
    # 所以两个模式**不能共用记忆区**——否则"下判断"的手会去污染伴写的语气。
    LIT_WS = 'literary'
    LIT_ACTIONS = {
        'chai': {
            'label': '拆文',
            # 每个动作自己要出多长，差别很大——拆文是「把材料摊开」，输出量
            # **正比于材料**（2 万字材料实测要出 6600–8800 字）；对话是「说几句话」。
            # 原来它们共用一个 4096，于是每拆一次都从中间被切断：交出去的是
            # 半份拆解，**看起来却像"就这么多"**（2026-09-20 猫猫实测）。
            # 给足上限、让它自己收笔——实测给 16384 时它自己就收笔了。
            # **写多长是它的判断，不该由 max_tokens 替它定。**
            'max_tokens': 16384,
            'system':
                '你把一份文本拆成可检索、可回指的单元。\n'
                '最小单元必须带四样：编号、白描（不复述原文，说清这段在做什么）、\n'
                '涉及的实体（人物/物件/地点）、原文锚点（能 grep 回去的那几句）。\n'
                '**硬规矩：事实可溯源。** 硬事实必须能回原文找到；原文没给就写「原文未明确」，\n'
                '**禁止推断填空**。这条和伴写那句「只核已写下的、不猜将要写的」是同一条约束的两面。\n'
                '不要评价好坏，不要给写作建议。\n'
                '输出用 markdown，标题用「##」。'
        },
        'shen': {
            'label': '审稿',
            # 审稿是「逐条挑问题」，比材料短得多，但要列全。
            'max_tokens': 8192,
            'system':
                '你审一份文稿。规矩只有两条：\n'
                '**一、每一条判断都要落到具体的字句上**，引出来，再说清为什么是问题。\n'
                '**二、不给空话。**「整体感觉不错，就是有点平」「还可以再打磨一下」\n'
                '——这类话既不真也没用，一律不要。\n'
                '先说你读到了什么（要具体），再说哪里卡住了、为什么。\n'
                '如果某一处你读不出来，就直说读不出来，不要硬凑一个说法。\n'
                '输出用 markdown，按问题逐条列，每条给位置。'
        },
        'sucai': {
            'label': '素材整理',
            'max_tokens': 8192,
            'system':
                '你整理一批文学素材：归档、去重、标来源。\n'
                '**来源永远比整理结果重要**——一条没有出处的素材等于没有。\n'
                '整理结果按主题分组，每条后面标它从哪儿来。\n'
                '有冲突的两条并列放着，不要替作者裁决谁对。\n'
                '输出用 markdown。'
        },
        'xiezuo': {
            'label': '短篇 / 散文 / 翻译',
            # 写作与翻译的输出**可能和材料一样长**（翻译尤其），给足。
            'max_tokens': 16384,
            'system':
                '你写（或译）一段中文。四条硬规矩：\n'
                '**一、不写「形容词＋的」单独作谓语。** 这是翻译腔最显眼的形状，中文的谓语要有骨头。\n'
                '**二、不写判断性总结句。** 尤其是结尾。场景自己会说话，不需要有人替它收口。\n'
                '**三、不制造效果。** 不为煽情而煽情，不为漂亮而漂亮。\n'
                '一个比喻如果是为了显示聪明，它就是多余的。\n'
                '**四、不替读者下结论。** 写到这里就够了，剩下的留给读的人。\n'
                '写场景时：人物独处、身体在动的地方放慢写细；心理活动和判断处快收，不要在那里磨。\n'
                '直接给正文，不要解释你为什么这么写。\n'
                '如果用户要求“全文翻译/整本翻译”，必须逐片完整翻译，不得摘要、不得跳段；'
                '所有分片沿用同一术语与语气，不能因为片与片之间接续而改写已完成内容。'
        },
    }

    # 自由对话的姿态：和四个动作共用"下判断要举证"这条底线，
    # 但它没有固定动作，所以把那四条语言规矩和"不推断填空"都写在明面上。
    LIT_CHAT_SYSTEM = (
        '你是通用文学工作台里的助手。\n'
        '这一区和伴写那区是**分开的两棵树**：伴写不替作者定向、不确定就沉默；\n'
        '这里相反——**要下判断**，但每一条判断都必须举证到原文（或到查到的出处），\n'
        '不许空口下。\n'
        '四条语言规矩：不写「形容词＋的」单独作谓语；不写判断性总结句；\n'
        '不制造效果；不替读者下结论。\n'
        '原文没给的就写「原文未明确」，**不推断填空**。\n'
        '读不出来就直说读不出来，不要硬凑一个说法。\n'
        '如果【全文阅读状态】显示已完成，说明后台已经逐片读过全文；必须结合全书记忆回答，'
        '不能因为当前检索片段不完整就说“我没拿到全文”。引用具体原句时才以当前片段为准。\n'
        '输出用 markdown。'
    )

    # 工具说明只在开着工具时挂上去——不开就不提，免得它惦记着非要查一次。
    LIT_TOOLS_SYSTEM = (
        '\n\n【你可以调用工具】\n'
        '要查东西时，在回答里写一个围栏块，格式就一种：\n'
        '```tool\n{{"call": "工具名", "args": {{...}}}}\n```\n'
        '可用的有：\n%s\n'
        '规矩：\n'
        '· 一次只调一个。看到它的结果之后再决定要不要接着查。\n'
        '· 引用要说清来自哪儿。**搜到但没点开看过的，不能当成原文引用。**\n'
        '· 查不到就说查不到，不要编。\n'
        '· 不需要查就直接答，不要为了用工具而用。'
    )

    def _api_lit(self):
        """文学模式：四个动作 + 自由对话。**写进 literary 区，不碰伴写区。**"""
        # 同样是裸解析：坏体在请求线程里抛，客户端拿到的是连接被关掉。
        req = self._json_body()
        if not req:
            return self._json({'error': '请求体不是合法 JSON（或为空）'}, 400)
        act = (req.get('action') or '').strip()
        text = (req.get('text') or '').strip()          # 材料框里的东西
        incoming = req.get('messages') or []            # 对话：前端带上历史
        # 勾了就用；**没勾但东西里有链接也用**——否则"贴一个网址让它读"整条路
        # 是死的（见 _lit_has_url）。这不是替她做决定：她贴链接就是要它去读。
        use_tools = bool(req.get('tools')) or _lit_has_url(text, incoming)

        _last_user = ''
        for _m in reversed(incoming):
            if isinstance(_m, dict) and (_m.get('role') or 'user') == 'user':
                _last_user = str(_m.get('content') or '')
                break
        _full_translate = act == 'chat' and is_full_translate_request(_last_user)
        if _full_translate:
            # 自由对话里明确要求“翻译全文”时，不能继续走检索问答；
            # 切换为固定的长文翻译动作，让全文按语义片完整处理。
            act = 'xiezuo'
            is_chat = False
            meta = self.LIT_ACTIONS.get(act)
        else:
            is_chat = (act == 'chat')
            meta = None if is_chat else self.LIT_ACTIONS.get(act)
        if not is_chat and not meta:
            return self._json({'error': '没有这个动作：%s' % act}, 400)
        if not is_chat and not text:
            return self._json({'error': '还没给它材料'}, 400)

        cfg = load_config()
        if not providers.configured(cfg):
            return self._json({'ok': False,
                               'err': '没接模型。点右上角「模型」选一家、填上 Key。'})

        # ---------------------------------------------------------------- messages
        # 选区是一个独立事实：动作默认只处理选区，对话默认围绕选区回答。
        selection = normalize_selection(req.get('selection'))
        sel_text = (selection or {}).get('text') or ''
        scope_text = text if _full_translate else (sel_text.strip() or text)
        chapter = req.get('chapter') if isinstance(req.get('chapter'), dict) else {}
        intent = (req.get('intent') or '').strip()
        pos_lines = []
        if chapter.get('title'):
            pos_lines.append('用户当前在看：第 %s/%s 章「%s」。' % (
                chapter.get('index', '?'), chapter.get('count', '?'), chapter.get('title')))
        if intent:
            pos_lines.append('用户正在做：%s。' % intent)
        if sel_text.strip():
            pos_lines.append('用户明确选中了一段原文；默认意图围绕这个选区。')
        position_note = ('【用户当前意图】\n' + '\n'.join(pos_lines)) if pos_lines else ''
        focus = ''
        if is_chat:
            for _m in reversed(incoming):
                if isinstance(_m, dict) and (_m.get('role') or 'user') == 'user':
                    focus = str(_m.get('content') or '')
                    break
        if sel_text:
            focus = ((focus + '\n') if focus else '') + sel_text[:4000]
        focus = focus or text[:2000]
        read_detail = fullread_block(max_chars=1800)
        _detail_notes = fullread_notes_for(focus, 1200)
        if _detail_notes:
            read_detail += '\n\n' + _detail_notes
        read_brief = fullread_block(max_chars=1200)
        limit = providers.input_budget(cfg)
        chat_limit = max(3000, limit - len(read_detail) - 300)
        chunk_limit = max(3000, limit - len(read_brief) - 1800)
        body = ''
        trunc = ''
        chunks = []
        chunked = False
        if is_chat:
            body = text
            if len(body) > chat_limit:
                body, trunc = relevant_excerpt(text, focus, chat_limit)
            selection_note = selection_block(selection, limit=max(6000, chat_limit - 500))
        else:
            # 动作作用于全文；若存在选区，则默认对选区执行。分片只是执行方式，
            # 不是缩范围：每一片都会处理，最后按原文顺序拼接。
            body = scope_text
            selection_note = (
                '【范围】用户明确要求翻译全文；选区不限制范围，'
                '必须覆盖完整材料。'
            ) if _full_translate else selection_block(
                selection, limit=max(6000, chunk_limit - 500))
            chunks = split_semantic_chunks(body, chunk_limit)
            chunked = len(chunks) > 1
            if chunked:
                print('[lit] 材料 %d 字，按 %d 片完整处理（不再只送前 N 字）'
                      % (len(body), len(chunks)), flush=True)
        if is_chat:
            # 历史由前端带；只要最后一条是她刚说的就行。材料框有东西就当上下文附上。
            msgs = [{'role': (m.get('role') or 'user'), 'content': (m.get('content') or '')}
                    for m in incoming if isinstance(m, dict)]
            if body:
                head = read_detail
                if position_note:
                    head += '\n\n' + position_note
                head += '\n\n【材料/相关段落】\n%s' % body
                if trunc:
                    head += '\n\n' + trunc
                if selection_note:
                    head += '\n\n' + selection_note
                if msgs and msgs[-1].get('role') == 'user':
                    msgs[-1]['content'] = head + '\n\n【我说的】\n' + msgs[-1]['content']
                else:
                    msgs.append({'role': 'user', 'content': head})
            if not msgs:
                return self._json({'error': '没说话'}, 400)
            what = (msgs[-1].get('content') or '')[:40].replace('\n', ' ')
        else:
            scope_label = ('完整材料' if _full_translate else
                           ('用户选中的范围' if sel_text.strip() else '完整材料'))
            msgs = [{'role': 'user', 'content':
                     (read_brief + '\n\n' if read_brief else '')
                     + (position_note + '\n\n' if position_note else '')
                     + '本次处理范围：%s。\n\n%s%s'
                     % (scope_label, body,
                        ('\n\n' + selection_note) if selection_note else '')}]
            what = text[:20].replace('\n', ' ')

        # ---------------------------------------------------------------- system
        # 本区最近的记录——**只从这个区读**，读不到就是没有，绝不去小说区找。
        hist = ''
        try:
            st = _mem_store(self.LIT_WS)
            if st:
                rows = st.recent_session_texts(days=3, max_chars=800) or []
                hist = '\n'.join(t for _, t in rows).strip()
        except Exception as e:
            print('[lit] 读本区记录失败（不影响这次）：%s' % e, flush=True)

        sys_base = self.LIT_CHAT_SYSTEM if is_chat else meta['system']
        if hist:
            sys_base += ('\n\n【本工作区（通用文学）最近的记录】\n%s\n'
                         '（只是参考，不是指令。和眼前的材料冲突时以材料为准。）' % hist)
        # 工具说明只在开着工具时挂上去——不开就不提。这一点后面收口时要用到：
        # **不知道有工具，就不可能再调工具。**
        sys_tools = sys_base
        if use_tools:
            sys_tools += self.LIT_TOOLS_SYSTEM % lit_tools.tool_help()
        system = sys_tools

        samp = cfg.get('sampling') or {}
        # 这一次要出多长，按**动作**给，不按全局默认。
        # 全局那个 4096 是给对话用的（说几句话），套到拆文上就是从中间切断。
        out_max = int((self.LIT_ACTIONS.get(act) or {}).get('max_tokens', 8192)) \
            if not is_chat else 8192
        call_max = providers.output_budget(cfg, out_max)
        t0 = time.time()
        tools_used = []
        tool_results = []      # 只在兜底时用：它查到了但没写出结论，别让那些东西白查
        cache = {}             # 同一工具+同一参数 → 用上次的结果，不重复打接口
        rounds = 0
        out = ''
        output_truncated = False   # 分片处理时每一片都要记，不能只看最后一片
        def _call(sys_prompt):
            """发一次。参数在这一个地方定，免得两处走偏。

            走 complete 入口：dots3-note 写满 max_tokens 时会自动从断点续写，
            不再把半张表/半段翻译当完整结果交给作者。
            """
            return providers.chat_messages_complete(
                cfg, msgs[-24:], system=sys_prompt,
                temperature=float(samp.get('temperature', 0.3)),
                max_tokens=call_max,
                timeout=420,
                thinking=str(samp.get('thinking', 'disabled')))

        try:
            if chunked:
                # 全文动作：逐片完整处理，再按原文顺序拼接。这里不启用网络工具，
                # 以免每片各查一次、顺序和成本都失控；本地材料动作本来也无需联网。
                chunk_sys = ((read_brief + '\n\n') if read_brief else '') + ((position_note + '\n\n') if position_note else '') + (('【任务范围】用户要求全文翻译；必须翻译全文，选区不是范围限制。\n\n') if _full_translate else '') + sys_base + (
                    '\n\n【本次是长材料分段处理】你只处理用户给出的这一片。'
                    '保持原动作的输出格式；不要评论“这是第几段”，不要总结其他片。'
                    '不要因为文段在中间而假设前文或后文；原文没给的信息照旧写“原文未明确”。')
                parts = []
                for _i, _ch in enumerate(chunks, 1):
                    _msgs = [{'role': 'user', 'content':
                              '【长材料第 %d/%d 片】\n\n%s'
                              % (_i, len(chunks), _ch['text'])}]
                    _piece = providers.chat_messages_complete(
                        cfg, _msgs, system=chunk_sys,
                        temperature=float(samp.get('temperature', 0.3)),
                        max_tokens=call_max, timeout=420,
                        thinking=str(samp.get('thinking', 'disabled')))
                    if providers.last_stop().get('reason') == 'max_tokens':
                        output_truncated = True
                    _piece = strip_tool_blocks(_piece).strip()
                    # 写作/翻译的输出就是成稿，不能为了分段而插入工作标题；
                    # 拆文/审稿/素材整理则需要片次边界，便于核对来源。
                    if act == 'xiezuo':
                        parts.append(_piece)
                    else:
                        parts.append('## 材料第 %d/%d 片\n\n%s' % (_i, len(chunks), _piece))
                out = '\n\n'.join(parts)
                pending = None
                rounds = len(chunks)
            else:
                # -------------------------------------------------- 工具循环
                # 模型要查就让它查，最多 LIT_MAX_ROUNDS 轮。它没照格式写就当不用工具，
                # 照常把那段话当答案——**认不出来不是故障，不许报错**。
                pending = None
                for _ in range(LIT_MAX_ROUNDS):
                    rounds += 1
                    out = _call(system)
                    if providers.last_stop().get('reason') == 'max_tokens':
                        output_truncated = True
                    call = parse_tool_call(out) if use_tools else None
                    if not call:
                        pending = None
                        break
                    pending = call
                    # 同一个工具、同一份参数，这一串里问过就不再打第二次。
                    # 它确实会重复调（实测同一篇文章连抓两次）——每多一次都是往
                    # 对方服务器上多拍一下，而这边的节流还白白等 1.2 秒。
                    key = json.dumps([call['call'], call['args']],
                                     sort_keys=True, ensure_ascii=False)
                    if key in cache:
                        res = cache[key]
                        print('[lit] 工具 %s 用上次的结果（同一参数，不再打一次）' % call['call'],
                              flush=True)
                    else:
                        res = lit_tools.run(call['call'], call['args'])
                        cache[key] = res
                    tools_used.append({'name': call['call'], 'args': call['args']})
                    # 存**完整**结果：界面上「放进材料框」要的是整篇，不是截过的。
                    tool_results.append((call['call'], res or ''))
                    print('[lit] 工具 %s %s → %d 字'
                          % (call['call'], json.dumps(call['args'], ensure_ascii=False)[:80],
                             len(res or '')), flush=True)
                    msgs.append({'role': 'assistant', 'content': out})
                    msgs.append({'role': 'user',
                                 'content': '【%s 的结果】\n%s\n\n'
                                            '（引用要标出处；不够可以再查一次，或直接说查不到。）'
                                            % (call['call'], res)})

                # -------------------------------------------------- 收口
                # 轮次用完它还在调工具——这时候 out 是一个纯工具块，strip 完就**空**了，
                # 作者会收到一个空回答。所以再发一次，这回明说不许调工具：
                # 查到的就这些，用它们答；没查到就直说没查到。
                if pending is not None:
                    rounds += 1
                    print('[lit] 轮次用尽仍在调工具（%s），收口一次' % pending['call'], flush=True)
                    # 收口用的是**没有工具说明**的那份 system：它这回不知道有工具可用，
                    # 也就没法再吐一个工具块出来。求它"别再调了"是没用的——实测它照调。
                    out = _call(sys_base +
                                '\n\n（就你手上查到的东西和已有的材料，直接回答。'
                                '没查到就直说没查到，不要编。）')
        except providers.EmptyReplyError as e:
            return self._json({'ok': False, 'sec': round(time.time() - t0, 1),
                               'err': '它没给出可依据的回应（%s）。' % e})
        except providers.ProviderError as e:
            # 把「等了多久」一起回出去——故障排查里这个数最有用：
            # **立刻回＝配置/协议不对**（比如拿 anthropic 协议去打 /chat/completions）；
            # **等满超时才回＝端点卡住或网络不通**。光看那句报错分不出这两者。
            return self._json({'ok': False, 'sec': round(time.time() - t0, 1),
                               'err': str(e)})

        answer = strip_tool_blocks(out)
        # 被输出上限截断**必须说出来**。实测（2026-09-19）：让她"整理这个账号的作品"，
        # 它把 288 篇一张表往里抄，抄到 6633 字被 `max_tokens` 从半行切断——
        # 交出去的是一张断掉的表，**看起来却像"就这么多"**。停因由 providers 留下
        # （`last_stop()`），这里只负责别把它咽掉；顺带指路到完整的那份。
        if answer.strip() and (output_truncated or providers.last_stop().get('reason') == 'max_tokens'):
            full = [n for n, r in tool_results if r and r.strip()]
            answer += ('\n\n---\n⚠️ **这段回答已自动续写到底，但模型仍在输出上限处停下，'
                       '不能保证已经收完**。'
                       + ('完整的原始材料在下面「原文 · %s」按钮里。'
                          % full[-1] if full else '可以把范围缩小，或按章节再问一次。'))
            print('[lit] 回答被 max_tokens 截断，已标注', flush=True)
        if not answer.strip() and tool_results:
            # 兜底：它只吐了工具块，正文一个字没有。
            # 与其交一张白卷，把查到的东西原样给出来——**查到了但没说，比没查到更糟**。
            answer = ('它这轮只顾着查，没把结论写出来。查到的东西原样在这儿：\n\n'
                      + '\n\n'.join('【%s】\n%s' % (n, (r or '')[:1200])
                                    for n, r in tool_results))
            print('[lit] 正文为空，已用工具结果兜底', flush=True)
        elif not answer.strip() and (out or '').strip() and not tools_used:
            # 另一类白卷：模型写了疑似工具围栏，但 JSON 解不开，
            # strip 把围栏剥光后正文也空了。把原文交回去，别吞成空白页。
            answer = out
            print('[lit] 正文为空且未识别工具调用，已回退原文', flush=True)

        # 记一条进**本区**的日文件：append-only，同内容不重复写。
        saved = False
        try:
            st = _mem_store(self.LIT_WS)
            if st:
                tag = '问' if is_chat else meta['label']
                extra = ('（查了 %s）' % '、'.join(t['name'] for t in tools_used)) if tools_used else ''
                st.append_session(
                    time.strftime('%Y-%m-%d'),
                    '%s ｜ [%s] 「%s…」→ 出 %d 字%s'
                    % (time.strftime('%H:%M'), tag, what, len(answer or ''), extra))
                saved = True
        except Exception as e:
            print('[lit] 记一条失败（不影响输出）：%s' % e, flush=True)

        # tool_raw：工具**查到的原文**。跟"它的答复"是两回事——
        # 她要"把读到的文章放进材料框"，要的是文章本身，不是它对文章的转述。
        # 界面上因此给两个键，由她选放哪个。
        #
        # **不去重就会给她两个一模一样的键**：同一篇被查了两次的话，
        # 两条内容是一样的，摆两个"原文 · lofter_post"只会让人犹豫该点哪个。
        raw_seen = set()
        raw_out = []
        for n, r in tool_results:
            k = (n, r)
            if k in raw_seen:
                continue
            raw_seen.add(k)
            raw_out.append({'name': n, 'text': r})
        return self._json({'ok': True, 'action': act,
                           'label': '对话' if is_chat else meta['label'],
                           'text': answer or '', 'ws': self.LIT_WS, 'saved': saved,
                           'tools_used': tools_used, 'rounds': rounds,
                           'tool_raw': raw_out,
                           # 不再有“只送前 N 字”的静默截断。长动作会全量分片；
                           # 长对话会明确标成相关段落检索，而不是冒充全文。
                           'mat_truncated': False,
                           'mat_focused': bool(trunc),
                           'mat_mode': ('retrieval' if (is_chat and trunc)
                                        else ('chunked' if chunked else 'full')),
                           'input_chunks': (len(chunks) if not is_chat else 1),
                           'selection_used': bool(sel_text.strip()),
                           'mat_chars': len(text),
                           'sec': round(time.time() - t0, 1)})

    def _api_export(self):
        """导出：文件进了这个页面，就必须能出得去。

        只有"进"没有"出"的写作软件是不完整的——等于把她写的东西扣在这儿了。
        所以导出走的是**下载**，不是"再存一份到服务器"：
        落到她自己的磁盘上、她自己的文件名，这个页面不替她保管。
        """
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        text = req.get('text') or ''
        fmt = (req.get('format') or 'txt').lower()
        if fmt not in ('txt', 'md', 'docx'):
            return self._json({'error': '不认识的导出格式：%s' % fmt}, 400)
        if not text.strip():
            return self._json({'error': '没有可导出的内容'}, 400)

        if fmt == 'docx':
            # 文学那边的输出是 markdown，直接塞进 Word 会看到一排 ##。
            # 写作区的正文是纯散文，**一个字都不许动**——所以只有对方明说
            # 这是 markdown 时才清理。
            data = docx_bytes(md_plain(text) if req.get('markdown') else text)
            ctype = ('application/vnd.openxmlformats-officedocument'
                     '.wordprocessingml.document')
        else:
            data = text.encode('utf-8')
            ctype = ('text/markdown; charset=utf-8' if fmt == 'md'
                     else 'text/plain; charset=utf-8')

        fname, fname_ascii = _safe_name(req.get('name'), fmt)
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        # 中文文件名要给两遍：filename 给纯 ASCII 兜底，filename* 给真的。
        self.send_header('Content-Disposition',
                         'attachment; filename="%s"; filename*=UTF-8\'\'%s'
                         % (fname_ascii, urllib.parse.quote(fname)))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)
        print('[export] %s · %s · %d 字' % (fname, fmt, len(text)), flush=True)

    def _api_rewrite(self):
        """作者对刚才那条按了「太重／太轻／没有新东西／给点思路」——重来一次。

        这条链路的意义不只是"改一版输出"：**按钮本身就是标注**。
        她点「太重」＝她说这条太强。记进埋点，和她在反馈表里手填的是同一件事，
        但成本低得多——所以这也是后面校准用的主要数据来源。
        """
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception as e:
            return self._json({'error': 'bad request: %s' % e}, 400)
        text = (req.get('text') or '').strip()
        prev = (req.get('prev') or '').strip()
        kind = (req.get('kind') or '').strip()
        prev_out = (req.get('prev_output') or '').strip()
        section = req.get('section') or '—'
        probe = bool(req.get('probe'))  # 冒烟脚本标记，见下面埋点处
        mode = (req.get('mode') or '').strip().upper() or None  # 继承卡片上的 P/M/S
        free = (req.get('free') or '').strip()          # 「你自己说」输入框
        recall = (req.get('recall') or '').strip()      # 记忆库手动召回（只这一次）
        history = req.get('history') or []              # 对话栏：最近几轮，只用来给语境
        if not text:
            return self._json({'error': '没有可重写的段落'}, 400)
        if not (USE_V3 and _v3) or not _v3[0].REWRITE.get(kind):
            return self._json({'error': '未知的重写类型：%s' % kind}, 400)
        if kind == 'free' and not free:
            return self._json({'error': '「你自己说」是空的'}, 400)

        cfg = load_config()
        t0 = time.time()
        r = _v3[0].REWRITE[kind]
        note = _v3[0].rewrite_note(kind, prev_out, free=free)
        if kind == 'free' and history:
            # 对话栏是连续几轮的，得让它知道前面说过什么，否则每轮都像第一次。
            # 只带最近 6 轮，带多了会把它拖回顾（长文本上下文的教训）。
            lines = []
            for h in history[-6:]:
                who = '她' if h.get('who') == 'her' else '你'
                if (h.get('text') or '').strip():
                    lines.append('%s：%s' % (who, h['text'].strip()[:300]))
            if lines:
                note = ('【你们前面已经说过的】\n' + '\n'.join(lines) + '\n\n') + note
        try:
            ctx = '\n'.join('§%s %s %s字' % (s.get('sec'), s.get('kind'), s.get('chars'))
                            for s in load_corpus().get('sections', [])[:60])
            cards = call_model(cfg, load_skill(), text, section, ctx,
                               prev=prev, ctx_paras=pick_context(text, prev),
                               mode=mode, rewrite=note, recall=recall)
        except Exception as e:
            return self._json({'error': '%s' % e}, 200)

        body = (cards[0].get('body') or '') if cards else ''
        # 同样的护栏：重写之后照样可能抄原文、照样可能撞开头
        try:
            import metrics as _M
            copy = _M.verbatim_span(body, text) if body else None
            if copy:
                cards = call_model(cfg, load_skill(), text, section, ctx,
                                   prev=prev, mode=mode, rewrite=note +
                                   '\n\n（你又把她原文抄进来了，删掉。）')
                body = (cards[0].get('body') or '') if cards else ''
        except Exception:
            pass

        try:
            _v3[1].record({
                'text_id': 'rw-%s' % time.strftime('%m%d%H%M%S'),
                # probe=1 的是 v3/smoke_rewrite.py 打的冒烟，不是她按的。
                # 分开记，否则调试用的几十条会把她真实点击的分布冲掉。
                'arm': 'v3-rewrite-probe' if probe else 'v3-rewrite',
                'rewrite_kind': kind,
                'author_feedback': {
                    'too_heavy': '太强', 'too_light': '太弱',
                    'no_novelty': '太强', 'give_ideas': '主动求思路',
                    'free': '她自己说的话',
                }.get(kind, kind),
                'her_words': free[:300] if kind == 'free' else '',
                'output_preview': body[:200],
                'prev_output': prev_out[:200],
                'metrics': {'output_chars': len(body)},
            })
        except Exception:
            pass
        return self._json({
            'cards': cards,
            'kind': kind,
            'label': r['label'],
            'elapsed_ms': int((time.time() - t0) * 1000),
        })

    def _api_memory_chat(self):
        """给浏览器里跑的文学记忆层当**模型通道**。

        位置选在这里有两个理由，都不是随手定的：
        · **密钥只在后端**——浏览器里摆一把 key 等于把它贴在窗户上，
          换台电脑、清个缓存就找不回来；而模型的实际使用者其实是它自己。
        · **协议只有一处判断**——`providers.chat()` 知道本项目该走
          /chat/completions 还是别的。凡是和已有调用长得一样的地方都该复用，
          抄一份就漏一次格式判断（见 llm_call 的注释，这个坑已经踩过）。

        另外这里**不设 json_mode**：不是每个上游都支持 response_format，
        而 LitMemoryCore 的 parseJsonStrict 本来就能剥掉围栏代码块、
        修尾逗号。少一份依赖，多一份兼容。
        """
        # 同样是裸解析：坏体在请求线程里抛，客户端拿到的是连接被关掉。
        req = self._json_body()
        if not req:
            return self._json({'error': '请求体不是合法 JSON（或为空）'}, 400)
        sysmsg, usermsg = '', ''
        for m in (req.get('messages') or []):
            c = m.get('content') or ''
            if m.get('role') == 'system':
                sysmsg += c
            else:
                usermsg += c
        if not usermsg.strip():
            return self._json({'error': '没有要发给模型的内容'}, 400)
        cfg = load_config()
        if not online(cfg):
            return self._json({'error': '还没配模型：设置里填上 api_key 之后，'
                                        '「这一 Part 写完」才能真的提炼出记忆'}, 503)
        t0 = time.time()
        try:
            content = providers.chat_messages_complete(
                cfg, [{'role': 'user', 'content': usermsg}], system=sysmsg,
                temperature=float(req.get('temperature') or 0.3),
                max_tokens=int(req.get('max_tokens') or 3072),
                timeout=180)
        except Exception as e:
            return self._json({'error': '%s' % e}, 200)
        if not (content or '').strip():
            return self._json({'error': '模型返回空内容'}, 200)
        print('[memory] 提炼一次 %d 字 / %.1fs' % (len(content), time.time() - t0),
              flush=True)
        return self._json({'content': content})

    # ── DS 网页端朗读桥：/api/tts ─────────────────────────────
    # 前端文学工作台点小喇叭 → POST {text} → 这里起 tts_read.py 子进程，
    # 用系统 Edge（独立配置）打开 chat.deepseek.com，把文本发过去、触发
    # 朗读。返回时不等朗读完成——它是浏览器发声，声音在 Edge 窗口里。
    def _api_tts(self):
        req = self._json_body()
        if not req:
            return self._json({'error': '请求体不是合法 JSON（或为空）'}, 400)
        text = (req.get('text') or '').strip()
        if not text:
            return self._json({'error': '文学编辑框是空的，没有东西可以朗读'}, 400)
        if len(text) > 12000:
            return self._json({'error': '文本过长（>12000 字符）。请先分段，或删掉一部分再朗读。'}, 400)
        if not os.path.exists(TTS_READ_SCRIPT):
            return self._json({'error': '朗读桥脚本缺失：%s' % TTS_READ_SCRIPT}, 500)

        py = _tts_python()
        if not py:
            return self._json({'error': '没找到能跑 Playwright 的 Python。'
                                        '请在系统里执行：pip install playwright'}, 500)

        global _TTS_PROC
        with _TTS_LOCK:
            if _TTS_PROC is not None and _TTS_PROC.poll() is None:
                return self._json({'error': '朗读已在运行中。若 Edge 窗口停在登录页，'
                                            '请登录后等待；或稍后再点。'}, 409)

            # 文本经临时文件传给子进程，避免命令行转义问题
            tmp = os.path.join(BASE, '_tts_pending.txt')
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(text)
            except Exception as e:
                return self._json({'error': '写临时文本失败：%s' % e}, 500)
            try:
                _TTS_PROC = subprocess.Popen(
                    [py, TTS_READ_SCRIPT, '--text-file', tmp],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=BASE)
            except Exception as e:
                _TTS_PROC = None
                return self._json({'error': '启动朗读失败：%s' % e}, 500)
            return self._json({'ok': True,
                               'message': '已发送给 DeepSeek，Edge 窗口会自动打开并朗读。'
                                          '若停在登录页，登录后会自动继续。'})

    def do_POST(self):
        p = self.path.split('?')[0]
        if p == '/api/doc':
            return self._api_doc()
        if p == '/api/sync':
            return self._api_sync()
        if p == '/api/config':
            return self._api_config()
        if p == '/api/test':
            return self._api_test()
        if p == '/api/initiative':
            return self._api_initiative()
        if p == '/api/probe/list':
            return self._api_probe_list(self._read_json())
        if p == '/api/probe/annotate':
            return self._api_probe_annotate(self._read_json())
        if p == '/api/probe/pick':
            return self._api_probe_pick(self._read_json())
        if p == '/api/probe/trial':
            return self._api_probe_trial(self._read_json())
        if p == '/api/probe/pairs':
            return self._api_probe_pairs(self._read_json())
        if p == '/api/probe/stats':
            return self._api_probe_stats(self._read_json())
        if p == '/api/probe/reset':
            return self._api_probe_reset(self._read_json())
        if p == '/api/attention':
            return self._api_attention()
        if p == '/api/profile':
            return self._api_profile()
        if p == '/api/fullread':
            if not (DOC_STORE.get('text') or '').strip():
                return self._json({'error': '还没有载入文档'}, 400)
            start_fullread(force=True)
            return self._json(_fullread_public())
        if p == '/api/rewrite':
            return self._api_rewrite()
        if p == '/api/lit':
            return self._api_lit()
        if p == '/api/export':
            return self._api_export()
        if p == '/api/memory/chat':
            return self._api_memory_chat()
        if p == '/api/tts':
            return self._api_tts()
        if p != '/api/cowrite':
            return self._json({'error': 'not found'}, 404)
        # 坏体不再抛给客户端——见 _json_body 的说明：原来这里是裸解析，
        # 一个截断的 body 会让连接被直接关掉，而她那边只看到"没反应"。
        req = self._json_body()
        if not req:
            return self._json({'error': '请求体不是合法 JSON（或为空）'}, 400)

        text = (req.get('text') or '').strip()
        prev = (req.get('prev') or '').strip()
        request_selection = normalize_selection(req.get('selection'))
        section = req.get('section') or '—'
        recall = (req.get('recall') or '').strip()   # 记忆库手动召回：挂在**这一次**上，用完就清
        corpus = load_corpus()
        cfg = load_config()
        t0 = time.time()

        # ---- 主导权档位：甲 / 乙 / 丙 ----
        # 丙之下"说不说"归模型；甲/乙仍是规则拦。见 initiative_mode()。
        initiative = initiative_mode()
        # 两个轴分开，见 call_model 的说明：
        #   delegate —— 说话权（说不说归模型）：只有丙开
        #   full_ctx —— 上下文形态（整篇 / 连续窗口）：乙、丙开
        delegate = (initiative == 'bing')
        full_ctx = initiative in ('yi', 'bing')

        # ---- 注意力机制 ----
        # 甲/乙：它决定「该不该出声」，false 就直接拦掉、**不调模型**。
        # 丙：它**不再拦**，只把现场翻成事实（attention.describe），说不说交给模型。
        attn = None
        attn_desc = ''
        anchor = (req.get('anchor') or '').strip()
        if USE_V3 and _v3 and _v3[2] and req.get('attention') is not None:
            try:
                _sig = req.get('attention') or {}
                attn = _v3[2].infer(_sig, delegate=delegate)[1]
                # 事实描述**三档都要**——它是"把规则从命令降为事实"的载体。
                # 甲乙丙的差别在**上下文形态**（连续窗口 / 整篇）和
                # **说话权**（规则 / 模型），不在给不给事实。
                attn_desc = _v3[2].describe(_sig, attn)
                # 事实句已经写完。Skill-V 只许改 speak 位，不许改这段事实。
                attn = _maybe_skillv(
                    attn, _sig, mode=req.get('mode'), text_len=len(text or ''))
            except Exception as e:
                print('[attention] 推断失败，按常规处理：%s' % e)
                attn = None
        # ---- 章：把"她在第几章"并进锚点与事实两块 ----
        # 锚点块是模型**第一个**读到的东西（U 形曲线的头），所以章名放这儿最有效；
        # 只放在整篇旁边的话，碰到"整篇降为核对表"那一版就等于说了也白说。
        #
        # ⚠️ 定位：**先靠文本匹配，匹配不到就退到光标坐标**。
        # 为什么必须有那条退路：`DOC_STORE` 是**载入那一刻**的快照，她新写的
        # 段落不在里面，`find_para_no` 于是返回 None——而"正在写新内容"恰恰是
        # 伴写最常见的场景，不是"在改已有段落"。退到前端按**光标位置**算的
        # 段号（`attention.para_no`：它数的是编辑区的段，不依赖文本匹配），
        # 章至少是准的。2026-09-20 之前这里没有退路，新段落一律没有章名，
        # 模型只好报行号——这正是她报的那个症状的**另一条**成因。
        cur_no = find_para_no(text) if text else None
        if not cur_no:
            try:
                _pn = (req.get('attention') or {}).get('para_no')
                cur_no = int(_pn) if _pn else None
            except Exception:
                cur_no = None
        cur_ch = chapter_of(cur_no)
        _anch_head = ''
        if cur_ch:
            # **这里不写段号**：她要求报位置时说章名、别报行号，而写在这儿的
            # "第 65–66 段"最容易被模型顺手抄进答复——那等于自己拆自己的台。
            _anch_head = '她此刻在第 %d 章「%s」。\n' % (cur_ch['no'], cur_ch['title'])
        _sel_prompt = selection_block(request_selection)
        if _sel_prompt:
            # 选区必须比普通光标锚点更早被看到；她一旦明确划了范围，
            # “这里”就不再是单个字符位置，而是一整段明确内容。
            anchor = _sel_prompt + ('\n\n' + anchor if anchor else '')
        if anchor:
            anchor = _anch_head + anchor
        elif _anch_head:
            # 锚点是**前端**传的。前端没传（旧页面、缓存里的旧 JS、或者
            # 光标脚本没接上）时，上面算出来的章名就白算了——而模型失去
            # 章名之后只能退回行号，正是她报的那个症状。所以这里往事实块
            # 里再放一份：**无论走哪条路径，章名都要在**。
            attn_desc = _anch_head.strip() + (('\n\n' + attn_desc) if attn_desc else '')
        _chidx = chapter_index_text()
        if _chidx:
            # 章目录拼在事实之后：模型引用位置时的唯一凭据。
            # ⚠️ 目录里**没有段号了**（理由见 chapter_index_text）：只要还留
            # 一处段号，模型就用段号报位置。所以这里另外交给它一个**替代手段**——
            # 想指"章内具体某一句"时引那句话本身。不给替代手段、只下禁令，
            # 它会自己编一个段号出来。
            _ch_head = ('【章目录】全篇的章（给你认路：哪一章在哪、有多长）。\n'
                        '**说位置就用章名**；要指**章内的某一句话**，'
                        '把那句话引出来就行——她认得自己写的字，不认得段号。\n')
            attn_desc = (attn_desc + '\n\n' + _ch_head + _chidx) if attn_desc \
                else (_ch_head + _chidx)

        # 不该出声的状态：直接返回沉默卡片，**不调模型**。
        # 这是注意力机制最主要的作用——大部分时刻正确答案是闭嘴。
        # （丙之下 speak 恒 true，这一段不会命中；它保留给甲/乙。）
        if attn and not attn.get('speak'):
            try:
                _v3[1].record({
                    'text_id': 'live-%s' % time.strftime('%m%d%H%M%S'),
                    'arm': 'v3-attention',
                    'attention_state': attn['state'],
                    'spoke': False,
                    'signals': attn['signals'],
                })
            except Exception:
                pass
            return self._json({
                'mode': 'attention',
                'cards': [{
                    'type': 'withhold',
                    'level': 'muted',
                    'title': '⊘ · %s' % attn['name'],
                    'layer': '⊘',
                    'body': attn['why'],
                    'evidence': [],
                }],
                'attention': attn,
                'error': None,
                'elapsed_ms': int((time.time() - t0) * 1000),
                'section': section,
            })

        cards, mode, err = [], 'offline', None
        if online(cfg):
            try:
                ctx = '\n'.join('§%s %s %s字' % (s.get('sec'), s.get('kind'), s.get('chars'))
                                for s in corpus.get('sections', [])[:60])
                # 附锚点索引与冲突条目，供模型做 locate / relate / present_conflict
                anchors = corpus.get('anchors', [])
                if anchors:
                    ctx += '\n\n【锚点索引】\n' + '\n'.join(
                        '· %s → %s' % (a.get('term', ''),
                                       '；'.join('§%s（%s）' % (h['sec'], h['part']) for h in a.get('hits', [])))
                        for a in anchors)
                conflicts = corpus.get('conflicts', [])
                if conflicts:
                    ctx += '\n\n【冲突条目】\n' + '\n'.join(
                        '· %s：%s' % (c.get('label', ''),
                                      '／'.join('%s（%s 处 · §%s）' % (s['form'], s['count'], s['sec'])
                                               for s in c.get('sides', [])))
                        for c in conflicts)
                # 上下文形态按档位：甲＝连续窗口，乙/丙＝整篇。
                # ctx_paras（字面挑片段）只在**老前端不送锚点**时才用得上。
                ctx_paras = [] if (anchor or full_ctx) else pick_context(text, prev)
                cards = call_model(cfg, load_skill(), text, section, ctx,
                                   prev=prev, ctx_paras=ctx_paras,
                                   mode=req.get('mode'),
                                   # 有锚点＝新版：状态以**事实**给出，不再以命令给出
                                   attn_hint=_v3[2].prompt_hint(attn)
                                   if (attn and _v3[2] and not anchor) else '',
                                   attn=attn, recall=recall,
                                   delegate=delegate, anchor=anchor,
                                   attn_desc=attn_desc, full_ctx=full_ctx)
                # 位置坐标清洗：**出口最后一道**（见 strip_lineno_coords）。
                # 放在跨轮护栏之前——护栏看到的就是最终文本。
                for _c in (cards or []):
                    if isinstance(_c, dict):
                        for _k in ('title', 'body'):
                            if _c.get(_k):
                                _c[_k] = strip_lineno_coords(_c[_k])
                # 跨轮开头护栏：最近几条里已有两条同一个开头形状 → 带禁令重写一次
                try:
                    import metrics as _M
                    body0 = (cards[0].get('body') or '') if cards else ''
                    # 丙：它回"不说"的时候，body0 是**理由**、不是伴写正文。
                    # 拿理由去过"照抄 / 撞开头"的护栏等于罚错人，先挡掉。
                    _silent = bool(cards) and cards[0].get('verdict') == 'no'
                    rep = (_M.opening_repeat(body0, _OPEN_HISTORY)
                           if (body0 and not _silent) else None)
                    # 照抄原文：形态问题，确定性可查，和解读深浅无关
                    copy = (_M.verbatim_span(body0, text)
                            if (body0 and not _silent) else None)
                    if rep or copy:
                        ban = rep['ban_char'] if rep else ''
                        note = ''
                        if copy:
                            note = ('\n\n（上一条作废，重写。你把她的原文抄进来了：'
                                    '「%s…」。不要引超过一处，也不要把她写的句子搬出来——'
                                    '你要说的是你自己的话。）' % copy[:16])
                            print('[verbatim-guard] 命中照抄：%s…' % copy[:20])
                        cards = call_model(cfg, load_skill(), text, section, ctx,
                                           prev=prev, ctx_paras=ctx_paras,
                                           # mode 必须一起带上：护栏重试是**第二次调用**，
                                           # 漏了它就会掉回分类器猜的模式——
                                           # 实测表现为"选了 S 却返回 M 的卡片"（2026-09-16）。
                                           mode=req.get('mode'),
                                           attn_hint=((_v3[2].prompt_hint(attn)
                                                       if (attn and _v3[2]
                                                           and not anchor) else '')
                                                      + note),
                                           attn=attn,
                                           ban_opening=ban,
                                           recall=recall,
                                           delegate=delegate, anchor=anchor,
                                           attn_desc=attn_desc, full_ctx=full_ctx)
                        # 位置坐标清洗：重写路径也过一道——它整块替换了 cards，
                        # 主路径那一遍覆盖不到这里的结果。
                        for _c in (cards or []):
                            if isinstance(_c, dict):
                                for _k in ('title', 'body'):
                                    if _c.get(_k):
                                        _c[_k] = strip_lineno_coords(_c[_k])
                        body0 = (cards[0].get('body') or '') if cards else ''
                    if body0:
                        _OPEN_HISTORY.append(_M.opening_shape(body0))
                        del _OPEN_HISTORY[:-_OPEN_HISTORY_MAX]
                except Exception as _e:
                    print('[opening-guard] 跳过：%s' % _e)
                mode = 'model'
                # ---- Jev 判定层（外部：local-jev → Ollama qwen2:7b）----
                # 默认关，且默认只看不改：判定落 v3/logs/jev.jsonl，不动 cards。
                # 要真拦得在 params.json 的 jev 块里开 mode=block + block_writing，
                # 而拦的动作默认是「带一句禁令重写一次」——与 opening/verbatim
                # 两条既有护栏同款。**不默认沉默**：沉默会打断她，跟 D9、
                # author_final_veto 相抵；要让外部模型闭嘴，得是她自己选的。
                try:
                    _b0 = (cards[0].get('body') or '') if cards else ''
                    _no_speak = bool(cards) and cards[0].get('verdict') == 'no'
                    if _jev and _b0 and not _no_speak:
                        _g = _jev.check_writing(_b0, context=text)
                        if _g['ok'] and _g['verdict'] == '回炉' \
                                and _jev.blocking('writing'):
                            if _jev.block_writing_action() == 'silence':
                                cards = []
                            else:
                                _iss = _g['detail'].get('issues') or ['质量不足']
                                _note = ('\n\n（上一条作废，重写。这一版没过判定层：'
                                         '%s）' % '、'.join(str(x) for x in _iss)[:80])
                                cards = call_model(cfg, load_skill(), text, section, ctx,
                                                   prev=prev, ctx_paras=ctx_paras,
                                                   mode=req.get('mode'),
                                                   attn_hint=(
                                                       (_v3[2].prompt_hint(attn)
                                                        if (attn and _v3[2]
                                                            and not anchor) else '')
                                                       + _note),
                                                   attn=attn, recall=recall,
                                                   delegate=delegate, anchor=anchor,
                                                   attn_desc=attn_desc,
                                                   full_ctx=full_ctx)
                                for _c in (cards or []):
                                    if isinstance(_c, dict):
                                        for _k in ('title', 'body'):
                                            if _c.get(_k):
                                                _c[_k] = strip_lineno_coords(_c[_k])
                except Exception as _je:
                    print('[jev-gate] 跳过：%s' % _je)
            except Exception as e:
                err = '%s' % e
                cards = offline_engine(text, corpus, section)
                mode = 'offline(fallback)'
        else:
            cards = offline_engine(text, corpus, section)

        # 记一条（时间节点）：这次她停在哪、我说了什么。**历史伴写文本**就是这么攒起来的。
        # 后台跑，不拖慢响应；写不进去也不影响这一次伴写。
        try:
            threading.Thread(target=mem_record, args=(text, cards), daemon=True).start()
        except Exception as _me:
            print('[memory] 起记录线程失败：%s' % _me, flush=True)

        return self._json({
            'mode': mode,
            'cards': cards,
            'attention': attn,
            'initiative': initiative,
            'delegate': delegate,
            'error': err,
            'elapsed_ms': int((time.time() - t0) * 1000),
            'section': section,
        })


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    cfg = load_config()
    print('=' * 58)
    print('  伴写 demo · 本地服务')
    print('=' * 58)
    print('  地址     : http://127.0.0.1:%d' % PORT)
    print('  模式     : %s' % ('真实模型 (%s @ %s)' % (cfg.get('model'), cfg.get('base_url'))
                            if online(cfg) else '离线演示（未配置 api_key）'))
    print('  策略     : %s（%d 字符，改完刷新页面即生效，无需重启）'
          % (os.path.basename(SKILL_PATH), len(load_skill())))
    print('  语料     : %s' % ('已载入 %d 节' % len(load_corpus().get('sections', []))
                            if os.path.exists(CORPUS_PATH) else '未找到'))
    print('  Ctrl+C 停止')
    print('=' * 58, flush=True)
    with Server(('127.0.0.1', PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n已停止')

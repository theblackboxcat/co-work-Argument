# -*- coding: utf-8 -*-
"""协变树移植进 CoWrite 的记忆层与判定层。

移植的是机制，不是「系统理解了作者」：

- 记忆写入只追加的地址账本：地址 + 一句话断言。不把原文片段当作可引用的树。
- 判层由代码根据**已在文本里核对过的事实**路由。模型自报的层名弃用。
- 说不说的硬条件由代码执行：生成之后的自重复、可选步数预算、
  未核对事实、账本指纹不符。模型的「说」不能盖过这些条件。
- 看见不等于许可说：账本里的地址可以出现在提示里，但只有证据词
  在本轮文本里再次出现时，地址才许留在出口正文里。

不注入主干 gloss。词表路线的阴性结果不在这里被改写。
"""
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LEDGER = os.path.join(HERE, 'state', 'cotree_ledger.jsonl')

REPEAT_T = 0.50
MIN_CHARS = 12

FACT_PROTOCOL = (
    '【交给代码核对的三行】先写这三行，没有的写「无」。'
    '不要写层名，不要写节点编号。\n'
    '并置：词甲 | 词乙\n'
    '再出现：词 @ 先前那句里能对上的原句\n'
    '变化：原先 -> 现在\n'
    '然后空一行，再写你要说的话。写不出可核对的事实，就只写这三行「无」，不要编。'
)

_NONE = {'', '无', '没有', '—', '-', '无。', 'none', 'None'}
_ID_RE = re.compile(
    r'(?<![A-Za-z0-9_])(?:addr-\d{4}|[STB]\d{2}(?:_[A-Za-z0-9_]+)?)(?![A-Za-z0-9_])')
_ADDR_RE = re.compile(r'(?<![A-Za-z0-9_])(addr-\d{4})(?![A-Za-z0-9_])')


def enabled(cfg):
    return bool((cfg or {}).get('cotree', True))


def _compact(s):
    return re.sub(r'\s+', '', s or '')


def grams4(s):
    s = _compact(s)
    return set(s[i:i + 4] for i in range(max(0, len(s) - 3)))


def jaccard4(a, b):
    if len(_compact(a)) < MIN_CHARS or len(_compact(b)) < MIN_CHARS:
        return 0.0
    ga, gb = grams4(a), grams4(b)
    union = len(ga | gb)
    return (len(ga & gb) / union) if union else 0.0


def buggy_pre_repeat(last_output, new_material, threshold=REPEAT_T):
    """E10 的检测位置：生成之前，拿上一轮输出去比新材料。

    新材料不同、模型却在复读上一轮时，这里不触发。保留此函数只为对照，
    服务器路径不调用它。
    """
    if not last_output:
        return False
    return jaccard4(last_output, new_material) > threshold


def repeats_prior(body, history, threshold=REPEAT_T):
    """生成之后，拿这一轮正文去比已经说出的话。"""
    for prev in history or []:
        if jaccard4(body, prev) > threshold:
            return True
    return False


def _absent(val):
    return (val or '').strip() in _NONE


def _spans(val):
    parts = re.split(r'\s*[|｜/]\s*', (val or '').strip())
    return [p.strip() for p in parts if p.strip() and not _absent(p)]


def parse_output(text):
    """拆模型输出。层名只记录，不采用。"""
    raw = (text or '').strip()
    verdict = ''
    m = re.match(
        r'^\s*[\[【]?\s*(不说|说|NO|YES|no|yes)\s*[\]】]?\s*[·、,，:：\-—]?\s*',
        raw)
    if m:
        verdict = 'no' if m.group(1) in ('不说', 'NO', 'no') else 'yes'
        raw = raw[m.end():].strip()
    facts = {'并置': '', '再出现': '', '变化': ''}
    saw_fact = False
    layer_model = ''
    body_lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.lower().startswith('verdict:'):
            v = s.split(':', 1)[1].strip()
            verdict = 'no' if ('不说' in v or v.lower() == 'no') else 'yes'
            continue
        if s.lower().startswith('layer:'):
            layer_model = s.split(':', 1)[1].strip()
            continue
        hit = False
        for key in facts:
            for sep in ('：', ':'):
                if s.startswith(key + sep):
                    facts[key] = s.split(sep, 1)[1].strip()
                    saw_fact = True
                    hit = True
                    break
            if hit:
                break
        if not hit:
            body_lines.append(line)
    return {
        'verdict': verdict,
        'layer_model': layer_model,
        'facts': facts,
        'saw_fact': saw_fact,
        'body': '\n'.join(body_lines).strip(),
    }


def _contains(span, text):
    span = (span or '').strip()
    return len(span) >= 2 and span in (text or '')


def verify_facts(facts, author_text, prior_text):
    """事实必须在文本里找得到。模型写了但文本里没有的，记为驳回。"""
    ok, bad = [], []
    author = author_text or ''
    prior = prior_text or ''
    whole = prior + '\n' + author

    ju = _spans(facts.get('并置'))
    if len(ju) >= 2 and not _absent(facts.get('并置')):
        a, b = ju[0], ju[1]
        if a != b and _contains(a, author) and _contains(b, author):
            ok.append({'kind': '并置', 'term': a, 'spans': [a, b]})
        else:
            bad.append({'kind': '并置', 'why': '两个词没有都出现在当前段'})
    elif facts.get('并置') and not _absent(facts.get('并置')):
        bad.append({'kind': '并置', 'why': '没有两个可分开的词'})

    second = (facts.get('再出现') or '').strip()
    if second and not _absent(second):
        term = re.split(r'\s*[@＠]\s*', second, maxsplit=1)[0].strip()
        if _contains(term, author) and _contains(term, prior):
            ok.append({'kind': '再出现', 'term': term})
        else:
            bad.append({'kind': '再出现', 'why': '当前段或先前文本里没有这个词'})

    change = (facts.get('变化') or '').strip()
    if change and not _absent(change):
        sides = re.split(r'\s*(?:->|→|=>)\s*', change, maxsplit=1)
        if len(sides) == 2:
            left, right = sides[0].strip(), sides[1].strip()
            if (left and right and left != right
                    and _contains(left, whole) and _contains(right, whole)):
                ok.append({'kind': '变化', 'term': right, 'spans': [left, right]})
            else:
                bad.append({'kind': '变化', 'why': '两边没有都出现在已给文本里'})
        else:
            bad.append({'kind': '变化', 'why': '缺少前后两边'})
    return ok, bad


def is_silence_body(body):
    """整段只有「无 / 不说 / ⊘」时，不是可出口的正文。

    dots3 实测会把三行空事实写成「无\\n无\\n无\\n\\n[⊘]」，没有「并置：」这种键名。
    """
    s = re.sub(r'\s+', '', body or '')
    s = re.sub(r'[\[【\]】]', '', s)
    return bool(s) and re.fullmatch(r'(?:无|没有|不说|SILENT|⊘)+', s) is not None


def route_layer(verified):
    kinds = [f['kind'] for f in verified]
    if '再出现' in kinds:
        return 'B'
    if '变化' in kinds:
        return 'C'
    if '并置' in kinds:
        return 'A'
    return ''


def strip_ids(body, keep):
    """出口正文只保留本轮许可的 addr。主干节点编号一律去掉。"""
    keep = set(keep or [])
    stripped = []

    def repl(m):
        token = m.group(0)
        if token in keep:
            return token
        stripped.append(token)
        return ''

    text = _ID_RE.sub(repl, body or '')
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text, stripped


class Decision:
    def __init__(self, **kw):
        self.withhold = kw.get('withhold', False)
        self.by = kw.get('by', '')
        self.reason = kw.get('reason', '')
        self.layer = kw.get('layer', '⊘')
        self.body = kw.get('body', '')
        self.layer_model = kw.get('layer_model', '')
        self.verified = kw.get('verified', [])
        self.rejected = kw.get('rejected', [])
        self.licensed = kw.get('licensed', [])
        self.stripped = kw.get('stripped', [])
        self.address = kw.get('address', '')
        self.parent = kw.get('parent', '')

    def public(self):
        return {
            'withhold': self.withhold,
            'by': self.by,
            'reason': self.reason,
            'struct_layer': self.layer,
            'layer_model_ignored': self.layer_model,
            'verified': [f['kind'] for f in self.verified],
            'rejected': self.rejected,
            'licensed': self.licensed,
            'stripped': self.stripped,
            'address': self.address,
            'parent': self.parent,
        }


class TreeSession:
    """只追加的地址账本。改写接口会拒绝。"""

    def __init__(self, path=None, max_spoken=None):
        self.path = path or DEFAULT_LEDGER
        self.max_spoken = max_spoken
        self.records = []
        self.history = []
        self.tampered = False
        self.armed_id = None
        self._used_id = None
        self._load()

    def _sha_path(self):
        return self.path + '.sha256'

    def fingerprint(self):
        if not os.path.exists(self.path):
            return ''
        h = hashlib.sha256()
        with open(self.path, 'rb') as f:
            h.update(f.read())
        return h.hexdigest()

    def _load(self):
        if not os.path.exists(self.path):
            return
        raw = open(self.path, 'rb').read()
        digest = hashlib.sha256(raw).hexdigest()
        sig = ''
        if os.path.exists(self._sha_path()):
            sig = open(self._sha_path(), encoding='utf-8').read().strip()
        if sig and sig != digest:
            self.tampered = True
            return
        for line in raw.decode('utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            self.records.append(json.loads(line))
        if not sig:
            self._write_sig(digest)

    def _write_sig(self, digest):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self._sha_path(), 'w', encoding='utf-8') as f:
            f.write(digest + '\n')

    def rewrite(self, *_a, **_k):
        raise RuntimeError('账本只追加，不改写')

    def _append(self, rec):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        self.records.append(rec)
        self._write_sig(self.fingerprint())

    def memory_block(self):
        if self.tampered:
            return ('【可寻址记忆】账本指纹与启动记录不一致，'
                    '本轮不发放任何引用许可。')
        if not self.records:
            return ''
        lines = ['【可寻址记忆】先前已说出的地址和一句话断言。'
                 '看见不等于可以引用：证据词没有再次出现时，不要提它的地址。']
        for rec in self.records[-5:]:
            lines.append('- %s（%s，证据词「%s」）：%s'
                         % (rec['id'], rec.get('layer') or '?',
                            rec.get('term') or '', rec.get('assertion') or ''))
        return '\n'.join(lines)

    def _record(self, record_id):
        for rec in self.records:
            if rec.get('id') == record_id:
                return rec
        return None

    def arm_parent(self, record_id):
        """这一轮在几条枝里选用哪一句。生成之后由代码把新断言的 parent 记成它。"""
        if not self._record(record_id):
            raise KeyError(record_id)
        self.armed_id = record_id

    def retrieve_along_parent(self):
        """本轮若已指定枝，取那一句。否则沿最后一条记录的 parent。再否则只取最后一句。不返回兄弟句，不返回地址。"""
        if self.tampered or not self.records:
            self._used_id = None
            return ''
        if self.armed_id:
            rec = self._record(self.armed_id)
            if not rec:
                self._used_id = None
                return ''
            self._used_id = self.armed_id
            return (rec.get('assertion') or '').strip()
        last = self.records[-1]
        pid = last.get('parent')
        if pid:
            rec = self._record(pid)
            if not rec:
                self._used_id = None
                return ''
            self._used_id = pid
            return (rec.get('assertion') or '').strip()
        self._used_id = last.get('id')
        return (last.get('assertion') or '').strip()

    def _edge_prompt(self, sent, current):
        return (
            '她刚刚写下的一句，接在先前某一句下面。沿那条边，这里只取出那一句，别的句子没有放进来。\n'
            '先前那一句：%s\n\n'
            '刚刚这一句：%s\n\n'
            '用平常的话回应刚刚这一句，并把先前那一句里已经写下的具体事物说进来。'
            '不要编下一步。不要写编号。'
            % (sent, current or '')
        )

    def parent_turn_prompt(self, current):
        """显式沿边取句。实验和夹具调用。伴写的默认一轮不走这里。"""
        sent = self.retrieve_along_parent()
        if not sent:
            return ''
        return self._edge_prompt(sent, current)

    def armed_turn_prompt(self, current):
        """只有本轮已经指定父边，才替换作者看到的伴写提示。
        账本非空、最后一条带 parent、或最近一句，都不是指定。
        """
        if self.tampered or not self.armed_id:
            return ''
        rec = self._record(self.armed_id)
        if not rec:
            self._used_id = None
            return ''
        sent = (rec.get('assertion') or '').strip()
        if not sent:
            self._used_id = None
            return ''
        self._used_id = self.armed_id
        return self._edge_prompt(sent, current)

    def legacy_snippet_block(self, snippets):
        """对照臂：旧记忆形态，原文片段，没有地址。服务器不调用。"""
        lines = ['【记忆片段】']
        for i, s in enumerate(snippets or [], 1):
            lines.append('- 片段%d：%s' % (i, s))
        return '\n'.join(lines)

    def _licensed(self, verified):
        if self.tampered:
            return []
        terms = {f.get('term') for f in verified if f.get('kind') == '再出现'}
        return [r['id'] for r in self.records if r.get('term') and r['term'] in terms]

    def finish(self, model_text, author_text='', prior_text=''):
        used = self._used_id
        self._used_id = None
        self.armed_id = None
        parsed = parse_output(model_text)
        if self.tampered:
            return Decision(
                withhold=True, by='code', reason='账本指纹与启动记录不一致',
                layer_model=parsed['layer_model'])
        if parsed['verdict'] == 'no' or is_silence_body(parsed['body']):
            return Decision(
                withhold=True, by='model' if parsed['verdict'] == 'no' else 'code',
                reason='模型判决不说' if parsed['verdict'] == 'no' else '模型输出的是沉默标记',
                body=parsed['body'], layer_model=parsed['layer_model'])

        if self.max_spoken is not None and len(self.history) >= self.max_spoken:
            return Decision(
                withhold=True, by='code', reason='步数预算用尽',
                layer_model=parsed['layer_model'])

        if repeats_prior(parsed['body'], self.history):
            return Decision(
                withhold=True, by='code', reason='生成后自重复超过 %.2f' % REPEAT_T,
                layer_model=parsed['layer_model'])

        verified, rejected = verify_facts(parsed['facts'], author_text, prior_text)
        layer = route_layer(verified)
        if parsed['saw_fact'] and not verified:
            return Decision(
                withhold=True, by='code', reason='事实未能在文本中核对',
                rejected=rejected, layer_model=parsed['layer_model'])
        if not layer:
            # 没有事实块：格式漂移。按既定下一步降为 A，不采用自报层名。
            layer = 'A'
            reason_note = 'format_drift'
        else:
            reason_note = ''

        licensed = self._licensed(verified) if layer in ('B', 'C') else []
        body, stripped = strip_ids(parsed['body'], licensed if layer != 'A' else [])
        if layer == 'A':
            licensed = []
        if not body:
            return Decision(
                withhold=True, by='code', reason='核对后没有可出口的正文',
                rejected=rejected, layer_model=parsed['layer_model'],
                stripped=stripped)

        cited = _ADDR_RE.findall(body)
        parent = ''
        for cid in cited:
            if cid in licensed:
                parent = cid
                break
        if not parent and used and self._record(used):
            parent = used
        term = ''
        for f in verified:
            if f.get('term'):
                term = f['term']
                break
        assertion = re.split(r'[。！？\n]', body, maxsplit=1)[0][:80]
        rec = {
            'id': 'addr-%04d' % (len(self.records) + 1),
            'layer': layer,
            'term': term,
            'assertion': assertion,
            'parent': parent or None,
            'drift': reason_note,
        }
        self._append(rec)
        self.history.append(body)
        return Decision(
            withhold=False, by='code', reason=reason_note, layer=layer,
            body=body, layer_model=parsed['layer_model'], verified=verified,
            rejected=rejected, licensed=licensed, stripped=stripped,
            address=rec['id'], parent=parent)


SESSION = TreeSession()

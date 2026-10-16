# -*- coding: utf-8 -*-
"""棘轮校验点：候选补丁落地前，检查它有没有碰 frozen / forbidden_files。

## 它为什么存在

`params.json` 的 `ratchet_lock` 里写着"禁止触碰的东西"——D2/D7/D9 的存在本身、
作者原文、模型本身、作者侧的交互动作。但**这个键此前没有任何代码读取点**：
一个只在文档里成立的护栏，等于没有护栏。

而这个系统的改动路径是：改参数目前靠**手改**（没有代码写 `params.json`）。
所以这道闸防的不是老代码，是**下一步要接进来的自进化提案层**
（`LCR-双层自进化方案.md` 的 M2）。它只做一件事：
**候选补丁落地之前过一道闸；触碰即拒绝，并把拒绝本身写进只追加的账本。**

## 它拦什么

| 规则 | 拦的是 |
|---|---|
| `frozen` | 冻结项。D2/D7/D9 落在 `bans.<模式>.<键>`，改强度即拒；`author_final_veto` 落在任何与作者确认有关的字段。另有 `frozen_files`：`bans.py`/`metrics.py` 是禁令本体，补丁通道不许改 |
| `forbidden` | 作者原文 / 模型本身（按扩展名与目录拦）；作者侧交互动作特殊——`web/**` 不是一律禁，而是**要求声明 kind**，只放行 `ui-readonly-card`（§5.4 的语义收窄：不改交互动作，只允许只读说明卡片） |
| `self` | 改 `ratchet_lock` 或 `_comment` 自己。**这一条最要紧：不然锁能解锁、白名单能改写自己** |
| `whitelist` | 碰白名单之外的顶层键（`_comment` 写着"除这些之外不要改别的"） |
| `history` | 改 `_v3x` 历史条目（铁律：只追加，不改写） |
| `budget` | 单轮动机超过两样（§5.1 第 4 条） |
| `malformed` / `stale` | 提案本身不合格式；或 `from` 与现值不符（基线过期，等于闭着眼改） |

## 用法

    python v3/ratchet.py --check  提案.json   # 只校验 + 留痕
    python v3/ratchet.py --apply  提案.json   # 校验通过才写 params.json（原子替换 + 单槽备份）
    python v3/ratchet.py --audit              # 自查：映射是否齐全、冻结值有没有漂移
    python v3/ratchet.py --seal               # 审计 + 封存当前受保护面的指纹快照（人按的）
    python v3/ratchet.py --seal-auto          # 无人值守封存：只在「无基线 + 无漂移 + 配置无错」时写
    python v3/ratchet.py --selftest           # 内置用例

退出码：`0` 通过 · `2` 拒绝 · `3` 配置有问题（映射缺项，先修配置再谈别的）。

`--seal` 与 `--seal-auto` 的差别**不是有没有人看着**，而是写错了会怎样：

  `--seal`      人按的。启动器在按之前会明说"封存会把此刻当成新基线，包括
                它正检出的不正常"，按下去就是**明知而确认**——这是允许的。
  `--seal-auto` 装包/无人值守调的。它**拒绝**在三种情况下写：
                  ① 已有基线          —— 覆盖等于把上一段历史抹掉
                  ② 配置有错（映射缺项）—— 那会把残缺的当成基准
                  ③ 与上次基线有漂移    —— 那正是要留给人看的证据，不能自己消掉
                三种都把**拒绝本身**写进账本（kind=`seal-skip`），免得"没封"
                和"封了"在事后看起来一样。

封存行带 `origin` 字段记来源（`manual` / `install`）：事后翻账本时，
"这条基线是人确认过的"和"这条是安装器自己立的"不能长得一样。

提案格式（路径一律相对项目根，即 `v3/` 的上一级）：

    {
      "patch_id": "p_01",
      "hypothesis": "……",
      "evidence_ids": ["evt_8f2a1c", "evt_3d99aa"],
      "changes": [
        {"target": "sampling.temperature", "from": 0.3, "to": 0.25},
        {"file": "web/index.html", "kind": "ui-readonly-card", "note": "只读说明卡片"}
      ]
    }

`target` 走参数通道（点分路径），`file` 走文件通道——**每项只能有一个**。

## 它防不住什么（必须说清楚，别把它当万能闸）

它只拦走 `--apply` 的手。**直接手改 `params.json` 它拦不住**——那是检测问题不是
预防问题，交给 `--seal` + `--audit` 的漂移比对：改过就对不上指纹。
真要预防，得把"改参数"这件事整个收进 `--apply` 这一条路。
"""
import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # 项目根（dsh-伴写）
PARAMS = os.path.join(HERE, 'params.json')
LEDGER = os.path.join(HERE, 'logs', '棘轮审计.jsonl')

LOCK_KEY = 'ratchet_lock'
GUARD_KEY = 'guard'

RULE_TEXT = {
    'frozen': '冻结项',
    'forbidden': '禁改项',
    'self': '棘轮自锁',
    'whitelist': '白名单',
    'history': '只追加历史',
    'budget': '单轮预算',
    'malformed': '提案格式',
    'stale': '基线不符',
}

PASS, REJECT, CONFIG = 0, 2, 3


# ── 读取 ────────────────────────────────────────────────────────────
def load_params(path=None):
    with open(path or PARAMS, encoding='utf-8') as f:
        return json.load(f)


def load_lock(params=None):
    return (params or load_params()).get(LOCK_KEY) or {}


def load_guard(params=None):
    return load_lock(params).get(GUARD_KEY) or {}


def _norm(s):
    """路径规范化：反斜杠转正斜杠、去掉开头的 ./ ——提案里的路径一律相对项目根。"""
    s = str(s).strip().replace('\\', '/')
    while s.startswith('./'):
        s = s[2:]
    return s


def _match_any(patterns, s):
    """返回第一个命中的模式；没命中返回 None（把命中项也报出来，好排查）。"""
    for pat in patterns or []:
        if fnmatch.fnmatchcase(s, pat):
            return pat
    return None


def _v(rule, at, why):
    return {'rule': rule, 'at': at, 'why': why}


def _md5_bytes(b):
    return hashlib.md5(b).hexdigest()


def _md5_file(path):
    try:
        with open(path, 'rb') as f:
            return _md5_bytes(f.read())
    except OSError:
        return None


def writable_keys(params, guard=None):
    """可被补丁改动的顶层键 = 全部顶层键 − 不可变键 − 只追加前缀。"""
    g = guard if guard is not None else load_guard(params)
    imm = set(g.get('immutable_keys') or [])
    pres = tuple(g.get('immutable_prefixes') or [])
    return [k for k in params
            if k not in imm and not (pres and k.startswith(pres))]


# ── 配置自查：受保护的每一样都得有机器可读映射 ──────────────────────
def config_errors(params=None):
    """映射缺一项，这个键就又变回"只在文档里的护栏"了——所以缺项是硬错误。"""
    p = params if params is not None else load_params()
    lock, g = load_lock(p), load_guard(p)
    errs = []
    if not lock:
        return ['params.json 里没有 %s 键' % LOCK_KEY]

    ft = g.get('frozen_targets') or {}
    for name in lock.get('frozen') or []:
        if name not in ft:
            errs.append('冻结项「%s」没有机器可读映射（guard.frozen_targets 缺键）' % name)
    fg = g.get('forbidden_globs') or {}
    for name in lock.get('forbidden_files') or []:
        if name not in fg:
            errs.append('禁改项「%s」没有机器可读映射（guard.forbidden_globs 缺键）' % name)
    if not g.get('immutable_keys'):
        errs.append('guard.immutable_keys 缺失：没有它，补丁可以改 ratchet_lock 自己')
    if not g.get('frozen_files'):
        errs.append('guard.frozen_files 缺失：禁令本体（bans.py/metrics.py）将不受保护')
    return errs


# ── 校验 ────────────────────────────────────────────────────────────
def _check_target(t, p, g, violations):
    top = _norm(t).split('.')[0]
    imm = set(g.get('immutable_keys') or [])
    if top in imm:
        violations.append(_v('self', t,
                             '顶层键「%s」不可被补丁修改——棘轮不能自己松扣' % top))
        return
    for pre in g.get('immutable_prefixes') or []:
        if top.startswith(pre):
            violations.append(_v('history', t,
                                 '「%s…」是只追加的历史条目，只能新增、不能改写' % pre))
            return
    for name, pats in (g.get('frozen_targets') or {}).items():
        hit = _match_any(pats, _norm(t))
        if hit:
            violations.append(_v('frozen', t,
                                 '触碰冻结项「%s」（匹配 %s）' % (name, hit)))
            return
    allowed = writable_keys(p, g)
    if top not in allowed:
        violations.append(_v('whitelist', t,
                             '「%s」不在可调旋钮白名单内。白名单 = %s'
                             % (top, ' / '.join(sorted(allowed)))))


def _check_file(f, g, ch, violations, notes):
    f = _norm(f)
    if f in ('v3/params.json', 'params.json'):
        violations.append(_v('malformed', f,
                             '参数改动请用 target 指到具体键，不接受整文件替换'))
        return
    if f in [_norm(x) for x in (g.get('frozen_files') or [])]:
        violations.append(_v('frozen', f,
                             '「%s」是受保护文件（禁令本体／禁令判定器），'
                             '补丁通道不许改；确需改动请作者亲自来' % f))
        return
    kinds = g.get('ui_kind_allowed') or {}
    kind_key = _match_any(list(kinds), f)
    for name, pats in (g.get('forbidden_globs') or {}).items():
        hit = _match_any(pats, f)
        if not hit:
            continue
        if kind_key:
            # 唯一带出口的禁改项：只读说明卡片。声明了且声明对了才放行。
            allow = kinds[kind_key]
            k = ch.get('kind')
            if not k:
                violations.append(_v('forbidden', f,
                                     '「%s」须声明 kind，且只能是 %s——'
                                     '不声明等于默认它是交互改动' % (f, '/'.join(allow))))
            elif k not in allow:
                violations.append(_v('forbidden', f,
                                     'kind=%s 不在允许之列（%s）' % (k, '/'.join(allow))))
            else:
                notes.append('%s（kind=%s）已放行，但文件改动需人工落地，--apply 不代写'
                             % (f, k))
        else:
            violations.append(_v('forbidden', f,
                                 '触碰禁改项「%s」（匹配 %s）' % (name, hit)))
        return


def check_patch(patch, params=None):
    p = params if params is not None else load_params()
    g = load_guard(p)
    rep = {
        'ok': True, 'patch_id': patch.get('patch_id'),
        'violations': [], 'notes': [], 'checked': 0,
        'config_errors': config_errors(p),
        'patch_sha256': hashlib.sha256(
            json.dumps(patch, ensure_ascii=False, sort_keys=True)
            .encode('utf-8')).hexdigest()[:16],
    }
    if rep['config_errors']:
        rep['ok'] = False
        return rep

    changes = patch.get('changes')
    if not isinstance(changes, list) or not changes:
        rep['violations'].append(_v('malformed', '(提案)',
                                    'changes 必须是非空列表'))
        rep['ok'] = False
        return rep

    for i, ch in enumerate(changes, 1):
        rep['checked'] += 1
        if not isinstance(ch, dict):
            rep['violations'].append(_v('malformed', '第%d项' % i, 'change 必须是对象'))
            continue
        has_t, has_f = bool(ch.get('target')), bool(ch.get('file'))
        if has_t == has_f:
            rep['violations'].append(_v(
                'malformed', ch.get('target') or ch.get('file') or '第%d项' % i,
                '每项必须且只能给一个 target（参数路径）或 file（文件路径）'))
            continue
        if has_t:
            _check_target(ch['target'], p, g, rep['violations'])
        else:
            _check_file(ch['file'], g, ch, rep['violations'], rep['notes'])

    # §5.1 第 4 条：每次最多调两样。只数参数通道的旋钮改动。
    mx = g.get('max_changes_per_round')
    knobs = [c for c in changes if isinstance(c, dict) and c.get('target')]
    if mx and len(knobs) > mx:
        rep['violations'].append(_v(
            'budget', '、'.join(str(c['target']) for c in knobs),
            '单轮改 %d 处旋钮，超过「每次最多调两样」（§5.1）' % len(knobs)))

    rep['ok'] = not rep['violations']
    return rep


# ── 留痕（只追加，永不改写）─────────────────────────────────────────
def record(rep, ledger=None, kind='check', extra=None):
    path = ledger or LEDGER
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    row = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'kind': kind,
        'patch_id': rep.get('patch_id'),
        'ok': rep.get('ok'),
        'checked': rep.get('checked'),
        'patch_sha256': rep.get('patch_sha256'),
        'violations': rep.get('violations') or [],
        'config_errors': rep.get('config_errors') or [],
    }
    if extra:
        row.update(extra)
    with open(path, 'a', encoding='utf-8') as f:      # 'a' —— 铁律：只追加
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


# ── 应用（唯一被许可的写参数路径）───────────────────────────────────
def _get_path(obj, dotted):
    cur = obj
    for part in _norm(dotted).split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_path(obj, dotted, value):
    parts = _norm(dotted).split('.')
    cur = obj
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            return False
        cur = cur[part]
    cur[parts[-1]] = value
    return True


def apply_patch(patch, params_path=None, ledger=None):
    path = params_path or PARAMS
    p = load_params(path)
    rep = check_patch(patch, params=p)

    # 值校验：from 对不上就说明提案是对着旧参数写的，闭着眼改比不改更坏。
    for ch in patch.get('changes') or []:
        if not isinstance(ch, dict) or not ch.get('target'):
            continue
        cur = _get_path(p, ch['target'])
        if 'from' in ch and ch['from'] != cur:
            rep['violations'].append(_v(
                'stale', ch['target'],
                'from=%r 与现值 %r 不符，提案基线已过期' % (ch['from'], cur)))
    rep['ok'] = not rep['violations'] and not rep['config_errors']

    if not rep['ok']:
        return rep                      # 拒绝 —— 一个字节都不写

    before = _md5_file(path)
    shutil.copy(path, path + '.bak')    # 单槽备份，与 server.py 的 config 写法一致
    for ch in patch.get('changes') or []:
        if ch.get('target'):
            _set_path(p, ch['target'], ch['to'])
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, path)               # 原子替换
    rep['params_md5_before'] = before
    rep['params_md5_after'] = _md5_file(path)
    rep['applied'] = [c['target'] for c in patch.get('changes') or []
                      if isinstance(c, dict) and c.get('target')]
    return rep


# ── 审计：受保护面的当前状态 + 与上次封存比漂移 ──────────────────────
def fingerprint(params=None):
    p = params if params is not None else load_params()
    g = load_guard(p)
    values = {}
    for name, pats in (g.get('frozen_targets') or {}).items():
        if not (name.startswith('D') and name[1:2].isdigit()):
            continue
        for mode in ('P', 'M', 'S'):
            for pat in pats:
                parts = _norm(pat).split('.')
                if len(parts) == 3 and parts[0] == 'bans':
                    values['bans.%s.%s' % (mode, name)] = \
                        ((p.get('bans') or {}).get(mode) or {}).get(name)
    files = {}
    for f in g.get('frozen_files') or []:
        fp = os.path.join(ROOT, _norm(f))
        files[_norm(f)] = _md5_file(fp) if os.path.exists(fp) else None
    # 锁本体的指纹。少了它有个洞：手改可以把**冻结项和它的映射一起删掉**，
    # 那样 config_errors 全过、值也全 strict，却是护得更少——必须能被看出来。
    lock_md5 = hashlib.md5(
        json.dumps(p.get(LOCK_KEY) or {}, ensure_ascii=False, sort_keys=True)
        .encode('utf-8')).hexdigest()
    return {'frozen_values': values, 'frozen_files': files, 'lock_md5': lock_md5}


def last_seal(ledger=None):
    path = ledger or LEDGER
    if not os.path.exists(path):
        return None
    seal = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('kind') == 'seal':
                seal = row
    return seal


def _bans_frozen():
    """bans.py 里还有一份 FROZEN 列表——两份不一致就是有人在偷偷动它。"""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import bans                                                  # noqa: E402
        return list(getattr(bans, 'FROZEN', []) or [])
    except Exception as e:                                           # noqa: BLE001
        return ['(读不到 bans.py：%s)' % e]


def audit(params_path=None, ledger=None, do_seal=False, origin='manual', auto=False):
    p = load_params(params_path)
    g = load_guard(p)
    out = {'ok': True, 'config_errors': config_errors(p),
           'checks': [], 'drift': []}
    ck = out['checks']

    # 1) 冻结项在每个模式下都必须还是 strict
    for name in [n for n in (load_lock(p).get('frozen') or [])
                 if n.startswith('D') and n[1:2].isdigit()]:
        for mode in ('P', 'M', 'S'):
            val = ((p.get('bans') or {}).get(mode) or {}).get(name)
            ok = (val == 'strict')
            ck.append({'check': 'bans.%s.%s == strict' % (mode, name), 'ok': ok,
                       'got': val})
            if not ok:
                out['ok'] = False

    # 2) bans.py 的 FROZEN 必须是 ratchet_lock.frozen 的子集
    bf = _bans_frozen()
    declared = list(load_lock(p).get('frozen') or [])
    missing = [x for x in bf if x not in declared]
    ck.append({'check': 'bans.FROZEN ⊆ ratchet_lock.frozen', 'ok': not missing,
               'got': missing or 'ok'})
    if missing:
        out['ok'] = False

    # 3) 与上次封存比漂移
    fp = fingerprint(p)
    seal = last_seal(ledger)
    if seal is None:
        ck.append({'check': '上次封存快照', 'ok': True, 'got': '无（跑 --seal 建一个）'})
    else:
        for k, v in (seal.get('frozen_values') or {}).items():
            if fp['frozen_values'].get(k) != v:
                out['drift'].append('%s: %r → %r' % (k, v, fp['frozen_values'].get(k)))
        for k, v in (seal.get('frozen_files') or {}).items():
            if fp['frozen_files'].get(k) != v:
                out['drift'].append('%s: %s → %s' % (k, v, fp['frozen_files'].get(k)))
        if seal.get('lock_md5') and seal['lock_md5'] != fp['lock_md5']:
            out['drift'].append('ratchet_lock 本体被改过（%s → %s）'
                                % (seal['lock_md5'][:8], fp['lock_md5'][:8]))
        # 把来源写进这一行：启动器详情框在"没漂移"时正好只显示这里两行，
        # 于是"这条基线是安装器替你签的、还是你自己按的"一眼可见。
        ck.append({'check': '与 %s 的快照比对（基线来源：%s）'
                            % (seal.get('ts'), seal.get('origin') or '未记来源'),
                   'ok': not out['drift'],
                   'got': '无漂移' if not out['drift'] else out['drift']})
        if out['drift']:
            out['ok'] = False

    if out['config_errors']:
        out['ok'] = False

    if do_seal:
        # auto=True 是"无人值守封存"（装包时调）：它比人按的那一下保守得多。
        # 人不在这里，没人能对"把此刻当成基线"这件事点头，所以三种情况一律不写。
        why = None
        if auto:
            # 判据是"审计整体通过"，不是"映射齐不齐"。少了 not out['ok'] 这一条，
            # 会出现最坏的一种封存：**没有基线、而冻结项已经被改成 loose** ——
            # 比不出漂移（没有基线），映射也齐全，于是它高高兴兴把"护栏已经松了"
            # 的现状封成基准，从此再没有东西可比。（这是写完之后自己踩出来的。）
            if out['config_errors']:
                why = '护栏配置有错（%s），不封存' % '；'.join(out['config_errors'][:2])
            elif not out['ok']:
                why = '审计未通过（%s），不封存' % (
                    '；'.join(out['drift']) or '冻结项/禁令本体与护栏声明不符')
            elif seal is not None:
                why = '已有基线（%s）——自动封存不覆盖' % seal.get('ts')
        if why:
            out['sealed'] = False
            out['seal_skipped'] = why
            # 只在"本来会写错"的时候留痕（审计没过 / 配置有错）。干净的
            # "已有基线、没漂移"不留——那种行会让账本里每一条都得读完才知道
            # 有没有事，而只追加的账本，价值就在"每行都发生过什么"。
            if auto and (out['config_errors'] or not out['ok']):
                rep = {'patch_id': '(seal-auto)', 'ok': out['ok'], 'checked': 0,
                       'patch_sha256': None, 'config_errors': out['config_errors'],
                       'violations': []}
                record(rep, ledger, kind='seal-skip',
                       extra={'origin': origin, 'reason': why})
        else:
            rep = {'patch_id': '(seal)', 'ok': out['ok'], 'checked': 0,
                   'patch_sha256': None, 'config_errors': out['config_errors'],
                   'violations': []}
            # kind 只能是 'seal'：last_seal 只认这一个 kind，错一个字母，
            # 一条"没封"的行就会被当成基线，从此比不出漂移。
            record(rep, ledger, kind='seal', extra=dict(fp, origin=origin))
            out['sealed'] = True
            out['seal_origin'] = origin
    return out


# ── 输出 ────────────────────────────────────────────────────────────
def render(rep, write=sys.stdout.write):
    if rep.get('config_errors'):
        head = '[配置]'
    else:
        head = '[OK]' if rep.get('ok') else '[拒绝]'
    write('%s 提案 %s ｜ 检查 %d 处改动 ｜ 指纹 %s\n'
          % (head, rep.get('patch_id') or '(无 id)', rep.get('checked') or 0,
             rep.get('patch_sha256') or '-'))
    for e in rep.get('config_errors') or []:
        write('   [配置] %s\n' % e)
    for v in rep.get('violations') or []:
        write('   [拒绝/%s] %s\n      %s\n'
              % (RULE_TEXT.get(v['rule'], v['rule']), v['at'], v['why']))
    for n in rep.get('notes') or []:
        write('   [注] %s\n' % n)
    if rep.get('applied'):
        write('   已写入：%s（参数 %s → %s）\n'
              % ('、'.join(rep['applied']), rep.get('params_md5_before'),
                 rep.get('params_md5_after')))


# ── 内置用例（包内也能自检，不依赖 _验收/ 目录）─────────────────────
_SELF_CASES = [
    ('合法参数补丁', {'patch_id': 'ok', 'changes': [
        {'target': 'sampling.temperature', 'to': 0.25}]}, True),
    ('碰冻结 D9', {'patch_id': 'f1', 'changes': [
        {'target': 'bans.M.D9_no_flow_interrupt', 'to': 'loose'}]}, False),
    ('碰冻结文件 bans.py', {'patch_id': 'f2', 'changes': [
        {'file': 'v3/bans.py', 'note': '改 D 规则文案'}]}, False),
    ('改锁自身', {'patch_id': 's1', 'changes': [
        {'target': 'ratchet_lock.frozen', 'to': []}]}, False),
    ('改白名单注释', {'patch_id': 's2', 'changes': [
        {'target': '_comment', 'to': '随便改'}]}, False),
    ('改历史条目', {'patch_id': 'h1', 'changes': [
        {'target': '_v32', 'to': '改写历史'}]}, False),
    ('作者原文', {'patch_id': 'a1', 'changes': [
        {'file': '小说.docx', 'kind': 'ui-readonly-card'}]}, False),
    ('交互卡片声明对', {'patch_id': 'u1', 'changes': [
        {'file': 'web/index.html', 'kind': 'ui-readonly-card'}]}, True),
    ('交互卡片不声明', {'patch_id': 'u2', 'changes': [
        {'file': 'web/index.html'}]}, False),
    ('超预算三样', {'patch_id': 'b1', 'changes': [
        {'target': 'sampling.temperature', 'to': 0.1},
        {'target': 'sampling.top_p', 'to': 0.9},
        {'target': 'classifier.threshold.P_max', 'to': 0.4}]}, False),
]


def selftest():
    """用临时 params 副本跑，绝不碰真实配置。"""
    with tempfile.TemporaryDirectory() as td:
        pp = os.path.join(td, 'params.json')
        lg = os.path.join(td, '审计.jsonl')
        shutil.copy(PARAMS, pp)
        p = load_params(pp)
        bad = 0
        for name, patch, want in _SELF_CASES:
            rep = check_patch(patch, params=p)
            got = rep['ok']
            flag = '[OK]' if got == want else '[不合]'
            if got != want:
                bad += 1
            print('   %s %-18s 期望%s 实得%s%s'
                  % (flag, name, '通过' if want else '拒绝',
                     '通过' if got else '拒绝',
                     '' if got == want else '  ← ' +
                     '；'.join(v['rule'] for v in rep['violations'])))
            record(rep, lg, kind='selftest')
        rows = sum(1 for _ in open(lg, encoding='utf-8'))
        ok_ledger = (rows == len(_SELF_CASES))
        if not ok_ledger:
            bad += 1
        print('   %s 账本留痕          %d 条（应 %d）'
              % ('[OK]' if ok_ledger else '[不合]', rows, len(_SELF_CASES)))
        # 拒绝的补丁没写盘
        same = _md5_file(pp) == _md5_file(PARAMS)
        if not same:
            bad += 1
        print('   %s 参数未被改动      %s'
              % ('[OK]' if same else '[不合]', _md5_file(pp)))
    print('\n内置用例：%d 条，不合 %d 条' % (len(_SELF_CASES) + 2, bad))
    return PASS if bad == 0 else REJECT


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='棘轮校验点：候选补丁应用前检查 frozen / forbidden_files')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', metavar='提案.json', help='只校验并留痕')
    g.add_argument('--apply', metavar='提案.json', help='校验通过才写入 params.json')
    g.add_argument('--audit', action='store_true', help='自查映射完整性与冻结值漂移（不封存）')
    g.add_argument('--seal', action='store_true', help='审计并封存当前受保护面指纹（人按的）')
    g.add_argument('--seal-auto', dest='seal_auto', action='store_true',
                   help='无人值守封存：只在「无基线 + 无漂移 + 配置无错」时写')
    g.add_argument('--selftest', action='store_true', help='跑内置用例')
    ap.add_argument('--params', help='params.json 路径（默认 v3/params.json）')
    ap.add_argument('--ledger', help='账本路径（默认 v3/logs/棘轮审计.jsonl）')
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    if a.audit or a.seal or a.seal_auto:
        auto = bool(getattr(a, 'seal_auto', False))
        out = audit(a.params, a.ledger, do_seal=(a.seal or auto),
                    origin='install' if auto else 'manual', auto=auto)
        for c in out['checks']:
            print('   %s %-34s %s' % ('[OK]' if c['ok'] else '[不合]',
                                      c['check'], c['got']))
        for e in out['config_errors']:
            print('   [配置] %s' % e)
        if out.get('sealed'):
            print('   已封存指纹（来源：%s）' % out.get('seal_origin'))
        elif out.get('seal_skipped'):
            print('   未封存 —— %s' % out['seal_skipped'])
        print('\n审计：%s' % ('通过' if out['ok'] else '有问题'))
        return PASS if out['ok'] else (CONFIG if out['config_errors'] else REJECT)

    try:
        with open(a.check or a.apply, encoding='utf-8') as f:
            patch = json.load(f)
    except (OSError, ValueError) as e:
        print('[配置] 提案读不进来：%s' % e)
        return CONFIG

    if a.check:
        rep = check_patch(patch, params=load_params(a.params) if a.params else None)
        if not rep['config_errors']:
            record(rep, a.ledger, kind='check')
        render(rep)
        if rep['config_errors']:
            return CONFIG
        return PASS if rep['ok'] else REJECT

    rep = apply_patch(patch, a.params, a.ledger)
    if not rep['config_errors']:
        record(rep, a.ledger, kind='apply',
               extra={'applied': rep.get('applied') or [],
                      'params_md5_before': rep.get('params_md5_before'),
                      'params_md5_after': rep.get('params_md5_after')})
    render(rep)
    if rep['config_errors']:
        return CONFIG
    return PASS if rep['ok'] else REJECT


if __name__ == '__main__':
    sys.exit(main())

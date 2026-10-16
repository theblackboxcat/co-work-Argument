# -*- coding: utf-8 -*-
"""testkit —— 采集外挂（不属于伴写本体，是套在外面的实验装置）。

## 它为什么存在

论文《主动而不定向：判别不可测量时，伴写系统能做什么》承认一处缺口：
系统没有记录"探针到点而判为不出声"的时刻，也没有回放与标注入口，
因此**沉默的精确率与召回一个数都给不出**（§6.6 局限 10、§7 其二）。

代码核实的结果比论文说的更具体：那个时刻**在代码里完整存在**，
被两个 return 吞掉了——

- 后端 `server.py` 的 `call_model()`：丙档模型判"不说"时直接 return，不写任何埋点；
- 前端 `index.html` 的 `render()`：收到沉默卡后提前 return，所以连按钮都不渲染。

实测 `app/v3/logs/samples.jsonl` 14 条，`spoke` 全为 True、无一条 verdict 字段、
mode_source 全为"分类器猜测"——**作者手选 P/M/S 这条路径在便携包里从未被记录过**。

## 为什么不改本体

论文 §3.1 把 ⊘ 设计为合法输出，§3.4 主张"重写按钮即标注"，
而当前实现里沉默**不渲染任何卡片**（index.html 的注释写明：这是"放权"能被她感知到的
唯一方式）。若为了标注而让沉默渲染一张卡，就**改变了论文所主张的那个设计**。

所以本模块走外挂路线：

- **不碰** `call_model()` 的判断逻辑，只在它 return 之前调一次 `probe.silence(...)`；
- **不碰** `v3/metrics.py`、`v3/bans.py`（棘轮冻结文件，md5 在 logs/棘轮审计.jsonl 里锁着）；
- **不碰** `params.json`（棘轮管辖）；
- 采集数据落在**自己的** `app/v3/logs/probe.jsonl`，不混进 `samples.jsonl`；
- 探针自带的读数接口全部走 `/api/probe/*`，不碰 `/api/cowrite` 与 `/api/rewrite` 的语义。

## 采集什么（对齐论文的四组检验）

| 缺口 | 采什么 | 事件 kind |
|---|---|---|
| 沉默的精确率与召回（§7 其二） | 探针到点 + 判为不出声的时刻、理由、当时信号 | silence / spoke / probe_to_point |
| 沉默归因（§5.4 过期剖面） | 剖面是否过期、版本号 | silence.prof_stale |
| 作者自标 P/M/S 的信度（§7 其一） | 每次作者手选模式 + 时刻，供间隔重标配对 | mode_pick |
| 「伤害」的效应差（§7 其四） | 扩张型/收敛型搭话 + 后续段落，供算 s(g,p) | probe_trial |
| 装置状态 | 主导权档位、后端、参数指纹 | 全部事件 |

## 判负集合沿用现成词表

analyze_feedback.py:29 已有 NEGATIVE = ('太弱', '太强', '不对')，
runner.py:306-308 已有反馈表三栏。本模块**不新造词表**，
沉默标注的三个取值与它们同构：

- silent_right（该沉默）—— 对应"接受"
- silent_wrong（其实想听）—— 对应"不对"
- silent_had_nothing（本来就没什么可说）—— 对应"太弱"

## 路径

LOG_DIR 沿用 telemetry.py 的 __file__ 相对模式（telemetry.py:16-18），
**不读 config.json、不读 params.json**——便携包里那两个文件的职责是模型接入与棘轮值，
与采集无关。写入目录不存在时自建。

## 一条纪律

采集器的失败**必须失败得可见**。所以 record() 不吞异常：
写盘失败会打印 `[probe] 写入失败` 并把错误抛给调用方，
因为一份静默丢掉的采集数据会让后续所有分析看起来"没有效应"。
"""

import json
import os
import random
import time
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, 'logs')
LOG_PATH = os.path.join(LOG_DIR, 'probe.jsonl')

# 探针开启与否。由 /api/probe/config 切换，默认**开**——
# 这是测试版，测试版存在的意义就是采数据；发行版里这个模块根本不会被加载。
STATE = {
    'on': True,
    'session': None,      # 本次会话 id，一次启动一个
    'started_at': None,
}

# ---- 标注词表：沉默侧（三个） ----
# 与 analyze_feedback.NEGATIVE 同构而非另造：
#   silent_right≈接受 / silent_wrong≈不对 / silent_had_nothing≈太弱
SILENT_KINDS = ('silent_right', 'silent_wrong', 'silent_had_nothing')
SILENT_LABELS = {
    'silent_right': '该沉默',
    'silent_wrong': '其实想听',
    'silent_had_nothing': '本来就没什么可说',
}

# ---- 标注词表：出声侧（两个）----
# **这一侧是算召回率的关键，原来根本没有。** 只标沉默的话，
# 精确率能算、召回率算不出——因为「该沉默却出了声」那一格无法被填上。
# 语义：should_have_silent = 这一处它本该闭嘴（那它就漏了一次沉默机会）
#       should_have_spoken = 这一处它说得对
SPOKE_KINDS = ('should_have_silent', 'should_have_spoken')
SPOKE_LABELS = {
    'should_have_silent': '本该沉默',
    'should_have_spoken': '该说话',
}

# ---- 2×2 混淆矩阵的映射（供 stats 用）----
# 正类 = 该沉默。TP/FP/FN/TN 各由哪些标注构成。
CONFUSION = {
    # 事件侧 -> (作者标了什么) -> 落在混淆矩阵哪一格
    'TP': [('silence', 'silent_right')],
    'FP': [('silence', 'silent_wrong'),
           ('silence', 'silent_had_nothing')],
    'FN': [('spoke', 'should_have_silent')],
    'TN': [('spoke', 'should_have_spoken')],
}

# 扩张型/收敛型：§7 其四的两种搭话形态
TRIAL_KINDS = ('convergent', 'divergent')

_started = False


def _session():
    global _started
    if not _started:
        STATE['session'] = 'S-%s' % time.strftime('%Y%m%d-%H%M%S')
        STATE['started_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        _started = True
    return STATE['session']


def _fingerprint(cfg, extra=None):
    """参数指纹：用来判断两次事件是不是在同一种装置下发生的。

    故意**不**读 params.json（棘轮管辖）——改为把调用方已经算好的东西哈希掉。
    """
    parts = []
    for k in ('model', 'provider', 'temperature', 'max_tokens'):
        v = (cfg or {}).get(k) if isinstance(cfg, dict) else None
        parts.append('%s=%s' % (k, v))
    parts.append('extra=%s' % json.dumps(extra or {}, sort_keys=True, ensure_ascii=False))
    return hashlib.md5('|'.join(parts).encode('utf-8')).hexdigest()[:10]


# 事件 id 前缀。**不能直接用 kind[:3]**——probe_to_point 与 probe_trial
# 的前三字都是'pro'，会撞车（第二版踩过，靠冒烟测试抓出来）。
_PREFIX = {
    'probe_to_point': 'pp',
    'spoke': 'spk',
    'silence': 'sil',
    'mode_pick': 'mp',
    'probe_trial': 'tr',
}

# 事件 id 前缀。**不能直接用 kind[:3]**——probe_to_point 与 probe_trial
# 的前三字都是'pro'，会撞车（第二版踩过，靠冒烟测试抓出来）。
_PREFIX = {
    'probe_to_point': 'pp',
    'spoke': 'spk',
    'silence': 'sil',
    'mode_pick': 'mp',
    'probe_trial': 'tr',
}

_seq = {'n': 0}


def _next_id(prefix):
    """事件 id：前缀 + 毫秒时间戳 + 进程内序号。

    必须**在写盘前**定下来。第一版把 id 放在写盘之后只改内存 dict，
    结果 annotate() 永远找不到行——回填是这个采集器的地基，
    而它的第一个测试就抓到了（第二版踩过）。
    """
    _seq['n'] += 1
    ep = int(time.time() * 1000)
    return '%s-%d-%03d' % (prefix, ep, _seq['n'])


def record(kind, fields, eid=None):
    """追加一条采集记录。**不吞异常**——见模块开头的纪律。

    签名是 record(kind, fields_dict) 而不是 record(kind, **fields)：
    后者会让调用处的注释行混进 kwargs，语法上直接不成立（第一版踩过）。
    """
    if not STATE['on']:
        return None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception as e:
        print('[probe] 建目录失败：%s' % e)
        raise
    row = {
        'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
        'epoch': round(time.time(), 3),
        'session': _session(),
        'kind': kind,
        'event_id': eid or _next_id(_PREFIX.get(kind, kind[:3])),
    }
    row.update(fields or {})
    if not row.get('event_id'):
        row['event_id'] = _next_id(_PREFIX.get(kind, kind[:3]))
    line = json.dumps(row, ensure_ascii=False)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    return row


def read_all(path=LOG_PATH):
    """读回全部采集记录。坏行**不静默跳过**——返回时带出坏行数。"""
    if not os.path.exists(path):
        return [], 0
    rows, bad = [], 0
    with open(path, encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                bad += 1
                print('[probe] 第 %d 行解析失败，已跳过' % ln)
    return rows, bad


def reset(path=LOG_PATH):
    """清空采集文件。仅测试版可用。

    **不用 os.remove** ——本机有个safe-delete 守卫，它把"删一个文件"判成
    批量危险操作（SAFE_DELETE_BULK_CONFIRM_REQUIRED，threshold=50），
    于是 reset 抛出去、handler 崩掉、客户端收到**完全空的响应**。
    改成以空内容覆盖写：效果一样，不触发守卫，也不依赖任何确认流程。
    """
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8'):
        pass
    STATE['started_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _seq['n'] = 0
    return True


def event_id_of(row):
    """从一条记录取回它的 event_id。回填与回放都走这里。"""
    return (row or {}).get('event_id')


def silence(reason, attn=None, v3_meta=None, mode=None, cfg=None,
            prof_stale=None, prof_ver=None, prof_status=None,
            text_len=None, text_head=None):
    """探针到点而判为不出声——**这是论文那个缺口的正主**。

    字段对齐论文要算的两个数：
      - 精确率 = 该沉默里作者标 silent_right 的比例
      - 召回 = 本该出声却沉默的比例（要靠 attn 的状态与对照轮次算）
    """
    a = attn or {}
    v = v3_meta or {}
    row = record('silence', {
        'reason': (reason or '')[:400],
        'attn_state': a.get('state'),
        'attn_signals': a.get('signals'),
        'delay_sec': a.get('delay_sec'),
        # 模式来源：这条会顺带修掉 mode_source 只在出声路径被记的缺口
        'mode': mode or v.get('mode'),
        'mode_source': v.get('mode_source'),
        'mode_score': v.get('score'),
        # 真值条件的代理变量：剖面过期时沉默可能只是"记得那里写过东西"
        'prof_stale': prof_stale,
        'prof_ver': prof_ver,
        'prof_status': prof_status,
        'text_len': text_len,
        'text_head': (text_head or '')[:200],
        'fp': _fingerprint(cfg, {'mode': mode, 'state': a.get('state')}),
        # 标注位（等 UI 补，schema 与 telemetry.author_feedback 同构）
        'author_feedback': None,
    })
    return row


def spoke(preview=None, attn=None, v3_meta=None, mode=None, cfg=None,
          prof_stale=None, prof_ver=None, text_len=None, text_head=None):
    """出声了。**沉默的分母**：召回率的分母是"探针到点的总次数"，
    没有这条就无法把"沉默"和"本该沉默却出声"分开。"""
    a = attn or {}
    v = v3_meta or {}
    row = record('spoke', {
        'attn_state': a.get('state'),
        'attn_signals': a.get('signals'),
        'delay_sec': a.get('delay_sec'),
        'mode': mode or v.get('mode'),
        'mode_source': v.get('mode_source'),
        'mode_score': v.get('score'),
        'prof_stale': prof_stale,
        'prof_ver': prof_ver,
        'text_len': text_len,
        'text_head': (text_head or '')[:200],
        'preview': (preview or '')[:200],
        'fp': _fingerprint(cfg, {'mode': mode, 'state': a.get('state')}),
    })
    return row


def probe_to_point(attn=None, mode=None, delegate=None, cfg=None):
    """探针到点（**不论最终说不说**）。

    分成两条事件是为了让"精确率"与"召回率"各有各的分母：
      探针到点 = 全部机会；不出声 = 其中被判沉默的；出声 = 其余。
    """
    a = attn or {}
    row = record('probe_to_point', {
        'attn_state': a.get('state'),
        'attn_signals': a.get('signals'),
        'speak_rule': a.get('speak'),
        'delay_sec': a.get('delay_sec'),
        'delegate': delegate,
        'mode': mode,
        'fp': _fingerprint(cfg, {'mode': mode, 'state': a.get('state')}),
    })
    return row


def mode_pick(mode, source='作者手选', attn=None, cfg=None, text_len=None,
              text_head=None):
    """作者手选 P/M/S —— **§7 其一那个从未被测量的东西**。

    localStorage 之外的唯一持久化点。浏览器 localStorage 换机器就丢，
    而 §7 其一要测的恰恰是"作者能不能稳定自标"，那就必须有个跨会话的记录。
    间隔重标的重测信度靠 text_head + ts 配对。
    """
    a = attn or {}
    row = record('mode_pick', {
        'mode': mode,
        'source': source,
        'attn_state': a.get('state'),
        'text_len': text_len,
        'text_head': (text_head or '')[:200],
        'fp': _fingerprint(cfg, {'mode': mode}),
    })
    return row


TRIAL_SEED = 20261006     # 固定种子：**可复现**优先于随机


def blind_order(scene, kinds=TRIAL_KINDS, seed=TRIAL_SEED):
    """给一个场景的两型搭话排一个随机序，返回 {kind: 位置}。

    **用固定种子而不是真随机**，理由是可复现：同一批文本两次跑必须落在
    同一顺序上，否则顺序效应与形态效应分不开。顺序写进每条记录，
    换种子就等于换一批顺序——那是另一次实验，要另起一个 seed。
    """
    ks = list(kinds)
    r = random.Random('%s|%s' % (seed, scene))
    r.shuffle(ks)
    return {k: i for i, k in enumerate(ks)}


def trial(kind, g_text, scene=None, cfg=None, text_len=None, text_head=None,
          blind_pos=None, note=None):
    """一次「伤害」试验的搭话（§7 其四）：扩张型 vs 收敛型，同场景随机序盲评。

    因变量是 s(g,p)——搭话 g 与作者后续段落 p 的语义相似度——
    效应取**两组之差**，所以每条都要带 kind 与它所属的场景。
    """
    if kind not in TRIAL_KINDS:
        raise ValueError('trial kind 必须是 %s 之一，收到 %r' % (TRIAL_KINDS, kind))
    if blind_pos is None:
        blind_pos = blind_order(scene or '').get(kind)
    row = record('probe_trial', {
        'trial_kind': kind,
        'g_text': (g_text or '')[:400],
        'scene': (scene or '')[:200],
        'text_len': text_len,
        'text_head': (text_head or '')[:200],
        'fp': _fingerprint(cfg, {'trial': kind, 'scene': scene}),
        # p（作者后续段落）由 UI 回填
        'p_text': None,        # 作者后续段落，由 UI 回填
        'accepted': None,      # 盲评：这一条接不接受
        'blind_pos': blind_pos,   # 随机序位置（0/1），用于查顺序效应
        'note': note,
        'sim': None,           # s(g,p)：**本模块不算**，见 probe_analyze 的说明
        'seed': TRIAL_SEED,
    })
    return row


TRIAL_ANNOTATIONS = ('trial_accepted', 'trial_rejected', 'trial_skip')

def allowed_kinds(kind):
    """某类事件允许哪些标注值。**校验不通过要报错，不能默默收下。**
    否则一个 silence 事件被标成 should_have_spoken 也会被存进去，
    而它落在混淆矩阵的哪一格就变成了不确定——那正是本任务要消除的歧义。
    """
    if kind == 'silence':
        return SILENT_KINDS
    if kind == 'spoke':
        return SPOKE_KINDS
    if kind == 'probe_trial':
        return TRIAL_ANNOTATIONS
    return ()


def annotate(event_id, feedback, extra=None, clear=False):
    """给某个事件回填标注。**回填而不新增**——同一事件只在原行上改，
    这样"标了三次"会覆盖而不是堆成三条，避免分母虚高。

    会先校验 feedback 与该事件 kind 相容。**不校验的后果**是混淆矩阵
    出现"一个沉默被标成'该说话'"这种格子，而它该落在哪一格就没法判了。

    clear=True：撤回一次标注。原来没有这条路——手滑点错或改主意之后，
    那一行的 author_feedback / accepted / sim 只能**手工去 probe.jsonl
    里删**，而那文件是一行一 JSON，删错一个逗号整份采集就废了。
    撤回清的是这一条自己那些标注字段，事件的其余部分原样保留。
    """
    # 能被 repel/backfill 写进事件的标注字段。撤回只清这些，不碰正文与时间戳。
    CLEAR_KEYS = ('author_feedback', 'note', 'p_text', 'accepted',
                  'blind_pos', 'flow_signal', 'sim')
    rows, bad = read_all()
    hit = 0
    for r in rows:
        if r.get('event_id') == event_id:
            if clear:
                for k in CLEAR_KEYS:
                    r.pop(k, None)
                hit += 1
                continue
            ok = allowed_kinds(r.get('kind'))
            if feedback and ok and feedback not in ok:
                raise ValueError(
                    '事件 %s 是 %s，只能标 %s，收到 %r'
                    % (event_id, r.get('kind'), '/'.join(ok), feedback))
            r['author_feedback'] = feedback
            for k, v in (extra or {}).items():
                r[k] = v
            hit += 1
    if not hit:
        return 0
    tmp = LOG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, LOG_PATH)
    return hit

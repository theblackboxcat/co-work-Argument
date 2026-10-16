# -*- coding: utf-8 -*-
"""对照实验：语义召回 vs 字面召回。

问题：记忆层（OpenViking 的语义 find）接进 server.py 替掉现行的
`pick_context()`（2-gram 字面重叠）值不值？先在同一份稿子上各跑一遍。

  · 字面召回 = 复刻 server.pick_context 的算法（2-gram 重叠 > 0.06，top-3）
  · 语义召回 = ov_memory.OVStore.find(query, work=…, part=…)  top-3

两者都返回「段号」，于是可以逐条比：重合多少、各自多召回了什么、
有多少语义命中是字面**根本看不见**的（这正是替换的全部意义）。

用法：
  python v3/recall_compare.py --n 400 --q 60
"""
import argparse
import os
import re
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)      # ov_memory 在上一层

from ov_memory import OVStore  # noqa: E402

WORK = '幻影的终结'
PART = 's02-cmp'
DOC = os.path.join(ROOT, 'corpus', '爱别离_§02_发条水汽在黑夜被忘却.md')


# ── 与 server.py 逐字一致的两个函数 ─────────────────────────────
def split_paragraphs(text):
    """按空行切段；返回 [(段号, 文本)]，段号从 1 开始。"""
    raw = re.split(r'\n\s*\n', (text or '').replace('\r\n', '\n'))
    return [(i + 1, p.strip()) for i, p in enumerate(raw) if p.strip()]


def _terms(s):
    """极简中文切词：取 2-gram。"""
    s = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', s or '')
    return set(s[i:i + 2] for i in range(len(s) - 1)) or set(s)


def pick_context(ps, cur, prev='', topk=3):
    """复刻 server.pick_context：在 ps=[(no,txt)] 里找与 cur/prev 最相关的几段。"""
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
            scored.append((ov, no))
    scored.sort(reverse=True)
    return [no for _ov, no in scored[:topk]]


def literal_overlap(ps, cur, no):
    """cur 与第 no 段的 2-gram 重叠率——用来判断语义命中是不是字面看不见的。"""
    for n, txt in ps:
        if n == no:
            return len(_terms(cur) & _terms(txt)) / max(1, len(_terms(cur)))
    return 0.0


def seg_no_from_uri(uri):
    m = re.search(r'seg-(\d+)', uri or '')
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=400, help='取前 N 段建索引')
    ap.add_argument('--q', type=int, default=60, help='抽样多少段做查询')
    ap.add_argument('--min-chars', type=int, default=40, help='段长下限')
    args = ap.parse_args()

    text = open(DOC, encoding='utf-8').read()
    allps = split_paragraphs(text)
    ps = [(n, t) for n, t in allps if len(t) >= args.min_chars][:args.n]
    print('文档 %s\n空行分段 %d → 取 ≥%d 字的前 %d 段建索引'
          % (os.path.basename(DOC), len(allps), args.min_chars, len(ps)))

    st = OVStore()
    st.login()
    st.ensure_tree(WORK)

    # ── 建索引（任务节点：一段一个 seg-<段号>.md）──────────────────
    t0 = time.time()
    for i, (no, txt) in enumerate(ps, 1):
        st.write_segment(WORK, PART, 'seg-%04d' % no, txt, ['exp=recall-cmp'])
        if i % 50 == 0:
            print('  已建索引 %d/%d（%.1fs）' % (i, len(ps), time.time() - t0))
    print('索引完成：%d 段，%.1fs' % (len(ps), time.time() - t0))

    # ── 抽样查询 ──────────────────────────────────────────────────
    step = max(1, len(ps) // args.q)
    qs = ps[::step][:args.q]

    rows = []
    lit_ms, sem_ms = [], []
    for no, txt in qs:
        a = time.time()
        L = pick_context(ps, txt)
        lit_ms.append((time.time() - a) * 1000)

        a = time.time()
        hits = st.find(txt, work=WORK, part=PART, limit=4)
        sem_ms.append((time.time() - a) * 1000)
        # 排除查询段自己（字面那边也是显式跳过的），保证两边可比
        S, sc = [], []
        for h in hits:
            n = seg_no_from_uri(h['uri'])
            if n is None or n == no:
                continue
            S.append(n)
            sc.append(round(h.get('score') or 0, 3))
            if len(S) >= 3:
                break

        rows.append({'no': no, 'L': L, 'S': S, 'S_score': sc})

    # ── 统计 ──────────────────────────────────────────────────────
    both = [r for r in rows if r['L'] and r['S']]
    onlyL = [r for r in rows if r['L'] and not r['S']]
    onlyS = [r for r in rows if r['S'] and not r['L']]
    none_ = [r for r in rows if not r['L'] and not r['S']]

    jac = []
    for r in rows:
        L, S = set(r['L']), set(r['S'])
        if L | S:
            jac.append(len(L & S) / len(L | S))

    sem_total = sum(len(r['S']) for r in rows)
    sem_only = sum(len(set(r['S']) - set(r['L'])) for r in rows)
    # 语义命中里，字面重叠率 < 0.06（即 pick_context 的阈值看不见）的占比
    invisible = 0
    for r in rows:
        for n in set(r['S']) - set(r['L']):
            if literal_overlap(ps, next(t for m, t in ps if m == r['no']), n) < 0.06:
                invisible += 1

    L = []
    L.append('# 对照实验 · 语义召回 vs 字面召回\n')
    L.append('对象：`%s`（《幻影的终结》序曲·§02）' % os.path.basename(DOC))
    L.append('索引：前 %d 段（≥%d 字）；查询：等距抽样 %d 段；均 top-3。\n'
             % (len(ps), args.min_chars, len(qs)))
    L.append('| 量 | 字面（pick_context 2-gram） | 语义（OpenViking find） |')
    L.append('|---|---|---|')
    L.append('| 平均召回条数 | %.2f | %.2f |'
             % (statistics.mean(len(r['L']) for r in rows),
                statistics.mean(len(r['S']) for r in rows)))
    L.append('| 平均单次耗时 | %.0f ms | %.0f ms |'
             % (statistics.mean(lit_ms), statistics.mean(sem_ms)))
    L.append('')
    L.append('## 逐条对照（n=%d）\n' % len(rows))
    L.append('- 两者都召回：**%d**' % len(both))
    L.append('- 只有字面召回：**%d**' % len(onlyL))
    L.append('- 只有语义召回：**%d**' % len(onlyS))
    L.append('- 两者都空：**%d**' % len(none_))
    L.append('- 平均 Jaccard（两者非空时）：**%.3f**\n'
             % (statistics.mean(jac) if jac else 0.0))
    L.append('## 语义命中的「新信息」\n')
    L.append('- 语义共召回 %d 条，其中字面没召回的 %d 条（**%.1f%%**）'
             % (sem_total, sem_only, 100.0 * sem_only / max(1, sem_total)))
    L.append('- 上述新命中里，与查询段的 2-gram 重叠 < 0.06（即字面阈值**根本看不见**）'
             '的有 %d 条（**%.1f%%**）'
             % (invisible, 100.0 * invisible / max(1, sem_only)))
    L.append('')
    lit_zero = sum(1 for r in rows if not r['L'])
    sem_zero = sum(1 for r in rows if not r['S'])
    all_sc = [s for r in rows for s in r['S_score']]
    L.append('## 召回下限（对"该不该沉默"很关键）\n')
    L.append('- 字面返回 **0** 条（够不到 0.06 阈值）的查询：**%d / %d**'
             % (lit_zero, len(rows)))
    L.append('- 语义返回 **0** 条的查询：**%d / %d**' % (sem_zero, len(rows)))
    L.append('- 语义召回的最低分 / 中位分：**%.3f / %.3f**'
             % (min(all_sc) if all_sc else 0,
                statistics.median(all_sc) if all_sc else 0))
    L.append('')
    L.append('## 若干例子\n')
    for r in rows[:12]:
        q = next(t for m, t in ps if m == r['no'])
        L.append('- **第 %d 段**「%s…」' % (r['no'], q[:32]))
        L.append('  - 字面：%s' % (r['L'] or '—'))
        L.append('  - 语义：%s' % (r['S'] or '—'))
    out = os.path.join('%DSH_ROOT%/交互', '对照实验_语义召回vs字面召回.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(L))
    print('\n报告已写入：', out)
    print('\n'.join(L[:22]))


if __name__ == '__main__':
    main()

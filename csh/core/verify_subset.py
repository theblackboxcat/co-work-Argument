#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
裁剪式重构的数字核验（与 verify_numbers.py 互补）。

verify_numbers.py 适用于「风格重写」：新旧数字必须**完全相等**。
本脚本适用于「按顶会写法只写必要部分重构」：新版允许**少**（数据被移到附录
或压缩成一句话），但不允许：
  1. 凭空出现旧版没有的数字 token（= 编造）
  2. 同一个统计量在新版里被写成一个不同的值（= 改数据）
  3. 图片丢失

用法:
    python verify_subset.py OLD.md NEW.md
    python verify_subset.py OLD.md NEW.md --explain
"""
import argparse
import re
import sys
from collections import Counter

# 数字 token：可选负号、小数、科学计数、分数、百分号、连字符范围（3-5）、千分位
NUM = re.compile(
    r'-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'      # 123 / 1.5 / 1e-4 / 2.5E+07
)
# 归一化时剥掉这些前后缀，避免 "180/180" 与 "180" 被当成两个不同 token
JUNK = re.compile(r'^[\s,\[\]{}()$、，。；：/\\|"\'`*+-]+|[\s,\[\]{}()$、，。；：/\\|"\'`*]+$')


def numbers(text: str) -> Counter:
    """抽取全部数字 token 并归一化（去千分位逗号、去包裹符号）。"""
    out = Counter()
    for m in NUM.finditer(text):
        tok = JUNK.sub('', m.group(0))
        if not tok:
            continue
        try:
            f = float(tok)
        except ValueError:
            continue
        # 统一 -0 与 0；保留有效数字，避免 4.0 == 4 的双份计数
        out[f'{f:g}'] += 1
    return out


def table_rows(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.startswith('|'))


def images(text: str) -> int:
    return len(re.findall(r'^!\[[^\]]*\]\([^)]+\)\s*$', text, re.M))


def fences(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.startswith('```'))


def split_blocks(text: str):
    """按 markdown 标题切成块，用于 --explain 定位差异所在章节。"""
    blocks, cur, name = [], [], '(preamble)'
    for ln in text.splitlines():
        m = re.match(r'^(#{1,4})\s+(.*)', ln)
        if m:
            blocks.append((name, '\n'.join(cur)))
            cur, name = [], m.group(2).strip()
        else:
            cur.append(ln)
    blocks.append((name, '\n'.join(cur)))
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('old')
    ap.add_argument('new')
    ap.add_argument('--explain', action='store_true',
                    help='用 difflib 定位每个差异所在的章节')
    args = ap.parse_args()

    old = open(args.old, encoding='utf-8').read()
    new = open(args.new, encoding='utf-8').read()

    no, nn = numbers(old), numbers(new)
    # 判据用「集合」而非「计数」：顶会论文会在摘要/正文/结论里重复引用同一个主结果，
    # 次数增加是正常的；只有「新版出现而旧版完全没有」才是编造。
    extra = Counter({t: c for t, c in (nn - no).items() if t not in no})
    missing = Counter({t: c for t, c in (no - nn).items() if t not in nn})
    # 新版某数字出现次数显著多于旧版（>2.5 倍且多 >=2 次）——疑似复制粘贴错误
    inflated = Counter({t: nn[t] - no[t] for t in no
                       if nn[t] > no[t] * 2.5 and nn[t] - no[t] >= 2})

    print(f'old  {args.old}: {table_rows(old)} table rows, {images(old)} images, '
          f'{len(no)} distinct number tokens')
    print(f'new  {args.new}: {table_rows(new)} table rows, {images(new)} images, '
          f'{len(nn)} distinct number tokens')
    print()

    ok = True

    # --- 硬判据 1：图片一个不能少 ---------------------------------------
    if images(new) < images(old):
        lost = images(old) - images(new)
        print(f'[FAIL] images lost: {lost}')
        ok = False
    else:
        print(f'[ OK ] images: {images(new)}/{images(old)}')

    # --- 硬判据 2：代码围栏必须成对 ---------------------------------------
    if fences(new) % 2:
        print(f'[FAIL] unbalanced code fences: {fences(new)}')
        ok = False
    else:
        print(f'[ OK ] code fences balanced: {fences(new)}//2 blocks')

    # --- 硬判据 3：不得凭空出现数字 -------------------------------------
    if extra:
        print(f'[FAIL] {len(extra)} number token(s) in NEW but absent from OLD '
              f'(fabricated?): {sorted(extra.items())[:40]}')
        ok = False
    else:
        print('[ OK ] no fabricated numbers: every NEW token exists in OLD')

    # --- 硬判据 4：数字出现次数异常膨胀 ----------------------------------
    if inflated:
        print(f'[WARN] {len(inflated)} token(s) appear >2.5x more often than in OLD: '
              f'{sorted(inflated.items())[:20]}')
    else:
        print('[ OK ] no number inflated beyond 2.5x')

    # --- 提示：裁剪掉的数字 ---------------------------------------------
    if missing:
        print(f'[INFO] {sum(missing.values())} distinct token(s) dropped entirely '
              f'(moved to appendix or compressed): {sorted(missing)[:40]}')
    else:
        print('[INFO] nothing dropped')

    if args.explain and (extra or missing or inflated):
        print('\n--- where each dropped token lived in OLD ---')
        blocks = split_blocks(old)
        newset = set(nn)
        for name, body in blocks:
            lost = {t for t in numbers(body) if t not in newset}
            if lost:
                print(f'  [{name}] -> {sorted(lost)}')

        print('\n--- inflated tokens: where do the extra copies live in NEW ---')
        nblocks = split_blocks(new)
        for t in sorted(inflated):
            hosts = [nm for nm, bd in nblocks if t in numbers(bd)]
            print(f'  {t}: {hosts}')

    print()
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
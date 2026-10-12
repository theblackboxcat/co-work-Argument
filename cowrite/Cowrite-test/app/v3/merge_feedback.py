# -*- coding: utf-8 -*-
"""把各批次的反馈表并成一份，供作者一次标完。

每跑一批语料（--tag 非P / --tag 流派 …）会在 logs/ 下留一份
`反馈表_<tag>.md`，并在 `_批次.json` 里记一行说明。
本脚本按记录的**先后顺序**把它们拼成 `反馈表.md`，
每条前面加批次前缀，避免两批都叫 T001 时撞号。

用法：
  python merge_feedback.py            # 合并所有已登记批次
  python merge_feedback.py --drop 流派   # 把某批撤下（重跑前用）
"""
import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'logs')
INDEX = os.path.join(LOG, '_批次.json')


def load_index():
    if not os.path.isfile(INDEX):
        return []
    with open(INDEX, encoding='utf-8') as f:
        return json.load(f)


def save_index(items):
    os.makedirs(LOG, exist_ok=True)
    with open(INDEX, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def renumber(body, prefix):
    """给 `## T00x` 换成 `## <前缀>-T00x`，避免撞号。"""
    return re.sub(r'^## (T\d+)', lambda m: '## %s-%s' % (prefix, m.group(1)),
                  body, flags=re.M)


def strip_head(body):
    """去掉批次文件自己的标题与说明，只留条目。"""
    lines = body.split('\n')
    i = 0
    for j, l in enumerate(lines):
        if l.startswith('## '):
            i = j
            break
    return '\n'.join(lines[i:]).strip()


def merge():
    items = load_index()
    if not items:
        print('还没有登记任何批次。跑 runner.py 时加 --tag <名字>。')
        return
    parts = ['# 反馈表 · 合并版（请作者标）', '',
             '每行填两栏：**反馈**（接受 / 太弱 / 太强 / 不对）、'
             '**还想写吗**（会立刻接着写 / 停了一下 / 不想写了）。',
             '空着也行——空着本身就是数据。', '',
             '> 填完把这个文件发我，或直接在对话里说 `非P-T003` 怎么样。', '',
             '## 批次', '']
    for it in items:
        parts.append('- **%s** ｜ %s ｜ %d 条 ｜ %s'
                     % (it['tag'], it.get('desc', ''), it.get('n', 0), it.get('ts', '')))
    parts.append('')
    for it in items:
        p = os.path.join(LOG, '反馈表_%s.md' % it['tag'])
        if not os.path.isfile(p):
            parts.append('> ⚠ 批次 %s 的文件不见了（%s）' % (it['tag'], p))
            parts.append('')
            continue
        with open(p, encoding='utf-8') as f:
            body = f.read()
        parts.append('---')
        parts.append('')
        parts.append('# 批次：%s ｜ %s' % (it['tag'], it.get('desc', '')))
        parts.append('')
        parts.append(renumber(strip_head(body), it['tag']))
        parts.append('')
    out = os.path.join(LOG, '反馈表.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    print('合并 %d 批 → %s' % (len(items), out))
    for it in items:
        print('   %-8s %s（%s 条）' % (it['tag'], it.get('desc', ''), it.get('n', 0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--drop', default=None, help='撤下某批次（按 tag）')
    a = ap.parse_args()
    if a.drop:
        items = [x for x in load_index() if x['tag'] != a.drop]
        save_index(items)
        print('已撤下 %s，剩 %d 批。' % (a.drop, len(items)))
    merge()


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""记忆层接入冒烟：验证 ① 日志不再叠 YAML 头 ② 同样内容不再写两遍 ③ overview 读回干净。

用法： python v3/smoke_memory.py
不依赖 server.py，只打 ov_memory 那一层；失败会抛。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ov_memory import OVStore  # noqa: E402

WORK = '_smoke'          # 明确标成测试品；跑完自己删掉，别混进真实检索
PART = 'p00'
TODAY = __import__('datetime').date.today().isoformat()

ok = 0
fail = []


def check(name, cond, extra=''):
    global ok
    if cond:
        ok += 1
        print('  ok   %s %s' % (name, extra))
    else:
        fail.append(name)
        print('  FAIL %s %s' % (name, extra))


s = OVStore()
s.login()
s.ensure_tree(WORK)
print('连接 %s  根 %s' % (s.base, s.root))

# ── ① 段写入 + overview 读回 ─────────────────────────────────────
seg = ('她把杯子放回桌上，没有立刻说话。窗外的雨停了一阵又下起来，'
       '声音比刚才小，像是隔着一层布。他等着，也不催。'
       '这一段要写的是等待本身，不是等的人。')
s.write_segment(WORK, PART, 'seg-0001', seg, day=TODAY)
s.write_overview(WORK, PART, '## 位置\n开头。她在等，他也在等。\n\n## 已经建起来的\n等待本身被写成有重量的东西。')

back = s.read_body('%s/resources/%s/%s/.overview.md' % (s.root, WORK, PART))
print('\n[overview 读回] %r' % back[:80])
check('overview 不含 YAML 头', not back.startswith('---'), repr(back[:20]))
check('overview 含正文', '已经建起来的' in back)

# ── ② 同一段内容连写两次，日志不应重复 ───────────────────────────
MARK = 'SMOKE'                          # 收尾时按这个标记把测试痕迹从日志里摘掉
line = '— %s：这段伴写只应出现一次 —' % MARK
s.append_session(TODAY, line)
s.append_session(TODAY, line)          # 故意重复
s.append_session(TODAY, line + '（第二条，不同的）')

log = s.read_body('%s/memories/sessions/%s.md' % (s.root, TODAY))
print('\n[日志] \n%s\n' % log)
check('日志不含 YAML 头', not log.lstrip().startswith('---'))
check('重复内容只写一次', log.count(line + '\n') == 1 or
      (log.count(line) - log.count(line + '（第二条')) == 1,
      '出现 %d 次' % log.count(line))
check('不同内容正常追加', '（第二条，不同的）' in log)

# ── ③ 召回能命中刚写的段 ─────────────────────────────────────────
hits = s.find('雨停了以后她在等什么', work=WORK, part=PART, limit=5)
print('[召回] %s' % [(h['uri'].split('/')[-1], h['level'], round(h['score'] or 0, 3)) for h in hits])
check('语义召回有结果', len(hits) > 0)

# ── ④ 装配记忆块，且不含 YAML 头 ─────────────────────────────────
blk = s.memory_block('雨停了以后她在等什么', work=WORK, part=PART)
check('记忆块有最近伴写', '最近几次的伴写' in blk)
check('记忆块有本次召回', '本次召回' in blk)
check('记忆块无 YAML 头泄漏', '\ngenerated_by' not in blk and blk.find('directory:') == -1)

# ── 收尾：把测试痕迹全部摘掉，别让它污染真实的记忆 ───────────────
try:
    s.rm('%s/resources/%s' % (s.root, WORK))
    print('[清理] 已删作品 %s' % WORK)
except Exception as e:
    print('[清理] 删作品失败（可手动）：%s' % str(e)[:120])

# 日志是 append-only，测试写进去的行不会自己消失——这里按标记摘一遍。
# 顺手把更早之前留下的、没带标记的旧冒烟行也一起清掉。
try:
    uri = '%s/memories/sessions/%s.md' % (s.root, TODAY)
    body = s.read_body(uri) or ''
    paras = [p.strip() for p in body.split('\n\n') if p.strip()]
    kept = [p for p in paras if MARK not in p and '冒烟' not in p]
    if len(kept) != len(paras):
        s.write(uri, '\n\n'.join(kept) + '\n', ['kind=session', 'day=%s' % TODAY])
        print('[清理] 日志去掉 %d 条测试行' % (len(paras) - len(kept)))
except Exception as e:
    print('[清理] 清日志失败（可手动）：%s' % str(e)[:120])

print('\n%d 通过，%d 失败 %s' % (ok, len(fail), fail if fail else ''))
sys.exit(1 if fail else 0)

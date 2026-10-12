# -*- coding: utf-8 -*-
"""埋点：每条样本一行 JSONL。

字段照执行文档 §5.2：
  text_id / initial_mode / rules_applied / author_feedback / modification_detail
  flow_signal / motivation_signal

再加几个 hy4 分析时必需的：时间戳、臂（baseline/v3）、自动层指标、输出摘要。
作者反馈与体验信号**先留空**，由作者补 —— 埋点只负责把位置占好，
不能自己伪造"系统有效"的数据。
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, 'logs')
LOG_PATH = os.path.join(LOG_DIR, 'samples.jsonl')


def ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)
    return LOG_PATH


def record(row):
    """追加一条记录。缺少的字段用 None 占位，不猜、不填默认值。"""
    ensure_dir()
    base = {
        'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
        'text_id': None,
        'arm': None,                 # baseline | v3
        'initial_mode': None,        # P | M | S
        'mode_score': None,
        'rules_applied': None,       # 如 "P-strict"
        'author_feedback': None,     # accepted | rejected | modified | too_weak | too_strong | wrong
        'modification_detail': None,
        'flow_signal': None,         # continued_immediately | paused | closed_tool
        'motivation_signal': None,   # kept_writing | stopped_writing | reopened_later
        'metrics': None,
        'output_preview': None,
    }
    base.update(row or {})
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(base, ensure_ascii=False) + '\n')
    return base


def read_all(path=LOG_PATH):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def update_feedback(text_id, arm, feedback, modification=None,
                    flow_signal=None, motivation_signal=None, path=LOG_PATH):
    """作者标注回填：按 (text_id, arm) 定位最近一条。"""
    rows = read_all(path)
    if not rows:
        return 0
    n = 0
    for r in rows:
        if r.get('text_id') == text_id and (arm is None or r.get('arm') == arm):
            if feedback is not None:
                r['author_feedback'] = feedback
            if modification is not None:
                r['modification_detail'] = modification
            if flow_signal is not None:
                r['flow_signal'] = flow_signal
            if motivation_signal is not None:
                r['motivation_signal'] = motivation_signal
            n += 1
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return n


def summary(path=LOG_PATH):
    """各信号的分布——给 hy4 看系统性偏差用。"""
    rows = read_all(path)
    if not rows:
        return {'total': 0}
    def dist(key):
        d = {}
        for r in rows:
            k = r.get(key) or '(未标注)'
            d[k] = d.get(k, 0) + 1
        return dict(sorted(d.items(), key=lambda x: -x[1]))
    return {
        'total': len(rows),
        'by_arm': dist('arm'),
        'by_mode': dist('initial_mode'),
        'feedback': dist('author_feedback'),
        'flow_signal': dist('flow_signal'),
        'motivation_signal': dist('motivation_signal'),
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'summary':
        print(json.dumps(summary(), ensure_ascii=False, indent=2))
    else:
        print('用法：telemetry.py summary')
        print('日志文件：', LOG_PATH)

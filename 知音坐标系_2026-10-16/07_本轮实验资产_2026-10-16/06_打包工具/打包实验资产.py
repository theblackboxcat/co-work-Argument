#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包实验资产：复制 + 剥离 key + 生成 MANIFEST（md5 + 字节数）。"""
import hashlib
import json
import re
import shutil
from pathlib import Path

SRC = Path('/workspace')
ART = Path('/root/.codebuddy/artifact/2f8a7d30-9c21-4f0b-1d4a-9e138d997000')
PKG = SRC / '实验资产_知音坐标系_2026-10-16'

MAP = [
    # (源, 包内相对路径)
    (SRC / '00_索引_README.md', '00_索引_README.md'),
    (SRC / '05_终检记录.md', '05_终检记录.md'),
    (SRC / '剩余研究问题_2026-10-16.md', '04_剩余研究问题.md'),

    (SRC / '研究背景与目标_作者口述_2026-10-15.md', '01_研究背景与理论/研究背景与目标_作者口述_2026-10-15.md'),
    (SRC / '核验与待裁分析_v4补报_E05a金标与v3冻结_2026-10-15.md', '01_研究背景与理论/核验_v4补报_E05a金标与v3冻结.md'),
    (SRC / '核验与待裁分析_v5_D123回应_拆锚撤回与仪器缺陷_2026-10-15.md', '01_研究背景与理论/核验_v5_拆锚撤回与仪器缺陷.md'),
    (SRC / '核验与待裁分析_v6_失效源定位_考察形式而非模型_2026-10-15.md', '01_研究背景与理论/核验_v6_失效源定位.md'),
    (SRC / '核验与待裁分析_v7_协变测量_默认对齐与错位缺失_2026-10-15.md', '01_研究背景与理论/核验_v7_协变测量.md'),

    # E0
    (SRC / 'score_v5_corrected.py', '02_实验/E0_零算力核验/score_v5_corrected.py'),
    (SRC / 'score_v5_output.txt', '02_实验/E0_零算力核验/score_v5_output.txt'),
    (SRC / 'verify_restored_caliber.py', '02_实验/E0_零算力核验/verify_restored_caliber.py'),
    # E1
    (SRC / 'exp_discriminate.py', '02_实验/E1_形式对照_定位vs判断/exp_discriminate.py'),
    (SRC / 'exp_discriminate_out.json', '02_实验/E1_形式对照_定位vs判断/exp_discriminate_out.json'),
    (SRC / 'exp_format_contrast.py', '02_实验/E1_形式对照_定位vs判断/exp_format_contrast.py'),
    (SRC / 'exp_format_contrast_out.json', '02_实验/E1_形式对照_定位vs判断/exp_format_contrast_out.json'),
    # E2
    (SRC / 'exp_covary.py', '02_实验/E2_协变测量/exp_covary.py'),
    (SRC / 'exp_covary_out.json', '02_实验/E2_协变测量/exp_covary_out.json'),
    (SRC / 'exp_covary_log.txt', '02_实验/E2_协变测量/exp_covary_log.txt'),
    # E3
    (SRC / 'dialogue_turn.py', '02_实验/E3_消融_gloss负资产/dialogue_turn.py'),
    (SRC / 'hist_A_v8.json', '02_实验/E3_消融_gloss负资产/hist_A_v8.json'),
    (SRC / 'hist_B_v4.json', '02_实验/E3_消融_gloss负资产/hist_B_v4.json'),
    (SRC / 'hist_C_notree.json', '02_实验/E3_消融_gloss负资产/hist_C_notree.json'),
    (SRC / 'hist_D_sparse.json', '02_实验/E3_消融_gloss负资产/hist_D_sparse.json'),
    (SRC / 'dialogue_history_strict.json', '02_实验/E3_消融_gloss负资产/dialogue_history_strict.json'),
    (SRC / '两个模型对话实验_首轮结果.md', '02_实验/E3_消融_gloss负资产/两个模型对话实验_首轮结果.md'),
    (SRC / '两个模型对话实验_第二轮_消融与修正.md', '02_实验/E3_消融_gloss负资产/两个模型对话实验_第二轮_消融与修正.md'),
    # E4
    (SRC / 'scale_dialogue.py', '02_实验/E4_规模对话_长度与意义度/scale_dialogue.py'),
    (SRC / 'scale_C1_log.json', '02_实验/E4_规模对话_长度与意义度/scale_C1_log.json'),
    (SRC / 'scale_C2_log.json', '02_实验/E4_规模对话_长度与意义度/scale_C2_log.json'),
    (SRC / 'scale_C3_log.json', '02_实验/E4_规模对话_长度与意义度/scale_C3_log.json'),
    (SRC / '规模对话实验_长度机理与意义度.md', '02_实验/E4_规模对话_长度与意义度/规模对话实验_长度机理与意义度.md'),
    # E5
    (SRC / 'live_dialogue.py', '02_实验/E5_现场对话_闸门修正/live_dialogue.py'),
    (SRC / 'live_history.json', '02_实验/E5_现场对话_闸门修正/live_history.json'),
    (SRC / '现场对话_我做一方_闸门修正与终止验证.md', '02_实验/E5_现场对话_闸门修正/现场对话_闸门修正与终止验证.md'),
    (SRC / '协变对话实验_日志.md', '02_实验/E5_现场对话_闸门修正/协变对话实验_日志.md'),
    # E6
    (SRC / '辩论选题线_结构级闸门与判断权.md', '02_实验/E6_辩论选题_结构级闸门/辩论选题线_结构级闸门与判断权.md'),
    # E7
    (SRC / 'feynman_batch.py', '02_实验/E7_费曼线_无引导批量/feynman_batch.py'),
    (SRC / 'feynman_batch.json', '02_实验/E7_费曼线_无引导批量/feynman_batch.json'),
    (SRC / 'feynman_shuffled.json', '02_实验/E7_费曼线_无引导批量/feynman_shuffled.json'),
    (SRC / '费曼线_从公开起点到我们此刻.md', '02_实验/E7_费曼线_无引导批量/费曼线_从公开起点到我们此刻.md'),
    (SRC / '费曼线_无引导批量与机制校准.md', '02_实验/E7_费曼线_无引导批量/费曼线_无引导批量与机制校准.md'),

    # 数据
    (SRC / 'trunk_v8_错位默认_DRAFT.json', '03_数据/树/trunk_v8_错位默认_DRAFT.json'),
    (ART / 'v4pkg/pkg/trunk_v4_s14_narrowed_DRAFT.json', '03_数据/树/trunk_v4_s14_narrowed_DRAFT.json'),
    (ART / 'verify/pkg2/03_锚与主干/anchors_external_FROZEN_yunjiu_2026-10-15.json',
     '03_数据/锚/anchors_external_FROZEN_yunjiu_2026-10-15.json'),
    (SRC / 'corpus_pool.json', '03_数据/语料/corpus_pool.json'),
    (ART / 'verify/pkg2/06_新包核验与续证/私语料_云酒与猫猫/_extracted_yunjiu.txt',
     '03_数据/私语料_不对外/_extracted_yunjiu.txt'),
    (ART / 'verify/pkg2/02_脚本/runs/v2_20261015_102822.jsonl', '03_数据/原始runs/v2a_102822.jsonl'),
    (ART / 'verify/pkg2/02_脚本/runs/v2_20261015_111753.jsonl', '03_数据/原始runs/v2b_111753.jsonl'),
    (ART / 'verify/pkg2/02_脚本/runs/v2_20261015_132811.jsonl', '03_数据/原始runs/v2c_132811.jsonl'),
    (ART / 'verify/pkg2/04_原始数据_runs/v3_s14s20sharpen_20261015_164100.jsonl', '03_数据/原始runs/v3_164100.jsonl'),
    (ART / 'v4pkg/pkg/v4_s14narrowed_20261015_173608.jsonl', '03_数据/原始runs/v4_173608.jsonl'),
    # 原始跑批器与端点层：没有它们，本包只能复算、无法重跑原始实验（补可复现性缺口）
    (ART / 'verify/pkg2/02_脚本/run_v3_s14s20sharpen.py', '03_数据/原始跑批器/run_v3_s14s20sharpen.py'),
    (ART / 'verify/pkg2/02_脚本/lib/providers.py', '03_数据/原始跑批器/lib/providers.py'),
    (ART / 'verify/pkg2/02_脚本/lib/__init__.py', '03_数据/原始跑批器/lib/__init__.py'),
    (SRC / 'dialogue_history.json', '02_实验/E3_消融_gloss负资产/dialogue_history.json'),
    (SRC / '打包实验资产.py', '06_打包工具/打包实验资产.py'),
]

KEY_RE = re.compile(r"^KEY\s*=\s*['\"](ak_[A-Za-z0-9]+)['\"]", re.M)
LOADER = """def _load_key():
    import os
    p = Path(__file__).with_name('config.json')
    if p.exists():
        try:
            return json.load(open(p, encoding='utf-8')).get('api_key', '')
        except Exception:
            return ''
    return os.environ.get('DOTS3_KEY', '')


KEY = _load_key()"""


def main():
    if PKG.exists():
        shutil.rmtree(PKG)
    for s, rel in MAP:
        d = PKG / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if not s.exists():
            print('[缺] %s' % s)
            continue
        shutil.copy2(s, d)
        if d.suffix == '.py' and ('BASE' in d.read_text(encoding='utf-8')):
            t = d.read_text(encoding='utf-8')
            t2 = KEY_RE.sub(LOADER, t)
            if t2 != t:
                d.write_text(t2, encoding='utf-8')
                print('[剥离key] %s' % rel)
    (PKG / 'config.example.json').write_text(
        json.dumps({'base_url': 'http://note3-prev-api.askdiandian.com',
                    'model': 'dots3-note-prev', 'api_key': ''},
                   ensure_ascii=False, indent=2), encoding='utf-8')
    (PKG / '注意_config.json不入库.txt').write_text(
        '真 key 写入 config.json（与脚本同目录），不要提交到公开库。\n'
        '已打包脚本中的硬编码 key 全部剥离，改为运行时读 config.json 或环境变量 DOTS3_KEY。\n',
        encoding='utf-8')

    rows, n, total = [], 0, 0
    for f in sorted(PKG.rglob('*')):
        if f.is_file():
            b = f.read_bytes()
            md5 = hashlib.md5(b).hexdigest()
            n += 1
            total += len(b)
            rows.append('%s  %8d  %s' % (md5, len(b), f.relative_to(PKG)))
    (PKG / 'MANIFEST.txt').write_text(
        '# 知音坐标系 实验资产 v1  MD5 清单\n# 文件数 %d  总字节 %d\n' % (n, total)
        + '\n'.join(rows) + '\n', encoding='utf-8')
    print('\n打包完成：%s\n文件数 %d  总字节 %d' % (PKG, n, total))


if __name__ == '__main__':
    main()

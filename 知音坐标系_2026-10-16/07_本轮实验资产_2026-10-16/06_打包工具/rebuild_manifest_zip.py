#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建去重版工程包的 MANIFEST_全集.txt 与两级 zip（包内 + 工作区）。

用法：python3 rebuild_manifest_zip.py [包目录]
  不带参数时，按本脚本所在位置（<包>/07/06_打包工具/）自动定位包目录。

规则（与历史归档一致）：
- MANIFEST 行格式：md5 + 两空格 + 右对齐 10 位字节数 + 两空格 + 包内相对路径
- 排序：路径 Unicode 码点序（等价于 UTF-8 字节序）
- MANIFEST 不含自身、不含任何 .zip
- zip 从包内构建，不含自身；构建后复制到包外工作区，两级 md5 一致
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

MANIFEST = 'MANIFEST_全集.txt'


def main():
    if len(sys.argv) > 1:
        pkg = Path(sys.argv[1]).resolve()
    else:
        pkg = Path(__file__).resolve().parents[2]  # <包>/07_.../06_打包工具/ -> 包根
    if not (pkg / '07_本轮实验资产_2026-10-16').is_dir():
        print('未找到包目录（缺 07_本轮实验资产_2026-10-16/）：%s' % pkg)
        sys.exit(1)
    zipname = pkg.name + '.zip'

    rows, n, total = [], 0, 0
    for f in sorted(pkg.rglob('*')):
        if not f.is_file():
            continue
        rel = f.relative_to(pkg).as_posix()
        if rel == MANIFEST or rel.endswith('.zip'):
            continue
        b = f.read_bytes()
        n += 1
        total += len(b)
        rows.append('%s  %10d  %s' % (hashlib.md5(b).hexdigest(), len(b), rel))

    header = ('# 知音坐标系 工程资料（去重版）MD5 清单（不含本清单自身）\n'
              '# 文件数 %d  总字节 %d\n' % (n, total))
    (pkg / MANIFEST).write_text(header + '\n'.join(rows) + '\n', encoding='utf-8')
    print('MANIFEST: %d files, %d bytes' % (n, total))

    inner = pkg / zipname
    outer = pkg.parent / zipname
    for p in (inner, outer):
        if p.exists():
            p.unlink()
    subprocess.run(['zip', '-r', '-q', str(inner), '.', '-x', zipname],
                   cwd=str(pkg), check=True)
    shutil.copy2(str(inner), str(outer))
    print('zip rebuilt: %s' % inner)
    print('zip copied:  %s' % outer)


if __name__ == '__main__':
    main()

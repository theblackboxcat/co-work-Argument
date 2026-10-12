# -*- coding: utf-8 -*-
"""给 Cowrite-test 装桌面快捷方式（不经 PowerShell）。

为什么不用 .ps1：本机的安全策略禁止从 Bash 调 PowerShell，而
PowerShell 工具在这个环境里对复杂脚本持续静默返回（exit 0/1 都
没有输出）。COM 接口 Python 也能用，所以直接建快捷方式。

刻意与发行版区分：文件名带「测试」，描述里写明端口 8792。
"""
import io
import os
import sys

ROOT = r'%DSH_ROOT%\cowrite-dist\Cowrite-test'
# **目标是 Python 版启动器，不是 .ps1**：
# PowerShell 那条路上有四道坎（无 BOM 被按 GBK 读、PATH/Path 字典撞车、
# 管道把子进程一起带走、工具对复杂脚本静默返回），逐条记在
# 启动测试版.py 的模块 docstring 里。绕开它比修它省事。
TARGET = os.path.join(ROOT, '启动测试版.py')
ICO = os.path.join(ROOT, 'cowrite.ico')
# 便携包自带的 python，不需要系统装Python
PSEXE = os.path.join(ROOT, 'runtime', 'python', 'python.exe')


def desktop_dir():
    """取桌面目录。**优先问注册表**——[Environment]::GetFolderPath 在
    重定向过桌面（OneDrive）的机器上会指到别处，而注册表里
    DesktopFolder 是当前用户真实的桌面。"""
    try:
        import winreg
        key = 'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Shell Folders'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, 'Desktop')[0]
    except Exception:
        pass
    for cand in (os.path.join(os.path.expanduser('~'), 'Desktop'),
                 os.path.join(os.environ.get('PUBLIC', ''), 'Desktop')):
        if cand and os.path.isdir(cand):
            return cand
    return os.path.expanduser('~')


def main():
    if not os.path.isfile(TARGET):
        print('找不到启动脚本：%s' % TARGET)
        return 1
    d = desktop_dir()
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    print('桌面目录：%s' % d)

    # 造一个 .ico 的副本并改名，这样两版的图标在资源管理器里
    # 不会因为同名而共用同一个缓存项
    ico_copy = os.path.join(ROOT, 'cowrite-test.ico')
    if not os.path.exists(ico_copy):
        with open(ICO, 'rb') as fi, open(ico_copy, 'wb') as fo:
            fo.write(fi.read())

    # 文件名带 v2：旧的那个保存时报「无法保存」（快捷方式文件可能仍被
    # 系统索引或资源管理器占用），换个名字避开。
    lnk_path = os.path.join(d, '伴写测试版 v2（采集）.lnk')
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        # **用 WScript.Shell 而不是 shell.SHCreateShortcut**：
        # 后者是 32 位 API，64 位 Python 上根本没有这个属性
        # （报"has no attribute 'SHCreateShortcut'"）。
        # WScript.Shell 两个架构都在，而且它做的事完全一样。
        ws = win32com.client.Dispatch('WScript.Shell')
        lnk = ws.CreateShortcut(lnk_path)
        lnk.TargetPath = PSEXE
        lnk.Arguments = '"%s"' % TARGET
        lnk.WorkingDirectory = ROOT
        lnk.IconLocation = '%s,0' % ico_copy
        lnk.Description = ('Cowrite-test 采集测试版（端口 8792，不启动记忆层）'
                           '——与桌面的「伴写启动器」是两份，互不影响')
        lnk.Save()
        pythoncom.CoUninitialize()
    except ImportError:
        print('缺 pywin32。请用这个跑：')
        print(r'  %USERPROFILE%\.workbuddy\binaries\python\envs'
              r'\cowrite-tools\Scripts\python.exe 装桌面图标.py')
        print('或手动：右键 启动测试版.ps1 → 发送到 → 桌面快捷方式')
        return 2
    except Exception as e:
        print('建快捷方式失败：%s' % e)
        print('手动办法：右键 %s → 发送到 → 桌面快捷方式' % TARGET)
        return 1

    print('桌面快捷方式已建：%s' % lnk_path)
    print('双击它启动采集测试版；发行版请用「伴写启动器」。')
    return 0


if __name__ == '__main__':
    sys.exit(main())

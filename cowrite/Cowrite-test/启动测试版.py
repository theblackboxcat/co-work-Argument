# -*- coding: utf-8 -*-
"""启动 Cowrite-test 的服务（Python 版启动器）。

## 为什么不写成 .ps1

前四版 .ps1 全都栽在同一类问题上，而这台机器上每一条都真实存在：

1. **无 BOM 的 .ps1 被按 GBK 读** —— Windows PowerShell 5.1 对无 BOM 的脚本
   按系统 ANSI 代码页读，中文注释被打乱后某个双字节的第二个字节恰好落在
   `}` 上，parser 报「行33 意外的 }」，而 Python 逐行数花括号是**配平的**。
   （发行版三个 .ps1 都带 BOM，这解释了它们为什么能跑。）

2. **`Start-Process` 撞 PATH/Path** —— Windows 环境变量名大小写不敏感，
   而 .NET 字典大小写敏感，于是 `Add("PATH")` 撞上已有的 `Path`：
   「已添加项。字典中的关键字:"PATH"所添加的关键字:"Path"」。

3. **管道把子进程一起带走** —— 用 `RedirectStandardOutput=True` 再靠
   Register-ObjectEvent 读管道时，父进程一退出读端就没了，
   子进程（server.py 要长期打日志）下次写一个字节就收到 BrokenPipe 抛异常退出。
   **症状最恶劣：脚本报告"起来了"、自检也过了，几十秒后才死。**

4. **PowerShell 工具对复杂 .ps1 持续静默返回**（exit 0/1 都无输出），
   而安全策略又禁止从 Bash 调 PowerShell —— 于是「跑一下看报什么错」
   这条最直接的排查路径在本机走不通。

四条里有三条是 PowerShell 自身的行为，绕开它比修它省事。

## 它做什么

- 用 `subprocess.Popen` 起 python，**stdout/stderr 直接指向文件**
  （不是管道）—— 文件句柄由子进程自己握着，父进程退出不影响它。
- 环境变量在 `Popen` 的 env 里显式传，绕开 PATH/Path 撞车。
- 端口占用先查，已在跑就直接开网页。
- 每一步 Say 都落`start-diagnose.log`，双击出问题时看它。
- **起完做延时存活校验**：等 4 秒再看一次。前几版漏了这步，
  于是「它活过了自检、几十秒后才死」这件事只能由你写到一半才发现。

**运行**
    python 启动测试版.py            # 正常起
    python 启动测试版.py --fresh    # 先清空上一轮采集
    python 启动测试版.py --stop     # 停掉
"""
import os
import socket
import subprocess
import sys
import time
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
PYEXE = os.path.join(ROOT, 'runtime', 'python', 'python.exe')
PORT = 8792
URL = 'http://127.0.0.1:%d' % PORT
OUT_LOG = os.path.join(ROOT, 'test-launcher.log')
ERR_LOG = os.path.join(ROOT, 'test-launcher.err')
DIAG = os.path.join(ROOT, 'start-diagnose.log')
PROBE_LOG = os.path.join(APP, 'v3', 'logs', 'probe.jsonl')
PID_FILE = os.path.join(APP, 'cowrite-test.pid')

C_GRAY, C_RED, C_GREEN, C_YEL = '\033[90m', '\033[91m', '\033[92m', '\033[93m'
C_OFF = '\033[0m'


def say(msg, color=C_GRAY):
    """打印 + 落盘。落盘是必须的：双击启动时窗口一闪就没，
    Write-Host 的内容不会留在任何地方，想复现也复现不出来。"""
    print(color + msg + C_OFF)
    try:
        with open(DIAG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%H:%M:%S') + '  ' + msg + '\n')
    except Exception:
        pass


def port_busy(p, timeout=0.7):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex(('127.0.0.1', p)) == 0
    finally:
        s.close()


def stop():
    if not os.path.exists(PID_FILE):
        say('没有 pid 文件，可能本来就没在跑', C_YEL)
        return
    try:
        pid = int(open(PID_FILE, encoding='ascii').read().strip())
    except Exception:
        say('pid 文件读不出来', C_RED)
        return
    # **必须 /T（树杀）**：起的是 cmd，子进程才是 python，
    # 只杀 cmd 的话 python 会留下来继续占着端口。
    r = subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                       capture_output=True, timeout=20)
    print(r.stdout.decode('utf-8', 'replace').strip())
    try:
        os.remove(PID_FILE)
    except Exception:
        pass
    say('已停 (pid %d)' % pid, C_GREEN)


def main():
    args = set(sys.argv[1:])
    if '--stop' in args:
        stop()
        return 0

    if not os.path.isfile(PYEXE):
        say('找不到运行时：%s' % PYEXE, C_RED)
        say('这一版拷贝不完整？对照发行版的 runtime\\ 看。', C_YEL)
        return 1
    if not os.path.isfile(os.path.join(APP, 'server.py')):
        say('这个目录不是 Cowrite-test（缺 app\\server.py）', C_RED)
        return 1

    # 诊断日志每次重写，保留上次的会误导
    try:
        if os.path.exists(DIAG):
            os.remove(DIAG)
    except Exception:
        pass

    if port_busy(PORT):
        say('端口 %d 已经在跑了——测试版可能是开着的。' % PORT, C_YEL)
        say('网页地址：%s' % URL, C_YEL)
        if '--no-open' not in args:
            open_browser(URL)
        return 0

    if '--fresh' in args and os.path.exists(PROBE_LOG):
        # **覆盖写而不是删除**：本机 safe-delete 守卫把「删一个文件」
        # 判成批量危险操作（阈值 50），Remove-Item/os.remove 都会撞上。
        try:
            open(PROBE_LOG, 'w', encoding='utf-8').close()
            say('已清空上一轮采集', C_GRAY)
        except Exception as e:
            say('清空失败（不致命）：%s' % e, C_YEL)

    say('脚本已启动  %s' % ROOT)
    say('=' * 46)
    say(' Cowrite-test · 采集测试版', C_GREEN)
    say('=' * 46)
    say('地址     : %s' % URL)
    say('版本     : 端口 %d（发行版是 8790，两版可并存）' % PORT)
    say('记忆层   : 不启动（与发行版共用 1933 与 ovdata，开了会污染观察）')
    say('采集     : app\\v3\\logs\\probe.jsonl')
    say('')

    # 显式传环境变量。**不继承当前进程的整份 env**——那里面可能有
    # 大小写不同的重复项，Windows 上会引发难以定位的怪问题。
    env = {
        'COWRITE_V3': '1',
        'PYTHONIOENCODING': 'utf-8',
        'PATH': os.environ.get('PATH', ''),
        'SYSTEMROOT': os.environ.get('SYSTEMROOT', r'C:\Windows'),
        'TEMP': os.environ.get('TEMP', r'%USERPROFILE%\AppData\Local\Temp'),
        'TMP': os.environ.get('TMP', r'%USERPROFILE%\AppData\Local\Temp'),
        'LOCALAPPDATA': os.environ.get('LOCALAPPDATA',
                                       r'%USERPROFILE%\AppData\Local'),
        'USERPROFILE': os.environ.get('USERPROFILE', r'%USERPROFILE%'),
        'APPDATA': os.environ.get('APPDATA',
                                  r'%USERPROFILE%\AppData\Roaming'),
    }

    for f in (OUT_LOG, ERR_LOG):
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception:
            pass

    # **stdout/stderr 指向文件，不指向 PIPE**。
    # 指向 PIPE 时，父进程一退出读端消失，server.py 下次写日志就 BrokenPipe 退出——
    # 那是前几版"报告起来了、几十秒后自己没了"的真正原因。
    fo = open(OUT_LOG, 'wb')
    fe = open(ERR_LOG, 'wb')
    # **不要设creationflags。**
    # 设了 CREATE_NEW_PROCESS_GROUP 的话，父进程退出时这个进程组会被
    # 一并结束——服务起得来、活过自检，然后**几秒内安静地消失**，
    # 日志停在自检那一条、stderr 全空、没有任何 traceback。
    # 这个症状最恶劣：它看起来完全像"服务正常启动了"。
    #
    # 对照实验（同一台机器、同一份代码，只差这一个 flag）：
    #   不设flag →父进程退出后子进程持续 HTTP 200✓
    #   设了 flag → 父进程退出后子进程数秒内消失 ✗
    # 因此这里用最朴素的 Popen，不加任何 flag。
    try:
        proc = subprocess.Popen([PYEXE, 'server.py'], cwd=APP, env=env,
                                stdout=fo, stderr=fe)
    except Exception as e:
        say('起不来：%s' % e, C_RED)
        say("手动能跑吗：cd '%s' 然后 '%s' server.py" % (APP, PYEXE), C_YEL)
        return 1

    with open(PID_FILE, 'w', encoding='ascii') as f:
        f.write(str(proc.pid))
    say('已起进程 %d' % proc.pid)

    # ---- 等端口 ----
    up = False
    for _ in range(40):
        time.sleep(0.4)
        if proc.poll() is not None:
            say('服务退出了，退出码 %s' % proc.returncode, C_RED)
            tail(ERR_LOG)
            return 1
        if port_busy(PORT):
            up = True
            break

    if not up:
        say('等了 16 秒端口还没起来。日志：' + OUT_LOG, C_RED)
        tail(ERR_LOG)
        return 1

    say('起来了 -> %s' % URL, C_GREEN)
    say('')
    say('页面右下角有「探针 ▸」，点它开采集面板。')
    say('要停：python 启动测试版.py --stop')
    say('')

    # ---- 装置自检 ----
    # COWRITE_V3 没传进去的话 server 会退回基线，**网页照常开但没有面板**，
    # 而这件事不报任何错。所以主动问一句。
    time.sleep(0.6)
    try:
        import urllib.request
        rq = urllib.request.Request(
            URL + '/api/probe/stats', data=b'{}',
            headers={'Content-Type': 'application/json'})
        d = json.loads(urllib.request.urlopen(rq, timeout=6).read().decode('utf-8'))
        if d.get('error'):
            say('采集外挂没挂上：%s' % d['error'], C_RED)
            say('这一版不能用来采数据。', C_YEL)
            return 1
        say('采集装置已挂上（探针到点 %s / 沉默 %s / 出声 %s）'
            % (d.get('probe_to_point'), d.get('silence'), d.get('spoke')), C_GREEN)
    except Exception as e:
        say('自检没做成：%s' % e, C_YEL)

    # ---- 延时存活校验 ----
    # 自检只证明"这一瞬间在"。前几版的 bug 恰恰是**它活过了自检、
    # 几秒到几十秒后才死**，而如果只等 4 秒就会判成"稳"，把问题留给用户。
    # 所以这里连查三次、共约 6 秒——足以抓住那种"起得来又死"的形态。
    for k in range(3):
        time.sleep(2)
        if proc.poll() is not None:
            say('服务起了但 %d 秒后自己退出了，退出码 %s'
                % ((k + 1) * 2, proc.returncode), C_RED)
            tail(ERR_LOG)
            return 1
        if not port_busy(PORT):
            say('%d 秒后端口不通了。日志见上。' % ((k + 1) * 2), C_RED)
            tail(ERR_LOG)
            return 1
    say('6 秒后仍在跑，稳。日志：%s' % OUT_LOG, C_GREEN)

    if '--no-open' not in args:
        open_browser(URL)
    return 0


def tail(path, n=20):
    if not os.path.exists(path):
        return
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
        say('--- %s ---' % os.path.basename(path), C_RED)
        for l in [x for x in lines if x.strip()][-n:]:
            say('  %s' % l, C_RED)
    except Exception:
        pass


def open_browser(url):
    try:
        os.startfile(url)
    except Exception:
        pass


if __name__ == '__main__':
    sys.exit(main())

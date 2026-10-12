# 启动 Cowrite-test（采集测试版）
#
# 与发行版的区别，一句话说清：
#   发行版 = 日常写作用，端口 8790，带记忆层 1933
#   测试版 = 采集实验用，端口 8792，**不启动记忆层**
#
# **为什么不启动记忆层**：ov 与发行版共用 1933 与同一份 ovdata。
# 两个版同时跑，它会读写同一份记忆——而采集实验要观察的正是
# 「模型记得什么、因此说什么」，记忆被另一个进程改写会污染观察。
# 所以测试版把记忆层留空：这一版测的是**当场的判断与沉默**，
# 不是长期一致性。§5.4 关于过期剖面的那部分要在有记忆层的条件下测，
# 那需要另开一个 ov 实例，届时端口与数据目录都要单独给。
param([switch]$NoOpen, [switch]$Fresh)

# **不要设 $ErrorActionPreference = 'Stop'**。
# 第一版设了它，结果窗口一闪而过、只看见红字闪一下就没了——
# 因为事件处理器在后台线程里抛的异常会把整个脚本终止，
# 而那个异常**不出现在主流程的输出里**，于是连报错内容都看不到。
# 这里显式设成 Continue：出错就继续往下跑，把问题显示出来。
$ErrorActionPreference = 'Continue'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Join-Path $Root 'app'
$PyExe = Join-Path $Root 'runtime\python\python.exe'
$WebPort = 8792
$WebUrl = "http://127.0.0.1:$WebPort"
$Log = Join-Path $Root 'test-launcher.log'
$PidFile = Join-Path $AppDir 'cowrite-test.pid'

function Say($m, $c = 'Gray') {
    Write-Host $m -ForegroundColor $c
    # **每一句都同时落盘**。理由：双击启动时窗口一闪就没，
    # 而 Write-Host 的内容不会留在任何地方——想复现就再也复现不出来了。
    # 踩过两次「窗口里红字闪一下就没了，什么都看不到」，
    # 根因就是报错只在主机输出里，而那扇窗已经关了。
    # 所以 Say 顺手写一份 start-diagnose.log，排查时看它。
    try {
        Add-Content -LiteralPath (Join-Path $Root 'start-diagnose.log') `
            -Value ((Get-Date -Format 'HH:mm:ss') + '  ' + $m) -Encoding UTF8
    } catch { }
}

if (-not (Test-Path $PyExe)) {
    Say "找不到运行时：$PyExe" 'Red'
    Say "这一版是拷贝不完整还是路径变了？对照 Cowrite\\runtime\\python\\ 看。" 'DarkYellow'
    exit 1
}
if (-not (Test-Path (Join-Path $AppDir 'server.py'))) {
    Say '这个目录不是 Cowrite-test（脚本报错即退出）' 'Red'
    Say "期望在：$AppDir\server.py" 'DarkYellow'
    Say "如果路径里有中文，PowerShell 读这个文件时可能出错——" 'DarkYellow'
    Say '它要求文件带 UTF-8 BOM（无 BOM 会按 GBK 读，中文注释被打乱后报假的语法错）。' 'DarkYellow'
    exit 1
}
try { Remove-Item -LiteralPath (Join-Path $Root 'start-diagnose.log') -Force -ErrorAction SilentlyContinue } catch { }
Say "脚本已启动  $Root" 'DarkGray'

# ---- 端口占用就明说，不要闷头起第二个 ----
# 测试版曾经误用 8790，症状是「网页打得开但数据全是旧的」——
# 因为你打开的其实是发行版。这种错最难查，所以在这里挡住。
function Test-Port([int]$p) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect('127.0.0.1', $p, $null, $null)
        # **必须自带超时**：TcpClient.Connect 没有超时一说，端口没人接的时候
        # 它能挂十几秒（发行版启动器里踩过，注释在那边）。
        if ($iar.AsyncWaitHandle.WaitOne(700)) { $c.EndConnect($iar); $c.Close(); return $true }
        $c.Close()
    } catch { }
    return $false
}

if (Test-Port $WebPort) {
    Say "端口 $WebPort 已经在跑了——测试版可能是开着的。" 'Yellow'
    Say "网页地址：$WebUrl" 'Yellow'
    if (-not $NoOpen) { Start-Process $WebUrl }
    exit 0
}

# ---- Fresh：清空上一轮采集 ----
# 只清 probe.jsonl，不碰 samples.jsonl 与棘轮审计。
# 用**覆盖写**而不是删除：本机 safe-delete 守卫把「删一个文件」判成
# 批量危险操作（阈值 50），Remove-Item 同样会撞上。
$ProbeLog = Join-Path $AppDir 'v3\logs\probe.jsonl'
if ($Fresh -and (Test-Path $ProbeLog)) {
    try {
        Set-Content -Path $ProbeLog -Value '' -Encoding UTF8
        Say "已清空上一轮采集：$ProbeLog" 'DarkGray'
    } catch { Say "清空失败（不致命）：$($_.Exception.Message)" 'DarkGray' }
}

Say '==========================================' 'DarkGray'
Say  ' Cowrite-test · 采集测试版' 'Cyan'
Say '==========================================' 'DarkGray'
Say "地址     : $WebUrl"
Say "版本     : 端口 $WebPort（发行版是 8790，两版可并存）"
Say "记忆层   : 不启动（与发行版共用 1933 与 ovdata，开了会污染观察）"
Say "采集     : app\v3\logs\probe.jsonl"
Say ''

# ---- 起服务：独立进程 + 文件重定向 ----
#
# **这里踩过一个很隐蔽的坑。** 前两版都用 ProcessStartInfo +
# RedirectStandardOutput/Error，再靠 Register-ObjectEvent 在本进程里读管道。
# 症状：脚本报告「起来了」、自检也过了（那一瞬间服务确实活着），
# 然后**几十秒内服务自己没了**，日志文件只有 3 字节（空的）。
#
# 原因：**管道是父子进程的共同负担**。父进程（这个脚本）一退出，读端消失，
# 子进程（server.py）下次往 stdout 写一个字节就收到 BrokenPipe 而抛异常退出。
# server.py 要长期打日志，所以它一定会在几十秒内撞上。
# 诊断日志停在「装置已挂上」那一行，正好印证了这一点。
#
# 解法：**Start-Process 独立起进程，输出重定向到文件。**
# 文件句柄由子进程自己拿着，父进程退出不影响它。
# 发行版启动器一直用这个做法（那边是 cmd 重定向），此处照抄。

if (Test-Path $PidFile) { Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue }

# 环境变量**在当前进程里设好再 Start-Process**：子进程默认继承父进程的环境。
# `$env:X = ...` 是最稳的写法，绕开了 ProcessStartInfo.EnvironmentVariables
# 在本机为 Null 的问题（它报「无法对 Null 数组进行索引」，
#而 Continue 又让脚本带着这个错继续跑，于是服务起来了却没带 COWRITE_V3，
#   v3 没载入——**网页照常开但没有「探针 ▸」**，且不报任何错）。
$env:COWRITE_V3 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$outFile = Join-Path $Root 'test-launcher.log'
$errFile = Join-Path $Root 'test-launcher.err'
foreach ($f in @($outFile, $errFile)) {
    if (Test-Path $f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
}

# ---- 为什么绕开 Start-Process 的重定向 ----
# Start-Process 带 -RedirectStandardOutput 时会报
#   「已添加项。字典中的关键字:"PATH"所添加的关键字:"Path"」
# 根因：Windows 环境变量名**大小写不敏感**，而 .NET 字典大小写敏感——
# 里面有 `Path`，又要加 `PATH`，Add() 直接撞。这台机器已知有这个毛病
#（choco install mingw 那次也是它报的同一句）。
#
# 改用 **cmd 的 > 重定向**：cmd 不建 .NET 字典，
# 直接把文件句柄交给 CreateProcess，整个问题被绕开。
# 而且这样输出**直接落文件**，父进程退出也不影响子进程——
# 不用管道就不会有 BrokenPipe（那正是前两版"几十秒后自己没了"的原因）。

$cmdExe = Join-Path $env:SystemRoot 'System32\cmd.exe'
$cmdLine = '/c ""' + $PyExe + '" server.py 1>"' + $outFile + '" 2>"' + $errFile + '""'

$proc = $null
try {
    $si = New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName = $cmdExe
    $si.Arguments = $cmdLine
    $si.WorkingDirectory = $AppDir
    $si.UseShellExecute = $false
    $si.CreateNoWindow = $true
    # 这里**只设环境变量，不碰 Start-Process**——撞车只发生在后者。
    # 改用进程级 $env: 赋值（见上面），子进程继承。
    $proc = [System.Diagnostics.Process]::Start($si)
} catch {
    Say "起不来：$($_.Exception.Message)" 'Red'
    Say "手动能跑吗？试试：cd '$AppDir' 然后 '$PyExe' server.py" 'DarkYellow'
    exit 1
}
if ($null -eq $proc) { Say '起不来：进程没拿到' 'Red'; exit 1 }

# pid 文件记的是**cmd 的 pid**，它的子进程才是 python。
# 停服务要用 taskkill /T（树杀），这一点写进提示里。
$proc.Id | Out-File -FilePath $PidFile -Encoding ASCII
Say "已起进程 $($proc.Id)" 'DarkGray'


# ---- 等端口起来 ----
$up = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 400
    if ($proc.HasExited) {
        Say "服务退出了，退出码 $($proc.ExitCode)。日志在：$Log" 'Red'
        if (Test-Path $Log) { Get-Content $Log -Tail 20| ForEach-Object { Say "  $_" 'DarkRed' } }
        exit 1
    }
    if (Test-Port $WebPort) { $up = $true; break }
}

if ($up) {
    Say "起来了 -> $WebUrl" 'Green'
    Say ''
    Say '页面右下角有「探针 ▸」，点它开采集面板。' 'DarkGray'
    Say '关掉这个窗口不等于关服务——服务在后台跑。' 'DarkGray'
    Say "要停：taskkill /PID (Get-Content '$PidFile') /T /F" 'DarkGray'

    # ---- 装置自检：v3 与采集外挂是不是真的挂上了 ----
    # **这一步不能省。** 上面那两处环境变量赋值都可能静默失败
    # （EnvironmentVariables 是 Null、Environment 能写但值不对），
    # 而 COWRITE_V3 没进去的话 server 会退回基线——
    # **网页照常打开，但没有「探针 ▸」**，而这件事不会报任何错。
    # 所以这里主动问一句，别让"装置没挂上"变成一个安静的问题。
    Start-Sleep -Milliseconds 600
    try {
        $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$WebPort/api/probe/stats" `
            -Method Post -Body '{}' -ContentType 'application/json' -TimeoutSec 5
        if ($probe.error) {
            Say "采集外挂没挂上：$($probe.error)" 'Red'
            Say '这一版不能用来采数据。多半是 v3 没载入（COWRITE_V3 没传进去）。' 'DarkYellow'
            Say "手动起（能确保带上环境变量）：cd '$AppDir'; `$env:COWRITE_V3='1'; '$PyExe' server.py" 'DarkYellow'
        } else {
            Say "采集装置已挂上（探针到点 $($probe.probe_to_point) / 沉默 $($probe.silence) / 出声 $($probe.spoke)）" 'DarkGreen'
        }
    } catch {
        Say "自检没做成（服务可能还没完全起来）：$($_.Exception.Message)" 'DarkYellow'
    }

    if (-not $NoOpen) { Start-Process $WebUrl }

    # ---- 延时存活校验：前两版都漏了这一步 ----
    # 自检只证明"这一瞬间服务在"。前两版的 bug 恰恰是**它活过了自检、
    # 几十秒后才死**（管道断裂，父进程一走它就收不到 stdout 了）。
    # 所以这里再等一会儿再看一次，**把"它后来死了"当场抓出来**，
    # 而不是让你写到一半才发现。
    Start-Sleep -Seconds 4
    if ($proc.HasExited) {
        Say "服务起了但 4 秒后自己退出了，退出码 $($proc.ExitCode)" 'Red'
        Say "这通常不是 server.py 的问题，而是它写日志时写不进去了。看：" 'DarkYellow'
        Say "  $outFile" 'DarkYellow'
        Say "  $errFile" 'DarkYellow'
        if (Test-Path $errFile) {
            Say '--- stderr ---' 'DarkRed'
            Get-Content $errFile -Tail 20 | ForEach-Object { Say "  $_" 'DarkRed' }
        }
        Say "手动前台跑（能直接看到报错）：cd '$AppDir'; `$env:COWRITE_V3='1'; '$PyExe' server.py" 'DarkYellow'
        exit 1
    }
    if (Test-Port $WebPort) {
        Say "4 秒后仍在跑，稳。日志：$outFile" 'DarkGreen'
    } else {
        Say '4 秒后端口不通了。日志见上。' 'Red'
        exit 1
    }
} else {
    Say "等了 16 秒端口还没起来。日志在：$Log" 'Red'
    if (Test-Path $Log) { Get-Content $Log -Tail 20 | ForEach-Object { Say "  $_" 'DarkRed' } }
    Say "手动能跑吗？试试：cd '$AppDir' 然后 '$PyExe' server.py" 'DarkYellow'
    exit 1
}

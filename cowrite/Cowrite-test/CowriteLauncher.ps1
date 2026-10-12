#requires -version 5.1
<#
====================================================================
 伴写启动器 (CowriteLauncher)
 --------------------------------------------------------------------
 双击桌面图标 = 拉起两样东西，然后开浏览器：
    ① OpenViking (1933) —— 记忆层的数据面
    ② 伴写网页服务 (8790) —— dsh-伴写/server.py
 顺序不能倒：网页服务启动时会去找记忆层，ov 没起来它也照跑（优雅降级），
 但那样这次写作就没有历史可依了，所以先把 ov 等出来。

 明确不做的事：不开机自启。不写 Run 键、不建计划任务、不放启动文件夹。
 要开机就有，得自己动手——这是故意的：伴写不是常驻服务，
 不想它在后台占着内存等一个可能不来的写作。

 布局：同一份文件既能跑分发出去的"便携布局"（app\ + runtime\ + ovdata\
 都在它旁边），也能跑本机的"开发布局"（应用在 lir\文献\dsh-伴写\）。
 判据是脚下有没有 app\server.py，见下面【配置】那一段。

 运行: powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File CowriteLauncher.ps1

 无头自检（不建窗口，跑完就退；给 selfcheck.ps1 与排障用）:
     powershell -NoProfile -ExecutionPolicy Bypass -File CowriteLauncher.ps1 -GuardCheck
   退出码：0=护栏无漂移（或还没封存过）  2=检出漂移  3=护栏配置错误  9=跑不起来

 它同时是"护栏检测"那条腿：棘轮校验点拦得住走补丁通道的改动，拦不住手改 params.json
 ——只有每次启动比一次指纹能发现。有漂移就在③那块标红，**不弹窗**：伴写的第一条铁律
 是不打断流动，启动器就站在它旁边，不该学个弹窗回来。
====================================================================
#>

param(
    [switch]$GuardCheck,      # 无头：只跑一次护栏审计就退出，不建窗口
    [string]$GuardParams,     # 排障/验收用：换掉 params.json 路径（不传就用真实配置）
    [string]$GuardLedger      # 同上，换掉棘轮账本路径
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ---------------------------- 配置 ----------------------------
# 启动器按脚下有没有 app\server.py，判自己坐在哪种布局里，只在这一段分岔；
# 下面全部 UI 与流程两种布局共用。这样分发出去的和本机开发用的是**同一份文件**，
# 不会出现"改了这边忘了那边"。
#
#   便携布局（分发出去的样子：整个目录可以搬到任何机器、任何位置）
#     <Root>\CowriteLauncher.ps1   ← 本文件（$Root = 本文件所在目录，下面 $AppDir 就是它）
#            \install.cmd           双击就装（内容纯 ASCII，所以不叫"安装.cmd"）
#            \install.ps1           首次运行：装运行时与记忆层
#            \selfcheck.ps1         环境体检（无头可跑，-Live 会真起一次）
#            \说明.txt
#            \app\                  应用本体（server.py + web/ + v3/）
#            \runtime\python\       内嵌 Python 3.13
#            \runtime\ov\           记忆层 venv（openviking==0.4.20）
#            \ovdata\               记忆层数据目录
#
#   开发布局（这台机器原来的样子）
#     启动器在 cowrite-launcher\，应用在 lir\文献\dsh-伴写\，
#     运行时用 workbuddy 托管的 python 与 ov venv。
$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir  = $Root

function Test-AsciiPath([string]$p) { return ($p -notmatch '[^\x00-\x7F]') }

if (Test-Path (Join-Path $Root 'app\server.py')) {
    $Layout  = '便携'
    $OvPy    = Join-Path $Root 'runtime\ov\Scripts\python.exe'
    $OvExe   = Join-Path $Root 'runtime\ov\Scripts\openviking-server.exe'
    $PyExe   = Join-Path $Root 'runtime\python\python.exe'
    $WebDir  = Join-Path $Root 'app'
    # ov 的数据目录相对当前工作目录，它对非 ASCII 路径又是硬伤（见下），
    # 所以能就地放就地放，安装目录里有中文就挪到 LOCALAPPDATA 去。
    $OvWork  = Join-Path $Root 'ovdata'
    if (-not (Test-AsciiPath $OvWork)) {
        $OvWork = Join-Path $env:LOCALAPPDATA 'Cowrite\ovdata'
    }
} else {
    $Layout  = '开发'
    $OvPy    = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\ov\Scripts\python.exe'
    $OvExe   = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\ov\Scripts\openviking-server.exe'
    $PyExe   = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\versions\3.13.12\python.exe'
    $WebDir  = '%DSH_ROOT%\lir\文献\dsh-伴写'
    $OvWork  = '%DSH_ROOT%\ovdata'
}

# 护栏（棘轮校验点）的三条路径，与 $WebDir 同源，两种布局都自动对得上。
# params.json 是候选补丁要改的东西；账本是 --seal 封指纹、--audit 比漂移的地方。
$RatchetPy     = Join-Path $WebDir 'v3\ratchet.py'
$RatchetParams = Join-Path $WebDir 'v3\params.json'
$RatchetLedger = Join-Path $WebDir 'v3\logs\棘轮审计.jsonl'

# ov 是 venv 里的 console script：直接双击那个 .exe 起不来，
# 得由同目录的 python.exe 去跑它——跟手工启动时观察到的命令行保持一致。
$OvPort   = 1933
# ov 只认纯 ASCII 的工作目录：里面一旦有中文，启动时就 UnicodeDecodeError 直接退出
# （实测在 %DSH_ROOT%\lir\文献\ 下起，报 'utf-8' codec can't decode 0xd5）。
# 所以上面两条路都显式给它一个纯 ASCII 的目录，从不让它继承当前目录。
$OvPid    = Join-Path $AppDir "ov.pid"

$WebPort  = 8790
$WebPid   = Join-Path $AppDir "cowrite-web.pid"

$WebUrl   = "http://127.0.0.1:8790"

$LauncherLog = Join-Path $AppDir "launcher.log"

# ---------------------------- 工具 ----------------------------
function Test-PortOpen([int]$p) {
    <# 必须自带超时。TcpClient.Connect 没有超时一说，端口没人接的时候
       它能挂十几秒——实测这一步就把整个启动流程拖死了。
       改成异步连接 + 最多等 800ms。 #>
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $c.BeginConnect('127.0.0.1', $p, $null, $null)
        if ($ar.AsyncWaitHandle.WaitOne(800)) {
            if ($c.Connected) { return $true }
        }
        return $false
    } catch { return $false }
    finally { try { $c.Close() } catch { } }
}

function Get-ByPidFile([string]$f) {
    if (Test-Path $f) {
        $id = (Get-Content $f -Raw -ErrorAction SilentlyContinue).Trim()
        if ($id -match '^\d+$') {
            $p = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
            if ($p) { return $p }
        }
    }
    return $null
}

function Get-OvProcess {
    $p = Get-ByPidFile $OvPid
    if ($p) { return $p }
    # ov 是 python.exe 跑 openviking-server.exe，所以按命令行认，不按进程名认
    $c = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -match 'openviking-server' } | Select-Object -First 1
    if ($c) { return (Get-Process -Id $c.ProcessId -ErrorAction SilentlyContinue) }
    return $null
}

function Get-WebProcess {
    $p = Get-ByPidFile $WebPid
    if ($p) { return $p }
    $c = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -match 'server\.py' } | Select-Object -First 1
    if ($c) { return (Get-Process -Id $c.ProcessId -ErrorAction SilentlyContinue) }
    return $null
}

function Start-Hidden([string]$exe, [string]$argList, [string]$workDir) {
    <# 起一个不露窗口的后台进程，返回 pid。

       为什么不用 Start-Process：它内部要用一个**不区分大小写**的字典装环境
       变量，环境里但凡有只是大小写不同的两个（Path/PATH、HTTP_PROXY/http_proxy
       都实测撞过），它就抛"已添加了具有相同键的项"，然后什么都不起。
       而这个重复是枚举不出来的——Env: 驱动大小写不敏感，永远只看得见一个，
       所以也没法提前清。.NET 的 Process 直接走 CreateProcess，没这道转换。

       为什么不用 cmd /c 包一层做重定向：那样拿到的 pid 是 cmd 的，
       点"停止"时只杀了壳，真正的服务还活着。

       代价：服务自己的 stdout 不落到文件里。启动器自己的动作照旧写
       launcher.log，"看日志"按钮指的就是它。

       走 ShellExecute 而不是直接 CreateProcess：前者由 shell 托管，
       服务因此不挂在启动器这个进程树下——关掉启动器窗口、甚至启动器
       自己崩了，正在写的网页服务也还在。 #>
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = $argList
    if ($workDir) { $psi.WorkingDirectory = $workDir }
    $psi.UseShellExecute = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    return $proc.Id
}

function Install-Hint {
    # 便携版第一次跑，运行时还没装——这是最可能撞上的一种"什么都没起来"。
    # 与其让人对着"找不到 xxx"猜，不如直接把下一步写出来。
    if ($Layout -eq '便携') { return '（首次使用要先运行同目录的『安装.ps1』）' }
    return ''
}

# openviking 的数据目录锁是一个 PID 文件（utils/process_lock.py）：启动时读它，
# 若里面那个 PID "还活着"就抛 DataDirectoryLocked 拒绝启动。它的存活检查只在
# Linux 分支顺带验一下"那进程是不是 OpenViking"（读 /proc/<pid>/cmdline），
# **Windows 分支没有这一步** —— 而 Windows 恰恰会复用 PID。
#
# 于是凑成一条几乎必然复现的故障链：
#   ① 上一次 ov 是被 Stop-Process -Force 杀的（见 Stop-All），atexit 里的清锁不执行
#      → 锁文件留在原地，写着那个已死的 PID；
#   ② 那个 PID 号随后被系统分给任意进程（本机实测分给了 svchost.exe）；
#   ③ 下次起 ov，它看到"PID 3848 活着"就判定锁被持有 → 直接退出 → 1933 永不开；
#   ④ 表现给用户的，就是「等记忆层超时（约 60s）。继续起网页——没有记忆也能写」。
#
# 下面这条函数替它补上 Windows 缺的那一步：锁指向的进程若压根不是 ov，就当陈旧锁清掉。
# 只在 1933 没开的前提下调用（Start-Ov 开头已判），所以不会误删真实例的锁。
function Clear-StaleOvLock {
    $lock = Join-Path $OvWork 'data\.openviking.pid'
    if (-not (Test-Path $lock)) { return $false }
    $raw = Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1
    $lockPid = 0
    if (-not [int]::TryParse(("$raw").Trim(), [ref]$lockPid)) { return $false }
    if ($lockPid -le 0) { return $false }
    $p = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    $stale = $false
    if ($null -eq $p) {
        $stale = $true                      # 持有者已经死了
    } elseif (("$($p.ProcessName)").ToLower() -notmatch 'python|openviking') {
        $stale = $true                      # PID 被复用给了不相干的进程
    }
    if ($stale) {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
        Write-Log "发现陈旧的数据目录锁（PID $lockPid 不是 ov），已清除：$lock"
    }
    return $stale
}

function Start-Ov {
    if (Test-PortOpen $OvPort) { return $null }
    foreach ($f in @($OvPy, $OvExe)) {
        if (-not (Test-Path $f)) { throw "找不到 OpenViking 组件：$f $(Install-Hint)" }
    }
    if (-not (Test-Path $OvWork)) {
        New-Item -ItemType Directory -Path $OvWork -Force | Out-Null
    }
    Clear-StaleOvLock | Out-Null
    $id = Start-Hidden $OvPy ('"' + $OvExe + '"') $OvWork
    $id | Set-Content $OvPid -Encoding ASCII
    return $id
}

function Start-WebProcess {
    if (Test-PortOpen $WebPort) { return $null }
    if (-not (Test-Path $PyExe)) { throw "找不到 python：$PyExe $(Install-Hint)" }
    if (-not (Test-Path (Join-Path $WebDir 'server.py'))) { throw "找不到 server.py：$WebDir" }
    $id = Start-Hidden $PyExe 'server.py' $WebDir
    $id | Set-Content $WebPid -Encoding ASCII
    return $id
}

function Stop-ByPidFile([string]$f, [scriptblock]$finder) {
    $p = & $finder
    if ($p) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
}

function Get-MemStatus {
    try {
        return (Invoke-RestMethod -Uri "$WebUrl/api/memory" -TimeoutSec 4)
    } catch { return $null }
}

function Open-Url([string]$url) {
    # 同样不用 Start-Process（见 Start-Hidden 的注释）。UseShellExecute 走默认浏览器。
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $url
    $psi.UseShellExecute = $true
    [void][System.Diagnostics.Process]::Start($psi)
}

function Open-Text([string]$path) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'notepad.exe'
    $psi.Arguments = '"' + $path + '"'
    $psi.UseShellExecute = $false
    [void][System.Diagnostics.Process]::Start($psi)
}

# ---------------------------- 护栏（棘轮校验点） ----------------------------
function Invoke-Capture([string]$Exe, [string[]]$ArgList, [string]$WorkDir, [int]$TimeoutSec = 25) {
    <# 起一个短命进程，把它的输出收回来——**一定要能超时**。
       走 .NET Process 而不是 & 调用运算符：解释器半死不活的时候，调用运算符会一直挂着，
       那比报错更没用（自检脚本里同一个理由，见 portable\selfcheck.ps1 的 Run）。 #>
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        # UseShellExecute=$false 时 FileName 不要加引号，API 自己处理带空格的路径。
        $psi.FileName = $Exe
        $psi.Arguments = ($ArgList | ForEach-Object {
            if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
        }) -join ' '
        if ($WorkDir) { $psi.WorkingDirectory = $WorkDir }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $p = [System.Diagnostics.Process]::Start($psi)
        $o = $p.StandardOutput.ReadToEnd()
        $e = $p.StandardError.ReadToEnd()
        if (-not $p.WaitForExit($TimeoutSec * 1000)) {
            try { $p.Kill() } catch { }
            return @{ code = -999; out = ''; err = "超时（>${TimeoutSec}s）" }
        }
        return @{ code = $p.ExitCode; out = $o.Trim(); err = $e.Trim() }
    } catch { return @{ code = -998; out = ''; err = $_.Exception.Message } }
}

function Invoke-OvDiagnose {
    <# 记忆层起不来时，把"为什么"捞回来。

       必要性来自一个结构性的沉默：启动器用 UseShellExecute 起 ov（为的是让
       服务不挂在启动器这棵进程树下，见 Start-Hidden），代价就是**服务的
       stderr 哪儿都不落**。于是记忆层起不来时，日志里只有一句"等记忆层超时"，
       而真正的原因（少一个模块、解释器找不到、配置没生成）全丢在空气里 ——
       对着那句话，下一步只能靠猜。这个函数把原因补上。

       查的是**启动入口那条链**：启动器实际起 ov 走的就是它。只查"openviking
       这个包在不在"是不够的，这一点有代价——包内 runtime\ov 是整体拷来的
       venv，拷贝规则误伤过一次（openai/_legacy_response.py 被删），
       顶层 import 正常、入口那一 import 就炸。 #>
    Write-Log '  记忆层为什么没起来 —— 跑一次诊断：'
    $ok = $true
    if (-not (Test-Path $OvPy)) { Write-Log "    x 找不到记忆层的解释器：$OvPy"; $ok = $false }
    if (-not (Test-Path $OvExe)) { Write-Log "    x 找不到记忆层入口：$OvExe"; $ok = $false }
    $ovConf = Join-Path $env:USERPROFILE '.openviking\ov.conf'
    if (-not (Test-Path $ovConf)) {
        Write-Log "    x 没有服务配置：$ovConf"
        Write-Log '      ov 找不到它会直接拒绝启动。安装脚本会生成它 —— 没跑过安装就先双击 install.cmd。'
        $ok = $false
    }
    if (-not $ok) { return }

    $r = Invoke-Capture $OvPy @('-B', '-c', "import importlib.metadata as m;import openviking.server.bootstrap;print(m.version('openviking'))") $OvWork 90
    if ($r.code -eq 0) {
        Write-Log "    入口可以加载（openviking $($r.out)）。那就不缺件 —— 接着看数据目录锁："
        # 缺件之外，真正最常见的其实是数据目录锁（见 Clear-StaleOvLock 上面那段注释）。
        # 2026-09-21 那次"入口可以加载却起不来"，就是锁被一个复用来的 PID 挡着，
        # 而当时的诊断只含糊地指向"端口被占／目录不可写／机器慢"，一条都不对。
        # 所以这里把锁的状态直接报出来，不再让下一个人去猜。
        $lock = Join-Path $OvWork 'data\.openviking.pid'
        if (-not (Test-Path $lock)) {
            Write-Log '    数据目录锁：没有（干净）'
        } else {
            $raw = Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1
            $lockPid = 0
            if ([int]::TryParse(("$raw").Trim(), [ref]$lockPid) -and $lockPid -gt 0) {
                $lp = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
                if ($null -eq $lp) {
                    Write-Log "    数据目录锁：指向 PID $lockPid，但那个进程已经没了 → 陈旧锁，会挡住 ov 启动。"
                    Write-Log "      点『启动』会自动清掉；要手动清就删 $lock"
                } elseif (("$($lp.ProcessName)").ToLower() -notmatch 'python|openviking') {
                    Write-Log "    数据目录锁：指向 PID $lockPid = $($lp.ProcessName)，这不是 ov"
                    Write-Log '      （Windows 把那个号复用给了别的进程）→ ov 会误判锁被持有而拒绝启动。'
                    Write-Log '      点『启动』会自动清掉。'
                } else {
                    Write-Log "    数据目录锁：PID $lockPid（$($lp.ProcessName)）正持有 —— 确实有实例在跑。"
                }
            } else {
                Write-Log "    数据目录锁：内容读不出来（$lock）"
            }
        }
        Write-Log '    若上面都不像，再往端口被占、数据目录不可写、或这台机器上就是慢这几处想。'
        return
    }
    if ($r.code -eq -999) { Write-Log '    入口探测超时（>90s）：加载它就是慢成这样，或者它卡在等网络。'; return }
    if ($r.code -eq -998) { Write-Log "    解释器起不来：$($r.err)"; return }
    Write-Log "    入口加载失败（退出码 $($r.code)）："
    foreach ($line in (($r.err -split "`r?`n") | Where-Object { $_ -ne '' } | Select-Object -Last 8)) {
        Write-Log "      $line"
    }
}

function Invoke-RatchetAudit {
    <# 跑一次 v3\ratchet.py --audit，把结果归成五种状态。
       它只比指纹、**不写任何东西**（--audit 不落账本，只有 --seal 才写）。
       退出码是 ratchet.py 定的：0=过、2=漂移、3=配置错误。 #>
    if (-not (Test-Path $RatchetPy)) {
        return @{ state = 'unavailable'; text = "没有 $RatchetPy" }
    }
    if (-not (Test-Path $PyExe)) {
        return @{ state = 'unavailable'; text = "没有可用的 python（$PyExe）" }
    }
    # -X utf8 不能省：ratchet.py 打的是中文，不加这个它在 Windows 上按 GBK 往外写，
    # 而我们按 UTF-8 收，收回来就是一堆问号。同一个坑自检脚本里也踩过，同一个解法。
    $ra = @('-X', 'utf8', $RatchetPy, '--audit')
    if ($GuardParams) { $ra += @('--params', $GuardParams) }
    if ($GuardLedger) { $ra += @('--ledger', $GuardLedger) }
    $r = Invoke-Capture $PyExe $ra $WebDir 25
    if ($r.code -eq -999 -or $r.code -eq -998) {
        return @{ state = 'unavailable'; text = "$($r.err)" }
    }
    $text = if ($r.out) { $r.out } else { $r.err }
    switch ($r.code) {
        0 {
            # 一次都没封存过时，audit 仍然报"通过"——那只是映射完整，比不出漂移。
            # 这两种"通过"差得很远，面板上必须分开说。
            if ($text -match '无（跑 --seal 建一个）') { return @{ state = 'unsealed'; text = $text } }
            return @{ state = 'ok'; text = $text }
        }
        2 { return @{ state = 'drift';  text = $text } }
        3 { return @{ state = 'config'; text = $text } }
        default { return @{ state = 'unavailable'; text = "退出码 $($r.code)：$text" } }
    }
}

# ---------------------- 无头模式：-GuardCheck ----------------------
# 给 selfcheck.ps1、排障、以后挂定时任务用：不建窗口，跑一次护栏审计就退出。
# -GuardParams / -GuardLedger 换掉那两个路径——用来"先审计一份候选配置再决定要不要采纳"，
# 或者让验收脚本拿一份动过手脚的副本去验"漂移真的会被点名"。不传就一律用真实配置。
# 退出码与 v3\ratchet.py 对齐，另加 9 = 跑不起来（没 python / 没 ratchet.py）。
if ($GuardCheck) {
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
    $g = Invoke-RatchetAudit
    Write-Output $g.text
    switch ($g.state) {
        'ok'       { exit 0 }
        'unsealed' { exit 0 }
        'drift'    { exit 2 }
        'config'   { exit 3 }
        default    { exit 9 }
    }
}

# ---------------------------- UI ----------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = "伴写启动器"
$form.ClientSize = New-Object System.Drawing.Size(500, 548)   # 比原来高 68 = 护栏那一块
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 253)

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "伴写启动器"
$lblTitle.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 16, [System.Drawing.FontStyle]::Bold)
$lblTitle.Location = New-Object System.Drawing.Point(16, 12)
$lblTitle.Size = New-Object System.Drawing.Size(240, 34)

$lblSub = New-Object System.Windows.Forms.Label
$lblSub.Text = "OpenViking 记忆层 + 伴写网页 · 不会开机自启"
$lblSub.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$lblSub.ForeColor = [System.Drawing.Color]::Gray
$lblSub.Location = New-Object System.Drawing.Point(18, 48)
$lblSub.Size = New-Object System.Drawing.Size(360, 20)

# ---- 记忆层 (ov) ----
$grpOv = New-Object System.Windows.Forms.GroupBox
$grpOv.Text = "① 记忆层 · OpenViking (1933)"
$grpOv.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10, [System.Drawing.FontStyle]::Bold)
$grpOv.Location = New-Object System.Drawing.Point(16, 78)
$grpOv.Size = New-Object System.Drawing.Size(468, 96)

$lblOv = New-Object System.Windows.Forms.Label
$lblOv.Text = "检测中…"
$lblOv.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9.5)
$lblOv.Location = New-Object System.Drawing.Point(14, 26)
$lblOv.Size = New-Object System.Drawing.Size(440, 22)

$lblOvHint = New-Object System.Windows.Forms.Label
$lblOvHint.Text = "记忆层不在也能写——只是这次没有历史可依"
$lblOvHint.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8)
$lblOvHint.ForeColor = [System.Drawing.Color]::Gray
$lblOvHint.Location = New-Object System.Drawing.Point(16, 58)
$lblOvHint.Size = New-Object System.Drawing.Size(436, 18)

$grpOv.Controls.AddRange(@($lblOv, $lblOvHint))

# ---- 网页服务 ----
$grpWeb = New-Object System.Windows.Forms.GroupBox
$grpWeb.Text = "② 伴写网页 (8790)"
$grpWeb.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10, [System.Drawing.FontStyle]::Bold)
$grpWeb.Location = New-Object System.Drawing.Point(16, 186)
$grpWeb.Size = New-Object System.Drawing.Size(468, 108)

$lblWeb = New-Object System.Windows.Forms.Label
$lblWeb.Text = "检测中…"
$lblWeb.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9.5)
$lblWeb.Location = New-Object System.Drawing.Point(14, 26)
$lblWeb.Size = New-Object System.Drawing.Size(440, 22)

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = "启动"
$btnStart.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$btnStart.Location = New-Object System.Drawing.Point(14, 60)
$btnStart.Size = New-Object System.Drawing.Size(80, 32)
$btnStart.UseVisualStyleBackColor = $true

$btnOpen = New-Object System.Windows.Forms.Button
$btnOpen.Text = "打开网页"
$btnOpen.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$btnOpen.Location = New-Object System.Drawing.Point(102, 60)
$btnOpen.Size = New-Object System.Drawing.Size(88, 32)
$btnOpen.UseVisualStyleBackColor = $true

$btnStop = New-Object System.Windows.Forms.Button
$btnStop.Text = "全部停止"
$btnStop.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$btnStop.Location = New-Object System.Drawing.Point(198, 60)
$btnStop.Size = New-Object System.Drawing.Size(88, 32)
$btnStop.UseVisualStyleBackColor = $true

$btnWebLog = New-Object System.Windows.Forms.Button
$btnWebLog.Text = "启动日志"
$btnWebLog.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$btnWebLog.Location = New-Object System.Drawing.Point(294, 60)
$btnWebLog.Size = New-Object System.Drawing.Size(88, 32)
$btnWebLog.UseVisualStyleBackColor = $true

$btnMem = New-Object System.Windows.Forms.Button
$btnMem.Text = "记忆状态"
$btnMem.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$btnMem.Location = New-Object System.Drawing.Point(390, 60)
$btnMem.Size = New-Object System.Drawing.Size(68, 32)
$btnMem.UseVisualStyleBackColor = $true

$grpWeb.Controls.AddRange(@($lblWeb, $btnStart, $btnOpen, $btnStop, $btnWebLog, $btnMem))

# ---- 护栏（棘轮校验点）----
# 独立一块，因为它是**看**的，不是**按**的：启动时自动比一次指纹，出问题标红。
# 放在服务状态下面而不是塞进按钮排里，是为了让"红"这件事一眼扫得到。
$grpGuard = New-Object System.Windows.Forms.GroupBox
$grpGuard.Text = "③ 护栏 · 棘轮校验点"
$grpGuard.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10, [System.Drawing.FontStyle]::Bold)
$grpGuard.Location = New-Object System.Drawing.Point(16, 302)
$grpGuard.Size = New-Object System.Drawing.Size(468, 64)

$lblGuard = New-Object System.Windows.Forms.Label
$lblGuard.Text = "检测中…"
$lblGuard.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9.5)
$lblGuard.Location = New-Object System.Drawing.Point(14, 24)
$lblGuard.Size = New-Object System.Drawing.Size(322, 24)

$btnGuardDetail = New-Object System.Windows.Forms.Button
$btnGuardDetail.Text = "详情"
$btnGuardDetail.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$btnGuardDetail.Location = New-Object System.Drawing.Point(340, 22)
$btnGuardDetail.Size = New-Object System.Drawing.Size(54, 28)
$btnGuardDetail.UseVisualStyleBackColor = $true

$btnGuardSeal = New-Object System.Windows.Forms.Button
$btnGuardSeal.Text = "封存基线"
$btnGuardSeal.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
$btnGuardSeal.Location = New-Object System.Drawing.Point(398, 22)
$btnGuardSeal.Size = New-Object System.Drawing.Size(62, 28)
$btnGuardSeal.UseVisualStyleBackColor = $true

$grpGuard.Controls.AddRange(@($lblGuard, $btnGuardDetail, $btnGuardSeal))

# ---- 状态输出 ----
$txtOut = New-Object System.Windows.Forms.TextBox
$txtOut.Multiline = $true
$txtOut.ReadOnly = $true
$txtOut.ScrollBars = 'Vertical'
$txtOut.Font = New-Object System.Drawing.Font("Consolas", 9)
$txtOut.Location = New-Object System.Drawing.Point(16, 374)
$txtOut.Size = New-Object System.Drawing.Size(468, 132)
$txtOut.BackColor = [System.Drawing.Color]::FromArgb(30, 32, 38)
$txtOut.ForeColor = [System.Drawing.Color]::FromArgb(220, 224, 230)
$txtOut.BorderStyle = 'FixedSingle'

$lblHint = New-Object System.Windows.Forms.Label
$lblHint.Text = "日志与 pid 放在启动器同目录。本启动器不注册开机自启——要开机就有，得自己加。"
$lblHint.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 8)
$lblHint.ForeColor = [System.Drawing.Color]::Gray
$lblHint.Location = New-Object System.Drawing.Point(16, 512)
$lblHint.Size = New-Object System.Drawing.Size(468, 24)

$form.Controls.AddRange(@($lblTitle, $lblSub, $grpOv, $grpWeb, $grpGuard, $txtOut, $lblHint))

# ---------------------------- 逻辑 ----------------------------
function Write-Log([string]$s) {
    $t = Get-Date -Format "HH:mm:ss"
    $line = "[$t] $s`r`n"
    try { $txtOut.AppendText($line) } catch { }
    # 同时落盘：窗口一关，框里的字就跟着没了，下次出问题无从查起。
    # 用 .NET 直接追加而不是 Add-Content——后者在窗口线程里会偶发静默失败，
    # 一旦失败就什么都查不到了。
    try {
        [System.IO.File]::AppendAllText($LauncherLog, $line,
            (New-Object System.Text.UTF8Encoding $false))
    } catch { }
}

function Update-Status {
    if (Test-PortOpen $OvPort) {
        $lblOv.Text = "● 运行中 — 127.0.0.1:$OvPort"
        $lblOv.ForeColor = [System.Drawing.Color]::SeaGreen
    } else {
        $lblOv.Text = "○ 未运行"
        $lblOv.ForeColor = [System.Drawing.Color]::Firebrick
    }
    if (Test-PortOpen $WebPort) {
        $lblWeb.Text = "● 运行中 — $WebUrl"
        $lblWeb.ForeColor = [System.Drawing.Color]::SeaGreen
        $btnStart.Enabled = $false
        $btnStop.Enabled  = $true
        $btnOpen.Enabled  = $true
        $btnMem.Enabled   = $true
    } else {
        $lblWeb.Text = "○ 未运行"
        $lblWeb.ForeColor = [System.Drawing.Color]::Firebrick
        $btnStart.Enabled = $true
        $btnStop.Enabled  = $false
        $btnOpen.Enabled  = $false
        $btnMem.Enabled   = $false
    }
}

function Update-GuardStatus {
    <# 每次启动比一次护栏指纹。
       这是"检测"那条腿：棘轮校验点（v3\ratchet.py）只拦得住走 --apply 的补丁，
       手改 params.json 它拦不住——只有这个比对能发现有人动过冻结面。

       这里**故意不弹窗**：有漂移就标红，等你回头看。伴写的第一条铁律是不打断流动，
       启动器站在它旁边，不该自己学了弹窗回来。 #>
    $g = Invoke-RatchetAudit
    switch ($g.state) {
        'ok'       { $lblGuard.Text = '● 无漂移 — 冻结项与指纹一致'
                     $lblGuard.ForeColor = [System.Drawing.Color]::SeaGreen }
        'unsealed' { $lblGuard.Text = '○ 尚未封存基线 — 没有可比的东西'
                     $lblGuard.ForeColor = [System.Drawing.Color]::DarkOrange }
        'drift'    { $lblGuard.Text = '★ 检出漂移 — 冻结面被改过，点「详情」'
                     $lblGuard.ForeColor = [System.Drawing.Color]::Firebrick }
        'config'   { $lblGuard.Text = '★ 配置错误 — 护栏映射不完整，点「详情」'
                     $lblGuard.ForeColor = [System.Drawing.Color]::Firebrick }
        default    { $lblGuard.Text = '· 护栏没跑起来（点「详情」看原因）'
                     $lblGuard.ForeColor = [System.Drawing.Color]::Gray }
    }
    # 落盘那一行要带点实质内容：窗口一关框里的字就没了，出问题时 log 是唯一的线索。
    $brief = @($g.text -split "`r?`n" |
               Where-Object { $_ -match '^\s*\[(不合|配置)\]' } |
               Select-Object -First 3) -join ' ｜ '
    if ($brief) { Write-Log "护栏：$($g.state) — $brief" }
    else        { Write-Log "护栏：$($g.state)" }
}

# 启动是**分步等端口**的：ov 先起来，等它真的能连上，再起网页。
# 用 Timer 而不是 Start-Sleep，否则整个窗口在等待期间是死的。
$script:Seq = $null
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 600

# 双击图标后的自动启动也交给 timer 的第一跳，而不是直接在 Shown 里干：
# Shown 事件期间 UI 还在完成首次绘制，在里面做阻塞式 I/O 会把窗口拖死
# （实测就是卡在这儿——端口探测本身只要 800ms，窗口却再也不动了）。
$script:BootPending = $true

$timer.Add_Tick({
    try {
        if ($script:BootPending) {
            $script:BootPending = $false
            Boot-Step
            if ($null -eq $script:Seq) { $timer.Stop() }
            return
        }
        Tick-Step
    } catch {
        Write-Log "轮询异常：$($_.Exception.Message)"
        $script:Seq = $null; $script:BootPending = $false
        $timer.Stop(); Update-Status
    }
})

function Boot-Step {
    Write-Log "伴写启动器 — 不注册开机自启（$Layout 布局）"
    Write-Log "应用 $WebDir"
    if ($Layout -eq '便携' -and -not (Test-Path $PyExe)) {
        Write-Log "运行时还没装：$PyExe"
        [System.Windows.Forms.MessageBox]::Show(
            "这个便携版还没装运行时。`n`n请右键同目录的『安装.ps1』→『使用 PowerShell 运行』，装完再双击本图标。",
            "伴写启动器", 'OK', 'Warning') | Out-Null
        Update-Status
        return
    }
    Update-GuardStatus      # 趁还没开写，先把护栏的事摆出来——写起来再发现就晚了
    Update-Status
    if ((Test-PortOpen $OvPort) -and (Test-PortOpen $WebPort)) {
        Write-Log "两个都在跑，直接开网页"
        Open-Url $WebUrl
        return
    }
    if (-not (Test-PortOpen $WebPort)) { Start-All; return }
    Write-Log "网页在跑，记忆层不在。可点『启动』补起记忆层。"
}

function Tick-Step {
    if ($null -eq $script:Seq) { return }
    $step = $script:Seq.Step
    $script:Seq.Waited += 1

    if ($step -eq 'ov') {
        if (Test-PortOpen $OvPort) {
            Write-Log "记忆层就绪 (1933)"
            try {
                $id = Start-WebProcess
                if ($null -eq $id) {
                    Write-Log "网页服务已在运行"
                    $script:Seq = $null; $timer.Stop(); Update-Status; Open-Url $WebUrl; return
                }
                Write-Log "网页服务进程已起 (pid $id)，等 8790 …"
                $script:Seq = @{ Step = 'web'; Waited = 0 }
            } catch {
                Write-Log "起网页服务失败：$($_.Exception.Message)"
                $script:Seq = $null; $timer.Stop(); Update-Status
            }
            return
        }
        if ($script:Seq.Waited -gt 100) {
            Write-Log "等记忆层超时（约 60s）。继续起网页——没有记忆也能写。"
            # 没有这一句，上面那行就是死胡同：它说出"没起来"，却半个字不提为什么。
            Invoke-OvDiagnose
            try {
                $id = Start-WebProcess
                Write-Log "网页服务进程已起 (pid $id)，等 8790 …"
                $script:Seq = @{ Step = 'web'; Waited = 0 }
            } catch {
                Write-Log "起网页服务失败：$($_.Exception.Message)"
                $script:Seq = $null; $timer.Stop(); Update-Status
            }
        }
        return
    }

    if ($step -eq 'web') {
        if (Test-PortOpen $WebPort) {
            Write-Log "网页就绪，开浏览器"
            $script:Seq = $null
            $timer.Stop()
            Update-Status
            Open-Url $WebUrl
            return
        }
        if ($script:Seq.Waited -gt 60) {
            Write-Log "等网页超时（约 36s）。可直接浏览器开 $WebUrl 试试。"
            $script:Seq = $null
            $timer.Stop()
            Update-Status
        }
    }
}

function Start-All {
    Write-Log "Start-All: 进入"
    $btnStart.Enabled = $false
    Update-Status
    $ovUp  = Test-PortOpen $OvPort
    $webUp = Test-PortOpen $WebPort
    Write-Log ("探测端口 ov=" + $ovUp + " web=" + $webUp)
    if (-not (Test-PortOpen $OvPort)) {
        try {
            Write-Log "准备起 ov：$OvPy"
            $id = Start-Ov
            Write-Log "记忆层进程已起 (pid $id)，等 1933 …"
        } catch {
            Write-Log "起记忆层失败：$($_.Exception.Message)"
            Write-Log "没关系，照样能写，只是这次没有历史。"
            if (-not (Test-PortOpen $WebPort)) {
                try { $wid = Start-WebProcess; Write-Log "网页服务进程已起 (pid $wid)，等 8790 …"; $script:Seq = @{ Step = 'web'; Waited = 0 }; $timer.Start() }
                catch { Write-Log "起网页服务也失败：$($_.Exception.Message)"; Update-Status }
                return
            }
            Update-Status
            return
        }
        $script:Seq = @{ Step = 'ov'; Waited = 0 }
        $timer.Start()
    } elseif (-not (Test-PortOpen $WebPort)) {
        try { $wid = Start-WebProcess; Write-Log "网页服务进程已起 (pid $wid)，等 8790 …"; $script:Seq = @{ Step = 'web'; Waited = 0 }; $timer.Start() }
        catch { Write-Log "起网页服务失败：$($_.Exception.Message)"; Update-Status }
    } else {
        Write-Log "两个都已经在跑"
        Update-Status
        Open-Url $WebUrl
    }
}

function Stop-All {
    Write-Log "停止网页服务 …"
    Stop-ByPidFile $WebPid { Get-WebProcess }
    Write-Log "停止记忆层 …"
    Stop-ByPidFile $OvPid { Get-OvProcess }
    # ov 是被 -Force 杀的，atexit 里的清锁不会跑，锁文件会留在原地；而它的 PID
    # 随后会被 Windows 复用给别的进程，下次启动就误判"锁被持有"（见 Clear-StaleOvLock）。
    # 所以停机时顺手把锁收掉，不留残骸。
    $ovLock = Join-Path $OvWork 'data\.openviking.pid'
    if (Test-Path $ovLock) { Remove-Item $ovLock -Force -ErrorAction SilentlyContinue }
    Write-Log "已停"
    Start-Sleep -Milliseconds 600
    Update-Status
}

$btnStart.Add_Click({ Start-All })
$btnOpen.Add_Click({ Open-Url $WebUrl })
$btnStop.Add_Click({ Stop-All })
$btnWebLog.Add_Click({ if (Test-Path $LauncherLog) { Open-Text $LauncherLog } else { [System.Windows.Forms.MessageBox]::Show("启动日志尚未生成", "伴写启动器", 'OK', 'Information') } })

$btnMem.Add_Click({
    $m = Get-MemStatus
    if ($null -eq $m) { [System.Windows.Forms.MessageBox]::Show("读不到 /api/memory —— 网页服务没起，或接口没开。", "记忆层", 'OK', 'Warning'); return }
    $txt = @(
        "可用:        $(if ($m.ok) { '是' } else { '否' })",
        "状态:        $($m.status)",
        "作品:        $($m.work)",
        "Part:        $($m.part)",
        "已灌段:      $($m.indexed) / $($m.total)",
        "错误:        $(if ($m.err) { $m.err } else { '（无）' })"
    ) -join "`n"
    [System.Windows.Forms.MessageBox]::Show($txt, "记忆层状态", 'OK', 'Information')
})

$btnGuardDetail.Add_Click({
    $g = Invoke-RatchetAudit
    $icon = 'Information'
    $head = switch ($g.state) {
        'ok'       { '目前没有漂移：冻结项取值、冻结文件指纹、锁本体指纹都与上次封存一致。' }
        'unsealed' { '还没封存过基线，所以没有可比的东西——现在只能查"护栏映射完不完整"。' }
        'drift'    { '检出漂移：下面点名的地方和你上次封存的不一样。' }
        'config'   { '配置错误：护栏映射不完整，有几条护栏其实没生效。' }
        default    { '护栏没跑起来。' }
    }
    if ($g.state -eq 'drift' -or $g.state -eq 'config') { $icon = 'Warning' }
    # 只挑有信息量的行：整篇审计十几行，全塞进 MessageBox 会变成一个挡住全屏的大方块，
    # 而真正要看的就是那几行 [不合] / [配置]。
    $lines = @($g.text -split "`r?`n" | Where-Object { $_.Trim() })
    $keep  = @($lines | Where-Object { $_ -match '\[不合\]|\[配置\]' })
    if (-not $keep) { $keep = @($lines | Select-Object -Last 2) }
    $body = (@($head, '', '── 明细 ──') + $keep + @(
        '', '── 说明 ──',
        '校验点只拦得住走 ratchet.py --apply 的补丁；手改 params.json 它拦不住，',
        '靠这个指纹比对检出。所以看到漂移，先弄清是谁改的、该不该改。',
        '「基线来源」：install = 装包时安装器自动封的、manual = 有人在这面板上按的、',
        '未记来源 = 那条基线写在 origin 字段之前（账本只追加，不改写旧行）。',
        ('文件：' + $RatchetPy),
        ('参数：' + $RatchetParams),
        ('账本：' + $RatchetLedger)
    )) -join "`r`n"
    [System.Windows.Forms.MessageBox]::Show($body, '护栏 · 棘轮审计', 'OK', $icon)
})

$btnGuardSeal.Add_Click({
    if ($GuardParams) {
        # 带 -GuardParams 时 params 是候选/副本，封存会把候选的指纹写成**正式基线**，
        # 把真实基线污染掉。这条口子必须堵死。
        [System.Windows.Forms.MessageBox]::Show(
            "这次是用 -GuardParams 指到别的 params.json 上跑的，不封存——那会把候选配置的指纹写成正式基线。",
            '护栏', 'OK', 'Warning')
        return
    }
    $g = Invoke-RatchetAudit
    $unsafe = ($g.state -eq 'drift' -or $g.state -eq 'config')
    $extra = ''
    if ($unsafe) {
        $extra = "`r`n`r`n【注意】现在正检出不正常。封存会把**此刻**的状态当成新基线，" +
                 "这一回的漂移证据就被抹掉了。`r`n先弄清是谁改的、该不该改，再决定封不封。"
    }
    $icon = if ($unsafe) { 'Warning' } else { 'Question' }
    $ans = [System.Windows.Forms.MessageBox]::Show(
        ("封存 = 把此刻的冻结项取值、冻结文件指纹、锁本体指纹写进账本，作为以后比对的基线。" +
         "只追加一行，不改别的东西。$extra`r`n`r`n要封存吗？"),
        '封存护栏基线', 'YesNo', $icon)
    if ($ans -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    if (-not (Test-Path $PyExe) -or -not (Test-Path $RatchetPy)) {
        [System.Windows.Forms.MessageBox]::Show('没有 python 或 ratchet.py，封存不了。', '护栏', 'OK', 'Warning')
        return
    }
    $r = Invoke-Capture $PyExe @('-X', 'utf8', $RatchetPy, '--seal') $WebDir 30
    Write-Log "封存护栏基线：退出码 $($r.code)"
    Update-GuardStatus
})

$form.Add_Shown({
    # 这里只负责把 timer 点着——真正干活的 Boot-Step 在 timer 的第一跳里。
    # WinForms 会吞掉事件里的异常，所以连这一步也兜住。
    try { Update-Status; $timer.Start() }
    catch {
        Write-Log "启动流程异常：$($_.Exception.Message)"
        Update-Status
    }
})

[void]$form.ShowDialog()

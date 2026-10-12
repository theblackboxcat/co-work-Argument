#requires -version 5.1
<#
====================================================================
 伴写便携版 · 自检  (selfcheck.ps1)
 --------------------------------------------------------------------
 不动任何东西，只把环境看一遍，逐项说清"能不能跑、缺哪一样"。
 安装完自动跑一次；之后任何时候也能单独跑：

   powershell -NoProfile -ExecutionPolicy Bypass -File selfcheck.ps1
   powershell -NoProfile -ExecutionPolicy Bypass -File selfcheck.ps1 -Json
   powershell -NoProfile -ExecutionPolicy Bypass -File selfcheck.ps1 -Live

 -Json  输出机器可读的一行 JSON（退出码 = 失败项数），给自己或别的脚本用。
 -Live  真的把网页服务起一次、读 /api/status、再停掉。比静态检查重，
        但那是唯一能证明"装完就能跑"的检查。

 退出码：0 = 全过（可以有提醒）；>0 = 失败项数。
 为什么要有这个东西：便携版出问题，症状永远是同一个"网页打不开"，
 而原因可能分布在 python、venv、配置、端口、路径编码五处。分开说，一次说清。
====================================================================
#>

[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$Live
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root   = Split-Path -Parent $MyInvocation.MyCommand.Path

# 布局判据必须和 CowriteLauncher.ps1 一模一样，否则自检说好的、启动器未必认。
if (Test-Path (Join-Path $Root 'app\server.py')) {
    $Layout = '便携'
    $AppDir = Join-Path $Root 'app'
    $PyExe  = Join-Path $Root 'runtime\python\python.exe'
    $OvPy   = Join-Path $Root 'runtime\ov\Scripts\python.exe'
    $OvExe  = Join-Path $Root 'runtime\ov\Scripts\openviking-server.exe'
    $OvWork = Join-Path $Root 'ovdata'
    if ($OvWork -match '[^\x00-\x7F]') { $OvWork = Join-Path $env:LOCALAPPDATA 'Cowrite\ovdata' }
} else {
    $Layout = '开发'
    $AppDir = '%DSH_ROOT%\lir\文献\dsh-伴写'
    $PyExe  = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\versions\3.13.12\python.exe'
    $OvPy   = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\ov\Scripts\python.exe'
    $OvExe  = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\ov\Scripts\openviking-server.exe'
    $OvWork = '%DSH_ROOT%\ovdata'
}
$OvConf = Join-Path $env:USERPROFILE '.openviking\ov.conf'

$script:Items = @()
function Rec([string]$id, [string]$level, [string]$detail) {
    $script:Items += [pscustomobject]@{ id = $id; level = $level; detail = $detail }
    if (-not $Json) {
        switch ($level) {
            'ok'   { Write-Host "  [ok] $id" -ForegroundColor Green }
            'warn' { Write-Host "  [!]  $id" -ForegroundColor Yellow }
            'fail' { Write-Host "  [x]  $id" -ForegroundColor Red }
            default { Write-Host "  [-]  $id" -ForegroundColor DarkGray }
        }
        if ($detail) { Write-Host "         $detail" -ForegroundColor DarkGray }
    }
}
function Head([string]$s) { if (-not $Json) { Write-Host ''; Write-Host $s -ForegroundColor Cyan } }

function Test-Tcp([int]$p) {
    # TcpClient.Connect 没有超时一说，端口没人接的时候能挂十几秒——
    # 那一步会把"自检"拖成"看起来死机"。异步连接 + 最多等 600ms。
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $c.BeginConnect('127.0.0.1', $p, $null, $null)
        if ($ar.AsyncWaitHandle.WaitOne(600)) { if ($c.Connected) { return $true } }
        return $false
    } catch { return $false }
    finally { try { $c.Close() } catch { } }
}

function Run([string]$exe, [string[]]$a, [int]$timeoutSec = 30) {
    # 要能设超时，所以走 .NET Process 而不是调用运算符——
    # 一个半死的解释器会把自检卡死，那比报错更没用。
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $exe
        $psi.Arguments = ($a | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $p = [System.Diagnostics.Process]::Start($psi)
        $o = $p.StandardOutput.ReadToEnd()
        $e = $p.StandardError.ReadToEnd()
        if (-not $p.WaitForExit($timeoutSec * 1000)) {
            try { $p.Kill() } catch { }
            return @{ code = -999; out = ''; err = "超时（>${timeoutSec}s）" }
        }
        return @{ code = $p.ExitCode; out = $o.Trim(); err = $e.Trim() }
    } catch { return @{ code = -998; out = ''; err = $_.Exception.Message } }
}

Head "伴写自检 · $Layout 布局"
Rec '位置' 'info' $Root

# ---------------------------- 一、应用本体 ----------------------------
Head '一、应用本体'
$need = @(
    'server.py', 'ov_memory.py', 'lit_tools.py', 'providers.py',
    'SKILL.md', 'WORKFLOW.md', 'config.example.json',
    'web\index.html', 'v3\policy.py', 'v3\attention.py', 'v3\classifier.py',
    'v3\SKILL_v3.md', 'v3\params.json'
)
$missing = @()
foreach ($f in $need) { if (-not (Test-Path (Join-Path $AppDir $f))) { $missing += $f } }
if ($missing.Count -eq 0) { Rec '关键文件齐全' 'ok' ("$($need.Count) 个都在") }
else { Rec '缺关键文件' 'fail' ($missing -join '、') }

# ---------------------------- 二、Python ----------------------------
Head '二、解释器'
$pyOk = $false
if (-not (Test-Path $PyExe)) {
    Rec '运行时 python' 'fail' "没有 $PyExe（先跑 install.ps1 / install.cmd）"
} else {
    $r = Run $PyExe @('-c', 'import sys;print(sys.version.split()[0])')
    if ($r.code -eq 0 -and $r.out -match '^3\.') {
        $pyOk = $true
        Rec '运行时 python' 'ok' "$PyExe  →  $($r.out)"
    } else { Rec '运行时 python 起不来' 'fail' "返回码 $($r.code)  $($r.err)" }
}

if ($pyOk -and $missing.Count -eq 0) {
    # 语法编译。半个拷贝过来的包最常见的坏法就是某个 .py 被截断了，
    # 而那种错要等点到某个功能才炸——不如现在一次问完。
    # 用内置的 compile() 而不是 py_compile.compile(cfile=os.devnull)：
    # 后者在 Windows 上会去写 "nul"，那是设备不是普通文件，py_compile 直接拒绝。
    # 读成 bytes 再 compile()，编码声明与 BOM 由解释器自己认，同时一个字节都不落盘。
    $code = @'
import sys, os
bad = []
for p in sys.argv[1:]:
    try:
        with open(p, 'rb') as f:
            src = f.read()
        compile(src, p, 'exec')
    except Exception as e:
        bad.append('%s: %s' % (os.path.basename(p), str(e)[:120]))
print('|'.join(bad))
'@
    $files = @()
    foreach ($f in @('server.py', 'ov_memory.py', 'lit_tools.py', 'providers.py',
                     'v3\policy.py', 'v3\attention.py', 'v3\classifier.py',
                     'v3\bans.py', 'v3\judge.py', 'v3\metrics.py')) {
        $p = Join-Path $AppDir $f
        if (Test-Path $p) { $files += $p }
    }
    $tmp = Join-Path $env:TEMP ('cowrite_syn_' + [Guid]::NewGuid().ToString('N').Substring(0, 8) + '.py')
    Set-Content -Path $tmp -Value $code -Encoding UTF8
    $r = Run $PyExe (@('-X', 'utf8', $tmp) + $files)
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    if ($r.code -eq 0 -and -not $r.out) { Rec '源码语法编译' 'ok' "$($files.Count) 个文件全过" }
    elseif ($r.out) { Rec '源码语法编译' 'fail' $r.out }
    else { Rec '源码语法编译' 'warn' "没跑成：$($r.err)" }
}

# 几个 JSON 是运行时要读的：params.json 决定分类器权重、workspaces.json 决定
# 记忆分区。截断的 JSON 会以"某个功能莫名不灵"的形式出现，不如现在解析一次。
$jsons = @('v3\params.json', 'workspaces.json', 'config.example.json')
$badJson = @()
foreach ($f in $jsons) {
    $p = Join-Path $AppDir $f
    if (-not (Test-Path $p)) { $badJson += "$f（不在）"; continue }
    try { [void](Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { $badJson += "$f：$($_.Exception.Message)" }
}
if ($badJson.Count -eq 0) { Rec '运行时 JSON' 'ok' "$($jsons.Count) 个都能解析" }
else { Rec '运行时 JSON 有问题' 'fail' ($badJson -join '；') }

# ---------------------------- 三、记忆层 ----------------------------
Head '三、记忆层（不装也能写，只是这次没有历史）'
if (-not (Test-Path $OvExe)) {
    Rec '记忆层' 'warn' '没装。网页能用，但没有历史可依。要装：install.cmd'
} else {
    if (-not (Test-Path $OvPy)) { Rec 'venv python' 'fail' "没有 $OvPy" }
    else {
        # 查的是**启动入口那条链**，不是"openviking 这个包在不在"。
        # 差别有代价：runtime\ov 是从一个 venv 拷过来的，拷贝规则误伤过一次
        # （openai/_legacy_response.py 被当成"我们自己的旧版文件"删掉），
        # 结果是 openviking 顶层 import 得好好的、版本元数据也在，
        # 而 openviking.server.bootstrap 一 import 就 ModuleNotFoundError
        # —— 记忆层根本起不来。当时这里只查版本，所以安装照样报"装完了"。
        # 启动器实际起的就是 bootstrap 这条链，那就照它查。
        # 里面一律用单引号：这段代码是要拼进命令行的，再用双引号就得处理
        # \" 转义，而那是 MSVCRT 的规则，不值得在这里赌。
        # -B 是别让这次探测往包里的 venv 写 __pycache__。
        $r = Run $OvPy @('-B', '-c', "import importlib.metadata as m;import openviking.server.bootstrap;print(m.version('openviking'))") 90
        if ($r.code -eq 0 -and $r.out) {
            Rec '记忆层入口' 'ok' "openviking $($r.out)（启动入口可以加载）"
        } else {
            $last = ($r.err -split "`r?`n" | Where-Object { $_ -ne '' } | Select-Object -Last 1)
            if (-not $last) { $last = "退出码 $($r.code)" }
            Rec '记忆层入口 import 失败' 'fail' $last
        }
    }
}
if (Test-Path $OvConf) {
    try {
        $c = Get-Content $OvConf -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($c.server.root_api_key) { Rec 'ov.conf' 'ok' "$OvConf（root key 已配）" }
        else { Rec 'ov.conf 缺 root_api_key' 'fail' $OvConf }
    } catch { Rec 'ov.conf 读不出来' 'fail' "$OvConf ：$($_.Exception.Message)" }
} else {
    Rec 'ov.conf' 'warn' "没有 $OvConf —— 记忆层启动时会拒绝启动（它必需这个文件）"
}
if (Test-Path $OvWork) {
    $w = $false
    try {
        $t = Join-Path $OvWork '.sc_write_test'
        Set-Content -Path $t -Value 'x' -Encoding ASCII -ErrorAction Stop
        Remove-Item $t -Force
        $w = $true
    } catch { }
    if ($w) {
        if ($OvWork -match '[^\x00-\x7F]') { Rec '数据目录可写' 'warn' "$OvWork（路径含非 ASCII，记忆层可能起不来）" }
        else { Rec '数据目录可写' 'ok' $OvWork }
    } else { Rec '数据目录不可写' 'fail' $OvWork }
} else {
    Rec '数据目录不存在' 'warn' "$OvWork（启动器会自己建）"
}
# 数据目录锁：openviking 靠一个 PID 文件防多实例争用同一数据目录。它的存活校验
# 在 Windows 上不验"那进程是不是它自己"（只有 Linux 分支读 /proc/<pid>/cmdline），
# 而 Windows 会复用 PID —— 上次若被强杀（atexit 清不了锁），锁里那个号被系统分给
# 别的进程，下次启动就永久被挡住。这正是"入口能加载却起不来"最常见的原因，
# 2026-09-21 就撞过（锁指向 svchost.exe），所以单独查一条报出来。
if (Test-Path $OvWork) {
    $ovLock = Join-Path $OvWork 'data\.openviking.pid'
    if (-not (Test-Path $ovLock)) {
        Rec '数据目录锁' 'ok' '没有残留锁'
    } else {
        $lockPid = 0
        $rawLock = Get-Content $ovLock -ErrorAction SilentlyContinue | Select-Object -First 1
        if ([int]::TryParse(("$rawLock").Trim(), [ref]$lockPid) -and $lockPid -gt 0) {
            $lp = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
            if ($null -eq $lp) {
                Rec '数据目录锁：陈旧' 'warn' "指向 PID $lockPid，那个进程已经没了（启动器会自动清掉）"
            } elseif (("$($lp.ProcessName)").ToLower() -notmatch 'python|openviking') {
                Rec '数据目录锁：被复用' 'warn' "PID $lockPid = $($lp.ProcessName)，不是记忆层进程 —— 会挡住启动（启动器会自动清）"
            } else {
                Rec '数据目录锁' 'ok' "PID $lockPid（$($lp.ProcessName)）正持有"
            }
        } else {
            Rec '数据目录锁内容异常' 'warn' $ovLock
        }
    }
}

# ---------------------------- 四、配置 ----------------------------
Head '四、模型配置'
$cfg = Join-Path $AppDir 'config.json'
if (-not (Test-Path $cfg)) {
    Rec 'config.json' 'warn' '没有：现在是离线演示模式，不发任何网络请求'
} else {
    try {
        $c = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($c.api_key) {
            Rec 'config.json' 'ok' "$($c.provider) / $($c.model)  key 长度 $($c.api_key.Length)"
        } else {
            Rec 'config.json 没填 key' 'warn' '离线演示模式（不发任何网络请求）'
        }
    } catch { Rec 'config.json 不是合法 JSON' 'fail' $_.Exception.Message }
}

# ---------------------------- 五、路径约定 ----------------------------
Head '五、路径约定'
if ($Root -match '[^\x00-\x7F]') { Rec '安装路径非 ASCII' 'warn' "$Root（记忆层的数据目录已改放到 $OvWork）" }
else { Rec '安装路径纯 ASCII' 'ok' $Root }
if ($Root -match ' ') { Rec '安装路径含空格' 'warn' $Root }
else { Rec '安装路径无空格' 'ok' '没有空格，Python 安装器不会挑这个' }
# ---------------------------- 六、端口 ----------------------------
Head '六、端口'
$ovUp = Test-Tcp 1933
$webUp = Test-Tcp 8790
if ($ovUp) { Rec '记忆层端口 1933' 'ok' '在跑' } else { Rec '记忆层端口 1933' 'info' '没在跑（没开就是没开，不是错）' }
if ($webUp) { Rec '网页端口 8790' 'ok' '在跑' } else { Rec '网页端口 8790' 'info' '没在跑' }

# ---------------------------- 七、护栏（棘轮校验点） ----------------------------
Head '七、护栏 · 棘轮校验点'
# 这里**不自带一套解析**：启动器有无头模式（-GuardCheck），同一份代码、同一个判据。
# 另写一份的下场是两边迟早说出不一样的话来——而这套东西存在的全部理由，
# 就是"判据只有一份，谁也别想绕"。
$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$launcher = Join-Path $Root 'CowriteLauncher.ps1'
if (-not (Test-Path $launcher)) {
    Rec '护栏自检' 'info' '同目录没有 CowriteLauncher.ps1，跳过'
} else {
    $r = Run $psExe @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                      '-File', $launcher, '-GuardCheck') 40
    $gout = $r.out
    # 只摘有信息量的两行：自检是给人扫的，不是把另一份报告整段抄过来。
    $gbad = @($gout -split "`r?`n" | Where-Object { $_ -match '\[(不合|配置)\]' } |
              Select-Object -First 2) -join '；'
    switch ($r.code) {
        0 {
            if ($gout -match '无（跑 --seal 建一个）') {
                Rec '护栏基线' 'info' '还没封存过基线——现在只能查映射完不完整，比不出漂移'
            } else {
                Rec '护栏指纹' 'ok' '冻结项、禁令本体、锁本体都与上次封存一致'
            }
        }
        2 { Rec '护栏指纹' 'fail' "检出漂移（冻结面被改过）：$gbad" }
        3 { Rec '护栏配置' 'fail' "护栏映射不完整，有几条护栏其实没生效：$gbad" }
        default { Rec '护栏自检' 'warn' "跑不起来（退出码 $($r.code)）：$($r.err)" }
    }
}

# ---------------------------- 八、真起一次（-Live） ----------------------------
if ($Live) {
    Head '八、真起一次（-Live）'
    if ($webUp) {
        Rec '起服务' 'info' '8790 上已经有东西在跑，跳过——不抢别人的端口'
    } elseif (-not $pyOk) {
        Rec '起服务' 'fail' '没有可用的 python'
    } else {
        # 这里**不重定向** stdout：这是个长命进程，它自己会往标准输出打东西。
        # 一旦把标准输出接成管道而我们又不持续读，管道缓冲区满了之后
        # 它会阻塞在写那一句上——服务就永远起不来了，而自检看到的只是"没起来"。
        # 让它继承这个控制台，代价是它会往这个窗口里打几行字。
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $PyExe
        $psi.Arguments = 'server.py'
        $psi.WorkingDirectory = $AppDir
        $psi.UseShellExecute = $false
        $p = [System.Diagnostics.Process]::Start($psi)
        $ok = $false
        $detail = ''
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 500
            if ($p.HasExited) { $detail = "进程已退出（码 $($p.ExitCode)）"; break }
            if (Test-Tcp 8790) {
                try {
                    $s = Invoke-RestMethod -Uri 'http://127.0.0.1:8790/api/status' -TimeoutSec 5
                    $ok = $true
                    $detail = "/api/status 通：" + (($s | ConvertTo-Json -Compress) -replace '\s+', ' ')
                } catch { $detail = "端口开了但 /api/status 读不到：$($_.Exception.Message)" }
                break
            }
        }
        if (-not $ok -and -not $detail) { $detail = '20 秒内没起来' }
        try { if (-not $p.HasExited) { $p.Kill() } } catch { }
        if ($ok) { Rec '起服务' 'ok' $detail } else { Rec '起服务' 'fail' $detail }
    }
}

# ---------------------------- 汇总 ----------------------------
$fail = @($script:Items | Where-Object { $_.level -eq 'fail' }).Count
$warn = @($script:Items | Where-Object { $_.level -eq 'warn' }).Count
$okn  = @($script:Items | Where-Object { $_.level -eq 'ok' }).Count

if ($Json) {
    Write-Output (([pscustomobject]@{
        layout = $Layout; root = $Root; app = $AppDir
        ok = $okn; warn = $warn; fail = $fail
        items = $script:Items
    }) | ConvertTo-Json -Depth 5 -Compress)
} else {
    Write-Host ''
    Write-Host "  全过 $okn 项，提醒 $warn 项，失败 $fail 项。" -ForegroundColor $(if ($fail) { 'Red' } else { 'Green' })
    if ($fail) {
        Write-Host '  标 [x] 的要先解决；标 [!] 的多数只是"某功能这次用不上"。' -ForegroundColor DarkGray
    }
}
exit $fail

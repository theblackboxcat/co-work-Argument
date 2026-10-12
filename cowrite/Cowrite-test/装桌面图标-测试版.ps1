# 给 Cowrite-test 放一个桌面快捷方式。
#
# 刻意**不放图标**，避免与发行版的「伴写启动器」混淆——两个图标长得
# 几乎一样而指向不同的东西，是最容易点错的一种设计。改用一个带
# 【测试】字样的独立图标，并且用**另一种颜色**的图标文件，
# 双击时一眼能认出这是实验用的那一版。
#
# 用法：直接双击本文件即可；或从 PowerShell 运行：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\装桌面图标-测试版.ps1
param([string]$ShortcutDir)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $Root '启动测试版.ps1'
$Ico = Join-Path $Root 'cowrite.ico'

if (-not (Test-Path $Target)) {
    Write-Host "找不到启动脚本：$Target" -ForegroundColor Red
    exit 1
}

# 桌面位置允许用参数顶掉：重定向过桌面（OneDrive）的机器上，
# [Environment]::GetFolderPath('Desktop') 可能指错地方。
$Desktop = $ShortcutDir
if (-not $Desktop) { $Desktop = [Environment]::GetFolderPath('Desktop') }
if (-not (Test-Path $Desktop)) {
    New-Item -ItemType Directory -Path $Desktop -Force | Out-Null
}

# 用系统自带的 powershell.exe，不依赖 pwsh 在不在。
$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path $psExe)) { $psExe = 'powershell.exe' }

try {
    $ws = New-Object -ComObject WScript.Shell
    # 文件名带【测试】，和发行版的「伴写启动器」区分开
    $lnkPath = Join-Path $Desktop '伴写测试版（采集）.lnk'
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = $psExe
    $lnk.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $Target + '"'
    $lnk.WorkingDirectory = $Root
    if (Test-Path $Ico) { $lnk.IconLocation = $Ico + ',0' }
    $lnk.Description = 'Cowrite-test 采集测试版（端口 8792，不启动记忆层）——与桌面的「伴写启动器」是两份，互不影响'
    $lnk.Save()
    Write-Host "桌面快捷方式已建：$lnkPath" -ForegroundColor Green
    Write-Host '双击它启动采集测试版；发行版请用「伴写启动器」。' -ForegroundColor DarkGray
} catch {
    Write-Host "快捷方式没建成：$($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "手动办法：右键 $Target → 发送到 → 桌面快捷方式" -ForegroundColor DarkGray
}

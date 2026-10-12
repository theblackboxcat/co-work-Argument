$ErrorActionPreference = 'Continue'
$root = '%USERPROFILE%\Doubao\chats\2026-10-09\必要性重建_本地\S1h2_es_select_fix'
Set-Location $root
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:PYTHONIOENCODING='utf-8'
New-Item -ItemType Directory -Force "$root\tune\stdout" | Out-Null
# clear partial outs
Remove-Item -Force "$root\tune\stdout\*" -ErrorAction SilentlyContinue
Remove-Item -Force "$root\tune\result_arm_*.json" -ErrorAction SilentlyContinue
Remove-Item -Force "$root\tune\hist_*.json" -ErrorAction SilentlyContinue
$seeds = @(100,101,102,103)
$lrs = @(0.005, 0.01, 0.02, 0.05)
$procs = @()
foreach ($s in $seeds) {
  foreach ($lr in $lrs) {
    $tag = "ES_main_s${s}_lr$lr"
    $out = "$root\tune\stdout\$tag.out"
    $err = "$root\tune\stdout\$tag.err"
    $arg = "run_arm.py --arm ES_main --seed $s --tune --lr $lr"
    $procs += Start-Process -FilePath "python" -ArgumentList $arg -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
  }
}
"launched $($procs.Count) at $(Get-Date -Format o)" | Set-Content "$root\tune\stdout\_launcher.log" -Encoding UTF8
$procs | Wait-Process
$codes = $procs | ForEach-Object { $_.ExitCode }
$fail = @($codes | Where-Object { $_ -ne 0 }).Count
$nres = (Get-ChildItem "$root\tune\result_arm_*.json" -ErrorAction SilentlyContinue | Measure-Object).Count
"done at $(Get-Date -Format o); fail=$fail; nres=$nres; codes=$($codes -join ',')" | Add-Content "$root\tune\stdout\_launcher.log" -Encoding UTF8
"DONE" | Set-Content "$root\tune\stdout\_DONE" -Encoding UTF8
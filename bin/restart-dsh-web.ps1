#Requires -Version 5
<#
  restart-dsh-web.ps1 —— 重启 Windows 侧 DSH Web（计划任务 dsh-web，:3080）。

  为什么不能直接 Stop-ScheduledTask + Start-ScheduledTask：
  2026-11-24 实测，在 DSH 自己的会话里跑这种「先停后起」脚本，Stop-ScheduledTask 会把任务的
  整个进程树（含调用它的 shell 与脚本本身）一起杀掉 —— 脚本死在 Stop 之后，Start 那行永远执行
  不到，DSH 就一直停着（当天就是这么掉的）。所以这里把真正的动作交给 WMI 起的 worker 进程：
  它的父进程是 WmiPrvSE，不在任务进程树里，任务被停时不会跟着死。调用方立刻返回，5 秒后 worker 动手。

  用法（在任何地方都安全，包括 DSH 自己的会话里）：
    powershell -NoProfile -ExecutionPolicy Bypass -File %USERPROFILE%\.dsh\bin\restart-dsh-web.ps1
  结果看日志：%USERPROFILE%\.dsh\tmp\restart-dsh-web.log
#>
param(
  [switch]$Worker,
  [int]$DelaySeconds = 5
)

$ErrorActionPreference = 'Continue'
$dshHome = Join-Path $env:USERPROFILE '.dsh'
$logDir = Join-Path $dshHome 'tmp'
$log = Join-Path $logDir 'restart-dsh-web.log'
$self = Join-Path $dshHome 'bin\restart-dsh-web.ps1'
$null = New-Item -ItemType Directory -Force -Path $logDir
function W($m) { "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m | Add-Content -Path $log }

if (-not $Worker) {
  $workerCmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Worker -DelaySeconds {1}' -f $self, $DelaySeconds
  W ("delegate restart of dsh-web to detached worker in {0}s" -f $DelaySeconds)
  $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $workerCmd }
  if ($r.ReturnValue -ne 0) { W ("FAIL spawn worker rc={0}" -f $r.ReturnValue); exit 1 }
  Write-Host ("delegated: worker pid {0}; log {1}" -f $r.ProcessId, $log)
  exit 0
}

# ---- worker：脱离任务进程树后自己干 ----
Start-Sleep -Seconds $DelaySeconds
W 'worker: stop dsh-web'
Stop-ScheduledTask -TaskName 'dsh-web' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
W 'worker: start dsh-web'
Start-ScheduledTask -TaskName 'dsh-web'

$ok = $false
for ($i = 0; $i -lt 24; $i++) {
  Start-Sleep -Seconds 5
  if (Get-NetTCPConnection -LocalPort 3080 -State Listen -ErrorAction SilentlyContinue) { $ok = $true; break }
}
$state = (Get-ScheduledTask -TaskName 'dsh-web').State
if ($ok) {
  W ("worker: OK 3080 listening, task state={0}" -f $state)
  exit 0
}
W ("worker: FAIL 3080 not listening after 120s, task state={0}; tail dsh-web.log:" -f $state)
Get-Content (Join-Path $dshHome 'dsh-web.log') -Tail 20 | ForEach-Object { W ("  " + $_) }
exit 1

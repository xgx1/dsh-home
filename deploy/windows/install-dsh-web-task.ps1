#Requires -Version 5
# 安装/修复 Windows 侧 dsh-web 计划任务（:3080 开机自启 + 5 分钟看门狗）。
#
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File %USERPROFILE%\.dsh\deploy\windows\install-dsh-web-task.ps1
#
# 为什么要这脚本：2026-11-24 发现原任务的 <Repetition> 挂在 LogonTrigger 上，Task Scheduler 直接
# 不注册（"Repeat: Every: N/A" / NextRunTime 为空）。结果是 Stop-ScheduledTask 或进程崩溃之后
# 永远不会自愈，DSH 就一直停着。这份 XML 把看门狗换成独立 TimeTrigger，并保留登录触发首启。

$ErrorActionPreference = 'Stop'
$home_ = Join-Path $env:USERPROFILE '.dsh'
$xmlPath = Join-Path $home_ 'deploy\windows\dsh-web-task.xml'
$launcher = Join-Path $home_ 'dsh-web-launch.ps1'
if (-not (Test-Path $xmlPath)) { throw "missing $xmlPath" }
if (-not (Test-Path $launcher)) { throw "missing $launcher" }

$xml = Get-Content -Raw -LiteralPath $xmlPath
# Register-ScheduledTask -Xml 只吃裸 XML；带 <?xml ... encoding?> 声明会报「无法切换编码」
$xml = ($xml -split "`n" | Where-Object { $_ -notmatch '^<\?xml' }) -join "`n"
# 本机化：作者 SID 与启动器绝对路径（XML 里存的是 SXHOME\Admin 的初版值）
$sid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$user = $env:USERNAME
$xml = $xml -replace '<UserId>S-1-5-21-[0-9-]+</UserId>', "<UserId>$sid</UserId>"
$xml = $xml -replace '<UserId>SXHOME\\Admin</UserId>', "<UserId>$env:COMPUTERNAME\$user</UserId>"
$xml = $xml -replace 'C:\\Users\\Admin\\.dsh\\dsh-web-launch.ps1', ($launcher -replace '\\', '\\')

# Register-ScheduledTask -Force 会先删后建；先停掉旧实例，免得留下没人管的孤儿进程。
Stop-ScheduledTask -TaskName 'dsh-web' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Register-ScheduledTask -TaskName 'dsh-web' -Xml $xml -Force | Out-Null

Start-ScheduledTask -TaskName 'dsh-web'
Start-Sleep -Seconds 20
$listen = Get-NetTCPConnection -LocalPort 3080 -State Listen -ErrorAction SilentlyContinue
$info = Get-ScheduledTaskInfo -TaskName 'dsh-web'
if (-not $listen) {
  Write-Host 'FAIL: 3080 not listening; tail of dsh-web.log:' -ForegroundColor Red
  Get-Content (Join-Path $home_ 'dsh-web.log') -Tail 30
  exit 1
}
Write-Host ("OK 3080 pid={0} state={1} next={2}" -f ($listen | Select-Object -First 1).OwningProcess,
  (Get-ScheduledTask -TaskName 'dsh-web').State, $info.NextRunTime)
if (-not $info.NextRunTime) {
  Write-Host 'WARN: NextRunTime 为空 —— 看门狗可能又没注册（查 schtasks /query /tn dsh-web /v /fo LIST 的 Repeat 行）' -ForegroundColor Yellow
}

# One-shot delayed restart of the dsh-web scheduled task, so the 0.2.1 rebuild
# and the dsh-extensions pull take effect without an interactive console.
# Run detached: Start-Process pwsh -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',<this>
$log = Join-Path $env:USERPROFILE '.dsh\restart-0.2.1.log'
function Note([string]$m) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $m" | Out-File $log -Append -Encoding utf8 }

Start-Sleep -Seconds 60

Note 'stopping dsh-web'
Stop-ScheduledTask -TaskName dsh-web -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

$held = Get-NetTCPConnection -LocalPort 3080 -State Listen -ErrorAction SilentlyContinue
if ($held) {
  Note "port 3080 still held by PID $($held.OwningProcess); killing it"
  Stop-Process -Id $held.OwningProcess -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
}

Note 'starting dsh-web'
Start-ScheduledTask -TaskName dsh-web
Start-Sleep -Seconds 30

$now = Get-NetTCPConnection -LocalPort 3080 -State Listen -ErrorAction SilentlyContinue
if ($now) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($now.OwningProcess)" -ErrorAction SilentlyContinue
  Note "OK 3080 listener PID $($now.OwningProcess), started $($proc.CreationDate)"
} else {
  Note 'FAILED: no listener on 3080 after restart'
}

# opencode-zen bridge (:8790): DSH provider opencode-zen 的前置中继。
# 拉起：计划任务 opencode-zen-bridge（登录时启动）。
$log = Join-Path $env:USERPROFILE '.dsh\opencode-zen-bridge.log'
& "C:\Users\Admin\scoop\apps\python\current\python.exe" "$env:USERPROFILE\.dsh\bin\opencode-zen-bridge.py" --host 127.0.0.1 --port 8790 *>> $log

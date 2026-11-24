param([switch]$Service)                     # -Service: 输出重定向到日志（计划任务没有控制台）
$ErrorActionPreference = 'Continue'
$DshHome = Join-Path $env:USERPROFILE '.dsh'
$env:DSH_HOME = $DshHome
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

# 固定入口 token：存在 ~\.dsh\.web-token 就用它，URL 不必每次从日志里抄。
# 文件是本机专属、gitignore 覆盖；删掉即回到「每次启动随机 token」。
$tokenFile = Join-Path $DshHome '.web-token'
if (Test-Path $tokenFile) {
  $env:DSH_WEB_TOKEN = (Get-Content $tokenFile -Raw).Trim()
}

# Web 宿主的工作区根（DSH 以它为默认项目目录）
Set-Location (Join-Path $env:USERPROFILE 'Project\MyAI')

# 凭据不在这里注入：DSH 自己从 $DSH_HOME\.credentials.yaml 按 apiKeyEnv 解析。

# 前台跑 Web UI；存活由计划任务 dsh-web 保证（登录触发首启 + 独立 TimeTrigger 每 5 分钟
# 看门狗，任务定义见 deploy/windows/dsh-web-task.xml —— 2026-11-24 之前看门狗挂在
# LogonTrigger 上，Task Scheduler 根本不注册，停了就再也不起来）。
# 手动重启走 bin/restart-dsh-web.ps1（WMI worker 脱离任务进程树，不会自己杀自己）。
# 日志用 Out-File -Encoding utf8：`*>>` 默认写 UTF-16LE，grep/tail 会看到乱码。
# 每轮起一个分隔行：没有时间戳的话，几十轮重启在一个只追加的文件里分不开。
if ($Service) {
  "=== {0} start dsh web ===" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') |
    Out-File -FilePath (Join-Path $DshHome 'dsh-web.log') -Append -Encoding utf8
  & dsh web --no-open 2>&1 | Out-File -FilePath (Join-Path $DshHome 'dsh-web.log') -Append -Encoding utf8
} else {
  & dsh web --no-open
}

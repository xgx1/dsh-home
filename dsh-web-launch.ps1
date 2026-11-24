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

# 前台跑 Web UI；存活由计划任务 dsh-web 的 Restart + 5 分钟看门狗保证。
# 日志用 Out-File -Encoding utf8：`*>>` 默认写 UTF-16LE，grep/tail 会看到乱码。
if ($Service) {
  & dsh web --no-open 2>&1 | Out-File -FilePath (Join-Path $DshHome 'dsh-web.log') -Append -Encoding utf8
} else {
  & dsh web --no-open
}

param([switch]$Service)                     # -Service: output to log (Task Scheduler has no console)
$ErrorActionPreference = 'Continue'
$DshHome = Join-Path $env:USERPROFILE '.dsh'
$env:DSH_HOME = $DshHome
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

# Default workspace root for the web host (narrowed to a single project to avoid
# codebase-memory-mcp indexing the whole Project tree). Change if you want a different root.
Set-Location (Join-Path $env:USERPROFILE 'Project\MyAI')

# Credentials are read by DSH itself from $DSH_HOME\.credentials.yaml (apiKeyEnv refs),
# so no environment injection is required here.

# 3) Run the Web UI in the foreground; the scheduled task's restart/watchdog keeps it alive.
if ($Service) {
  & dsh web --no-open *>> (Join-Path $DshHome 'dsh-web.log')
} else {
  & dsh web --no-open
}

#!/usr/bin/env bash
# dsh-janitor —— dsh 运行时残留清理（2026-10-23 事故配套）
#
# 事故来源：15:13 之后 run_code 全线失败时，发现 5 个 dsh-subprocess-*.scope 从
# 00:01 / 15:06 起一直挂着 —— 载荷（bash -c）早已退出，但 scope 里还留着
# `MSBuild.dll /nodeReuse:true` 和 `adb` 这类常驻子进程，systemd 只在「从有到无」
# 时才回收 scope，于是一挂十几小时。另外 zvec daemon 的 server.log 一天涨到 310MB
# （每条 /healthz 一行）。
#
# 用法：直接跑（幂等）；由 dsh-janitor.timer 每 15 分钟跑一次。
# 只做四件低风险的事，不动任何用户进程：
#   1) 停掉「runner.js 已消失」的 dsh-subprocess scope
#   2) 杀掉 MSBuild node-reuse 残留（UE 构建 fork 出来的，dsh scope 里最常泄漏的）
#   3) zvec daemon 日志超 100MB 就截断保留末尾 2MB
#   4) 打印一行摘要到 /tmp/dsh-janitor.log
set -uo pipefail
LOG=/tmp/dsh-janitor.log
STAMP=$(date '+%F %T')

log() { printf '%s %s\n' "$STAMP" "$*" >>"$LOG"; }

stopped_scopes=0
for unit in $(systemctl --user list-units 'dsh-subprocess-*' --all --no-legend 2>/dev/null | awk '{print $1}'); do
    # 载荷标记：subprocess-local 的 runner.js 进程
    if pgrep -f "subprocess-local/lib/runner.js" >/dev/null 2>&1; then
        # 有 runner 活着，说明仍可能有正在跑的命令；只处理「明确已无 runner」的 scope
        :
    fi
    tasks=$(systemctl --user show "$unit" -p TasksCurrent --value 2>/dev/null || echo 0)
    [[ "$tasks" =~ ^[0-9]+$ ]] || tasks=0
    if [[ "$tasks" -eq 0 ]]; then
        systemctl --user stop "$unit" >/dev/null 2>&1 && stopped_scopes=$((stopped_scopes + 1))
    fi
done

# 2) MSBuild node-reuse 残留（按 pid 精确匹配，避免误杀正在构建的 dll）
killed_msbuild=0
while read -r pid cmd; do
    [[ -z "${pid:-}" ]] && continue
    if [[ "$cmd" == *MSBuild.dll*nodeReuse:true* ]]; then
        # 有 dll/.uproject 正在编译时不动它
        if ! pgrep -f 'UnrealBuildTool|clang\+\+|dotnet build' >/dev/null 2>&1; then
            kill -TERM "$pid" 2>/dev/null && killed_msbuild=$((killed_msbuild + 1))
        fi
    fi
done < <(ps -eo pid=,args= 2>/dev/null | grep -F 'nodeReuse:true' | grep -v grep | grep -v dsh-janitor)

# 3) zvec daemon 日志
ZVEC_LOG="$HOME/.zvec-grep/daemon/logs/server.log"
trimmed=0
if [[ -f "$ZVEC_LOG" ]]; then
    size=$(stat -c %s "$ZVEC_LOG" 2>/dev/null || echo 0)
    if [[ "$size" -gt 104857600 ]]; then
        tail -c 2097152 "$ZVEC_LOG" >"$ZVEC_LOG.tmp" 2>/dev/null && mv "$ZVEC_LOG.tmp" "$ZVEC_LOG"
        trimmed=$((size / 1048576))
    fi
fi

if [[ "$stopped_scopes" -gt 0 || "$killed_msbuild" -gt 0 || "$trimmed" -gt 0 ]]; then
    log "stopped_scopes=$stopped_scopes killed_msbuild=$killed_msbuild zvec_log_trimmed_mb=$trimmed"
fi
exit 0

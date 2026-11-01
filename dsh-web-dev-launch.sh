#!/usr/bin/env bash
# dsh-web-dev-launch.sh —— DSH 开发实例（:3081）启动入口，由 dsh-web-dev.service 调用。
#
# 与生产的 ~/.dsh/dsh-web-launch.sh 同构，开发实例差别如下：
#   1. DSH_HOME=~/.dsh-dev —— sessions/storages/配置与生产完全隔离
#   2. 跑 worktree 检出的 apps/cli/lib/bin.js（而不是 ~/.local/bin/dsh → 生产检出）
#   3. 端口 3081（生产是 3080）
#   4. BILI_NATIVE_DSH_LANE=dsh-dev —— 与生产各自的 billion-context 代理互不 attach
#      （否则 dev 重启会顺着父进程 watchdog 带走生产正在用的那个代理）
set -e
source "$HOME/.dsh/dsh-env.sh"          # 只导出 .credentials.yaml 里的 *_API_KEY
export DSH_HOME="$HOME/.dsh-dev"
# 仅开发实例覆盖 Helix.desktop，显式分配终端；保留原 XDG 数据路径与默认关联。
export XDG_DATA_DIRS="$DSH_HOME/native-open:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
# cua-driver native 与 dsh-web 同进程，要操作 Wayland 窗口必须注入显示环境（同生产）。
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export DISPLAY="${DISPLAY:-:0}"
export CUA_DRIVER_RS_ENABLE_WAYLAND=1
export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-Hyprland}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export BILI_NATIVE_DSH_LANE=dsh-dev
exec node "$HOME/projects/MyAI/deepseek-harness-dev/apps/cli/lib/bin.js" web --port 3081 --no-open

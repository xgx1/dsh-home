#!/usr/bin/env bash
# dsh-desktop-launch.sh —— DSH 桌面操作实例（:3082）启动入口，由 dsh-web-desktop.service 调用。
#
# 与 ~/.dsh/dsh-web-launch.sh（生产 :3080）、~/.dsh-dev/dsh-web-dev-launch.sh（开发 :3081）同构，本实例差别：
#   1. DSH_HOME=~/.dsh-desktop —— sessions/storages 与生产、开发都隔离
#   2. 跑 worktree 检出的 apps/cli/lib/bin.js（deepseek-harness-desktop，分支 desktop-ops）
#   3. 端口 3082
#   4. BILI_NATIVE_DSH_LANE=dsh-desktop —— lane 必须唯一，否则会 attach 到别人的
#      billion-context 代理并随对方重启被带走
set -e
source "$HOME/.dsh/dsh-env.sh"          # 只导出 .credentials.yaml 里的 *_API_KEY
export DSH_HOME="$HOME/.dsh-desktop"
# 仅本实例覆盖 Helix.desktop，显式分配终端；保留原 XDG 数据路径与默认关联。
export XDG_DATA_DIRS="$DSH_HOME/native-open:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
# cua-driver native 与 dsh-web 同进程，要操作 Wayland 窗口必须注入显示环境（同生产）。
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export DISPLAY="${DISPLAY:-:0}"
export CUA_DRIVER_RS_ENABLE_WAYLAND=1
export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-Hyprland}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export BILI_NATIVE_DSH_LANE=dsh-desktop
# 固定入口 token（packages/host/authentication-token 读 DSH_WEB_TOKEN）：
# 重启后打印的链接不变，已开着的标签页不会因为换 token 全部 401。
# 值存在不入库的 .web-token 里（repo 是公开的，别把 token 写进这个脚本）。
WEB_TOKEN_FILE="$HOME/.dsh-desktop/.web-token"
if [ ! -s "$WEB_TOKEN_FILE" ]; then
  head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=' > "$WEB_TOKEN_FILE"
  chmod 600 "$WEB_TOKEN_FILE"
fi
export DSH_WEB_TOKEN="$(cat "$WEB_TOKEN_FILE")"
exec node "$HOME/projects/MyAI/deepseek-harness-desktop/apps/cli/lib/bin.js" web --port 3082 --no-open

# ~/.dsh/bin/agent-shell-env.sh —— 让 agent 会话里的 GUI 默认落到它自己的嵌套桌面。
#
# 怎么生效：给 dsh-web.service / dsh-web-dev.service 加一行
#   Environment=BASH_ENV=%h/.dsh/bin/agent-shell-env.sh
# 于是每条 bash 工具命令（非交互 bash）启动时都会 source 这里。
#
# 做什么：按当前工作区找到（必要时拉起）这个会话的 agent 桌面，导出
#   WAYLAND_DISPLAY / DISPLAY / NIRI_SOCKET  →  新开的 GUI 全落在那个桌面里，
# 人的桌面一个窗口都不会多。生产桌面的值另存成 PROD_*，用 prod-niri / prod-x 调。
#
# 关掉：AGENT_DESKTOP=0 <命令>（单条命令不进 agent 桌面）

[ -n "${_DSH_AGENT_SHELL_ENV:-}" ] && return 0
_DSH_AGENT_SHELL_ENV=1

# 记下生产桌面的值（只记一次，后面命令里也一直有效）
: "${PROD_DISPLAY:=${DISPLAY:-:0}}"; export PROD_DISPLAY
: "${PROD_WAYLAND_DISPLAY:=${WAYLAND_DISPLAY:-wayland-1}}"; export PROD_WAYLAND_DISPLAY
if [ -z "${PROD_NIRI_SOCKET:-}" ] || [ ! -S "${PROD_NIRI_SOCKET}" ]; then
  for _s in /run/user/1000/niri.wayland-1.*.sock; do
    [ -S "$_s" ] && PROD_NIRI_SOCKET="$_s"
  done
fi
export PROD_NIRI_SOCKET

case "${AGENT_DESKTOP:-1}" in
  0|no|off|false) return 0 ;;
esac

_adesk_bin="$HOME/.dsh/bin/agent-desktop.py"
[ -f "$_adesk_bin" ] || return 0

_adesk_root() {
  local d i
  d="$(pwd -P 2>/dev/null || pwd)"
  i=0
  while [ "$i" -lt 12 ]; do
    if [ -e "$d/.git" ] || [ -e "$d/AGENTS.md" ] || [ -e "$d/.dsh" ]; then
      printf '%s' "$d"; return 0
    fi
    [ "$d" = "/" ] && break
    [ "$d" = "$HOME" ] && break
    d="$(dirname "$d")"
    i=$((i + 1))
  done
  printf '%s' "$(pwd -P 2>/dev/null || pwd)"
}

_adesk_ws="$(_adesk_root)"
_adesk_key="ws-$(printf '%s' "$_adesk_ws" | md5sum | cut -c1-8)"
_adesk_dir="$HOME/.dsh/agent-desktops/$_adesk_key"

[ -r "$_adesk_dir/env.sh" ] && . "$_adesk_dir/env.sh"

if [ -z "${AGENT_DESKTOP_NIRI_PID:-}" ] || ! kill -0 "$AGENT_DESKTOP_NIRI_PID" 2>/dev/null; then
  if command -v python3 >/dev/null 2>&1; then
    python3 "$_adesk_bin" up --key "$_adesk_key" --workspace "$_adesk_ws" --quiet >/dev/null 2>&1
    [ -r "$_adesk_dir/env.sh" ] && . "$_adesk_dir/env.sh"
  fi
fi

if [ -n "${AGENT_DESKTOP_NIRI_PID:-}" ] && kill -0 "$AGENT_DESKTOP_NIRI_PID" 2>/dev/null; then
  export AGENT_DESKTOP=1 AGENT_DESKTOP_KEY="$_adesk_key" \
         AGENT_DESKTOP_WORKSPACE="$_adesk_ws"
  mkdir -p "$_adesk_dir" 2>/dev/null
  date +%s > "$_adesk_dir/heartbeat" 2>/dev/null
fi

return 0

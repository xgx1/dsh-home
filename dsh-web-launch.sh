#!/usr/bin/env bash
set -e
source "$HOME/.dsh/dsh-env.sh"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
# 2026-09-22 用户指示：cua-driver native 与 dsh-web 同进程，要操作 Wayland 窗口必须注入显示环境。
# WAYLAND_DISPLAY=wayland-1（Hyprland /run/user/1000/wayland-1）；DISPLAY=:0 保留作 X11 兜底。
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export DISPLAY="${DISPLAY:-:0}"
# 2026-09-22 追加：cua-driver 0.28.0 的原生 Wayland 后端是 opt-in（health_report 明示），
# 不设则 X11 通道枚举不到 Wayland 原生窗口（Chrome 已 --ozone-platform=wayland）。
export CUA_DRIVER_RS_ENABLE_WAYLAND=1
# 2026-09-22 再补：cua-driver 按 XDG_CURRENT_DESKTOP 识别 compositor，缺失时 Hyprland
# 输入插件报 "production Hyprland input plugin is unavailable"（实测 bring_to_front/hotkey 拒绝）。
# XDG_SESSION_TYPE 一并带上，供 libei/portal 通道识别会话类型。
export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-Hyprland}"
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
# 2026-09-30：billion-context 的代理按 lane 隔离。生产与 dev 若共用 lane "dsh"，
# 两边的 bili-native 会互相 attach 到同一个代理——而该代理的生命周期绑在拉起它的
# 那个 dsh 进程上（父进程 watchdog），dev 一重启就把生产的模型链路一起带走。
# 固定各自的 lane，各起各的代理（端口按 lane sticky 分配）。
export BILI_NATIVE_DSH_LANE=dsh-prod
# 2026-10-24：/tmp 是 32G tmpfs（size=50% RAM，Arch tmp.mount 带 usrquota）。当天约 22G 修复样本
# 落进 /tmp 后用户 tmpfs 配额到顶，而 run_code（PTC）每次 spawn 前必须写
# /tmp/dsh-subprocess-launch-*/launch-request.json（subprocess-local/src/runner-protocol.ts:104），
# 内核以 EDQUOT(122) 拒绝 —— libuv 1.52 的 errno 名表没有 EDQUOT，于是报成
# “worker spawn failed: code=UNKNOWN errno=-122 syscall=write”，整个 run_code 工具全挂。
# 把临时目录挪到大盘（/mnt/Storage，btrfs）：PTC 启动文件、输出 spill、shell-activity 不再和内存盘抢配额。
# 目录不可用时静默回退 /tmp，保证服务一定能起来。
if [ -d /mnt/Storage/tmp ] && [ -w /mnt/Storage/tmp ]; then
  export TMPDIR=/mnt/Storage/tmp
fi
exec dsh web --no-open

#!/usr/bin/env bash
# install-systemd-units.sh —— 把 deploy/systemd-user/ 里的 unit 部署到 systemd 用户目录
#
# 为什么需要它：~/.config/systemd/user/ 不在任何 git 仓库里，而这几个服务是
# DSH 生产实例与 MCP 的前置（dsh-web 拉 MCP 子进程；headroom-deepseek 提供
# MCP 要连的 :8787）。新设备只拉 ~/.dsh 是不够的，unit 得跟着过去。
#
# 用法：
#   ./install-systemd-units.sh --dry-run    # 只显示会做什么
#   ./install-systemd-units.sh              # 部署 + reload + enable
#   ./install-systemd-units.sh --start      # 追加：立即启动（新设备首次部署用）
#
# 幂等：已存在同名 unit 时会覆盖（本目录是权威副本），内容相同则跳过。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/systemd-user"
DEST="${HOME}/.config/systemd/user"

dry=0
start=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    --start)   start=1 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数：$arg（用 --help）" >&2; exit 2 ;;
  esac
done

[ -d "$SRC" ] || { echo "找不到 unit 源目录：$SRC" >&2; exit 1; }

if [ "$dry" = 0 ] && ! systemctl --user show-environment >/dev/null 2>&1; then
  echo "无法连接 systemd 用户总线。先试：" >&2
  echo "  export XDG_RUNTIME_DIR=/run/user/\$(id -u)" >&2
  exit 1
fi

changed=0
skipped=0
for unit in "$SRC"/*.service; do
  name="$(basename "$unit")"
  target="$DEST/$name"
  if [ -f "$target" ] && cmp -s "$unit" "$target"; then
    echo "  跳过      $name（内容已一致）"
    skipped=$((skipped + 1))
    continue
  fi
  if [ "$dry" = 1 ]; then
    echo "  会写入    $name -> $target"
  else
    install -Dm 644 "$unit" "$target"
    echo "  已写入    $name"
  fi
  changed=$((changed + 1))
done

if [ "$dry" = 1 ]; then
  echo
  echo "（dry-run，未做任何改动；会写 $changed 个、跳过 $skipped 个）"
  exit 0
fi

if [ "$changed" -gt 0 ]; then
  systemctl --user daemon-reload
  echo "  已执行    systemctl --user daemon-reload"
fi

# enable（不 start）：让服务随登录自启
for unit in "$SRC"/*.service; do
  systemctl --user enable "$(basename "$unit")" >/dev/null 2>&1 || true
done
echo "  已 enable 全部 unit（随用户会话自启）"

if [ "$start" = 1 ]; then
  systemctl --user start headroom-deepseek.service headroom-scnet.service \
    headroom-siliconflow.service headroom-moda.service 2>/dev/null || true
  echo "  headroom-* 已启动"
  echo "  dsh-web 最后启动（它会中断当前会话）：systemctl --user start dsh-web.service"
fi

echo
echo "完成：写入 $changed，跳过 $skipped。"
echo "核对：systemctl --user list-unit-files 'headroom*' 'dsh-web*'"

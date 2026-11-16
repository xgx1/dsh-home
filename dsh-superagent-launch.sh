#!/usr/bin/env bash
# dsh-superagent-launch.sh —— Super-agent 实验实例（:3082），profile=superagent，由 dsh-superagent.service 调用。
#
# 跑 dev 检出的代码，但用独立 profile：super-agent 改进程级 PATH 与 git 配置，
# 所以不跟 3081（web profile）共用进程。
set -e
source "$HOME/.dsh/dsh-env.sh"          # 只导出 .credentials.yaml 里的 *_API_KEY
export DSH_HOME="$HOME/.dsh-dev"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export BILI_NATIVE_DSH_LANE=dsh-superagent
exec node "$HOME/projects/MyAI/deepseek-harness-dev/apps/cli/lib/bin.js" superagent --port 3082 --no-open

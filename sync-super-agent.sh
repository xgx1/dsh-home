#!/usr/bin/env bash
# sync-super-agent.sh —— 把上游 aowind 的最新提交同步进我们的 fork，并把 dev 检出里的指针推上去。
#   aowind（upstream）是真源；deepseek-ai/dsh-superagent-prototype（official）只是参考资料，不 merge。
set -euo pipefail
SUB="$HOME/projects/MyAI/deepseek-harness-dev/extensions/dsh-super-agent"
DEV="$HOME/projects/MyAI/deepseek-harness-dev"

cd "$SUB"
git fetch --all --quiet
echo "--- 上游新提交："; git log --oneline main..upstream/main | head -10 || true
git merge --no-edit upstream/main
echo "--- 官方原型的未跟踪提交（只看不并）："; git log --oneline main..official/main | head -5 || true
git push origin main

cd "$DEV"
git add extensions/dsh-super-agent
if git diff --cached --quiet; then echo "--- 指针未变"; else git commit -m "chore(extensions): bump dsh-super-agent" && git log --oneline -1; fi

systemctl --user restart dsh-superagent.service
echo "--- 已重启 :3082"

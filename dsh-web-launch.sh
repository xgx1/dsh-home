#!/usr/bin/env bash
set -e
source "$HOME/.dsh/dsh-env.sh"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
exec dsh web --no-open

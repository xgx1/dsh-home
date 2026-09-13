# dsh API key 环境变量导出
# 从 ~/.dsh/.credentials.yaml 读取（YAML 结构，key 可能有缩进）
# 只导出以 _API_KEY 结尾的键；供 ~/.bashrc 与 dsh 服务共用
if [ -f "$HOME/.dsh/.credentials.yaml" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # 去行首空白
    line="${line#"${line%%[![:space:]]*}"}"
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%:*}"
    val="${line#*:}"
    # 去 value 前导空白与可能的 CR
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%$'\r'}"
    case "$key" in
      *_API_KEY) [ -n "$val" ] && export "$key=$val" ;;
    esac
  done < "$HOME/.dsh/.credentials.yaml"
fi

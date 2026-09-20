# AGENTS.md — DSH 全局规则（用户级）

本文件由 dsh-agent-instructions 在启动时注入到每个新会话。保持精简，不要稀释系统提示词。
只放**任何工作区都成立**的规则；工作区特有的路径与仓库事实（DSH 检出在哪、dsh-extensions 的 submodule、install-skill.sh 用法）落在各自工作区的 AGENTS.md。

## 修改位置

- 需要重启 `dsh-web.service`（会中断当前对话）或可能影响其他会话的改动，动手前先确认；纯代码/文档提交可直接做。
- 改任何 git submodule 要在**各自目录里**提交、推送，再回上层仓库更新指针；上层只保存指针。
- **`~/.dsh` 本身是 git 仓库**（`main` → `xgx1/dsh-home`，公开），只跟踪配置层：`AGENTS.md`、`settings.yaml`、`.agent-presets/`、`profiles/*/` 的 composition 与 lock、启动脚本。**密钥（`.credentials.yaml`/`.env`）与运行时数据（`sessions/`、`storages/`、根 `skills/` 软链）永不入库**——改完要提交并推送，新增跟踪内容前先读 `~/.dsh/README.md` 的排除清单与「只锚根目录」陷阱。

## 技能

- 运行时技能目录 `~/.dsh/skills/` 里**受管技能全是软链，不是副本**；**不要手工往里面复制技能**——副本会与仓库漂移。
- 技能按上游仓库分组：`<技能源仓>/skills/<上游仓库名>/`。**组内目录与上游一一对应**——组树 = 上游树 + 本地改动移植到对应文件，上游各层级（`skills/<名>/`、`.agents/skills/<名>/`、`plugins/<插件>/skills/<名>/`）原样保留，**不拍平到组根**；分组 README 叫 `README.dsh-local.md`。本地改名只写在 frontmatter 的 `name:` 上，所以技能名不随上游目录名变。
- **项目专用技能不放主库**：落在各项目自己的 `<项目根>/.dsh/skills/`。
- **命令的平台约定**：技能里的命令按平台分节——Linux（本机 Arch）用 `bash`、Windows 用 `PowerShell`，代码块语言标记即平台归属，两者不混写在同一段里。只给 PowerShell 的方案一律补 bash 等价（补不了就写明「Linux 上无对应方案＋原因＋可替代做法」，不许编造跑不通的命令）；只有 bash 的方案不必再写 PowerShell 版本。

## 调用语法

- 选工具先宽后窄：先枚举候选工具再落选，不要默认只挑最常用的那个。
- 信息不全时先用只读工具铺开再动手，不猜测文件名与路径。
- 长任务分步提交，每步先验证再继续；失败时先看错误原文再换方案。

## GUI 窗口

- 助手拉起的图形程序一律自动落到 **AI 工作区（Hyprland workspace 10）**，不抢焦点、不切用户工作区，用户 `Super+0` 随时可看。判据是窗口进程的 cgroup 落在 `dsh-*`（`dsh-web.service` / `dsh-subprocess-*.scope`；setsid / nohup / reparent 都改不掉），实现在 `~/.config/hypr/hyprland.lua` 的「AI 窗口隔离」段；用户自己起的程序（`session-N.scope`）不受影响。
- **启动 GUI 程序用 `aiw <命令>`**（`~/.local/bin/aiw`）：由 Hyprland 执行器起，带 `workspace 10 silent` 直接落位，且**进程不会随命令结束被回收**——在 DSH 的 bash 里直接 `setsid nohup` 起的图形进程会在命令 scope 拆除时一起被杀。
- 要主动打开给用户看：`aiw --here <命令>`；跳过兜底规则用 `AIW_SHOW=1`；换目标工作区用 `AIW_WS=7 aiw …`。
- 本机 Hyprland 0.56 的派发一律是 Lua：`hyprctl dispatch 'hl.dsp.…'`（旧写法 `hyprctl dispatch fullscreen 0` 会被当 Lua 求值报错），另有 `hyprctl eval` / `hyprctl repl` 可现场读写状态。

## 代码检索

omni preset 的 persona 已写完整检索优先级，这里只留判据：图查不到 ≠ 代码不存在——先 `check_index_coverage` / `query_graph(graph="missed")` 核覆盖，再回退文本搜索并标注「图未覆盖」；未索引的仓库先 `index_repository` 再查图。详见技能 `cbm-graph-first`。

## 模型目录

- **所有模型（任何项目/工具加载的）一律存放在 `~/.model/`**，按工具或项目分子目录；项目或工具原本的模型位置**只保留软链接**指回 `~/.model`，模型实体不随项目目录移动、不入库、不重复拷贝。
- 约定：`~/.model/<工具或项目名>/<模型文件>`；原位置用 `ln -s ~/.model/... <原路径>` 恢复引用。
- 同一模型的不同量化/版本视为重复，只保留**实际在用**的一份；判断"在用"以运行进程与配置文件的**实际引用**为准（`ps` 命令行、`/proc/<pid>/cwd`、配置文件里的 `model` 字段），不靠猜。
- 2026-09-20 已迁移：Bonsai2-27B（PQ2_0 + mmproj）、fcitx vinput 的 sherpa-onnx ASR、zvec-grep 嵌入模型，并删除未引用的死重（Bonsai PTQ1_0、vinput qwen3-asr-1.7b、960ms 流式）。

# AGENTS.md — DSH 全局规则（用户级）

本文件由 dsh-agent-instructions 在启动时注入到每个新会话。保持精简，不要稀释系统提示词。
只放**任何工作区都成立**的规则；工作区特有的路径与仓库事实（DSH 检出在哪、dsh-extensions 的 submodule、install-skill.sh 用法）落在各自工作区的 AGENTS.md。

## 修改位置

- **DSH 本体的生产检出默认只读**：`~/projects/MyAI/deepseek-harness`（分支 `master`，`dsh-web.service` 的 3080 就跑在它上）。DSH 的功能开发只改同层级的 worktree `~/projects/MyAI/deepseek-harness-dev`（分支 `dev`，dev 实例 `dsh-web-dev.service` → `:3081`，`DSH_HOME=~/.dsh-dev`）；**除非用户在当次需求里主动点名要改生产检出**。细节与禁止清单见 `~/projects/MyAI/AGENTS.md`「DSH 改动落点」。
- 需要重启 `dsh-web.service`（会中断当前对话）或可能影响其他会话的改动，动手前先确认；纯代码/文档提交可直接做。
- **改动默认提交并推送**：`~/.dsh`、`dsh-extensions` 与其 submodule 提交后直接推 origin（submodule 先推，再推上级），不必每次再问。（2026-10-17 用户指示）
- 改任何 git submodule 要在**各自目录里**提交、推送，再回上层仓库更新指针；上层只保存指针。
- **`~/.dsh` 本身是 git 仓库**（`main` → `xgx1/dsh-home`，公开），只跟踪配置层：`AGENTS.md`、`settings.yaml`、`.agent-presets/`、`profiles/*/` 的 composition 与 lock、启动脚本。**密钥（`.credentials.yaml`/`.env`）与运行时数据（`sessions/`、`storages/`、根 `skills/` 软链）永不入库**——改完要提交并推送，新增跟踪内容前先读 `~/.dsh/README.md` 的排除清单与「只锚根目录」陷阱。

## DSH 开发红线

以下几条都是崩过生产换来的，别删、别绕：

- **不许删 `packages/llm/llm/src/index.ts` 里的 `assertNever` 兼容导出**（L54-57，注释写明了保留条件）：外部 turtle-ui TUI 还在从这个包 import；删掉再重建，`dsh tui` 的 import 必挂。等 turtle-ui 迁完再删。
- **新增插件包必须走完五件套**，漏一步 preset 就起不来：① 包内 `tsconfig.json`（extends 根 `tsconfig.base.json`、`rootDir: src`、`outDir: lib/types`、references 声明依赖）→ ② 根 `tsconfig.host.json` 的 `references` 加引用 → ③ `pnpm run gen-tsconfig-paths` 重生成包别名 → ④ `apps/cli/package.json` 加依赖 + `pnpm install` → ⑤ 全量 `pnpm run build:lib:host` 通过且该包测试通过。**preset 引用了未构建好的包 = 所有用该 preset 的新会话起不来**，而 `omni` 是默认 preset。
- **包装 provider 时，候选技能上的 `provider` 必须等于外层注册名**：别让内层 provider 顶着旧名字返回数据——名字不匹配会解析到错误的 provider。
- **更新 CBM（`codebase-memory-mcp`）二进制后必须重启 `codebase-memory.service`**，否则常驻 daemon 握着旧 inode，全线 MCP 请求超时。该 unit 是**用户级**：`systemctl --user restart codebase-memory.service`。
- **改完 `~/.dsh/.agent-presets/` 或 `profiles/` 后，先确认能加载，再重启 `dsh-web.service`**：顺序反了就是先断了当前对话、再发现 preset 加载不了。

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

- 助手拉起的 GUI 进程**会在 DSH 命令 scope 拆除时被回收**——要长驻就自己 `setsid` / systemd 管，别指望命令返回后窗口还在。（2026-10-05 已拆「AI 窗口隔离」：不再自动搬 workspace 10，`aiw` / `AIW_SHOW` / `AIW_WS` 全部废止。）
- 本机 Hyprland 0.56 的派发一律是 Lua：`hyprctl dispatch 'hl.dsp.…'`（旧写法 `hyprctl dispatch fullscreen 0` 会被当 Lua 求值报错），另有 `hyprctl eval` / `hyprctl repl` 可现场读写状态。

## 代码检索

- `zvec_grep_search`（语义检索）要求工作区已建索引，未建会返回 `INDEX_MISSING`。**这时不要反复重试、也不要自己跑 `zg index`**：立刻改用 `zvec_grep_rg` 做精确检索；索引由 `zg-autoidx` 代理在后台自动构建，工具结果里出现「已自动为该工作区建好索引」后再回去用语义检索。（2026-10-23 事故：0.2.2 的 `zg` 索引没人建，每次 `zvec_grep_search` 都白跑一轮。）

omni preset 的 persona 已写完整检索优先级，这里只留判据：图查不到 ≠ 代码不存在——先 `check_index_coverage` / `query_graph(graph="missed")` 核覆盖，再回退文本搜索并标注「图未覆盖」；未索引的仓库先 `index_repository` 再查图。详见技能 `cbm-graph-first`。

## 逆向证据层（REA）

看闭源产物（二进制 / APK / Electron-JS / ELF / 固件 / 进程行为）时先想 REA（`morluto/rea`），别手搓 `strings` / `objdump`。MCP 已注册在生产 web profile（`~/.dsh/profiles/web/cordis.patch.yml` 的 `mcp-rea`，热加载，不用重启），工具命名空间 `mcp__rea__*`（170 个）；技能 `reverse-engineer-anything` 已装，分组仓 `dsh-extensions/skills/rea`（fork `xgx1/rea`，与 CLI 同钉 tag `rea-agents-6.4.0`）。

- CLI 是 `rea`（`~/.npm-global/bin/rea`，`~/.local/bin/rea` 软链指过去）：`rea doctor --json` 查引擎就绪，`rea analyze-*` / `inspect-artifact` 直接干活。
- 已装引擎：Ghidra 12.1.2（`/opt/ghidra`）、JADX、apktool、binwalk、pwntools + pwndbg + gdb、mitmproxy、adb、完整 JDK、.NET SDK。**Hopper / IDA / JEB 是付费软件或自带服务，对应 provider 报 unavailable 属预期**，不是配置坏。
- **Ghidra 必须显式给 `GHIDRA_INSTALL_DIR=/opt/ghidra`**（已写进 MCP 条目的 `env`）：REA 的 PATH 发现要求 `ghidra`/`ghidraRun` 的真实路径落在 Ghidra 树内，而 Arch 的 `/usr/bin/ghidra` 只是包装脚本，走 PATH 必然失败。
- **`toolCallTimeoutMs` 别调回默认**（现为 600000）：REA 侧 Ghidra 冷启动默认允许 330 s，客户端默认 60 s 就会中途取消，首次查询白跑。
- 升级时 CLI 与技能一起动——技能比 npm 包新会描述服务端不存在的工具。`rea doctor` 的「Installed REA skill identity is missing」只因它只认自家客户端目录（claude/codex/omp/pi），不认 `~/.dsh/skills`，可忽略。

## 模型目录

- **所有模型（任何项目/工具加载的）一律存放在 `~/.model/`**，按工具或项目分子目录；项目或工具原本的模型位置**只保留软链接**指回 `~/.model`，模型实体不随项目目录移动、不入库、不重复拷贝。
- 约定：`~/.model/<工具或项目名>/<模型文件>`；原位置用 `ln -s ~/.model/... <原路径>` 恢复引用。
- 同一模型的不同量化/版本视为重复，只保留**实际在用**的一份；判断"在用"以运行进程与配置文件的**实际引用**为准（`ps` 命令行、`/proc/<pid>/cwd`、配置文件里的 `model` 字段），不靠猜。
- 2026-10-12 实况：`~/.model/` 目前**只有 `laya/`**。约定的两个例外（迁不动，别当成没做）：zvec-grep 的嵌入模型在 `~/.zvec-grep/models/`（工具自管，CPU 小模型）；fcitx vinput 的 sherpa-onnx ASR 在 `~/.local/share/vinput/models/`。
- **本机当前没有本地大模型**（2026-10-15 用户确认弃用并清空配置：权重、systemd 单元、profile 里的 provider 条目都已删）。要重新用本地模型得先重下权重并按上面约定落 `~/.model/`，再往 profile 的 `llm-pi-ai` provider 表里加条目。
- Laya 决策模型在 `~/.model/laya/hf`（用 `HF_HOME` 指过去）；推理环境在 `~/.local/share/laya/venv`（torch ROCm / gfx1100），由用户级 `laya-sidecar.service` 在 `:8083` 常驻服务（约 5.5 GB 显存）。

## 浏览器

- **ego 跑共享 profile 模式**：ego 不另起浏览器，而是挂到用户日常 Helium 的同一个进程（`--remote-debugging-port=9222`，来自 `~/.config/helium-browser-flags.conf`，故 Helium 必须经桌面图标 / `helium-browser` 启动才带该 flag）。`egoBin` = `~/.local/share/ego-lite-runtime/bin/ego-shared.mjs`，profile 直接用 `~/.config/net.imput.helium`。**不要**跑 `ego-browser --stop`、也不要把插件的 `idleTimeoutMin` 打开——共享模式下这两者都会关掉用户自己的浏览器。
- **访问网页优先用 ego**：能开页面就先用 `ego_*` 工具（`ego_navigate` → `ego_snapshot` → `ego_click`/`ego_fill`）在 ego 浏览器里真开一次，登录态、Cookie、人机验证都在用户自己的窗口里。`web_search` 只做找线索与摘要；`curl`/`webshare` 抓页面、Playwright/CUA 驱浏览器都退居备选——只有 ego 起不来（`ego_doctor` 报错）或任务本就不需要浏览器时才换。

## 长驻进程与 scope 卫生（2026-10-23）

- 经 dsh 跑 UE 构建时带 `-nodeReuse:false`（或 `/nodeReuse:false`）；跑过 `adb start-server` 的要在收尾 `adb kill-server`。这两类常驻子进程会让 `dsh-subprocess-*.scope` 永不退出（实测有 scope 从 00:01 挂到 16:18），累积后拖死整机。
- `~/.dsh/bin/dsh-janitor.sh` 每 15 分钟由 `dsh-janitor.timer` 清一次：停掉空 `dsh-subprocess` scope、杀 MSBuild node-reuse 残留、截断超 100MB 的 zvec daemon 日志。手工排查先看 `/tmp/dsh-janitor.log`。
- 2026-10-23 起 dsh 自己会回收 scope 里的孤儿：载荷退出后等 3s，若 cgroup 里只剩「沿用载荷会话号」的进程（MSBuild node-reuse 那种）就 `systemctl --user stop` 收掉整个 scope 并打一条 `reaped inherited stragglers`；**`setsid` 起来的进程自成一个会话，会被保留** —— 所以「要长驻就自己 setsid / 交给 systemd」这条依然成立。
- bili 的「request sent DIRECT (uncompressed)」现在只对「远端 + 有 wire 尺寸请求体」上报；本机 loopback（dsh↔openviking、MCP health）不再刷屏。若真有自定义 wire 的**模型**端点要过代理压缩，用 `BILI_EXTRA_MODEL_PATHS=/api/llm/generate,...`（逗号分隔路径子串）声明后重启 dsh。
- `run_code` 的失败现在带 `[diagnostic] code/errno/syscall`，宿主日志同时有 `ptc-runtime-node: worker <stage> failed: …`；scope 启动路径整体坏掉时可用 `DSH_SUBPROCESS_CONTAINMENT=direct` 临时回到直连进程树。
- 抓 HTTP/JSON 用 `web_fetch`（`tool-web` 已开 `fetch`）；ego-browser 只用于需要登录态或真实交互的页面。在页面上下文里 `fetch` 跨站 API 会被 CORS 挡死（2026-10-23 共 39 次 `TypeError: Failed to fetch`）。

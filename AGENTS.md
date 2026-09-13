# AGENTS.md — DSH 全局规则（root，用户级）

本文件由 dsh-agent-instructions 在启动时注入到每个新会话。保持精简，不要稀释系统提示词。

## 修改位置（2026-09-13 起：DSH 单检出）

- DSH 仓库原「`master/` 主检出 + `dev/` worktree」双检出已下线：`dev` 分支（本地与 `fork` 远端）、`dev/` worktree、3081 dev 实例、`dsh-web-dev.service` 全部移除。现在只有 `deepseek-harness/` 一个检出（**目录于 2026-09-13 由 `master/` 改名，分支仍叫 `master`**）。
- **生产实例（3080）就跑在这份 `deepseek-harness/` 检出上**（`~/.local/bin/dsh` → `deepseek-harness/apps/cli/lib/bin.js`，由 `dsh-web.service` 托管）——改它就是改生产。
- 因此：需要重启 `dsh-web.service`（会中断当前对话）或可能影响其他会话的改动，动手前先确认；纯代码/文档提交可直接做。
- 如果要重新引入「改动不落主检出」的纪律，自行开 worktree（`git worktree add ../MyAI-dev -b dev`）——目前没有，也不再默认要求。
- 其他仓库（`dsh-extensions/`）本来就是单检出，按各自分支提交。`dsh-context-compression-selector` 已无本地检出（生产 profile 走 npm registry `0.1.0`）。
- `dsh-extensions/` 的 `vendor/`（第三方上游克隆，生产 `link:` 目标）与 `skills/`（技能分组仓）**都是 git submodule**，各自带独立 `.git` 与远端：改它们要在各自目录里提交、推送，再回 `dsh-extensions` 更新指针（见 MyAI `docs/adr/0005`）。`vendor/` 与 `skills/` 不再被 `.gitignore` 忽略。
- `rider-skills` 曾于 2026-09-13 因无消费者删除，同日随技能归位**重新引入**——现在是 `dsh-extensions/skills/rider-skills`（fork `xgx1/rider-skills`）。
- `update-app`（CLI + `update-all` 技能）已移出工作区，独立仓库位于 `~/projects/update-app`。
- **`~/.dsh` 本身已是 git 仓库**（2026-09-13 起，`main` → `xgx1/dsh-home`，公开），只跟踪「配置层」：`AGENTS.md`、`settings.yaml`、`.agent-presets/`（含 preset 自带技能）、`profiles/*/` 的 composition 与 lock、启动脚本。**密钥（`.credentials.yaml`/`.env`）与运行时数据（`sessions/`、`storages/`、根 `skills/` 软链等）永不入库**——改这里之后要提交并推送，新增跟踪内容前先读 `~/.dsh/README.md` 的排除清单与「只锚根目录」陷阱。新设备恢复步骤亦见该 README（依赖 `~/projects/MyAI` 与 `update-app` 先就位）。

## 技能：分组仓 + 一键部署（2026-09-13 起）

- 运行时技能目录是 `~/.dsh/skills/`；其中**受管技能全是软链**，不是副本。
- **技能按上游仓库分组**：`dsh-extensions/skills/<上游仓库名>/`。有上游的组是公开 fork，无上游的组是自建仓。**组内目录与上游一一对应**（2026-09-13 起对齐）：fork 的树 = 上游最新树 + 本地改动移植到对应文件，上游不同层级（`skills/<名>/`、`.agents/skills/<名>/`、`skills/engineering/<名>/`、`plugins/<插件>/skills/<名>/`）原样保留，**不再把技能拍平到组根**；我们的分组 README 叫 `README.dsh-local.md`。改名类本地改动只写在 frontmatter 的 `name:` 上，所以技能名不随上游目录名变。来源判据看 `agents/openai.yaml` 与残存的 `license:`/`compatibility:` 键——**`author: Sx` 与中文 frontmatter 不是「自研」的证据**，那是本地化层批量盖的章（见 MyAI `docs/adr/0006`）。
- **项目专用技能不放主库**：落在各项目自己的 `<项目根>/.dsh/skills/`（已有先例：YellowRiverSluice、HydroVault2）。
- 用 `dsh-extensions/install-skill.sh` 安装/更新：它扫描**三个**技能源——① `dsh-extensions/skills/<分组>/**/SKILL.md`（**递归发现、不限深度**，技能目录 = 含 `SKILL.md` 的目录，上游层级不一，硬编码层数会静默漏技能；跳过 `tests/`/`fixtures/`/`examples/`/`sample*` 噪音并**打印跳过清单**；同名副本取路径最浅者，故 `skills/`、`.agents/skills/` 优先于 `.openclaw/skills/` 之类分发副本；技能名优先取 frontmatter 的 `name:`）、② `~/projects/update-app/skills/`、③ `~/projects/*/.dsh/skills/`——把每个技能目录软链到 `~/.dsh/skills/<name>`。幂等；覆盖真实目录需 `--force`（先备份到 `~/.dsh/skill-backups/`）。`--dry-run` 预演，`--list` 只看清单。
- **不要再手工往 `~/.dsh/skills/` 复制技能**——副本会与仓库漂移（曾出现运行时那份还在教已被删除的仓库）。
- **命令的平台约定（2026-09-13 起）**：技能里的命令按平台分节——**Linux（本机 Arch）用 `bash`、Windows 用 `PowerShell`**，代码块语言标记即平台归属，两者不混写在同一段里。只给 PowerShell 的方案**一律补 bash 等价**（补不了就在文中写明「Linux 上无对应方案＋原因＋可替代做法」，不许编造跑不通的命令）；只有 bash 的方案**不必再写 PowerShell 版本**。
- 顺手工具：`install-skill.sh --dry-run` 的输出里「新建 N」应为 0，否则说明有技能没被纳入受管源。

## 调用语法（把可能性调大）

- 选工具先宽后窄：先枚举候选工具再落选，不要默认只挑最常用的那个。
- 信息不全时先用只读工具铺开再动手，不猜测文件名与路径；代码库里的检索走「cbm 查图优先」（见下节），glob/grep 是兜底而不是起点。
- 长任务分步提交，每步先验证再继续；失败时先看错误原文再换方案。

## 代码检索（cbm 查图优先）

- 在代码库里找代码：先用 codebase-memory MCP 查图——search_graph 定符号、trace_path 查调用链/影响面、get_architecture 看架构、search_code 图增强搜索；grep/glob 只做兜底（字面量、文件名、原始计数）。
- 图查不到 ≠ 代码不存在：先 check_index_coverage / query_graph(graph="missed") 核覆盖，再回退文本搜索并标注「图未覆盖」。
- 未索引的仓库先 index_repository（秒级）再查图；流程与回退判据见技能 `cbm-graph-first`。
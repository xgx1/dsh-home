# ~/.dsh — DSH 配置层仓库

本仓库把 DSH（DeepSeek Harness）的**用户级配置层**纳入版本控制，便于在多台设备之间同步。
它 **不是** 一个自包含的安装：`~/.dsh` 是寄生在若干项目仓库之上的配置层，恢复一台新设备需要先备好这些依赖（见 [新设备恢复](#新设备恢复)）。

## 什么进仓库，什么不进

跟踪的是「换台机器还该保持一样」的东西：

| 路径 | 内容 |
|---|---|
| `AGENTS.md` | 用户级全局规则，每个新会话启动时注入 |
| `settings.yaml` | 模型路由、权限预设、压缩策略等全局设置 |
| `.agent-presets/` | 自建 agent preset（`omni` / `manager` / `simple`）及其携带的技能 |
| `profiles/{web,tui,headless}/` | 各 profile 的 composition：`cordis.yml` + `cordis.patch.yml` + `pnpm-workspace.yaml` + `package.json` + lock |
| `dsh-env.sh` / `dsh-web-launch.sh` | 启动脚本，被 `dsh-web.service` 调用 |
| `keys.example.yaml` | 凭据模板（**只有键名与格式说明，没有值**） |

不跟踪、且**永远不该**进仓库的：

| 路径 | 原因 |
|---|---|
| `.credentials.yaml` | 17 个 API key，多数明文。跨设备靠 `keys.example.yaml` 重建 |
| `.env` / `**/.env` | 本机环境层，本身就构成一份凭据 |
| `sessions/` `attachments/` `cache/` | 纯本机运行时数据（~190MB）。`sessions/` 目录名按项目路径编码，换设备即失效 |
| `storages/` `task-manager/` | 全是本机绝对路径的本机状态，跨设备会互相覆盖 |
| `skills/` | 根目录下的 301 条**全是软链**，由 `dsh-extensions/install-skill.sh` 从仓库外部生成。注意 `.gitignore` 里写的是 `/skills/`（锚定根目录）——`.agent-presets/*/skills/` 是 preset 自带的技能，属于要跟踪的内容，别把它一起吞掉 |
| `bin/` `evolve/` | 本机专属（`bin/hypr-place` 依赖 Hyprland；`evolve/` 含 `rubric.key`） |
| `profiles/*/node_modules/` | 依赖产物，靠 `pnpm install` 重建 |

判断标准只有一条：**这台设备独有的状态，不属于这个仓库。**

## 依赖：`~/.dsh` 恢复不了的东西

`profiles/web/package.json` 里 6 个依赖全是 `link:` 绝对路径，全部指向 `~/projects/MyAI/dsh-extensions/`：

```json
"@changfenhuang/dsh-genui": "link:/home/sx/projects/MyAI/dsh-extensions/vendor/dsh-genui"
```

因此恢复顺序必须是**先项目、后配置**。新设备需要：

1. `~/projects/MyAI`（含 `dsh-extensions`，其下 `vendor/` 与 `skills/` 是 git submodule，共 17 个）
2. `~/projects/update-app`（`install-skill.sh` 的技能源之一）
3. DSH 本体检出 `~/projects/MyAI/deepseek-harness` 与 `~/.local/bin/dsh`

## 新设备恢复

```bash
# 1. 先备好上面「依赖」一节的三个仓库，并初始化 submodule
cd ~/projects/MyAI/dsh-extensions && git submodule update --init --recursive

# 2. 取回本仓库（若 ~/.dsh 已存在，先保证它与远端一致）
cd ~/.dsh && git init -b main && git remote add origin https://github.com/xgx1/dsh-home.git
git fetch origin && git checkout -f main

# 3. 重建 profile 依赖（link: 指向刚备好的 dsh-extensions）
cd ~/.dsh/profiles/web && pnpm install
mkdir -p patches        # 空目录不进 git，但组成需要它存在

# 4. 重建技能软链（301 条，指向 dsh-extensions/skills/）
~/projects/MyAI/dsh-extensions/install-skill.sh

# 5. 重建凭据（三选一，优先级从高到低）
cp ~/.dsh/keys.example.yaml ~/.dsh/.credentials.yaml && chmod 600 ~/.dsh/.credentials.yaml
#    然后填入真实值；或直接用 dsh 配置界面逐个保存；或用启动环境覆盖：
#    DEEPSEEK_API_KEY=… dsh web
```

`chmod 600` 不是可选项：POSIX 上 DSH 会拒绝加载任何其他用户可读的凭据文件。

## systemd 用户单元（同样不在仓库里，靠部署脚本落地）

`~/.config/systemd/user/` 不受任何 git 管理，但这些服务是生产实例与 MCP 的前置。
权威副本在 **`deploy/systemd-user/`**，用脚本落地：

```bash
~/.dsh/deploy/install-systemd-units.sh --dry-run   # 先看会做什么
~/.dsh/deploy/install-systemd-units.sh             # 写入 + daemon-reload + enable
~/.dsh/deploy/install-systemd-units.sh --start     # 新设备：顺带启动 headroom-*
```

| unit | 作用 |
|---|---|
| `dsh-web.service` | DSH 生产实例（3080），同时**拉起全部 MCP 子进程** |
| `headroom-deepseek.service` | `:8787` 代理——`mcp-headroom` 连的就是它 |
| `headroom-scnet` / `headroom-siliconflow` / `headroom-moda` | 另外三个上游代理（`:8789` / `:8788` / `:8790`） |

unit 里**没有任何密钥**——`dsh-web-launch.sh` 会 source `dsh-env.sh`，把 `.credentials.yaml`
的 `*_API_KEY` 注入启动环境。所以本仓库可以公开，而密钥仍只在各设备本地的凭据文件里。

`headroom-moda.service` 在本机是 `disabled` 的（休眠条目），脚本仍会部署它；启动与否由你决定。

## MCP 前置依赖（配置同步 ≠ 那台设备能用）

`profiles/web/cordis.patch.yml` 里的 MCP 条目（cbm / ue / headroom / playwright）**随本仓库同步**，
但每条 `stdio` 型 MCP 都要**在设备上有那个命令**，否则 DSH 会静默跳过它（配置里带着
`failOnStartupError: false`），表现为"工具凭空消失"而没有任何报错。新设备需要另行安装：

| MCP | 命令 | 安装方式 | 本机版本 |
|---|---|---|---|
| cbm | `codebase-memory-mcp` | `uv tool install codebase-memory-mcp` | v0.10.8 |
| playwright | `playwright-mcp` | `npm i -g @playwright/mcp`（软链到 `~/.local/bin`） | 0.0.80 |
| headroom | `headroom` | `uv tool install headroom-ai` | v0.37.0 |

装完用 `command -v <命令>` 逐个确认，再重启 `dsh-web.service`（MCP 子进程由它拉起）。
`http` 型（如 `mcp-ue` 的 `127.0.0.1:8000`）不依赖命令，依赖那台设备的服务在跑。

`headroom` 那条还必须清代理——它要连本机 8787，而 `dsh-web` 继承的 `all_proxy=socks5://…`
会让子进程报 `socksio` 缺失；该条目的 `env` 段就是为此显式清空 `*_proxy` 并设 `no_proxy`。
**它连的 8787 由 `headroom-deepseek.service` 提供**，所以那份 unit 也是前置（见上一节）。

## 凭据机制备忘

`~/.dsh/dsh-env.sh` 把 `.credentials.yaml` 里所有 `*_API_KEY` 导出到启动环境——所以本机走的是
`dsh-web-launch.sh` → `dsh-env.sh` → 环境变量这条路径。DSH 自身的查找优先级是：

1. **启动环境**（`DEEPSEEK_API_KEY=… dsh`）——只读，本次运行覆盖一切
2. **`.credentials.yaml`**（存储文件）——产品写入的目标
3. 项目 `.env`（`<cwd>/.env`）
4. `$DSH_HOME/.env`

格式硬约束：顶层只允许 `version` / `refs` / `records` 三个键，`version` 必须为 `1`，空值非法
（删除一个键是删掉整行）。未知顶层键会被**大声拒绝**而不是静默忽略——这正是「密钥不进仓库、
配置里只出现键名」能成立的原因。

## 维护约定

- 这个仓库跟踪 `~/.dsh` 的**根目录本身**，所以 `git status` 很容易被运行时噪音污染。新增任何
  跟踪内容前，先确认它不属于上面「不进仓库」的任何一类。
- 本机是**单检出生产环境**：`dsh-web.service` → `~/.dsh/dsh-web-launch.sh` → `deepseek-harness/`
  检出。改 `~/.dsh` 里的 composition 会被 DSH 热加载，改代码则可能影响正在运行的会话。
- 提交前自查：`git status --short` 与 `git diff --cached --stat` 里不应出现 `.credentials.yaml`、
  `.env`、任何 `sessions/` 路径。

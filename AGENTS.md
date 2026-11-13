# AGENTS.md — DSH 全局规则（用户级）

只放**任何工作区都成立**的规则；工作区特有的路径与仓库事实（DSH 检出在哪、dsh-extensions 的 submodule、install-skill.sh 用法）落在各自工作区的 AGENTS.md。

## 修改位置

- **改动默认提交并推送**：`~/.dsh`、`dsh-extensions` 与其 submodule 提交后直接推 origin（submodule 先推，再推上级），不必每次再问。（2026-10-17 用户指示）submodule 改动在各自目录里提交，上层只保存指针。
- **`~/.dsh` 本身是 git 仓库**（`main` → `xgx1/dsh-home`，公开），只跟踪配置层：`AGENTS.md`、`settings.yaml`、`.agent-presets/`、`profiles/*/` 的 composition 与 lock、启动脚本。**密钥（`.credentials.yaml`/`.env`）与运行时数据（`sessions/`、`storages/`、根 `skills/` 软链）永不入库**——新增跟踪内容前先读 `~/.dsh/README.md` 的排除清单与「只锚根目录」陷阱。

## 浏览器

- **ego 跑共享 profile**：挂用户日常 Helium 的同一个进程（`--remote-debugging-port=9222`，故 Helium 须经桌面图标 / `helium-browser` 启动）；`egoBin` = `~/.local/share/ego-lite-runtime/bin/ego-shared-bili.mjs`（探 9224，该端口是 socat 转发到 9222）。**不要**跑 `ego-browser --stop`、也不要把插件的 `idleTimeoutMin` 打开——共享模式下两者都会关掉用户自己的浏览器。
- **ego 不许抢用户前台**：CDP 层已丢弃 `Target.activateTarget`、新 tab 用 `background: true`（`EGO_ALLOW_ACTIVATE=1` 放行），补丁清单在插件 runtime 的 `PATCHES.md`。**ego 运行时重装 / 插件更新后补丁会丢，要重打**；验收：`niri msg focused-window` 记标题 → 跑一次 `ego_navigate`/`ego_snapshot` → 标题应不变。
- **访问网页优先用 ego**：`ego_navigate` → `ego_snapshot` → `ego_click`/`ego_fill` 在用户自己的窗口里真开一次（登录态、Cookie、人机验证都在那里）；`web_search` 只做找线索，`curl`/Playwright/CUA 退居备选。

## 后台窗口控制

操作另一批 GUI 应用（Unity、Unreal、浏览器、.NET）或改这套 scoped 输入能力时，先加载技能 `background-window-control`；命令、坑与证据都在技能里。硬约束：

- 能力只存在于 niri fork（`/home/sx/projects/niri`，分支 `scoped-input-poc`）；上游 `niri` 包已卸载，生产桌面自 2026-11-05 起跑 fork。
- **重启 `niri.service` 等于重启整个桌面会话，动手前先问用户**；救急用 `niri-fallback.service`（`/usr/bin/niri`，仅恢复用）。
- waybar 由 `waybar.service`（`Restart=always`）托管；不要改回 while 循环（会被 reparent 到 systemd --user，桌面重启后不退出，每会话多一个 bar）。
- 回归夹具在 `~/projects/MyAI/.scratch/background-window-control/regression-visibility`（`python3 cycle.py 1 smoke.py` 自检）。
- 红线：只清理自己起的进程；禁止 `pkill -f`；不读剪贴板；不把未定向的键鼠发进当前会话。

## 会话监察（dsh-guard）

本机同时跑多个会话（GUI 里开着的、后台 teammate）。`~/.dsh/bin/dsh-guard.py` 每分钟由 `dsh-guard.timer` 扫 `~/.dsh/sessions/*`、`~/.dsh-dev/sessions/*` 的新 tool call 与主机状态，命中就追加 `~/.dsh/guard/findings.jsonl` 并给桌面发 critical 通知；**只读**：不写会话、不杀进程、不改别人的东西。

- 规则表就是脚本里的 `RULES`（改规则改那里，别在别处拷贝）：生产检出里的 git 写与 `pnpm build/install/test`、重启/停 `dsh-web`/`niri`/`waybar`、`pkill -f`、`kill -9 -1`、`pacman` 动 niri、`hyprctl`、往 `~/.dsh/skills` 写实体文件、碰 `.credentials.yaml`；主机侧盯 `dsh-web`/`niri` 的 MainPID、waybar 实例数、niri socket 数、niri 包与 `/usr/bin/niri` 是否回来。
- 读法：`dsh-guard.py status | report -m <分钟> | since -m <分钟>`，或 `journalctl --user -u dsh-guard -f`。命中 ≠ 违规，按 severity 人判；用户批准的动作也会被记录（带 session id），别当成别人的错。

## 其他桌面观察（dsh-desktops + dsh-view）

`~/.dsh/bin/dsh-desktops.py` 发现并盯着「别的桌面」，`dsh-view.py` 在 http://127.0.0.1:8793/ 展示（看进度、可直接接手）；由 `deploy/install-systemd-units.sh` 装成 `dsh-view.service` 与 `dsh-observe.timer`（每分钟）。

- 三类：① agent 桌面（配置在 `~/.dsh/agent-desktops/<key>/`，label 取 `desk.json` 的 workspace）；② 别的嵌套环境（配置在别处，label 取目录名；与其它桌面共用 `/run/user/1000`，靠 pid 自己的 socket 认）；③ 裸 `Xvfb :N`（防御路径，本机已无 Xvfb，容器里的不算）。
- **每个桌面从自己 IPC socket 名认 wayland**（`niri.wayland-3.<pid>.sock` → `wayland-3`）；不能取进程环境里的 `WAYLAND_DISPLAY`——嵌套 niri 的那项指向生产合成器。
- 采集：整屏 grim 到 `~/.dsh/watch/desktops/<key>/shots/`，每窗用 fork 的 scoped-shot 单独抓（不动剪贴板、别的工作区也抓得到）；索引 `watch/desktops.json`，截图超 1 GiB 自动裁。
- 接手：`dsh-desktops.py action <桌面> focus-window|type|key|click ...`；agent 桌面走 agent 座位，**嵌套回归环境只看不控**（`Mod+U` 过去直接操作），裸 X 走那台 X 自己的 XTEST。
- 只读边界：除面板上明确的按钮外，采集侧不改任何桌面状态；别人的会话、窗口、剪贴板一律不碰。

## agent 桌面

每个工具会话一个嵌套 niri 桌面（生产合成器的 Wayland 客户端，走真 GPU）；钩子把每条 bash 命令的 `WAYLAND_DISPLAY`/`DISPLAY`/`NIRI_SOCKET` 指过去，**GUI 默认就在这里起**（含 UE/Unity），桌面窗口停在生产 `ue` 工作区、不抢人的焦点。

- 机制：`~/.config/systemd/user/dsh-web{,-dev}.service.d/agent-desktop.conf` 设 `BASH_ENV=~/.dsh/bin/agent-shell-env.sh`；按工作区 key（根目录 md5 前 8 位，`ws-xxxxxxxx`）找或拉起桌面，连续 30 分钟无命令也无窗口就自动收。
- 管理：`agent-desktop.py list | up [--key K] | down [--key K|--all] | env | run -- <命令> | prune`。人的桌面用 `prod-niri` / `prod-xdo` / `prod-grim` 或 `PROD_*` 变量；`niri msg` 不带前缀 = 自己的桌面。systemd 单元与 niri `spawn-at-startup` 拉的程序仍在生产桌面。
- **接管输入只走 agent 座位**：`scoped-target <生产窗口 id>` 钉住，再 `agent-seat-probe agent-0 click|text|keys ...`（坐标是钉住表面的千分数；中文自动 `wl-copy` + `ctrl+v`）。**别用 `wtype`**：它按注册表顺序绑最后一个 seat，哪天绑到 `seat0` 就打进人的窗口。
- 需要物理 GPU 会话（VR/OpenXR 预览、独占全屏、GPU 基准）才回生产桌面：`AGENT_DESKTOP=0 <命令>`，`^UnrealEditor$` 窗口会被投到 `ue`（`Mod+U`）；其他 GPU 程序自己搬：`prod-niri msg action move-window-to-workspace --window-id N --focus false ue`。
- 兜底与禁忌：钩子拉不起桌面时退回生产桌面并在 stderr 告警；不要用 `NIRI_SOCKET=$PROD_NIRI_SOCKET ...` 把程序塞进生产桌面；已开错桌面的窗口不会自动搬。
- 看 `ue` 里的窗口只抓单窗（`scoped-shot <window-id> <路径>`），不要整屏 grim（会切走人的视图）；`open-focused false` 已能压掉客户端的 activation 请求，但没命中规则的窗口仍会抢焦点。

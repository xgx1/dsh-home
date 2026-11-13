# AGENTS.md — DSH 全局规则（用户级）

只放**任何工作区都成立**的规则；工作区特有的路径与仓库事实（DSH 检出在哪、dsh-extensions 的 submodule、install-skill.sh 用法）落在各自工作区的 AGENTS.md。

## 修改位置

- **改动默认提交并推送**：`~/.dsh`、`dsh-extensions` 与其 submodule 提交后直接推 origin（submodule 先推，再推上级），不必每次再问。（2026-10-17 用户指示）
- 改任何 git submodule 要在**各自目录里**提交、推送，再回上层仓库更新指针；上层只保存指针。
- **`~/.dsh` 本身是 git 仓库**（`main` → `xgx1/dsh-home`，公开），只跟踪配置层：`AGENTS.md`、`settings.yaml`、`.agent-presets/`、`profiles/*/` 的 composition 与 lock、启动脚本。**密钥（`.credentials.yaml`/`.env`）与运行时数据（`sessions/`、`storages/`、根 `skills/` 软链）永不入库**——改完要提交并推送，新增跟踪内容前先读 `~/.dsh/README.md` 的排除清单与「只锚根目录」陷阱。

## 浏览器

- **ego 跑共享 profile 模式**：ego 不另起浏览器，而是挂到用户日常 Helium 的同一个进程（`--remote-debugging-port=9222`，来自 `~/.config/helium-browser-flags.conf`，故 Helium 必须经桌面图标 / `helium-browser` 启动才带该 flag）。`egoBin` = `~/.local/share/ego-lite-runtime/bin/ego-shared-bili.mjs`（探 9224；9224 是 socat 转发到 9222，所以实际挂在日常 Helium 上；探不到才用 `~/.config/net.imput.helium-bili` 自起一份）。**不要**跑 `ego-browser --stop`、也不要把插件的 `idleTimeoutMin` 打开——共享模式下这两者都会关掉用户自己的浏览器。
- **ego 不许抢用户前台**（2026-11-04 用户要求）：共享 profile 下 ego 每次 `ego_*` 调用都会激活 tab（`focusSpace`/`switchTab`/`createTab` 全走 `Target.activateTarget`，新建 tab 还被 Chromium 默认激活），把用户当前 tab 顶掉并抢窗口焦点。修法是在 CDP 传输层 `transport.mjs` 的 `call()`/`sendRaw()` 里丢弃 `Target.activateTarget` 的实际发送（记账保留，`activeHint` 不受影响），两处 `Target.createTarget` 加 `background: true`；`EGO_ALLOW_ACTIVATE=1` 放行（观察窗「弹出为真实窗口」`ego-browser --open` 是显式用户动作，由 `ego-shared-bili.mjs` 在 argv 含 `--open` 时设置）。两棵树都打了：`~/.local/share/ego-lite-runtime/runtime/`（egoBin 实际指向）与插件副本 `~/.dsh/profiles/web/node_modules/dsh-ego-browser/runtime/`，改动清单记在插件 runtime 的 `PATCHES.md`。**ego 运行时重装 / 插件更新后补丁会丢，要重打**；验收方法：`niri msg focused-window` 记标题 → 跑一次 `ego_navigate`/`ego_snapshot` → 标题应不变。
- **访问网页优先用 ego**：能开页面就先用 `ego_*` 工具（`ego_navigate` → `ego_snapshot` → `ego_click`/`ego_fill`）在 ego 浏览器里真开一次，登录态、Cookie、人机验证都在用户自己的窗口里。`web_search` 只做找线索与摘要；`curl`/`webshare` 抓页面、Playwright/CUA 驱浏览器都退居备选——只有 ego 起不来（`ego_doctor` 报错）或任务本就不需要浏览器时才换。

## 后台窗口控制（本机能力）

要在不打断当前工作的前提下操作另一批 GUI 应用（Unity、Unreal、浏览器、.NET 等），或改这套 scoped 输入能力时，先加载技能 `background-window-control`；命令、坑与证据都在技能里。

- 能力只存在于 niri fork（`/home/sx/projects/niri`，分支 `scoped-input-poc`）起的实例里；上游 `niri` 包已彻底卸载，生产桌面自 2026-11-05 起跑 fork。
- **重启 `niri.service` 等于重启整个桌面会话，动手前先问用户**；救急用 `niri-fallback.service`（走 `/usr/bin/niri`，仅恢复用）。
- waybar 由 `waybar.service`（用户单元，`Restart=always`）托管；不要改回 while 循环（会被 reparent 到 systemd --user，桌面重启后不退出，每会话多一个 bar）。
- 回归夹具在 `~/projects/MyAI/.scratch/background-window-control/regression-visibility`（`python3 cycle.py 1 smoke.py` 自检）。
- 红线：只清理自己起的进程；禁止 `pkill -f`；不读剪贴板；不把未定向的键鼠发进当前会话。

## 会话监察（dsh-guard，2026-11-05）

本机同时跑多个会话（GUI 里开着的、后台 teammate 都算）。`~/.dsh/bin/dsh-guard.py` 每分钟由
`dsh-guard.timer` 扫一遍 `~/.dsh/sessions/*` 与 `~/.dsh-dev/sessions/*` 里新出现的 tool call，
命中红线就追加到 `~/.dsh/guard/findings.jsonl` 并给桌面发 critical 通知；主机侧同时盯 unit 与进程状态。
**它只读**：不写会话、不杀进程、不改别人的东西。

- 规则表就是脚本里的 `RULES`（改规则改那里，别在别处拷贝一份）。当前覆盖：生产检出里的 git 写操作与
  `pnpm build/install/test`、重启/停 `dsh-web`、重启/停 `niri`/`waybar`、`pkill -f`、`kill -9 -1`、
  动 `/usr/bin/niri`（已不存在）、`pacman -S/-R niri`、`hyprctl`、往 `~/.dsh/skills` 写实体文件、
  碰 `.credentials.yaml`。主机侧：`dsh-web`/`niri` 的 MainPID 变化、
  waybar 实例数 ≠ 1、niri socket 数 > 1、niri 包被装回来、`/usr/bin/niri` 又出现。
- 读法：`dsh-guard.py status`（主机状态 + 5 分钟内有活动的会话）、`dsh-guard.py report -m 120`
  （最近 2 小时命中）、`dsh-guard.py since -m 480`（只读回放 8 小时，不动 state）、
  `journalctl --user -u dsh-guard -f`（每轮跑批日志）。命中 ≠ 违规，按 severity 人判。
- 我自己（用户明确批准的动作）也会被记进去：日志里带 session id，别把它当别人的错。

## 其他桌面观察（dsh-desktops + dsh-view，2026-11-05）

agent 默认在自己的 agent 桌面里干活（生产合成器上的嵌套 niri，走真 GPU），那些程序在我的屏幕上看不到
（它们只以 `niri` 窗口的形式在 `ue` 工作区里）。**回归环境也一样**：那两套夹具现在起的是
挂生产合成器的私有嵌套 niri（窗口同样停 `ue`），本机已经没有 Xvfb（`xorg-server-xvfb` 2026-11-06 卸载，
`xvfb-run` 也没了）。
`~/.dsh/bin/dsh-desktops.py` 负责发现并盯着它们，`dsh-view.py` 在 http://127.0.0.1:8793/ 的「其他桌面」区展示，
可以看进度，也可以直接接手。

- 发现三类（除 `niri.service` 的 MainPID 之外的每个 niri 都算"别的桌面"）：
  ① **agent 桌面**（`-c` 配置在 `~/.dsh/agent-desktops/<key>/` 下，label 取 `desk.json` 的 workspace）；
  ② **别的嵌套环境**（配置在别处，如 `.scratch/background-window-control/regression-visibility/poc.kdl`，
  label 取它所在目录名；它们现在也共用 `/run/user/1000`，靠 pid 自己的 socket 认，别再用 runtime 目录区分）；
  ③ **裸 X 服务器**（`Xvfb :N`，见下）。
  每类的 wayland 从**自己 IPC socket 名**里认（`niri.wayland-3.<pid>.sock` → `wayland-3`），
  不能取进程环境里的 `WAYLAND_DISPLAY`——嵌套 niri 的那一项指向生产合成器。
- 采集（`dsh-observe.timer` 每分钟；service 里三条 ExecStart 依次跑我的桌面、别的桌面、回收过期 agent 桌面）：整屏用 grim 截到
  `~/.dsh/watch/desktops/<key>/shots/`，每个窗口用 fork 的 scoped-shot 单独抓一张（别的工作区也抓得到，
  不动剪贴板），窗口/工作区列表来自嵌套 niri 的 IPC；索引 `watch/desktops.json`，事件
  `watch/desktop-events.jsonl`。截图保留 24h / 1 GiB，自动裁。
- 接手（面板按钮，或命令行）：
  `dsh-desktops.py action <桌面> focus-window --window N | type --text 文本 | key --combo Return | click --x X --y Y`。
  **agent 桌面**走 agent 座位：`scoped-target <生产窗口 id>` 钉住，再用 `agent-seat-probe agent-0` 点击/打字，
  人的指针与焦点不动（中文自动 `wl-copy` + `ctrl+v`）。**裸 X 卡片**走那台 X 自己的 XTEST。
  **嵌套回归环境只看不控**（nested）：它在 `ue` 里本来就是一个生产窗口，`Mod+U` 过去直接操作即可；
  面板对它的输入会明确提示这一点。
- 面板：`http://127.0.0.1:8793/`，点图看大图；开「点击接管」后点图就是点那个桌面（截图是 0.5 缩放，
  页面自动 ×2 换算）；窗口按钮聚焦该窗口，输入框 + 发送/回车往当前焦点窗口打字。
- `dsh-view.service`（127.0.0.1:8793）与 `dsh-observe.timer`（每分钟）都由 `deploy/install-systemd-units.sh` 装。
- 第三类是**裸 X 服务器**（2026-11-06 补；同日本机卸载了 `xorg-server-xvfb`，所以这条现在只是防御——
  万一哪个会话又装回来/在别的机器上跑，面板照样能看见）：会话自己开的 `Xvfb :N`（例如 Unity 要固定分辨率就 `Xvfb :143 -screen 0 1600x1000x24` + `openbox`）。
  它里面没有 niri，靠 niri 扫不到，以前在面板上完全看不见。现在 `dsh-desktops.py` 也扫 Xvfb，只认 DSH 会话拉起的
  （进程 cgroup 在 `dsh-*` / `app-*` 里；容器里的 Xvfb 不算），面板上显示为 `xvfb` 卡片：整屏用 `import -display :N -window root`，
  窗口用 `xdotool search` + `import -window <id>` 逐窗抓；接手用 `dsh-desktops.py action xvfb-143 type --text … | key --combo … | click --x X --y Y`
  （先 focus 最大的有名窗口）。那是另一台 X server，人的指针/键盘/焦点一点不动。
- 但**别默认开裸 Xvfb 跑 GUI**：它没 GPU（llvmpipe）、也没有真窗口管理，只是"能看见"。要 GPU 就在自己的 agent 桌面里跑；
  确实需要固定分辨率的 X 环境，就在自己 agent 桌面的 X11（例如 `:10`）里跑，而不是另开 Xvfb。
- 只读边界：除了面板上这些明确按钮，采集侧不改任何桌面状态；别人的会话、窗口、剪贴板一律不碰。

## agent 桌面（GUI 默认落点，2026-11-06）

每个工具会话一个嵌套 niri 桌面，它是生产合成器的一个 **Wayland 客户端**（不是 X 里的窗口）：
父表面 = 生产 niri 的 Wayland → 嵌套 niri fork → 首次连 X11 时 niri 自拉 xwayland-satellite。
和人的桌面共用 `/run/user/1000`（DBus/Pulse/portal 不用另配）。

- **走真 GPU（2026-11-06 换掉 Xvfb）**：以前父表面是 Xvfb（X 虚拟帧缓冲 = 纯内存软件光栅化、没有 DRI3），
  Mesa 只能给 llvmpipe，所以 agent 桌面是软渲染、跑不动 UE/Unity 的 GPU 部分。改成挂在生产合成器上以后，
  嵌套 niri 和它里面的客户端直接拿到 `/dev/dri/renderD128`（实测 3 个 fd），日志里没有 DRI3/dmabuf 告警。
  代价：每个 agent 桌面在 `ue` 工作区是一个普通窗口（规则匹配 app-id `^niri$` → `ue` + `open-focused false`），
  不会抢人的焦点；要看用 `Mod+U` 或仪表盘的窗口截图。
- 机制：`~/.config/systemd/user/dsh-web.service.d/agent-desktop.conf`（和 `dsh-web-dev` 同名 drop-in）
  给服务加 `Environment=BASH_ENV=/home/sx/.dsh/bin/agent-shell-env.sh`。每条 bash 工具命令进 shell 时：
  1) 记下生产桌面的 `PROD_DISPLAY` / `PROD_WAYLAND_DISPLAY` / `PROD_NIRI_SOCKET`；
  2) 按工作区 key（工作区根目录 md5 前 8 位，形如 `ws-6f1aa0a4`）找桌面，没有就拉起；
  3) 导出 agent 桌面的 `WAYLAND_DISPLAY` / `DISPLAY`（嵌套 niri 的 X11 socket）/ `NIRI_SOCKET`。
  拉起后 supervisor 会把嵌套桌面那个生产窗口搬到 `ue`（`move-window-to-workspace --focus false`），
  人的视图和焦点一点不动。
- 管理：`agent-desktop.py list | up [--key K] | down [--key K|--all] | env | run -- <命令> | prune`。
  连续 30 分钟没有命令、也没有窗口就自动收；有窗口就一直留着。
- 人（生产）桌面：`prod-niri msg ...`、`prod-xdo ...`、`prod-grim ...`，或直接用 `PROD_*` 变量。
  `niri msg` 不带前缀 = 你自己的桌面。要看/接别人的 agent 桌面用下面「其他桌面观察」那套。
- 观察/接手：http://127.0.0.1:8793/ 的「其他桌面」区（实时图 + 窗口按钮 + 打字/点击接管）。
- 不经过钩子的：systemd 单元/timer、从 niri 配置 `spawn-at-startup` 拉的程序 —— 它们还在生产桌面。
- 已经开错桌面的窗口不会自动搬家，只能关掉重开。
- **接管输入只走 agent 座位**（`/home/sx/projects/agent-seat-probe/target/debug/`）：
  `scoped-target <嵌套窗口 id>` 把生产 niri 的 `agent-0` 座位钉在这个桌面的窗口上，然后
  `agent-seat-probe agent-0 click <x> <y>` / `agent-seat-probe agent-0 text '...'` /
  `agent-seat-probe agent-0 keys 'ctrl+v'`；坐标是钉住表面的千分数。人的指针、键盘焦点、当前工作区都不动。
  中文等非 ASCII：`wl-copy`（写进这个桌面自己的 Wayland 剪贴板）再 `keys 'ctrl+v'`，`dsh-desktops.py` 已自动这么干。
  **别用 `wtype` 往生产合成器打字**：它按注册表顺序绑最后一个 seat（现在恰好是 `agent-0`，能工作纯属巧合，
  哪天绑到 `seat0` 就直接打进了人的窗口）。
- **GUI 默认就在 agent 桌面里起，UE/Unity 这类 GPU 负载也一样**（agent 桌面已经是真 GPU）。
  不要用 `NIRI_SOCKET=$PROD_NIRI_SOCKET niri msg action spawn -- ...` 把程序塞进生产桌面——
  2026-11-06 12:12 就是这么把 UnrealEditor 开到 `ue`（生产合成器的工作区）而不是 agent 桌面里的。
  照常跑（`./UnrealEditor ...`、`niri msg action spawn -- ...` 都行，钩子已经把环境指过去了）就落在自己的桌面。
- 只有**必须碰物理 GPU 会话**的才回生产桌面：VR/OpenXR 预览（monado 要独占设备）、独占全屏、GPU 基准。
  用 `AGENT_DESKTOP=0 <命令>` 起，窗口规则会把 `^UnrealEditor$` 投到 `ue`（`Mod+U` 看）。
- 兜底：钩子拉不起 agent 桌面时会**退回生产桌面**（`AGENT_DESKTOP=0`）并在 stderr 告警，不再把死 socket 留在环境里
  （2026-11-06 修：之前 env.sh 里的 WAYLAND_DISPLAY 可能是上次回收掉的桌面的）。
- **GPU 类负载不许再开在人当前的工作区**（2026-11-06 修）：生产 niri 已声明命名工作区 `workspace "ue"`
  （Mod+U 切过去，Mod+Shift+U 把当前窗口丢过去），并加了窗口规则把所有 app-id `^UnrealEditor$` 的窗口
  （含资产编辑器/VR Preview 这类子窗）投到 `ue` + `open-focused false`。其他要 GPU 的程序启动后自己搬：
  `prod-niri msg action move-window-to-workspace --window-id N --focus false ue`。
- 坑：`open-on-workspace` 只在**目标命名工作区已声明且存在**时生效，否则退回当前工作区（niri 文档原话，
  2026-11-06 实测：没声明 `workspace "ue"` 时规则静默失效）。`Mod+U` 也一样按名字解析。
- 已修（niri fork `1e7a8e6f`）：`open-focused false` 现在**也压掉客户端自己的 activation 请求**
  ——以前 UE 新开一个子窗就能把人的视图拽到 `ue`。命中时 niri 打一条
  `ignoring activation request: window rules say open-focused false`。新起的嵌套/agent 桌面已经用上，
  生产桌面要等下次**桌面会话重启**才换到新二进制；没命中规则的窗口照旧按 xdg-activation 抢焦点
  （实测另一窗口仍能抢回来），所以别以为全局禁用了。
- 看/验证 `ue` 里的窗口**不要**用整屏 grim（那会切走人的视图、也可能截到别的工作区）：用
  `NIRI_SOCKET=/run/user/1000/niri.wayland-1.<pid>.sock /home/sx/projects/agent-seat-probe/target/debug/scoped-shot <window-id> <路径>`
  —— 只抓那一个窗口，不动焦点；要整屏就先把 `ue` 聚焦再切回来（会闪一下，能不用就不用）。

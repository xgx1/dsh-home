
import json, os, subprocess, io

CORE_TOOLS = ["run_code","read","write","edit","bash","present","todo_write","ask_user_question",
              "job_*","terminal_*","user_terminal_*","skill","search_context","compress","decompress",
              "absorb","acp_*","read_image","working_directory","web_search",
              "list_mcp_resources","list_mcp_resource_templates","read_mcp_resource"]
WF_TOOLS = ["subagent","subagent_fork","workflow","ralph","create_goal","get_goal","update_goal"]


# 22 组：2026-11-15 用户要求「再细一点」——dotnet 拆构建/应用，testing 拆写测试/审计，ops 拆桌面/基础设施。
DOTNET_BUILD = ['binlog-*','build-parallelism','build-perf-*','check-bin-obj-clash','compile-feature',
                'copy-to-output-directory','detect-static-dependencies','directory-build-organization',
                'eliminate-redundant-restores','find-repeated-work-within-one-build','including-generated-files',
                'incremental-build','mtp-hot-reload','resolve-project-references','troubleshoot-binlog-mcp',
                'dump-collect']
DSHDEV = ['agentic-workflows','codebase-design','create-custom-agent','dsh-extension-dev','enable-project-skills',
          'extension-points','filter-syntax','graph-query-first-prompt','headroom-provider-onboard',
          'improve-codebase-architecture','installing-dsh-extensions','navigating-code','role-templates',
          'scaffold-exercises','sdd-no-git-adaptation','setup-matt-pocock-skills','software-factory']

TEST_WRITE = ['writing-mstest-tests','run-tests','tdd','tdd-fanout','tdd-write-feature','test-driven-development',
              'testability-obstacle','generate-testability-wrappers','scaffold-dotnet-test-project',
              'code-testing-agent','code-testing-extensions','filter-syntax','platform-detection','microbenchmarking']
TEST_AUDIT = ['assertion-quality','coverage-analysis','crap-score','eval-performance','exp-*','find-untested-sources',
              'grade-tests','test-analysis-extensions','test-anti-patterns','test-gap-analysis','test-smell-detection',
              'test-tagging','test-value-evidence','vectorization']
OPS_DESKTOP = ['background-window-control','batch-file-organizing','baidupcs-download-pipeline','cache-notes',
               'fcitx-voice-input','media-convert-defaults','modelscope-daily','obs-studio-locale-cwd-fix',
               'video-transcribe-cn-env']
OPS_INFRA = ['local-git-archive-server','local-llm-amd','platform-detection','qmd','setup-local-sdk',
             'vr-and-aliyunpan-setup','win-headless-edge-browser-check','win-install-vs2022-ue']

DOTNET_APP = ['dotnet-*','maui-*','msbuild*','migrate-*','mcp-csharp-*','nuget-*','analyzing-dotnet-performance','author-component','collect-user-input','configure-auth','convert-blazor-server-to-webapp','convert-to-cpm','coordinate-components','create-blazor-project','create-datadriven-aspnetcore','csharp-refactoring','clr-activation-debugging','debugging-code','fetch-and-send-data','finding-tests','optimizing-ef-core-queries','plan-ui-change','property-patterns','refactoring-code','support-prerendering','system-text-json-net11','technology-selection','thread-abort-migration','use-igniteui-blazor','use-js-interop','winforms-expert','process-api-net11']

configs = {
  'core': {'skills': ['cbm-graph-first','ponytail','ponytail-*','git-pull-commit-push','git-merge-cleanup','using-git-worktrees','git-guardrails-claude-code'], 'mcp': ['cbm'], 'tools': CORE_TOOLS},
  'search': {'skills': [], 'mcp': ['zvecgrep'], 'tools': []},
  'unity': {'skills': ['csharp-scripts','csharp-expert','code-testing'], 'mcp': ['unity'], 'tools': []},
  'unreal': {'skills': ['unreal-*','ue-*','ue5-*','create-editor-plugin','create-toolset','plugin-documenter','read-uasset','graphics-debug','renderdoc-gpu-debug','strip-cpp-comments'], 'mcp': ['ue'], 'tools': []},
  'dotnet': {'skills': DOTNET_APP, 'mcp': [], 'tools': []},
  'dotnet-build': {'skills': DOTNET_BUILD, 'mcp': [], 'tools': []},
  'testing': {'skills': TEST_WRITE, 'mcp': [], 'tools': []},
  'test-audit': {'skills': TEST_AUDIT, 'mcp': [], 'tools': []},
  'dsh-dev': {'skills': DSHDEV, 'mcp': ['cbm'], 'tools': []},
  'ops-desktop': {'skills': OPS_DESKTOP, 'mcp': [], 'tools': ['ego_*','cua_driver_native__*']},
  'ops-infra': {'skills': OPS_INFRA, 'mcp': [], 'tools': []},
  'js': {'skills': ['setup-ts-deep-modules','wakaru','authoring-github-workflows'], 'mcp': [], 'tools': []},
  'ui-design': {'skills': ['ui-styling','ui-ux-pro-max'], 'mcp': [], 'tools': []},
  'design-brand': {'skills': ['design','design-system','brand','banner-design'], 'mcp': [], 'tools': []},
  'proj-find-work': {'skills': ['find-work','find-work-image','taobao-web-ops','xhs-web-ops'], 'mcp': [], 'tools': []},
  'ende': {'skills': ['setup-ts-deep-modules','wakaru','authoring-github-workflows'], 'mcp': [], 'tools': []},
  'blender': {'skills': ['blender-*'], 'mcp': ['unity'], 'tools': ['blender_*','mcp__unity__blender_bridge']},
  'rea': {'skills': ['rea-*','reverse-engineer-anything','open-apk','wakaru','read-uasset','android-tombstone-symbolication','apple-crash-symbolication','image-author-reverse-search','scanned-doc-ocr-extraction'], 'mcp': ['rea'], 'tools': []},
  'agent': {'skills': ['create-skill','create-skill-test','improve-skill-quality','writing-*','using-superpowers','brainstorming','grill-me','systematic-debugging','recap','wizard','wayfinder','loop-me','handoff','claude-handoff','ask-matt','chief-of-staff','triage','implement','research','teach','meeting','wait-what'], 'mcp': [], 'tools': ['ego_*','cua_driver_native__*','team_task_*']},
  'obsidian': {'skills': ['obsidian-*','json-canvas','pdf','slides','scanned-doc-ocr-extraction','meeting'], 'mcp': [], 'tools': []},
  'docs': {'skills': ['pdf','scanned-doc-ocr-extraction','meeting','batch-file-organizing','media-convert-defaults','video-transcribe-cn-env'], 'mcp': [], 'tools': []},
  'wf-plan': {'skills': ['grill-with-docs','grilling','writing-plans','make-feature-plan','to-spec','feature-inventory-docs-first','to-questionnaire','to-tickets'], 'mcp': [], 'tools': WF_TOOLS},
  'wf-build': {'skills': ['execute-feature-plan','executing-plans','subagent-driven-development','tdd','tdd-write-feature','implement-spec','add-software-feature','init-feature-dev','prototype','tdd-fanout','fix-feature-issues','dispatching-parallel-agents','optimize-feature-code'], 'mcp': [], 'tools': WF_TOOLS},
  'wf-verify': {'skills': ['verification-before-completion','code-review','review-feature-code','requesting-code-review','test-gap-analysis','receiving-code-review','write-manual-test-doc','diagnosing-bugs','diagnosing-superpowers'], 'mcp': [], 'tools': WF_TOOLS},
  'wf-ship': {'skills': ['finishing-a-development-branch','summarize-feature-work','solidify-feature-lessons','retro','write-feature-docs','cleanup-worktrees','setup-pre-commit','pr','dev-docs'], 'mcp': [], 'tools': WF_TOOLS},
   # 任务台的两层管理器（ADR-0014）：会话住在 <DSH_HOME>/task-manager/console，只拿 task_* 工具。
   'task-console': {'skills': [], 'mcp': [], 'tools': ['task_*']},
   # 执行会话：要能收尾回报（task_report / task_test_doc），进入待测试后还要自己写用例真跑、
   # 模拟点桌面窗口再交回正式测试文档（2026-11-19 用户要求），所以带测试四技能与桌面工具面。
   'task-exec': {'skills': ['tdd-fanout','write-manual-test-doc','verification-before-completion','background-window-control'],
                 'mcp': [], 'tools': ['task_report', 'task_test_doc', 'task_list', 'ego_*', 'cua_driver_native__*']},
   # 全能力（2026-11-17 用户要求）：所有技能、所有 MCP server、所有工具。
   'everything': {'skills': ['*'], 'mcp': ['cbm','ue','unity','zvecgrep','rea'], 'tools': ['*']},

}

WFD = ['wf-plan','wf-build','wf-verify','wf-ship']

def probe(p):
    def has(pat):
        cmd = "find %r -maxdepth 4 -name %r -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/_import/*' 2>/dev/null | head -1" % (p, pat)
        try:
            return bool(subprocess.run(['bash','-lc',cmd],capture_output=True,text=True,timeout=45).stdout.strip())
        except Exception:
            return False
    return has

projects, report = {}, []
ws = json.load(open('/home/sx/.dsh/storages/workspace.json'))['tables']['workspaces']
for wid, v in ws.items():
    p, title = v['path'], v.get('title','')
    exists = os.path.isdir(p)
    stack = []
    if exists:
        has = probe(p)
        if os.path.exists(os.path.join(p,'ProjectSettings','ProjectVersion.txt')) or has('ProjectVersion.txt'):
            stack.append('unity')
        if has('*.uproject'):
            stack.append('unreal')
        if has('*.sln') or has('*.csproj'):
            stack.append('dotnet')
        if os.path.exists(os.path.join(p,'package.json')) or has('tsconfig.json'):
            stack.append('js')
    if title == 'System': stack = ['unreal','dotnet','js','blender']
    if title == 'unrealengine': stack = ['unreal','dotnet']
    if title in ('计划','ps'): stack = ['obsidian']
    if title == 'hgame': stack = ['dotnet','js','rea']
    if title in ('empty','0526','li-dfy'):
        # empty stays unconfigured on purpose: it is the nothing-at-all test workspace.
        if title != 'empty' or True:
            stack = []
    if title in ('XianXia','SxGame','template','PsShowcase','YellowRiverSluice','cave','Moon_VR_TCP','VR_92_2') and 'unreal' not in stack:
        stack.append('unreal')
    if title in ('solar_system_ios','HoloLensView'): stack = ['unity','dotnet']
    if title in ('法律','被骗'): stack = ['search']
    sel = ['core'] + [s for s in dict.fromkeys(stack) if s in configs and s != 'core']
    coding = title in ('MyAI','find-work','ps-tool','System','PsShowcase','PsShowcaseWeb','vr-quiz','ue5.8','unrealengine','hgame','wivrn-src')
    if 'search' not in sel and (coding or title in ('计划','ps','法律','被骗')):
        sel.append('search')
    if title == 'MyAI': sel.append('agent')
    if 'dotnet' in sel: sel.append('dotnet-build')
    if any(s in sel for s in ('dotnet', 'js', 'unity', 'unreal')): sel += ['testing', 'test-audit']
    if title == 'MyAI': sel += ['dsh-dev', 'ops-desktop', 'ops-infra']
    if coding: sel += WFD
    sel = list(dict.fromkeys(sel))
    if title == 'MyAI': sel.append('ende')
    if title == 'hgame': sel.append('agent')
    if title == 'empty':
        report.append((title, p, exists, '(unlisted)'))
        continue
    projects[p] = sel
    report.append((title, p, exists, ','.join(sel)))

# 任务台（2026-11-17 用户要求）：会话别堆在「未分组」——管理器进「任务台·管理器」工作区，
# 执行会话进它自己的任务工作区（worktree）。工具可见性按 cwd 发放，这些目录必须先登记，
# 否则新派出去的执行会话一个工具都没有。
TASK_SEATS = {}
for _home in ('/home/sx/.dsh', '/home/sx/.dsh-dev'):
    for _seat in ('manager', 'console'):
        TASK_SEATS[_home + '/task-manager/' + _seat] = ['task-console']
        projects.setdefault(_home + '/task-manager/' + _seat, ['task-console'])
    try:
        _tasks = json.load(open(_home + '/task-manager/tasks.json'))
    except Exception:
        _tasks = []
    if not isinstance(_tasks, list):
        _tasks = []
    for _t in _tasks:
        if not isinstance(_t, dict):
            continue
        _p = _t.get('project')
        if isinstance(_p, str) and os.path.isdir(_p):
            projects.setdefault(_p, ['core'])
        _d = _t.get('directory')
        if isinstance(_d, str) and os.path.isdir(_d) and _t.get('status') != 'done':
            TASK_SEATS[_d] = ['core', 'task-exec']
            projects.setdefault(_d, ['core', 'task-exec'])
    # 座位登记（task-manager/seats.json）：worktree 可能还没写进 tasks.json，
    # 但只要要起执行会话，就必须先有工具。
    try:
        _seats = json.load(open(_home + '/task-manager/seats.json'))
    except Exception:
        _seats = []
    if isinstance(_seats, list):
        for _s in _seats:
            if isinstance(_s, str) and os.path.isdir(_s):
                TASK_SEATS[_s] = ['core', 'task-exec']
                projects.setdefault(_s, ['core', 'task-exec'])

projects.setdefault('/home/sx', ['core','search','ops-desktop','ops-infra'])
for scratch in ('/tmp', '/home/sx/projects/test', '/mnt/Video/test'):
    projects.setdefault(scratch, ['core','search','ops-desktop','ops-infra'] if scratch == '/tmp' else ['core','testing','test-audit'])
for extra, sel in {
    '/home/sx/projects/MyAI/deepseek-harness': ['core','search','js','ui-design','agent','testing','test-audit','dsh-dev','ops-desktop','ops-infra']+WFD,
    '/home/sx/projects/MyAI/deepseek-harness-dev': ['core','search','js','ui-design','agent','testing','test-audit','dsh-dev','ops-desktop','ops-infra']+WFD,
    '/home/sx/projects/MyAI/.scratch/mgr-ws-demo': ['core'],
    '/home/sx/projects/ps-tool': ['core','search','unreal','dotnet','dotnet-build','testing','test-audit','rea']+WFD,
    '/home/sx/projects/hgame': ['core','dotnet','dotnet-build','testing','test-audit','js','rea'],
    '/home/sx/projects/find-work': ['core','search','dotnet','dotnet-build','testing','test-audit','proj-find-work']+WFD,
}.items():
    projects.setdefault(extra, sel)

# /mnt/Video/PsShowcase 是 UE + Unity + Web + 文档的混装交付仓库，用户要求（2026-11-17）这个会话要全部能力。
projects['/mnt/Video/PsShowcase'] = ['everything']

# dsh-Go：Flutter/Dart 客户端 + Node 插件 SDK 与引擎桥 + .github/workflows（CI 是契约）。
# 只有 services/share-worker 一个 tsconfig 却把整套 .NET 测试技能（testing/test-audit）带进来，去掉；
# js 与 dsh-dev（扩展/插件开发）才是这个仓库用得到的（2026-11-16 用户要求「正确且合适」）。
projects['/mnt/Video2/dsh-Go'] = ['core','js','dsh-dev']

# XianXia：2026-11-17 按 codeup 的布局重构成「父库 + 两个子模块」——/mnt/Video2/XianXia 是父库，
# 客户端在 XianXia/（UE5 VR），服务端在 XianXiaServer/（.NET 10）。父库的 workspace 记录按 *.uproject+csproj
# 探测已经同时拿到 unreal 与 dotnet；两个子目录各自单独开会话时也要有工具（未列入 = 一个工具都没有），
# 客户端照旧给 unreal + 两套测试，服务端给 dotnet 与测试（应用与构建分开）。
projects['/mnt/Video2/XianXia/XianXia'] = ['core','unreal','testing','test-audit']
projects['/mnt/Video2/XianXia/XianXiaServer'] = ['core','dotnet','dotnet-build','testing','test-audit']

# 用户要求（2026-11-15）：UI 设计与设计品牌对每个项目都生效。
UNIVERSAL = ['ui-design', 'design-brand']
# 例外：/mnt/Video2/aur 是 AUR 打包工作区（只有 PKGBUILD），设计技能不适用（2026-11-16）。
NO_UNIVERSAL = {'/mnt/Video2/aur'}
for key, sel in projects.items():
    if key in NO_UNIVERSAL:
        continue
    projects[key] = list(dict.fromkeys(UNIVERSAL + sel))
for _seat_path, _seat_sel in TASK_SEATS.items():
    if _seat_path not in projects or projects[_seat_path] == ['core']:
        projects[_seat_path] = _seat_sel
# find-work 自己的四个技能只在这个项目里可见。
if '/home/sx/projects/find-work' in projects:
    projects['/home/sx/projects/find-work'] = list(dict.fromkeys(
        projects['/home/sx/projects/find-work'] + ['proj-find-work']))

# qq-bot：bash + .mjs 粘 Docker/systemd 的运维仓库。js 是 SnowCatQQ/SnowLuma 等 vendor 检出里的 tsconfig 误判，
# 既没有自己的前端也没有 .NET 测试，UI/设计技能同样不适用——只给 core（2026-11-16 用户要求「正确且合适」）。
# 2026-11-17 并入 find-work：真实路径 + 两个历史软链路径都要写（selectionOf 是精确字符串匹配）
for _qq in ('/home/sx/projects/find-work/qq-bot', '/mnt/Video2/qq-bot', '/home/sx/projects/qq-bot'):
    projects[_qq] = ['core']

# Plugins：/mnt/Video2/Plugins 是 Unity 第三方插件与删包留档（4120 个 .cs、105 个 asmdef、9269 个 .meta，没有
# ProjectSettings / csproj / package.json，既不是 Unity 工程也编译不了），只能读不能构建：unity 那套 dotnet-CLI
# 技能与 unity-mcp 都用不上，UI/设计技能同样不适用——只给 core（2026-11-16 用户要求「正确且合适」）。
projects['/mnt/Video2/Plugins'] = ['core']

# captcha-solver：FastAPI + cloakbrowser 的验证码求解服务，纯 Python、无前端无 UI；设计/品牌技能不适用，
# .NET 的 testing/test-audit 同样不适用——只给 core（2026-11-16 用户要求「正确且合适」）。
projects['/mnt/Video2/captcha-solver'] = ['core']

# 3dtiles：Rust（src-tree，cargo）+ C++ 的 3D Tiles 切片流水线，加上 .NET 离线瓦片服务（tile-server）和 UE 工程（ue/OfflineTiles）。
# 2026-11-16 曾因 src-tree/vs/vs.sln 被 *.sln 误判而只给 core；2026-11-17 用户要求「虚幻、js、子 agent 都打开」——主目录给 core+unreal+js+WFD；
# testing/test-audit 仍然不要（tile-server 没有测试工程，那套 .sln 误判的教训还在），UI/设计技能同样不适用。
projects['/home/sx/projects/3dtiles'] = ['core', 'unreal', 'js'] + WFD
# 源码目录单独开会话时也要有工具（未列入 projects 的路径三样都不给），只给 core。
projects['/home/sx/projects/3dtiles/src-tree'] = ['core']

# _from-system：从 Windows 机器搬来的中转目录——图集目录（967MB 图片）+ 脚本生成的 index.html，加一套 UE 5.8 的
# PowerShell 构建脚本/日志和一个 2KB 的 .uproject 空壳（无 Source/Content，本机也没有 pwsh）。unreal/testing 全是
# *.uproject 误判，页面由 build-index.ps1 生成、不手写样式——只给 core（2026-11-16 用户要求「正确且合适」）。
projects['/mnt/Video2/_from-system'] = ['core']

# plugins：Unity 插件源码库（unity-pkgs 各包源码 + CoplayDev/unity-mcp 检出 + 购买的 .unitypackage）。probe 只探到
# UniTask.NetCore.sln（Unity 包的 asmdef 不是 csproj，唯一的 Unity 工程 NaughtyAttributes 在 maxdepth 5 外），
# dotnet-build/testing/test-audit 全是 *.sln 误判；dotnet 那套 Blazor/MAUI/迁移技能在这里同样是噪音（源码不可构建，
# 只有 unity-mcp/Server 的 pytest）。要的是 unity 三件 csharp 技能 + unity MCP（本机有 6000.7.0b5）——只给 core + unity
# （2026-11-16 用户要求「正确且合适」）。
projects['/home/sx/projects/plugins'] = ['core', 'unity']

# KO2：UE6 源码引擎（/home/sx/projects/unrealengine/ue6）上的 C++ 游戏工程，*.uproject 探测是对的。
# testing/test-audit 来自 3 个 UBT 的 *.Build.cs/*.Target.cs——这是 UnrealBuildTool 的 C# 定义，不是 .NET 工程，也没有测试；
# 设计/品牌是 web 视觉技能，UMG/Slate 界面由 unreal-umg-*/ue-ui-umg-slate 覆盖——只给 core + unreal
# （2026-11-16 用户要求「正确且合适」）。
projects['/mnt/Video2/KO2'] = ['core','unreal']

# jami：C++/Qt（界面是 QML）+ CMake 的 Jami 客户端，走 gerrit 评审、cqfd（docker 镜像 ci-client-qt）跑测试，
# 架构与编码/git 规则写在仓库自带的 jami-client-qt/AGENTS.md 与 .agents/topics/ 里；Tailwind/shadcn 那套 web 设计技能、
# 品牌物料技能都不适用（QML 不是 web UI，且仓库自带 clang-format/qmlformat 规则）——只给 core。
# 真实仓库在父目录下（jami-client-qt 与 jami-patches 两个 git 仓），会话直接开在仓库里时同样只给 core，
# 否则那里一个工具都没有（2026-11-16 用户要求「正确且合适」）。
for repo in ('/mnt/Video2/jami', '/mnt/Video2/jami/jami-client-qt', '/mnt/Video2/jami/jami-patches'):
    projects[repo] = ['core']

# 待整理：文档/资料堆（docx/pdf/xlsx/csv、扫描件、会议录音与视频转录、旧 Windows 桌面导出），既没有代码也没有 UI。
# 要的是 PDF 阅读、扫描件 OCR、会议纪要、批量归档与媒体转换；office/docx/pptx/xlsx 是 harness 自带技能，本来就加载得到，不必列。
# web 设计（Tailwind/shadcn）与品牌物料对本目录不适用，universal 那两条不挂——给 core + docs（2026-11-16 用户要求「正确且合适」）。
projects['/mnt/Video2/待整理'] = ['core','docs']

# 任务台管理器会话的控制台目录（ADR-0014）：不加这条，管理器会话一个工具都没有。
for home in ('/home/sx/.dsh', '/home/sx/.dsh-dev'):
    projects[home + '/task-manager/console'] = ['task-console']
    # 执行会话住这里（拿到 core 全套工具），项目路径由简报给出、用 bash 进 worktree 干活。
    projects[home + '/task-manager/exec'] = ['core', 'task-exec']


def q(s): return json.dumps(s, ensure_ascii=False)
out = io.StringIO()
out.write('# 技能 / MCP / 工具 的按项目选择。未列入此处的项目 = 空选择 = 不加载任何技能与 MCP，且一个工具都不允许。\n')
out.write('# 依据 ~/.dsh/storages/workspace.json 的 24 个工作区 + 各自工程标记（*.uproject / ProjectSettings / *.sln|csproj / package.json）。\n')
out.write('# selectionOf() 是精确字符串匹配：同一项目既有软链键又有真实路径键时，两套都要写。\n')
out.write('# tools 是白名单 glob：一条都不匹配的工具被屏蔽；MCP 工具也可由其 server（mcp 字段）放行。\n')
out.write('# /mnt/Video2/empty 故意不列：它是「什么都不给」的验证工作区。\n\n')
out.write('configs:\n')
for name, body in configs.items():
    out.write('  %s:\n' % name)
    for key in ('skills','mcp','tools'):
        vals = body[key]
        out.write('    %s:' % key + (' []\n' if not vals else '\n'))
        for s in vals:
            out.write('      - %s\n' % q(s))
out.write('projects:\n')
for p, sel in projects.items():
    out.write('  %s:\n' % q(p))
    for s in sel:
        out.write('    - %s\n' % q(s))

for path in ('/home/sx/.dsh/agent-configs.yaml', '/home/sx/.dsh-dev/agent-configs.yaml'):
    open(path,'w',encoding='utf-8').write(out.getvalue())
print('wrote both homes;', len(configs), 'configs;', len(projects), 'project keys;', len(out.getvalue()), 'chars')
for t,p,e,s in sorted(report):
    print('%-18s %s %-42s %s' % (t[:18], 'ok  ' if e else 'MISS', p, s))

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
  'wf-plan': {'skills': ['grill-with-docs','grilling','writing-plans','make-feature-plan','to-spec','feature-inventory-docs-first','to-questionnaire','to-tickets'], 'mcp': [], 'tools': WF_TOOLS},
  'wf-build': {'skills': ['execute-feature-plan','executing-plans','subagent-driven-development','tdd','tdd-write-feature','implement-spec','add-software-feature','init-feature-dev','prototype','tdd-fanout','fix-feature-issues','dispatching-parallel-agents','optimize-feature-code'], 'mcp': [], 'tools': WF_TOOLS},
  'wf-verify': {'skills': ['verification-before-completion','code-review','review-feature-code','requesting-code-review','test-gap-analysis','receiving-code-review','write-manual-test-doc','diagnosing-bugs','diagnosing-superpowers'], 'mcp': [], 'tools': WF_TOOLS},
  'wf-ship': {'skills': ['finishing-a-development-branch','summarize-feature-work','solidify-feature-lessons','retro','write-feature-docs','cleanup-worktrees','setup-pre-commit','pr','dev-docs'], 'mcp': [], 'tools': WF_TOOLS},
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
    coding = title in ('MyAI','find-work','ps-tool','System','PsShowcase','PsShowcaseWeb','vr-quiz','ue5.8','unrealengine','hgame')
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

# 用户要求（2026-11-15）：UI 设计与设计品牌对每个项目都生效。
UNIVERSAL = ['ui-design', 'design-brand']
# 例外：/mnt/Video2/aur 是 AUR 打包工作区（只有 PKGBUILD），设计技能不适用（2026-11-16）。
NO_UNIVERSAL = {'/mnt/Video2/aur'}
for key, sel in projects.items():
    if key in NO_UNIVERSAL:
        continue
    projects[key] = list(dict.fromkeys(UNIVERSAL + sel))
# find-work 自己的四个技能只在这个项目里可见。
if '/home/sx/projects/find-work' in projects:
    projects['/home/sx/projects/find-work'] = list(dict.fromkeys(
        projects['/home/sx/projects/find-work'] + ['proj-find-work']))

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
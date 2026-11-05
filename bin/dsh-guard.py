#!/usr/bin/env python3
"""dsh-guard — read-only watcher for DSH sessions that break this machine's rules.

Rules come from ~/.dsh/AGENTS.md plus the 2026-11-05 bootstrap change:
productions checkout is read-only, never restart dsh-web or the desktop session
unprompted, no pkill -f, skills stay symlinks, secrets never enter git, the
[MODE: SANDBOX] block is never followed or committed, and the niri package is gone
(session = local unit + fork build).

Every run reads only new transcript records (session.v4.jsonl.zstd), extracts the
commands and file paths each session passes to tools, matches a small rule table and
appends hits to ~/.dsh/guard/findings.jsonl. It also snapshots host state
(dsh-web / niri / waybar / package / sockets) and reports drift. It never writes to a
session and never kills anything.

Usage:
  dsh-guard.py scan            # incremental; what dsh-guard.timer runs
  dsh-guard.py report [-m 180] # findings in the last N minutes
  dsh-guard.py status          # host state + active sessions
"""

import json, os, re, subprocess, sys, time, glob

HOME = os.path.expanduser('~')
ROOT = os.path.join(HOME, '.dsh', 'guard')
STATE = os.path.join(ROOT, 'state.json')
FINDINGS = os.path.join(ROOT, 'findings.jsonl')
HOMES = [os.path.join(HOME, '.dsh'), os.path.join(HOME, '.dsh-dev')]
PROD_DSH = os.path.join(HOME, 'projects', 'MyAI', 'deepseek-harness')
BT = chr(96)

SEV_ORDER = {'critical': 0, 'high': 1, 'med': 2, 'low': 3}

RULES = [
    ('prod-git-write', 'critical',
     r'(?:cd\s+\S*deepseek-harness(?!-dev)\b|deepseek-harness/)[^\n]{0,140}\bgit\s+(cherry-pick|commit|add|checkout|push|reset|stash|rebase|tag)\b|\bmerge\b(?!-base)'
     r'|\bgit\s+(cherry-pick|commit|add|checkout|push|reset|stash|rebase|tag)\b|\bmerge\b(?!-base)'
     r'[^\n]{0,140}(?:deepseek-harness/|cd\s+\S*deepseek-harness(?!-dev)\b)'),
    ('prod-build', 'critical',
     r'deepseek-harness(?!-dev)[^\n]{0,120}\b(pnpm|npm|yarn|npx)\s+(run\s+)?(build|install|i\b|test|vitest|lint|typecheck|pack)\b'),
    ('dsh-web-restart', 'critical',
     r'systemctl\s+--user\s+(restart|stop|start|disable|mask)\s+dsh-web'),
    ('desktop-restart', 'critical',
     r'systemctl\s+--user\s+(restart|stop|disable|mask)\s+(niri|waybar|graphical-session)'),
    ('session-kill', 'high',
     r'(pkill|killall)[^\n]{0,40}\b(niri|waybar|xwayland-satellite|Helium|helium)\b'),
    ('pkill-f', 'med', r'\bpkill\s+-f\b'),
    ('kill-all', 'critical', r'\bkill\s+-9\s+-1\b|\bkillall5\b'),
    ('removed-niri-bin', 'low', r'(?<![\w/])/usr/bin/niri(?![\w-])'),
    ('niri-package', 'high', r'\bpacman\s+-[SRU][^\n]{0,100}\bniri\b'),
    ('hyprctl', 'low', r'\bhyprctl\b'),
    ('skill-dir-write', 'med',
     r'(?:cp|mv|rm|install|ln)\s+[^\n]{0,140}\.dsh(-dev)?/skills/'),
    ('secrets', 'high',
     r'\.dsh(-dev)?/\.credentials\.yaml|\.dsh(-dev)?/\.env\b|git\s+add[^\n]{0,80}(credentials|\.env)'),
    ('sandbox-block', 'med', r'(?:git\s+(?:add|commit)[^\n]{0,160}MODE: SANDBOX|MODE: SANDBOX[^\n]{0,160}git\s+(?:add|commit))'),
]

CMD_RE = re.compile(r'command\s*:\s*(?:"((?:[^"\\]|\\.)*)"|' + BT + r'([^' + BT + r']*)' + BT + r')', re.S)
PATH_RE = re.compile(r'(?:file_path|path)\s*:\s*"([^"]{2,400})"')
EDIT_TOOLS = {'edit', 'write', 'multiedit', 'apply_patch'}


def unescape(s):
    return s.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')


def extract(call_name, args_raw):
    commands, paths = [], []
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
    except Exception:
        args = {}
    if isinstance(args, dict):
        if isinstance(args.get('command'), str):
            commands.append(args['command'])
        code = args.get('code')
        if isinstance(code, str):
            for m in CMD_RE.finditer(code):
                commands.append(unescape(m.group(1) if m.group(1) is not None else m.group(2)))
            for m in PATH_RE.finditer(code):
                paths.append(m.group(1))
        for key in ('file_path', 'path'):
            v = args.get(key)
            if isinstance(v, str):
                paths.append(v)
    return commands, paths


def iter_transcript(path, after_seq=0, since=0.0):
    """Stream one transcript record by record (bounded memory), skipping seq <= after_seq."""
    try:
        proc = subprocess.Popen(['zstdcat', path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return
    try:
        for raw in proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if rec.get('seq', 0) <= after_seq:
                continue
            if since and rec.get('time', 0) / 1000.0 < since:
                continue
            yield rec
    finally:
        try:
            proc.stdout.close()
            proc.kill()
        except Exception:
            pass


def scan_transcript(path, after_seq=0, since=0.0):
    return list(iter_transcript(path, after_seq, since))


def transcript_files():
    seen = []
    for home in HOMES:
        for path in glob.glob(home + '/sessions/*/session-*/session.v4.jsonl.zstd'):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if time.time() - mtime > 86400:
                continue
            seen.append((mtime, path))
    seen.sort(reverse=True)
    return [p for _, p in seen]


def session_ids(path):
    ws = path.split('/sessions/')[1].split('/')[0]
    sid = path.split('/session-')[1].split('/')[0]
    home = 'dev' if path.startswith(os.path.join(HOME, '.dsh-dev')) else 'prod'
    return home, ws, sid


def check_record(rec, path):
    if rec.get('type') != 'tool/call':
        return []
    d = rec.get('data') or {}
    name = d.get('name') or ''
    home, ws, sid = session_ids(path)
    commands, paths = extract(name, d.get('arguments') or '')
    hits = []
    for cmd in commands:
        if re.search(r'\b(grep|rg|ls|cat|readlink)\b', cmd) and '/usr/bin/niri' in cmd:
            cmd = cmd.replace('/usr/bin/niri', 'NIRI-README-MENTION')
        for rule, sev, rx in RULES:
            m = re.search(rx, cmd)
            if m:
                hits.append((rule, sev, cmd[max(0, m.start() - 60):m.end() + 60].replace('\n', ' ')))
    for p in paths:
        if p == PROD_DSH or p.startswith(PROD_DSH + '/') or (PROD_DSH + '/') in p:
            if '-dev' not in p:
                hits.append(('prod-file-write', 'critical', '%s -> %s' % (name, p)))
        if re.search(r'\.dsh(-dev)?/skills/', p):
            hits.append(('skill-dir-write', 'med', '%s -> %s' % (name, p)))
    return [dict(rule=r, sev=s, detail=det, name=name, home=home, ws=ws, sid=sid[:8],
                 t=rec.get('time', 0) / 1000.0) for r, s, det in hits]


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {'files': {}, 'host': {}}


def save_state(state):
    os.makedirs(ROOT, exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, STATE)


def host_snapshot():
    snap = {}
    for unit in ('dsh-web.service', 'dsh-web-dev.service', 'niri.service', 'waybar.service'):
        try:
            out = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'ActiveState',
                                  '-p', 'MainPID', '-p', 'ActiveEnterTimestamp'],
                                 capture_output=True, text=True, timeout=15).stdout
        except Exception:
            out = ''
        props = dict(l.split('=', 1) for l in out.splitlines() if '=' in l)
        snap[unit] = {'state': props.get('ActiveState', ''), 'pid': props.get('MainPID', ''),
                      'since': props.get('ActiveEnterTimestamp', '')}
    try:
        snap['waybar_instances'] = int(subprocess.run(['pgrep', '-c', '-x', 'waybar'],
                                                      capture_output=True, text=True).stdout.strip() or 0)
    except Exception:
        snap['waybar_instances'] = -1
    snap['niri_sockets'] = len(glob.glob('/run/user/1000/niri.wayland-*.sock'))
    snap['niri_pkg'] = subprocess.run(['pacman', '-Q', 'niri'], capture_output=True).returncode == 0
    snap['usr_bin_niri'] = os.path.exists('/usr/bin/niri')
    return snap


def host_findings(prev, cur, now):
    out = []

    def add(rule, sev, detail):
        out.append(dict(rule=rule, sev=sev, detail=detail, name='host', home='-', ws='-', sid='-', t=now))

    if prev:
        for unit in ('dsh-web.service', 'niri.service'):
            p, c = prev.get(unit) or {}, cur.get(unit) or {}
            if p.get('pid') and c.get('pid') != p.get('pid'):
                add('host-%s-restarted' % unit.split('.')[0], 'critical',
                    'pid %s -> %s (%s)' % (p.get('pid'), c.get('pid'), c.get('state')))
            elif p.get('state') == 'active' and c.get('state') != 'active':
                add('host-%s-down' % unit.split('.')[0], 'critical',
                    'state %s -> %s' % (p.get('state'), c.get('state')))
    if cur.get('waybar_instances', 1) > 1:
        add('host-waybar-duplicate', 'med', 'waybar instances = %s (expected 1)' % cur['waybar_instances'])
    if cur.get('niri_sockets', 1) > 1:
        add('host-niri-multi-session', 'high', 'niri sockets = %s' % cur['niri_sockets'])
    if cur.get('niri_pkg'):
        add('host-niri-package-returned', 'high', 'pacman -Q niri succeeded again')
    if cur.get('usr_bin_niri'):
        add('host-usr-bin-niri', 'med', '/usr/bin/niri exists again')
    return out


def append_findings(items):
    if not items:
        return 0
    os.makedirs(ROOT, exist_ok=True)
    with open(FINDINGS, 'a') as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + '\n')
    return len(items)


def notify(items):
    seen = {}
    for it in items:
        if it['sev'] not in ('critical', 'high'):
            continue
        key = it['rule'] + it['sid']
        if key in seen:
            continue
        seen[key] = 1
        body = '%s [%s/%s] %s' % (it['rule'], it['home'], it['sid'], (it['detail'] or '')[:160])
        try:
            subprocess.run(['notify-send', '-a', 'dsh-guard', '-u', 'critical',
                            'DSH 会话越界: ' + it['sev'], body], timeout=10)
        except Exception:
            pass


def cmd_scan(args):
    state = load_state()
    files = state.setdefault('files', {})
    now = time.time()
    new, scanned = [], 0
    for path in transcript_files():
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        known = files.get(path)
        if known is None:
            # first sight: remember where we started instead of replaying history
            files[path] = {'seq': -1, 'mtime': mtime, 'since': now}
            continue
        if known.get('mtime') == mtime:
            continue
        after = known.get('seq', -1)
        since = known.get('since', 0) if after < 0 else 0.0
        recs = scan_transcript(path, after, since)
        scanned += 1
        for rec in recs:
            new.extend(check_record(rec, path))
            known['seq'] = max(known.get('seq', 0), rec.get('seq', 0))
        known['mtime'] = mtime
    cur = host_snapshot()
    new.extend(host_findings(state.get('host') or {}, cur, now))
    state['host'] = cur
    save_state(state)
    append_findings(new)
    if new:
        notify(new)
    if not args.get('quiet'):
        for it in sorted(new, key=lambda i: (SEV_ORDER.get(i['sev'], 9), -i['t'])):
            print('%s %-8s %-22s %s/%s %s' % (time.strftime('%H:%M:%S', time.localtime(it['t'])),
                                              it['sev'], it['rule'], it['home'], it['sid'],
                                              (it['detail'] or '')[:200]))
        print('findings: %d (sessions scanned: %d)' % (len(new), scanned))
    return 0


def load_findings_file():
    out = []
    try:
        with open(FINDINGS) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return out


def cmd_since(args):
    """Read-only sweep over the last N minutes; does not touch state or findings."""
    minutes = float(args.get('minutes', 180))
    cutoff = time.time() - minutes * 60
    items = []
    for path in transcript_files():
        try:
            if os.path.getmtime(path) < cutoff:
                continue
        except OSError:
            continue
        for rec in scan_transcript(path, 0):
            if (rec.get('time', 0) / 1000.0) < cutoff:
                continue
            items.extend(check_record(rec, path))
    items.sort(key=lambda i: (SEV_ORDER.get(i['sev'], 9), -i['t']))
    if not items:
        print('no rule hits in the last %.0f minutes' % minutes)
    for it in items:
        print('%s %-8s %-22s %-4s %-26s %s %s' % (
            time.strftime('%m-%d %H:%M:%S', time.localtime(it['t'])), it['sev'], it['rule'],
            it['home'], it['ws'][:26], it['sid'], (it['detail'] or '').replace(chr(10), ' ')[:200]))
    print('--- total %d hits in the last %.0f min' % (len(items), minutes))
    return 0


def cmd_report(args):
    minutes = float(args.get('minutes', 180))
    cutoff = time.time() - minutes * 60
    items = [i for i in load_findings_file() if i['t'] >= cutoff]
    items.sort(key=lambda i: (SEV_ORDER.get(i['sev'], 9), -i['t']))
    if not items:
        print('no findings in the last %.0f minutes' % minutes)
    for it in items:
        print('%s %-8s %-22s %-4s %-26s %s %s' % (
            time.strftime('%m-%d %H:%M:%S', time.localtime(it['t'])), it['sev'], it['rule'],
            it['home'], it['ws'][:26], it['sid'], (it['detail'] or '').replace('\n', ' ')[:200]))
    print('--- total %d findings (last %.0f min)' % (len(items), minutes))
    return 0


def cmd_status(args):
    cur = host_snapshot()
    for unit, v in cur.items():
        if isinstance(v, dict):
            print('%-20s %-8s pid=%-8s since=%s' % (unit, v['state'], v['pid'], v['since']))
    print('%-20s %s' % ('waybar instances', cur['waybar_instances']))
    print('%-20s %s' % ('niri sockets', cur['niri_sockets']))
    print('%-20s %s' % ('niri package installed', cur['niri_pkg']))
    print('%-20s %s' % ('/usr/bin/niri exists', cur['usr_bin_niri']))
    now = time.time()
    active = []
    for path in transcript_files():
        try:
            if now - os.path.getmtime(path) > 300:
                continue
        except OSError:
            continue
        active.append(path)
    print('active sessions (mtime < 5 min): %d' % len(active))
    for p in active:
        home, ws, sid = session_ids(p)
        print('  %s/%s %s' % (home, sid[:8], ws))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else 'scan'
    args = {}
    for i, a in enumerate(argv):
        if a in ('-m', '--minutes') and i + 1 < len(argv):
            args['minutes'] = argv[i + 1]
        if a in ('-q', '--quiet'):
            args['quiet'] = True
    if cmd == 'since':
        return cmd_since(args)
    if cmd == 'report':
        return cmd_report(args)
    if cmd == 'status':
        return cmd_status(args)
    return cmd_scan(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""dsh-desktops.py -- 发现并盯着"其他桌面"：agent 在嵌套环境里跑的 Xvfb+niri 桌面。

为什么要它：agent 干活默认在嵌套环境里（Xvfb 父显示 → niri → xwayland-satellite），
那里跑的程序在人的屏幕上完全看不到。这个工具每分钟给每个这样的桌面截一张图、
列出窗口、抓每个窗口的图，并支持定向送键鼠（接手）。

发现方式：扫 /proc 里 XDG_RUNTIME_DIR 不是 /run/user/1000 的 niri 实例；
顺带认出没被任何 niri 拿走的裸 Xvfb 桌面。

  dsh-desktops.py discover                     # 现在有哪些其他桌面
  dsh-desktops.py snapshot [-q]                # 采集一次（timer 调用）
  dsh-desktops.py windows <key>                # 某个桌面的窗口
  dsh-desktops.py action <key> focus-window --window N
  dsh-desktops.py action <key> type --text 你好
  dsh-desktops.py action <key> key --key Return
  dsh-desktops.py action <key> click --x 640 --y 400
  dsh-desktops.py prune

只读采集；只有 action 子命令会往那个桌面里送输入（人在页面上点的）。
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

HOME = os.path.expanduser('~')
DSH = os.path.join(HOME, '.dsh')
WATCH = os.path.join(DSH, 'watch')
ROOT = os.path.join(WATCH, 'desktops')
INDEX = os.path.join(WATCH, 'desktops.json')
EVENTS = os.path.join(WATCH, 'desktop-events.jsonl')
STATE = os.path.join(WATCH, 'desktop-state.json')
PROD_RUNTIME = '/run/user/%d' % os.getuid()
NIRI = shutil.which('niri') or '/usr/local/bin/niri'
GRIM = shutil.which('grim') or '/usr/bin/grim'
MAGICK = shutil.which('magick') or '/usr/bin/magick'
XDOTOOL = shutil.which('xdotool') or '/usr/bin/xdotool'
SCOPED_SHOT = os.path.join(HOME, 'projects', 'agent-seat-probe', 'target', 'debug', 'scoped-shot')

RETAIN_HOURS = 24.0
MAX_BYTES = 1024 * 1024 * 1024
SHOT_SCALE = '0.5'
SHOT_QUALITY = '70'
MAX_WINDOWS = 16
JSONL_MAX = 8 * 1024 * 1024
EVENTS_KEEP = 400


def now_ts():
    return time.time()


def stamp(ts=None, fmt='%Y-%m-%dT%H:%M:%S'):
    return datetime.fromtimestamp(ts if ts is not None else now_ts()).strftime(fmt)


def ensure_dirs():
    os.makedirs(ROOT, exist_ok=True)


def read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def append_jsonl(path, obj):
    try:
        if os.path.exists(path) and os.path.getsize(path) > JSONL_MAX:
            os.replace(path, path + '.1')
    except OSError:
        pass
    try:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + '\n')
    except OSError:
        pass


def proc_environ(pid):
    try:
        with open('/proc/%s/environ' % pid, 'rb') as fh:
            raw = fh.read()
    except OSError:
        return {}
    env = {}
    for item in raw.split(b'\0'):
        if b'=' in item:
            k, v = item.split(b'=', 1)
            env[k.decode('utf-8', 'replace')] = v.decode('utf-8', 'replace')
    return env


def proc_cmdline(pid):
    try:
        with open('/proc/%s/cmdline' % pid, 'rb') as fh:
            return [x.decode('utf-8', 'replace') for x in fh.read().split(b'\0') if x]
    except OSError:
        return []


def run(argv, env=None, timeout=20):
    try:
        res = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, '', str(exc)


def niri_env(desk):
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin',
           'XDG_RUNTIME_DIR': desk.get('runtime') or PROD_RUNTIME,
           'HOME': HOME}
    if desk.get('niri_socket'):
        env['NIRI_SOCKET'] = desk['niri_socket']
    if desk.get('wayland'):
        env['WAYLAND_DISPLAY'] = desk['wayland']
    return env


def niri_json(desk, *args):
    code, out, err = run([NIRI, 'msg', '-j', *args], env=niri_env(desk), timeout=10)
    if code != 0:
        return None, (err or out).strip()[:200]
    try:
        return json.loads(out), None
    except ValueError:
        return None, 'unparsable niri json'


def desktop_key(kind, ident):
    return '%s-%s' % (kind, ident)


def discover():
    """扫 /proc 找"别的桌面"。返回 list[dict]。"""
    found = {}
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        argv = proc_cmdline(entry)
        if not argv:
            continue
        exe = os.path.basename(argv[0])
        if exe not in ('niri', 'Xvfb'):
            continue
        env = proc_environ(entry)
        rt = env.get('XDG_RUNTIME_DIR')
        if exe == 'niri':
            if not rt or os.path.normpath(rt) == os.path.normpath(PROD_RUNTIME):
                continue                      # 生产桌面，不算"其他桌面"
            socket = env.get('NIRI_SOCKET')
            if not socket:
                cands = sorted(glob.glob(os.path.join(rt, 'niri.*.sock')))
                socket = cands[0] if cands else None
            config = ''
            for i, a in enumerate(argv):
                if a == '-c' and i + 1 < len(argv):
                    config = argv[i + 1]
            wayland = env.get('WAYLAND_DISPLAY')
            if not wayland:
                # 合成器自己的进程里没有 WAYLAND_DISPLAY；socket 名要从 runtime 目录里认。
                for cand in sorted(glob.glob(os.path.join(rt, 'wayland-*'))):
                    name = os.path.basename(cand)
                    if name.endswith('.lock'):
                        continue
                    wayland = name
                    break
            desk = {
                'key': desktop_key('niri', entry),
                'kind': 'niri',
                'pid': int(entry),
                'runtime': rt,
                'wayland': wayland,
                'niri_socket': socket,
                'x_display': env.get('DISPLAY'),
                'config': config,
                'label': os.path.basename(os.path.dirname(config)) if config else 'niri',
            }
            if not desk['niri_socket']:
                continue
            ver, _err = niri_json(desk, 'version')
            if ver is None:
                continue                      # 进程在但 IPC 不通（启动中/已坏）
            desk['version'] = ver.get('compositor') if isinstance(ver, dict) else str(ver)
            found[desk['key']] = desk
    return sorted(found.values(), key=lambda d: (d['kind'], d['label'], d['key']))


def desktop_paths(desk):
    base = os.path.join(ROOT, desk['key'])
    return base, os.path.join(base, 'shots'), os.path.join(base, 'winshots')


def capture_shot(desk, ts):
    base, shots_dir, _ = desktop_paths(desk)
    d = os.path.join(shots_dir, stamp(ts, '%Y%m%d'))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as exc:
        return None, 0, str(exc)
    path = os.path.join(d, stamp(ts, '%H%M%S') + '.jpg')
    if os.path.exists(path):
        path = os.path.join(d, stamp(ts, '%H%M%S-%f') + '.jpg')
    if desk['kind'] == 'niri':
        env = niri_env(desk)
        env['HOME'] = HOME
        code, out, err = run([GRIM, '-s', SHOT_SCALE, '-t', 'jpeg', '-q', SHOT_QUALITY, path],
                             env=env, timeout=30)
    else:
        code, out, err = run([MAGICK, 'import', '-display', desk['display'], '-window', 'root',
                              '-resize', '50%', '-quality', SHOT_QUALITY, path],
                             env={'PATH': '/usr/bin:/bin', 'HOME': HOME}, timeout=30)
    if code != 0 or not os.path.exists(path):
        return None, 0, (err or out or 'capture failed').strip()[:200]
    size = os.path.getsize(path)
    latest = os.path.join(base, 'latest.jpg')
    try:
        if os.path.islink(latest) or os.path.exists(latest):
            os.unlink(latest)
        os.symlink(path, latest)
    except OSError:
        pass
    return os.path.relpath(path, WATCH), size, None


def nested_windows(desk):
    """嵌套 niri 的窗口列表 + 每个窗口的截图。"""
    windows, err = niri_json(desk, 'windows')
    if windows is None:
        return [], err
    workspaces, _ = niri_json(desk, 'workspaces')
    ws_by_id = {w.get('id'): w for w in (workspaces or [])}
    rows = []
    for w in windows[:MAX_WINDOWS]:
        ws = ws_by_id.get(w.get('workspace_id')) or {}
        layout = w.get('layout') or {}
        rows.append({
            'id': w.get('id'), 'title': w.get('title'), 'app_id': w.get('app_id'),
            'pid': w.get('pid'), 'workspace_id': w.get('workspace_id'),
            'workspace_idx': ws.get('idx'), 'is_focused': w.get('is_focused'),
            'is_floating': w.get('is_floating'), 'is_urgent': w.get('is_urgent'),
            'tile_size': layout.get('tile_size'), 'window_size': layout.get('window_size'),
        })
    return rows, None


def x11_windows(desk):
    env = {'DISPLAY': desk['display'], 'PATH': '/usr/bin:/bin'}
    code, out, err = run([XDOTOOL, 'search', '--onlyvisible', '--name', ''], env=env, timeout=10)
    if code != 0:
        return [], (err or out).strip()[:200]
    rows = []
    for wid in out.split()[:MAX_WINDOWS]:
        code, name, _ = run([XDOTOOL, 'getwindowname', wid], env=env, timeout=5)
        code2, geom, _ = run([XDOTOOL, 'getwindowgeometry', '--shell', wid], env=env, timeout=5)
        meta = {}
        for line in (geom or '').splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                meta[k.strip()] = v.strip()
        rows.append({'id': int(wid), 'title': (name or '').strip(), 'app_id': 'x11',
                     'x': meta.get('X'), 'y': meta.get('Y'),
                     'width': meta.get('WIDTH'), 'height': meta.get('HEIGHT')})
    return rows, None


def window_shots(desk, windows, ts):
    """niri 桌面用 scoped-shot 逐窗口抓图（别的工作区也抓得到，不动剪贴板）。"""
    out = {}
    if desk['kind'] != 'niri' or not windows or not os.path.exists(SCOPED_SHOT):
        return out
    base, _shots, win_dir = desktop_paths(desk)
    d = os.path.join(win_dir, stamp(ts, '%Y%m%d'))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return out
    env = niri_env(desk)
    env['HOME'] = HOME
    for w in windows:
        wid = w.get('id')
        if wid is None:
            continue
        png = os.path.join(d, '%s-%s.png' % (stamp(ts, '%H%M%S'), wid))
        jpg = os.path.join(d, '%s-%s.jpg' % (stamp(ts, '%H%M%S'), wid))
        code, out_s, err = run([SCOPED_SHOT, str(wid), png], env=env, timeout=20)
        if code != 0 or not os.path.exists(png):
            out[str(wid)] = {'error': (err or out_s or 'scoped-shot failed').strip()[:160]}
            continue
        code, _o, _e = run([MAGICK, png, '-resize', '50%', '-quality', SHOT_QUALITY, jpg],
                           timeout=20)
        ok = code == 0 and os.path.exists(jpg)
        if ok:
            try:
                os.unlink(png)
            except OSError:
                pass
            path = jpg
        else:
            path = png
        out[str(wid)] = {'path': os.path.relpath(path, WATCH), 'bytes': os.path.getsize(path)}
    return out


def diff_desktop(prev, cur, ts, key):
    events = []
    if not prev:
        return events
    p = {str(w.get('id')): w for w in prev.get('windows') or []}
    c = {str(w.get('id')): w for w in cur.get('windows') or []}
    for wid, w in c.items():
        if wid not in p:
            events.append({'ts': ts, 'desktop': key, 'kind': 'window-open', 'window': w})
    for wid, w in p.items():
        if wid not in c:
            events.append({'ts': ts, 'desktop': key, 'kind': 'window-close', 'window': w})
    for wid, w in c.items():
        old = p.get(wid)
        if old and (old.get('title') != w.get('title')):
            events.append({'ts': ts, 'desktop': key, 'kind': 'window-retitle', 'window': w,
                           'old_title': old.get('title')})
    pf, cf = prev.get('focused'), cur.get('focused')
    if (pf or {}).get('id') != (cf or {}).get('id'):
        events.append({'ts': ts, 'desktop': key, 'kind': 'focus-change',
                       'from': (pf or {}).get('title'), 'to': (cf or {}).get('title')})
    return events


def cmd_snapshot(args):
    quiet = args.get('quiet')
    ts = now_ts()
    ensure_dirs()
    prev_state = read_json(STATE, {}) or {}
    desktops = discover()
    state = {}
    events = []
    for desk in desktops:
        shot_rel, shot_bytes, shot_err = capture_shot(desk, ts)
        if desk['kind'] == 'niri':
            windows, werr = nested_windows(desk)
            workspaces, _ = niri_json(desk, 'workspaces')
        else:
            windows, werr = x11_windows(desk)
            workspaces = []
        shots = window_shots(desk, windows, ts)
        for w in windows:
            w['shot'] = shots.get(str(w.get('id')))
        focused = next((w for w in windows if w.get('is_focused')), None)
        desk.update({'shot': {'path': shot_rel, 'bytes': shot_bytes, 'error': shot_err},
                     'windows': windows, 'window_error': werr,
                     'workspaces': workspaces,
                     'focused': focused,
                     'at': stamp(ts), 'ts': ts})
        state[desk['key']] = {'windows': windows, 'focused': focused}
        events.extend(diff_desktop(prev_state.get(desk['key']), desk, ts, desk['key']))
    write_json(STATE, state)
    write_json(INDEX, {'generated_at': ts, 'at': stamp(ts), 'desktops': desktops,
                       'count': len(desktops)})
    for ev in events:
        append_jsonl(EVENTS, ev)
    removed, freed, total = prune()
    if not quiet:
        if not desktops:
            print('%s 没有发现其他桌面（嵌套环境没在跑）' % stamp(ts))
        for d in desktops:
            print('%s %-22s %-7s windows=%d %s %s' % (
                stamp(ts), d['label'], d['kind'], len(d.get('windows') or []),
                d['key'], (d.get('shot') or {}).get('error') or ''))
        print('events=%d pruned=%d freed=%.1fMB storage=%.1fMB'
              % (len(events), removed, freed / 1048576.0, total / 1048576.0))
    return 0


def cmd_discover(args):
    desktops = discover()
    if args.get('json'):
        print(json.dumps(desktops, ensure_ascii=False))
        return 0
    if not desktops:
        print('没有其他桌面在跑。起一个嵌套环境（environment.py）后这里会列出来。')
        return 0
    for d in desktops:
        print('%-22s %-6s pid=%-7s runtime=%s' % (d.get('label'), d['kind'], d.get('pid'),
                                                  d.get('runtime')))
        print('    key=%s wayland=%s niri=%s x=%s config=%s' % (
            d['key'], d.get('wayland'), d.get('niri_socket'), d.get('x_display'), d.get('config')))
    return 0


def find_desktop(key):
    desktops = discover()
    for d in desktops:
        if d['key'] == key:
            return d
    for d in desktops:
        if (d.get('label') or '') == key:
            return d
    hits = [d for d in desktops if (d.get('label') or '').startswith(key)]
    return hits[0] if len(hits) == 1 else None


def cmd_windows(args):
    desk = find_desktop(args['key'])
    if not desk:
        print('找不到桌面 %s（先 discover）' % args['key'])
        return 1
    windows, err = (nested_windows(desk) if desk['kind'] == 'niri' else x11_windows(desk))
    if err:
        print('错误: %s' % err)
        return 1
    if args.get('json'):
        print(json.dumps(windows, ensure_ascii=False))
        return 0
    for w in windows:
        print('  %s%-6s %-24s %s' % ('*' if w.get('is_focused') else ' ', w.get('id'),
                                     (w.get('app_id') or '')[:24], (w.get('title') or '')[:70]))
    return 0


def x_input(display, argv, timeout=20):
    env = {'DISPLAY': display, 'PATH': '/usr/bin:/bin', 'HOME': HOME}
    return run([XDOTOOL] + argv, env=env, timeout=timeout)


def focus_x_root(display):
    """把 X 焦点交给嵌套 niri 的窗口（裸 Xvfb 没有 WM，默认焦点常在 PointerRoot）。"""
    code, out, _err = x_input(display, ['search', '--onlyvisible', '--name', ''])
    best = None
    for wid in (out or '').split():
        code2, geom, _ = x_input(display, ['getwindowgeometry', '--shell', wid])
        meta = dict(line.split('=', 1) for line in (geom or '').splitlines() if '=' in line)
        try:
            area = int(meta.get('WIDTH', 0)) * int(meta.get('HEIGHT', 0))
        except ValueError:
            continue
        _c, name, _e = x_input(display, ['getwindowname', wid])
        name = (name or '').strip()
        # 裸 Xvfb 上 niri 自己那个窗口是有名字的；覆盖全屏的无名窗口不是它。
        rank = (1 if name else 0, area)
        if area and (best is None or rank > best[0]):
            best = (rank, wid)
    if best:
        x_input(display, ['windowfocus', best[1]])
        x_input(display, ['mousemove', '--sync', '--', '10', '10'])
    return best[1] if best else None


def cmd_action(args):
    key = args.get('target') or args.get('key')
    desk = find_desktop(key)
    if not desk:
        print('找不到桌面 %s' % (key,))
        return 1
    op = args.get('op')
    if op == 'focus-window' and desk['kind'] == 'niri':
        code, out, err = run([NIRI, 'msg', 'action', 'focus-window', '--id', str(args['window'])],
                             env=niri_env(desk), timeout=10)
        print(out.strip() or err.strip())
        return code
    if op == 'close-window' and desk['kind'] == 'niri':
        code, out, err = run([NIRI, 'msg', 'action', 'close-window', '--id', str(args['window'])],
                             env=niri_env(desk), timeout=10)
        print(out.strip() or err.strip())
        return code
    display = desk.get('x_display') or desk.get('display')
    if desk['kind'] == 'niri' and not display:
        print('这个桌面没有 X 父显示，送不了输入（只用 niri IPC 的 focus-window）')
        return 1
    if op in ('type', 'key', 'click'):
        focus_x_root(display)
    if op == 'type':
        code, out, err = x_input(display, ['type', '--delay', '25', '--', args.get('text') or ''])
    elif op == 'key':
        code, out, err = x_input(display, ['key', '--clearmodifiers', args.get('combo') or 'Return'])
    elif op == 'click':
        code, out, err = x_input(display, ['mousemove', '--sync', args.get('x') or '0',
                                           args.get('y') or '0', 'click', '1'])
    else:
        print('未知操作 %s' % (op,))
        return 2
    print((out or err or '').strip()[:300])
    return code


def prune():
    if not os.path.isdir(ROOT):
        return 0, 0, 0
    cutoff = now_ts() - RETAIN_HOURS * 3600
    files = []
    for root, _dirs, names in os.walk(ROOT):
        for name in names:
            if not name.endswith(('.jpg', '.png')):
                continue
            path = os.path.join(root, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, path))
    removed = freed = 0
    for mtime, size, path in files:
        if mtime < cutoff:
            try:
                os.unlink(path)
                removed += 1
                freed += size
            except OSError:
                pass
    total = sum(s for _m, s, p in files if os.path.exists(p))
    if total > MAX_BYTES:
        for mtime, size, path in sorted(files):
            if total <= MAX_BYTES:
                break
            if not os.path.exists(path):
                continue
            try:
                os.unlink(path)
                removed += 1
                freed += size
                total -= size
            except OSError:
                pass
    for root, _dirs, _names in os.walk(ROOT, topdown=False):
        if root == ROOT:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass
    return removed, freed, total


def cmd_prune(args):
    removed, freed, total = prune()
    print('删除 %d 张，释放 %.1f MB，剩余 %.1f MB' % (removed, freed / 1048576.0, total / 1048576.0))
    return 0


VALUE_FLAGS = ('window', 'x', 'y', 'text', 'combo')


def parse_args(rest, cmd):
    args = {}
    positional = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ('-q', '--quiet'):
            args['quiet'] = True
        elif a == '--json':
            args['json'] = True
        elif a.startswith('--'):
            name = a[2:]
            if name in VALUE_FLAGS and i + 1 < len(rest):
                args[name] = rest[i + 1]
                i += 1
            else:
                args[name] = True
        else:
            positional.append(a)
        i += 1
    if positional:
        if cmd == 'action':
            args['target'] = positional[0]
            if len(positional) > 1:
                args['op'] = positional[1]
        else:
            args['key'] = positional[0]
    return args


def main(argv):
    cmd = argv[1] if len(argv) > 1 else 'snapshot'
    args = parse_args(argv[2:], cmd)
    if cmd == 'discover':
        return cmd_discover(args)
    if cmd == 'windows':
        return cmd_windows(args) if args.get('key') else print('用法: dsh-desktops.py windows <key>') or 2
    if cmd == 'action':
        if not (args.get('target') and args.get('op')):
            print('用法: dsh-desktops.py action <桌面> '
                  'focus-window --window N | type --text 文本 | key --combo Return | click --x X --y Y')
            return 2
        return cmd_action(args)
    if cmd == 'prune':
        return cmd_prune(args)
    return cmd_snapshot(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))

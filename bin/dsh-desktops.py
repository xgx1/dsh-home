#!/usr/bin/env python3
"""dsh-desktops.py -- 发现并盯着"其他桌面"：agent 在嵌套环境里跑的 Xvfb+niri 桌面。

为什么要它：agent 干活默认在嵌套环境里（Xvfb 父显示 → niri → xwayland-satellite），
那里跑的程序在人的屏幕上完全看不到。这个工具每分钟给每个这样的桌面截一张图、
列出窗口、抓每个窗口的图，并支持定向送键鼠（接手）。

两类"别的桌面"：
  1) agent 自己的桌面：~/.dsh/agent-desktops/<key>/ 下由 agent-desktop.py 起的 niri
     （它们和人的桌面共用 /run/user/1000，所以不能靠 XDG_RUNTIME_DIR 区分，靠 config 路径）；
  2) 别的嵌套环境：XDG_RUNTIME_DIR 不是 /run/user/1000 的 niri（regression-visibility 那种）。

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
AGENT_DESK_ROOT = os.path.join(DSH, 'agent-desktops')
WATCH = os.path.join(DSH, 'watch')
ROOT = os.path.join(WATCH, 'desktops')
INDEX = os.path.join(WATCH, 'desktops.json')
EVENTS = os.path.join(WATCH, 'desktop-events.jsonl')
STATE = os.path.join(WATCH, 'desktop-state.json')
PROD_RUNTIME = '/run/user/%d' % os.getuid()
NIRI = shutil.which('niri') or '/usr/local/bin/niri'
GRIM = shutil.which('grim') or '/usr/bin/grim'
WL_COPY = shutil.which('wl-copy') or '/usr/bin/wl-copy'
MAGICK = shutil.which('magick') or '/usr/bin/magick'
XDOTOOL = shutil.which('xdotool') or '/usr/bin/xdotool'
PROBE_DIR = os.path.join(HOME, 'projects', 'agent-seat-probe', 'target', 'debug')
SCOPED_SHOT = os.path.join(PROBE_DIR, 'scoped-shot')
SCOPED_TARGET = os.path.join(PROBE_DIR, 'scoped-target')
PROBE = os.path.join(PROBE_DIR, 'agent-seat-probe')
WL_PASTE = shutil.which('wl-paste') or '/usr/bin/wl-paste'

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


def dsh_owned_pid(pid):
    """这个进程是不是 DSH 会话拉起来的（cgroup 落在 dsh-*.scope 里）。

    用来把"会话自己开的 Xvfb"和容器里的 Xvfb（docker-*.scope）分开——后者不属于任何人。
    """
    try:
        with open('/proc/%s/cgroup' % pid, 'r', encoding='utf-8', errors='replace') as fh:
            cg = fh.read()
    except OSError:
        return False
    return 'dsh-' in cg or 'app-' in cg


def run(argv, env=None, timeout=20, input_text=None):
    try:
        res = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout,
                             input=input_text)
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


def prod_niri_pid():
    try:
        out = subprocess.run(['systemctl', '--user', 'show', '-p', 'MainPID', '--value',
                              'niri.service'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ''
    out = out.strip()
    return int(out) if out.isdigit() and out != '0' else None


def prod_wayland_display():
    try:
        out = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ''
    for line in (out or '').splitlines():
        if line.startswith('WAYLAND_DISPLAY='):
            name = line.split('=', 1)[1].strip()
            if os.path.exists(os.path.join(PROD_RUNTIME, name)):
                return name
    for cand in sorted(glob.glob(os.path.join(PROD_RUNTIME, 'wayland-*'))):
        base = os.path.basename(cand)
        if not base.endswith('.lock'):
            return base
    return ''


def prod_niri_socket():
    try:
        out = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ''
    for line in (out or '').splitlines():
        if line.startswith('NIRI_SOCKET='):
            sock = line.split('=', 1)[1].strip()
            if os.path.exists(sock):
                return sock
    for sock in sorted(glob.glob(os.path.join(PROD_RUNTIME, 'niri.wayland-1.*.sock'))):
        pid = sock.rsplit('.', 2)[-2]
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            continue
        return sock
    return ''


def prod_env():
    """生产桌面（人的桌面）的环境：scoped 输入打到这里，但不碰人的焦点和指针。"""
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': HOME, 'XDG_RUNTIME_DIR': PROD_RUNTIME}
    wl = prod_wayland_display()
    if wl:
        env['WAYLAND_DISPLAY'] = wl
    sock = prod_niri_socket()
    if sock:
        env['NIRI_SOCKET'] = sock
    return env


def nested_output_size(desk):
    outputs, _err = niri_json(desk, 'outputs')
    for _name, out in (outputs or {}).items():
        logical = out.get('logical') or {}
        try:
            return int(logical['width']), int(logical['height'])
        except (KeyError, TypeError, ValueError):
            continue
    return 1920, 1080


def scoped_click(desk, x, y):
    """点 agent 桌面里的某个位置：fork 的 scoped 指针钉住在那个嵌套窗口上。

    人的指针和焦点一点也不动；坐标按千分数送给 niri，它按钉住的表面等比映射。
    """
    wid = desk.get('parent_window')
    if not wid or not os.path.exists(SCOPED_TARGET):
        return 1, '', '缺 parent_window 或 scoped-target（这个桌面要先重开）'
    env = prod_env()
    code, out, err = run([SCOPED_TARGET, str(wid)], env=env, timeout=10)
    if code != 0:
        return code, out, err
    width, height = nested_output_size(desk)
    nx = int(round(max(0.0, min(float(x), width)) * 1000.0 / max(1, width)))
    ny = int(round(max(0.0, min(float(y), height)) * 1000.0 / max(1, height)))
    return run([PROBE, 'agent-0', 'click', str(nx), str(ny)], env=env, timeout=15)


def scoped_pin(desk):
    """把生产 niri 的 agent 座位钉到这个 agent 桌面的窗口上（键盘焦点随客户端的 seat 走）。"""
    wid = desk.get('parent_window')
    if not wid or not os.path.exists(SCOPED_TARGET):
        return 1, '', '缺 parent_window 或 scoped-target（这个桌面要先重开）'
    return run([SCOPED_TARGET, str(wid)], env=prod_env(), timeout=10)


def probe_keys(desk, combo):
    """单键/组合键：走 agent 座位的虚拟键盘，只可能落到钉住的窗口，人的座位碰不到。

    不用 wtype：它按注册表顺序绑最后一个 seat（也就是 agent-0），能工作靠的是巧合，
    万一哪天绑到 seat0 就会把字打进人的窗口里。probe 只显式连 agent-0。
    """
    code, out, err = scoped_pin(desk)
    if code != 0:
        return code, out, err
    spec = (combo or 'Return').strip()
    if not spec:
        return 1, '', '空组合键'
    return run([PROBE, 'agent-0', 'keys', spec], env=prod_env(), timeout=20)


def clip_set(env, text):
    """把文本放进目标桌面自己的剪贴板。

    wl-copy 设完剪贴板会 fork 出常驻进程继续当 owner，用 subprocess.run 等它退出会
    一直等到超时，所以这里起进程、写完 stdin 就放手。
    """
    try:
        proc = subprocess.Popen([WL_COPY], env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        proc.stdin.write(text.encode())
        proc.stdin.close()
    except OSError as exc:
        return 1, '', str(exc)
    time.sleep(0.3)
    return 0, '', ''


def clipboard_paste(desk, text):
    """非 ASCII（中文等）：塞进嵌套桌面的剪贴板，再用 agent 座位按 Ctrl+V。

    probe 的 text 模式只带 US 布局；中文这类字符只能走剪贴板，而且剪贴板要放进
    嵌套合成器自己的 wl_display，客户端才读得到。
    """
    wayland = desk.get('wayland')
    if not wayland:
        return 1, '', '这个桌面没有 Wayland socket，没法粘贴'
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': HOME,
           'XDG_RUNTIME_DIR': desk.get('runtime') or PROD_RUNTIME,
           'WAYLAND_DISPLAY': wayland}
    code, out, err = clip_set(env, text)
    if code != 0:
        return code, out, err
    return probe_keys(desk, 'ctrl+v')


def probe_text(desk, text):
    """打字：ASCII 走 probe 的 text 模式，打不了的字符自动改走剪贴板粘贴。"""
    if not text:
        return 1, '', '空文本'
    code, out, err = scoped_pin(desk)
    if code != 0:
        return code, out, err
    code, out, err = run([PROBE, 'agent-0', 'text', text], env=prod_env(), timeout=40)
    if code == 0:
        return code, out, err
    pasted = clipboard_paste(desk, text)
    if pasted[0] == 0:
        return 0, (out or '') + (pasted[1] or '') + '（含非 ASCII，走剪贴板粘贴）', ''
    return code, (out or '') + (pasted[1] or ''), (err or '') + (pasted[2] or '')


def discover():
    """扫 /proc 找"别的桌面"：agent 自己的桌面（~/.dsh/agent-desktops/）与别的嵌套环境。"""
    found = {}
    prod_pid = prod_niri_pid()
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        argv = proc_cmdline(entry)
        if not argv:
            continue
        if os.path.basename(argv[0]) != 'niri':
            continue
        if prod_pid and int(entry) == prod_pid:
            continue                          # 人的桌面，不算"别的桌面"
        env = proc_environ(entry)
        rt = env.get('XDG_RUNTIME_DIR') or PROD_RUNTIME
        config = ''
        for i, a in enumerate(argv):
            if a == '-c' and i + 1 < len(argv):
                config = argv[i + 1]
        agent_dir = os.path.dirname(config) if config.startswith(AGENT_DESK_ROOT + os.sep) else ''
        # 回归环境（regression-visibility / regression-mpx）现在也挂在生产合成器上、共用
        # /run/user/1000，不能再拿 runtime 目录区分；只要不是 niri.service 那个进程，
        # 能按 pid 找到它自己的 IPC socket，就算"别的桌面"（kind=nested）。
        desc = read_json(os.path.join(agent_dir, 'desk.json'), {}) if agent_dir else {}
        key = os.path.basename(agent_dir) if agent_dir else desktop_key('niri', entry)
        socket = desc.get('niri_socket') or env.get('NIRI_SOCKET')
        if not socket:
            own = sorted(glob.glob(os.path.join(rt, 'niri.wayland-*.%s.sock' % entry)))
            if own:
                socket = own[0]
            else:
                cands = sorted(glob.glob(os.path.join(rt, 'niri.*.sock')))
                socket = cands[0] if cands else None
        wayland = desc.get('wayland')
        if not wayland and socket:
            # 嵌套 niri 自己的进程环境里 WAYLAND_DISPLAY 指向生产合成器（它是人家的客户端），
            # 绝不能拿它当这个桌面的 display；从我自己的 IPC socket 名里认。
            part = os.path.basename(socket).split('.')
            if len(part) >= 2 and part[0] == 'niri' and part[1].startswith('wayland-'):
                wayland = part[1]
        if not wayland:
            # 合成器自己的进程里没有 WAYLAND_DISPLAY；socket 名要从 runtime 目录里认。
            for cand in sorted(glob.glob(os.path.join(rt, 'wayland-*'))):
                name = os.path.basename(cand)
                if name.endswith('.lock'):
                    continue
                wayland = name
                break
        desk = {
            'key': key,
            'kind': 'agent' if agent_dir else 'nested',
            'pid': int(entry),
            'runtime': rt,
            'wayland': wayland,
            'niri_socket': socket,
            'x_display': desc.get('app_display') or desc.get('xvfb_display') or env.get('DISPLAY'),
            'app_display': desc.get('app_display'),
            'parent_window': desc.get('parent_window'),
            'parent_wayland': desc.get('parent_wayland') or '',
            'workspace': desc.get('workspace') or '',
            'config': config,
            'label': (desc.get('workspace') or key) if agent_dir
                     else nested_label(config, entry),
        }
        if not desk['niri_socket']:
            continue
        ver, _err = niri_json(desk, 'version')
        if ver is None:
            continue                          # 进程在但 IPC 不通（启动中/已坏）
        desk['version'] = ver.get('compositor') if isinstance(ver, dict) else str(ver)
        found[desk['key']] = desk

    # 裸 X 服务器（Xvfb）：有些会话不走 agent 桌面，自己开 Xvfb + WM 跑 GUI。
    # 那些窗口不在人的屏幕上、里面也没有 niri，靠 niri 扫不到，但一样得看得见。
    # 只认 DSH 会话拉起来的（cgroup 落 dsh-*/app-*），容器里的 Xvfb 不算。
    used = set()
    for desk in found.values():
        xd = desk.get('x_display') or desk.get('display')
        if xd:
            used.add(str(xd).split('.')[0])
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        argv = proc_cmdline(entry)
        if not argv or os.path.basename(argv[0]) != 'Xvfb':
            continue
        display = ''
        for a in argv[1:]:
            if a.startswith(':') and len(a) > 1:
                display = a.split('.')[0]
                break
        if not display or display in used or not dsh_owned_pid(entry):
            continue
        key = 'xvfb-%s' % display.lstrip(':')
        found[key] = {
            'key': key, 'kind': 'xvfb', 'pid': int(entry), 'runtime': PROD_RUNTIME,
            'wayland': None, 'niri_socket': None, 'x_display': display, 'display': display,
            'app_display': display, 'parent_window': None, 'parent_wayland': '',
            'workspace': '', 'config': '', 'label': 'Xvfb %s' % display, 'version': 'Xvfb',
        }
    return sorted(found.values(), key=lambda d: (d['kind'], d['label'], d['key']))


def desktop_paths(desk):
    base = os.path.join(ROOT, desk['key'])
    return base, os.path.join(base, 'shots'), os.path.join(base, 'winshots')


def nested_label(config, pid):
    """给非 agent 的嵌套实例起个人看得懂的名字（回归环境叫 regression-visibility 这种）。"""
    base = os.path.basename(os.path.dirname(config)) if config else ''
    if base in ('', 'run', 'tmp'):
        try:
            cwd = os.readlink('/proc/%s/cwd' % pid)
        except OSError:
            cwd = ''
        base = os.path.basename(cwd.rstrip('/')) or base
    return base or 'nested'


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
    if desk['kind'] in ('niri', 'agent', 'nested'):
        env = niri_env(desk)
        env['HOME'] = HOME
        code, out, err = run([GRIM, '-s', SHOT_SCALE, '-t', 'jpeg', '-q', SHOT_QUALITY, path],
                             env=env, timeout=30)
    else:
        display = desk.get('x_display') or desk.get('display')
        code, out, err = run([MAGICK, 'import', '-display', display, '-window', 'root',
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
    env = {'DISPLAY': desk.get('x_display') or desk.get('display'), 'PATH': '/usr/bin:/bin'}
    code, out, err = run([XDOTOOL, 'search', '--onlyvisible', '--name', ''], env=env, timeout=10)
    if code != 0:
        return [], (err or out).strip()[:200]
    code, scr, _ = run([XDOTOOL, 'getdisplaygeometry'], env=env, timeout=5)
    parts = (scr or '').split()
    try:
        screen = (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        screen = (0, 0)
    rows = []
    for wid in out.split():
        code, name, _ = run([XDOTOOL, 'getwindowname', wid], env=env, timeout=5)
        code2, geom, _ = run([XDOTOOL, 'getwindowgeometry', '--shell', wid], env=env, timeout=5)
        meta = {}
        for line in (geom or '').splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                meta[k.strip()] = v.strip()
        title = (name or '').strip()
        try:
            width = int(meta.get('WIDTH') or 0)
            height = int(meta.get('HEIGHT') or 0)
        except ValueError:
            width = height = 0
        # 裸 X 里 xdotool 会把根窗口和一堆无名的子窗口都列出来：扔掉无名的，
        # 以及正好铺满整屏的无名根窗口（有名字的全屏窗口要留，那是真的全屏应用）。
        if not title:
            continue
        if screen != (0, 0) and (width, height) == screen and not title:
            continue
        rows.append({'id': int(wid), 'title': title, 'app_id': 'x11',
                     'x': meta.get('X'), 'y': meta.get('Y'),
                     'width': meta.get('WIDTH'), 'height': meta.get('HEIGHT')})
        if len(rows) >= MAX_WINDOWS:
            break
    return rows, None


def window_shots(desk, windows, ts):
    """niri 桌面用 scoped-shot 逐窗口抓图（别的工作区也抓得到，不动剪贴板）。"""
    out = {}
    if desk['kind'] == 'xvfb':
        # 裸 Xvfb 里没有 niri，逐窗口只能用 X 自己抓（import -window <id>）。
        display = desk.get('x_display') or desk.get('display')
        base, _shots, win_dir = desktop_paths(desk)
        d = os.path.join(win_dir, stamp(ts, '%Y%m%d'))
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return out
        env = {'PATH': '/usr/bin:/bin', 'HOME': HOME, 'DISPLAY': display}
        for w in windows:
            wid = w.get('id')
            if wid is None or not w.get('width'):
                continue
            path = os.path.join(d, '%s-%s.jpg' % (stamp(ts, '%H%M%S'), wid))
            code, out_s, err = run([MAGICK, 'import', '-display', display, '-window', str(wid),
                                    '-resize', '50%', '-quality', SHOT_QUALITY, path],
                                   env=env, timeout=20)
            if code != 0 or not os.path.exists(path):
                out[str(wid)] = {'error': (err or out_s or 'import failed').strip()[:160]}
                continue
            out[str(wid)] = {'path': os.path.relpath(path, WATCH), 'bytes': os.path.getsize(path)}
        return out
    if desk['kind'] not in ('niri', 'agent', 'nested') or not windows or not os.path.exists(SCOPED_SHOT):
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
        if desk['kind'] in ('niri', 'agent', 'nested'):
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
        print('%-34s %-7s pid=%-7s wayland=%s x=%s' % (
            (d.get('label') or '')[:34], d['kind'], d.get('pid'), d.get('wayland'),
            d.get('x_display')))
        print('    key=%s niri=%s x11(app)=%s config=%s' % (
            d['key'], d.get('niri_socket'), d.get('app_display'), d.get('config')))
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
    windows, err = (nested_windows(desk) if desk['kind'] in ('niri', 'agent', 'nested')
                    else x11_windows(desk))
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


def desk_wayland_env(desk):
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': HOME,
           'XDG_RUNTIME_DIR': desk.get('runtime') or PROD_RUNTIME}
    if desk.get('wayland'):
        env['WAYLAND_DISPLAY'] = desk['wayland']
    return env


def type_text(desk, display, text):
    """打字：ASCII 走 xdotool；中文等非 ASCII 走这个桌面的 Wayland 剪贴板 + Ctrl+V。

    （agent 桌面已经改走 agent 座位了，这条只留给 X 父显示的嵌套环境。）
    xdotool type 只认 X keysym，中文会直接报 "Invalid multi-byte sequence"。wl-copy 把文本
    放进嵌套 niri 的剪贴板，xwayland-satellite 会在 X11 侧同步选区，X11 窗口 Ctrl+V 就能拿到；
    Wayland 原生窗口收不到 XTEST，这条路对它们无效（见文末限制）。
    """
    text = text or ''
    if text.isascii():
        return x_input(display, ['type', '--delay', '25', '--', text])
    if not os.access(WL_COPY, os.X_OK):
        return 1, '', '非 ASCII 文本需要 wl-copy，本机没装'
    proc = subprocess.Popen([WL_COPY], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, env=desk_wayland_env(desk),
                            start_new_session=True)
    try:
        _out, err = proc.communicate(text.encode('utf-8'), timeout=5)
    except subprocess.TimeoutExpired:
        err = b''
    time.sleep(0.3)
    code, out2, err2 = x_input(display, ['key', '--clearmodifiers', 'ctrl+v'])
    if code != 0:
        return code, out2, (err2 or err.decode('utf-8', 'replace'))
    return 0, 'via-clipboard', ''


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
    if op == 'focus-window' and desk['kind'] in ('niri', 'agent', 'nested'):
        code, out, err = run([NIRI, 'msg', 'action', 'focus-window', '--id', str(args['window'])],
                             env=niri_env(desk), timeout=10)
        print(out.strip() or err.strip())
        return code
    if op == 'close-window' and desk['kind'] in ('niri', 'agent', 'nested'):
        code, out, err = run([NIRI, 'msg', 'action', 'close-window', '--id', str(args['window'])],
                             env=niri_env(desk), timeout=10)
        print(out.strip() or err.strip())
        return code
    if desk['kind'] == 'agent':
        # 键盘、指针都走生产 niri 的 agent 座位（钉在这个嵌套窗口上）：Wayland 原生窗口
        # 收得到，人的座位和指针一点不动。中文走嵌套桌面的剪贴板 + Ctrl+V。
        if op == 'type':
            code, out, err = probe_text(desk, args.get('text') or '')
        elif op == 'key':
            code, out, err = probe_keys(desk, args.get('combo') or 'Return')
        elif op == 'click':
            code, out, err = scoped_click(desk, args.get('x') or 0, args.get('y') or 0)
        else:
            print('未知操作 %s' % (op,))
            return 2
        print((out or err or '').strip()[:300])
        return code
    display = desk.get('x_display') or desk.get('display')
    if desk['kind'] in ('niri', 'nested') and not display:
        print('这个桌面没有可注入的 X display（回归/嵌套环境）：只能看图、聚焦、关窗口；'
              '要操作它，它在 ue 里是一个生产窗口，Mod+U 过去直接用')
        return 1
    if op in ('type', 'key', 'click'):
        focus_x_root(display)
    if op == 'type':
        code, out, err = type_text(desk, display, args.get('text') or '')
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
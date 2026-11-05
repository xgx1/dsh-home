#!/usr/bin/env python3
"""agent-desktop.py —— 给每个 agent 会话一个自己的嵌套桌面，GUI 默认落到那里。

结构（和 regression-visibility 里的嵌套环境同一套路，但不用手动起 satellite）：
  Xvfb（父 X display）→ niri fork（winit 后端）→ 首次有 X11 客户端连接时 niri 自己拉起
  xwayland-satellite，于是这个 niri 同时有 Wayland 和 X11 两种客户端。

关键点：niri 自己也会在 XDG_RUNTIME_DIR 里建 wayland-N 和 niri.wayland-N.PID.sock，
所以嵌套桌面和生产桌面共用 /run/user/1000，DBus/Pulse/portal 都不用另外配。
会话里的 GUI 靠环境变量指过来：WAYLAND_DISPLAY / DISPLAY(niri 的 X11 socket) / NIRI_SOCKET。

命令：
  agent-desktop.py key [--cwd DIR]                  # 算这个工作区的桌面 key
  agent-desktop.py up [--key K] [--workspace W] [-q] # 保证桌面在跑（systemd 临时单元）
  agent-desktop.py env [--key K]                    # 打印 export 行
  agent-desktop.py run [--key K] -- CMD...          # 带着桌面环境跑命令
  agent-desktop.py list                             # 有哪些桌面
  agent-desktop.py down [--key K|--all]             # 关掉
  agent-desktop.py heartbeat [--key K]              # 续命（shell 钩子每次命令调）
  agent-desktop.py supervise --key K [--size WxH]   # 内部：常驻监督进程
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HOME = os.path.expanduser('~')
DSH = os.path.join(HOME, '.dsh')
ROOT = os.path.join(DSH, 'agent-desktops')
RUNTIME = os.environ.get('AGENT_DESKTOP_RUNTIME') or ('/run/user/%d' % os.getuid())
NIRI = os.environ.get('AGENT_DESKTOP_NIRI') or '/home/sx/projects/niri/target/release/niri'
XVFB = shutil.which('Xvfb') or '/usr/bin/Xvfb'
NIRI_MSG = NIRI
DEFAULT_SIZE = '1920x1080'
IDLE_TIMEOUT = float(os.environ.get('AGENT_DESKTOP_IDLE') or 1800)
KEEP_DAYS = 7.0
WS_MARKERS = ('.git', 'AGENTS.md', '.dsh')


def now():
    return time.time()


def stamp(ts=None):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts if ts is not None else now()))


def key_for_cwd(cwd):
    """工作区根目录决定桌面：同一个仓库/项目里的所有命令共用一个桌面。"""
    d = os.path.realpath(cwd or os.getcwd())
    root = d
    cur = d
    while True:
        if any(os.path.exists(os.path.join(cur, m)) for m in WS_MARKERS):
            root = cur
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        if cur == HOME:
            break
        cur = parent
    digest = hashlib.md5(root.encode('utf-8')).hexdigest()[:8]
    return 'ws-' + digest, root


def sanitize(key):
    return re.sub(r'[^A-Za-z0-9._-]', '-', key or '')[:64]


def desk_dir(key):
    return os.path.join(ROOT, sanitize(key))


def unit_name(key):
    return 'dsh-agent-desk-%s.service' % sanitize(key)


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
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def desk_state(key):
    """读桌面状态；进程没了就当没有。"""
    doc = read_json(os.path.join(desk_dir(key), 'desk.json'))
    if not doc:
        return None
    if not alive(doc.get('niri_pid')):
        return None
    return doc


def env_lines(doc):
    lines = [
        '# %s 生成的 agent 桌面环境（%s），source 它会改 WAYLAND_DISPLAY/DISPLAY/NIRI_SOCKET' % (
            os.path.basename(__file__), stamp()),
        'export AGENT_DESKTOP=1',
        'export AGENT_DESKTOP_KEY=%s' % doc['key'],
        'export AGENT_DESKTOP_WORKSPACE=%s' % doc.get('workspace', ''),
        'export AGENT_DESKTOP_WAYLAND=%s' % doc['wayland'],
        'export AGENT_DESKTOP_DISPLAY=%s' % doc['app_display'],
        'export AGENT_DESKTOP_XVFB=%s' % doc['xvfb_display'],
        'export AGENT_DESKTOP_NIRI_SOCKET=%s' % doc['niri_socket'],
        'export AGENT_DESKTOP_NIRI_PID=%s' % doc['niri_pid'],
        'export WAYLAND_DISPLAY=%s' % doc['wayland'],
        'export DISPLAY=%s' % doc['app_display'],
        'export NIRI_SOCKET=%s' % doc['niri_socket'],
    ]
    return lines


def write_env_files(doc):
    d = desk_dir(doc['key'])
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'env.sh'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(env_lines(doc)) + '\n')
        write_json(os.path.join(d, 'desk.json'), doc)
        os.utime(os.path.join(d, 'heartbeat'), None) if os.path.exists(os.path.join(d, 'heartbeat')) else None
    except OSError:
        pass


def touch_heartbeat(key):
    d = desk_dir(key)
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'heartbeat'), 'w', encoding='utf-8') as fh:
            fh.write('%d\n' % int(now()))
    except OSError:
        pass


def cleanup_stale_sockets():
    """清掉死掉的 niri / wayland socket：SIGKILL 之后这些文件会留在 runtime 目录里。"""
    removed = []
    for sock in glob.glob(os.path.join(RUNTIME, 'niri.wayland-*.sock')):
        pid = sock.rsplit('.', 2)[-2] if sock.count('.') >= 3 else ''
        try:
            os.kill(int(pid), 0)
            continue
        except (OSError, ValueError):
            pass
        try:
            os.unlink(sock)
            removed.append(sock)
        except OSError:
            pass
    # wayland-N 本体和锁文件：只有确实没有活着的 niri 认领时才删
    live_waylands = set()
    for sock in glob.glob(os.path.join(RUNTIME, 'niri.wayland-*.sock')):
        name = os.path.basename(sock)[len('niri.'):]
        live_waylands.add(name.rsplit('.', 2)[0] + '-' + name.rsplit('.', 2)[1])
    for cand in glob.glob(os.path.join(RUNTIME, 'wayland-*')):
        name = os.path.basename(cand)
        base = name[:-len('.lock')] if name.endswith('.lock') else name
        # 生产桌面（wayland-1）与还活着的 agent 桌面都别动
        if base == 'wayland-1':
            continue
        if any(w.endswith('-' + base.split('-')[-1]) for w in live_waylands):
            continue
        if os.path.exists(os.path.join(RUNTIME, 'niri.' + base + '.')) or \
           any(os.path.basename(s).startswith('niri.' + base + '.') for s in
               glob.glob(os.path.join(RUNTIME, 'niri.*.sock'))):
            continue
        try:
            os.unlink(cand)
            removed.append(cand)
        except OSError:
            pass
    return removed


def prune_old():
    try:
        for name in os.listdir(ROOT):
            path = os.path.join(ROOT, name)
            if not os.path.isdir(path):
                continue
            try:
                if now() - os.path.getmtime(path) > KEEP_DAYS * 86400:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass


# ── supervise：真正干活的那个进程（由 systemd-run 拉起，常驻到空闲） ──────────

def child_env(display):
    return {'PATH': '/usr/local/bin:/usr/bin:/bin',
            'HOME': HOME,
            'XDG_RUNTIME_DIR': RUNTIME,
            'DISPLAY': display,
            'WINIT_UNIX_BACKEND': 'x11',
            'XDG_SESSION_TYPE': 'wayland',
            'XDG_CURRENT_DESKTOP': 'niri'}


def start_xvfb(size, log):
    width, height = size.split('x')
    rfd, wfd = os.pipe()
    # -displayfd 收任意 fd 号；把它 dup 成一个专门的可继承 fd 直接交给 Xvfb，
    # 不依赖 preexec_fn（preexec 之后 subprocess 还会关一遍未在 pass_fds 里的 fd）。
    xfd = os.dup(wfd)
    os.set_inheritable(xfd, True)
    proc = subprocess.Popen([XVFB, '-displayfd', str(xfd),
                             '-screen', '0', '%sx%sx24' % (width, height),
                             '-nolisten', 'tcp'],
                            stdout=log, stderr=log, pass_fds=(xfd,))
    os.close(xfd)
    os.close(wfd)
    line = os.read(rfd, 64).decode('utf-8', 'replace')
    os.close(rfd)
    num = line.strip().splitlines()[0] if line.strip() else ''
    if not num.isdigit():
        raise RuntimeError('Xvfb 没吐出 display 号：%r' % line)
    return proc, ':' + num


def wait_for(pattern, path, timeout=20.0):
    rx = re.compile(pattern)
    end = now() + timeout
    while now() < end:
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            text = ''
        found = rx.findall(text)
        if found:
            return found[0]
        time.sleep(0.15)
    return None


def write_kdl(path):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('// agent 桌面：工具会话自己的嵌套 niri；故意不配热键、不 spawn 任何东西\n'
                 'prefer-no-csd\n'
                 'hotkey-overlay {\n'
                 '    skip-at-startup\n'
                 '}\n')


def cmd_supervise(args):
    key = sanitize(args.key)
    size = args.size or DEFAULT_SIZE
    d = desk_dir(key)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    config = os.path.join(d, 'config.kdl')
    write_kdl(config)
    niri_log = open(os.path.join(d, 'niri.log'), 'w')
    xvfb_log = open(os.path.join(d, 'xvfb.log'), 'w')
    stop = {'now': False}

    def _stop(_sig, _frm):
        stop['now'] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    xvfb = None
    niri = None
    try:
        xvfb, parent_display = start_xvfb(size, xvfb_log)
        env = child_env(parent_display)
        # 别把父进程的 Wayland/IPC 带进去
        for k in ('WAYLAND_DISPLAY', 'NIRI_SOCKET'):
            env.pop(k, None)
        niri = subprocess.Popen([NIRI, '-c', config], env=env,
                                stdout=niri_log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
        log_path = os.path.join(d, 'niri.log')
        wayland = wait_for(r'listening on Wayland socket: (\S+)', log_path)
        ipc = wait_for(r'IPC listening on: (\S+)', log_path)
        app_display = wait_for(r'listening on X11 socket: (:\d+)', log_path)
        missing = [n for n, v in (('wayland', wayland), ('ipc', ipc), ('x11', app_display)) if not v]
        if missing:
            raise RuntimeError('niri 没起来（缺 %s），日志见 %s/niri.log' % (','.join(missing), d))
        try:
            version = subprocess.run([NIRI, '--version'], capture_output=True, text=True,
                                     timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = ''
        doc = {'key': key, 'workspace': args.workspace or '', 'size': size,
               'created_at': now(), 'updated_at': now(),
               'niri_pid': niri.pid, 'xvfb_pid': xvfb.pid,
               'wayland': wayland, 'niri_socket': ipc,
               'app_display': app_display, 'xvfb_display': parent_display,
               'config': config, 'version': version}
        write_env_files(doc)
        touch_heartbeat(key)
        print('%s 桌面就绪 key=%s wayland=%s x11=%s parent=%s' % (
            stamp(), key, wayland, app_display, parent_display), flush=True)

        last_check = now()
        while not stop['now']:
            time.sleep(2.0)
            if xvfb.poll() is not None or niri.poll() is not None:
                print('%s 子进程退出（xvfb=%s niri=%s）' % (stamp(), xvfb.poll(), niri.poll()),
                      flush=True)
                break
            if now() - last_check < 30:
                continue
            last_check = now()
            hb = os.path.join(d, 'heartbeat')
            try:
                idle = now() - os.path.getmtime(hb)
            except OSError:
                idle = 0.0                 # 钩子还没写过心跳，先别收
            if idle <= IDLE_TIMEOUT:
                continue
            windows = 0
            try:
                res = subprocess.run([NIRI_MSG, 'msg', '-j', 'windows'],
                                     env={'PATH': '/usr/bin:/bin', 'HOME': HOME,
                                          'XDG_RUNTIME_DIR': RUNTIME, 'NIRI_SOCKET': ipc},
                                     capture_output=True, text=True, timeout=10)
                windows = len(json.loads(res.stdout))
            except (OSError, subprocess.SubprocessError, ValueError):
                windows = 0
            if windows == 0:
                print('%s 空闲 %.0f 分钟且没有窗口，收工' % (stamp(), idle / 60.0), flush=True)
                break
    except Exception as exc:                       # noqa: BLE001 —— 监督进程要把原因写进日志
        print('%s 失败：%s' % (stamp(), exc), flush=True)
        raise
    finally:
        stop['now'] = True
        for proc in (niri, xvfb):
            if proc is None or proc.poll() is not None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=6)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
        try:
            doc = read_json(os.path.join(d, 'desk.json')) or {}
            for sock in (doc.get('niri_socket'),):
                if sock and os.path.exists(sock):
                    try:
                        os.unlink(sock)
                    except OSError:
                        pass
            for name in ('env.sh', 'env.json', 'desk.json'):
                try:
                    os.unlink(os.path.join(d, name))
                except OSError:
                    pass
            cleanup_stale_sockets()
        except OSError:
            pass
        niri_log.close()
        xvfb_log.close()
        print('%s 监督进程结束 key=%s' % (stamp(), key), flush=True)
    return 0


# ── CLI 其余部分 ───────────────────────────────────────────────────────────

def cmd_key(args):
    key, root = key_for_cwd(args.cwd)
    print(key)
    return 0


def unit_state(name):
    try:
        res = subprocess.run(['systemctl', '--user', 'show', '-p', 'ActiveState', '--value', name],
                             capture_output=True, text=True, timeout=10)
        return (res.stdout or '').strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def cmd_up(args):
    key, root = key_for_cwd(args.cwd)
    if args.workspace:
        root = args.workspace
    key = sanitize(args.key or key)
    doc = desk_state(key)
    if doc:
        touch_heartbeat(key)
        if not args.quiet:
            print('已在运行：%s  wayland=%s  x11=%s' % (key, doc['wayland'], doc['app_display']))
        return 0
    prune_old()
    os.makedirs(desk_dir(key), exist_ok=True)
    name = unit_name(key)
    subprocess.run(['systemctl', '--user', 'stop', name],
                   capture_output=True, text=True, timeout=15)
    cmd = ['systemd-run', '--user', '--unit', name, '--collect', '--quiet',
           '--description=agent desktop (%s)' % key,
           sys.executable, os.path.abspath(__file__), 'supervise', '--key', key,
           '--workspace', root]
    if args.size:
        cmd += ['--size', args.size]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0 and 'already' not in (res.stderr or ''):
        sys.stderr.write('启动失败：%s\n' % ((res.stderr or res.stdout).strip()[:300]))
        return 1
    deadline = now() + 30
    while now() < deadline:
        doc = desk_state(key)
        if doc:
            touch_heartbeat(key)
            if not args.quiet:
                print('已启动：%s  %s  wayland=%s  x11=%s' % (
                    key, root, doc['wayland'], doc['app_display']))
            return 0
        time.sleep(0.2)
    try:
        with open(os.path.join(desk_dir(key), 'niri.log'), 'r', encoding='utf-8',
                  errors='replace') as fh:
            tail = ''.join(fh.readlines()[-6:])
    except OSError:
        tail = ''
    sys.stderr.write('桌面没起来（key=%s），日志尾部：\n%s\n' % (key, tail.strip() or '(空)'))
    return 1


def cmd_env(args):
    key, _root = key_for_cwd(args.cwd)
    key = sanitize(args.key or key)
    doc = desk_state(key)
    if not doc:
        sys.stderr.write('桌面 %s 没在跑（先 up）\n' % key)
        return 1
    print('\n'.join(env_lines(doc)))
    return 0


def cmd_run(args):
    key, _root = key_for_cwd(args.cwd)
    key = sanitize(args.key or key)
    if cmd_up(argparse.Namespace(key=key, cwd=args.cwd, workspace=None, size=None, quiet=True)):
        return 1
    doc = desk_state(key)
    if not doc:
        return 1
    env = dict(os.environ)
    env.update({'WAYLAND_DISPLAY': doc['wayland'], 'DISPLAY': doc['app_display'],
                'NIRI_SOCKET': doc['niri_socket'], 'AGENT_DESKTOP': '1',
                'AGENT_DESKTOP_KEY': key, 'XDG_RUNTIME_DIR': RUNTIME})
    try:
        os.execvpe(args.argv[0], args.argv, env)
    except OSError as exc:
        sys.stderr.write('执行失败：%s\n' % exc)
        return 127


def cmd_list(args):
    if not os.path.isdir(ROOT):
        print('还没有 agent 桌面')
        return 0
    rows = []
    for name in sorted(os.listdir(ROOT)):
        doc = read_json(os.path.join(ROOT, name, 'desk.json'))
        if not doc:
            continue
        live = alive(doc.get('niri_pid'))
        rows.append((live, doc))
    if not rows:
        print('还没有 agent 桌面')
        return 0
    for live, doc in rows:
        print('%-4s %-12s %-28s wayland=%-9s x11=%-4s parent=%-4s' % (
            'up' if live else 'dead', doc.get('key'), (doc.get('workspace') or '')[:28],
            doc.get('wayland'), doc.get('app_display'), doc.get('xvfb_display')))
    return 0


def cmd_down(args):
    if args.all:
        keys = []
        for name in os.listdir(ROOT) if os.path.isdir(ROOT) else []:
            keys.append(name)
    else:
        keys = [sanitize(args.key)] if args.key else [key_for_cwd(args.cwd)[0]]
    for key in keys:
        subprocess.run(['systemctl', '--user', 'stop', unit_name(key)],
                       capture_output=True, text=True, timeout=30)
        print('已停止 %s' % key)
    return 0


def cmd_prune(args):
    removed = cleanup_stale_sockets()
    prune_old()
    if removed and not args.quiet:
        print('清掉 %d 个死 socket' % len(removed))
    return 0


def cmd_heartbeat(args):
    key = sanitize(args.key) if args.key else key_for_cwd(args.cwd)[0]
    touch_heartbeat(key)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description='agent 桌面管理')
    sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('key'); p.add_argument('--cwd')
    p.set_defaults(fn=cmd_key)
    p = sub.add_parser('up'); p.add_argument('--key'); p.add_argument('--cwd')
    p.add_argument('--workspace'); p.add_argument('--size'); p.add_argument('-q', '--quiet',
                                                                             action='store_true')
    p.set_defaults(fn=cmd_up)
    p = sub.add_parser('env'); p.add_argument('--key'); p.add_argument('--cwd')
    p.set_defaults(fn=cmd_env)
    p = sub.add_parser('run'); p.add_argument('--key'); p.add_argument('--cwd')
    p.add_argument('argv', nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser('list'); p.set_defaults(fn=cmd_list)
    p = sub.add_parser('down'); p.add_argument('--key'); p.add_argument('--cwd')
    p.add_argument('--all', action='store_true'); p.set_defaults(fn=cmd_down)
    p = sub.add_parser('heartbeat'); p.add_argument('--key'); p.add_argument('--cwd')
    p.set_defaults(fn=cmd_heartbeat)
    p = sub.add_parser('prune'); p.add_argument('-q', '--quiet', action='store_true')
    p.set_defaults(fn=cmd_prune)
    p = sub.add_parser('supervise'); p.add_argument('--key', required=True)
    p.add_argument('--workspace'); p.add_argument('--size'); p.set_defaults(fn=cmd_supervise)
    args = ap.parse_args(argv[1:])
    if not getattr(args, 'fn', None):
        ap.print_help()
        return 2
    if getattr(args, 'argv', None) and args.argv and args.argv[0] == '--':
        args.argv = args.argv[1:]
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))

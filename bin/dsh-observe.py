#!/usr/bin/env python3
"""dsh-observe.py -- 只读的桌面/会话观察器（每分钟截图 + 窗口与桌面信息）。

配合 dsh-guard.py：guard 看会话命令行，observe 看"屏幕上现在是什么"。

  dsh-observe.py snapshot            # 截图 + 窗口/工作区/输出快照 + 事件 diff（timer 调用）
  dsh-observe.py status              # 最近一次快照摘要 + 存储占用
  dsh-observe.py windows             # 当前窗口列表（id/工作区/app_id/标题）
  dsh-observe.py events [-m N]       # 最近 N 分钟的开窗/关窗/换焦点/搬工作区事件
  dsh-observe.py shots [-m N]        # 最近 N 分钟的截图文件
  dsh-observe.py prune               # 按保留策略清理截图

只读：不注入输入、不改窗口、不写别人的东西。截图存在 ~/.dsh/watch/shots/。
"""

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
SHOTS = os.path.join(WATCH, 'shots')
WINSHOTS = os.path.join(WATCH, 'winshots')
LATEST_JSON = os.path.join(WATCH, 'latest.json')
WINDOWS_JSONL = os.path.join(WATCH, 'windows.jsonl')
EVENTS_JSONL = os.path.join(WATCH, 'events.jsonl')
SHOTS_JSONL = os.path.join(WATCH, 'shots.jsonl')
NIRI = shutil.which('niri') or '/usr/local/bin/niri'
GRIM = shutil.which('grim') or '/usr/bin/grim'
MAGICK = shutil.which('magick') or '/usr/bin/magick'
# fork 的 ScopedScreenshot IPC：按窗口 id 抓图，窗口在别的工作区也能抓到，且不动剪贴板。
SCOPED_SHOT = os.path.join(HOME, 'projects', 'agent-seat-probe', 'target', 'debug', 'scoped-shot')
MAX_WINDOW_SHOTS = 16

RETAIN_HOURS = 24.0          # 截图保留时长
MAX_SHOT_BYTES = 512 * 1024 * 1024       # 整屏截图总上限
MAX_WIN_BYTES = 2048 * 1024 * 1024       # 每窗口截图总上限
SHOT_SCALE = '0.5'           # 半分辨率：1280x720 左右，jpeg q70 约 130 KB/张
SHOT_QUALITY = '70'
MIN_FREE_BYTES = 20 * 1024 ** 3      # 剩余空间低于 20G 就不截图，只记窗口信息
JSONL_MAX = 8 * 1024 * 1024


def now_ts():
    return time.time()


def stamp(ts=None):
    return datetime.fromtimestamp(ts or now_ts()).strftime('%Y-%m-%dT%H:%M:%S')


def day(ts=None):
    return datetime.fromtimestamp(ts or now_ts()).strftime('%Y%m%d')


def hms(ts=None):
    return datetime.fromtimestamp(ts or now_ts()).strftime('%H%M%S')


def ensure_dirs():
    os.makedirs(SHOTS, exist_ok=True)


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


def tail_jsonl(path, limit):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            rows = fh.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in rows:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def user_env():
    """systemd --user 会话环境里的 WAYLAND_DISPLAY / NIRI_SOCKET。"""
    env = dict(os.environ)
    try:
        out = subprocess.run(['systemctl', '--user', 'show-environment'],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return env
    for line in out.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            if k in ('WAYLAND_DISPLAY', 'NIRI_SOCKET', 'XDG_RUNTIME_DIR',
                     'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE', 'DISPLAY'):
                env[k] = v
    env.setdefault('XDG_RUNTIME_DIR', '/run/user/%d' % os.getuid())
    return env


def niri_json(env, *args, timeout=10):
    try:
        res = subprocess.run([NIRI, 'msg', '-j', *args], env=env,
                             capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if res.returncode != 0:
        return None, (res.stderr or res.stdout).strip().splitlines()[:2]
    try:
        return json.loads(res.stdout), None
    except ValueError:
        return None, 'unparsable niri msg output'


def niri_text(env, *args, timeout=10):
    try:
        res = subprocess.run([NIRI, 'msg', *args], env=env,
                             capture_output=True, text=True, timeout=timeout)
        return (res.stdout or '').strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def capture_shot(env, ts):
    """截一张半分辨率 jpeg；返回 (相对路径, 字节数, 错误)。"""
    ensure_dirs()
    if shutil.disk_usage(SHOTS).free < MIN_FREE_BYTES:
        return None, 0, 'low disk space, skipped'
    d = os.path.join(SHOTS, day(ts))
    os.makedirs(d, exist_ok=True)
    base = hms(ts)
    path = os.path.join(d, base + '.jpg')
    if os.path.exists(path):                 # 同一秒内手动重跑时不覆盖
        n = 1
        while os.path.exists(os.path.join(d, '%s-%d.jpg' % (base, n))):
            n += 1
        path = os.path.join(d, '%s-%d.jpg' % (base, n))
    cmd = [GRIM, '-s', SHOT_SCALE, '-t', 'jpeg', '-q', SHOT_QUALITY, path]
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, 0, str(exc)
    if res.returncode != 0 or not os.path.exists(path):
        return None, 0, (res.stderr or 'grim failed').strip().splitlines()[:2]
    size = os.path.getsize(path)
    latest = os.path.join(WATCH, 'latest.jpg')
    try:
        if os.path.islink(latest) or os.path.exists(latest):
            os.unlink(latest)
        os.symlink(path, latest)
    except OSError:
        pass
    return os.path.relpath(path, WATCH), size, None


def capture_window_shots(env, windows, ts):
    """逐个窗口抓图（fork 的 ScopedScreenshot：别的工作区也抓得到，不动剪贴板）。

    返回 {窗口 id: {'path': 相对路径, 'bytes': n}}；失败记 {'error': ...}，不影响其它窗口。
    """
    out = {}
    if not windows or not os.path.exists(SCOPED_SHOT):
        return out
    try:
        if shutil.disk_usage(WATCH).free < MIN_FREE_BYTES:
            return out
    except OSError:
        return out
    d = os.path.join(WINSHOTS, day(ts), hms(ts))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return out
    for w in windows[:MAX_WINDOW_SHOTS]:
        wid = w.get('id')
        if wid is None:
            continue
        png = os.path.join(d, '%s.png' % wid)
        jpg = os.path.join(d, '%s.jpg' % wid)
        try:
            res = subprocess.run([SCOPED_SHOT, str(wid), png], env=env,
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            out[str(wid)] = {'error': str(exc)}
            continue
        if res.returncode != 0 or not os.path.exists(png):
            out[str(wid)] = {'error': (res.stderr or 'capture failed').strip().splitlines()[:2]}
            continue
        converted = False
        try:
            conv = subprocess.run([MAGICK, png, '-resize', '50%', '-quality', '70', jpg],
                                  capture_output=True, text=True, timeout=20)
            converted = conv.returncode == 0 and os.path.exists(jpg)
        except (OSError, subprocess.SubprocessError):
            converted = False
        if converted:
            try:
                os.unlink(png)
            except OSError:
                pass
            path = jpg
        else:
            path = png
        out[str(wid)] = {'path': os.path.relpath(path, WATCH),
                         'bytes': os.path.getsize(path)}
    return out


def active_sessions(max_age=300):
    """最近还在动的 DSH 会话（id + 工作区目录）。"""
    now = now_ts()
    found = []
    for root in (os.path.join(DSH, 'sessions'),
                 os.path.join(os.path.expanduser('~'), '.dsh-dev', 'sessions')):
        if not os.path.isdir(root):
            continue
        home = 'prod' if root.startswith(DSH + os.sep) else 'dev'
        for ws in sorted(os.listdir(root)):
            wsdir = os.path.join(root, ws)
            if not os.path.isdir(wsdir):
                continue
            try:
                sessions = sorted(os.listdir(wsdir))
            except OSError:
                continue
            for sess in sessions:
                f = os.path.join(wsdir, sess, 'session.v4.jsonl.zstd')
                try:
                    mtime = os.path.getmtime(f)
                except OSError:
                    continue
                if now - mtime > max_age:
                    continue
                sid = sess.split('session-')[-1]
                found.append({'home': home, 'session': sid, 'workspace_dir': ws,
                              'cwd': ws.strip('-').replace('-', '/'),
                              'idle_s': int(now - mtime)})
    found.sort(key=lambda r: r['idle_s'])
    return found


def windows_doc(env):
    """窗口 + 工作区 + 输出 + 版本，逐窗口带上所在工作区/输出。"""
    doc = {'wm': 'niri', 'version': None, 'error': None,
           'outputs': [], 'workspaces': [], 'windows': [], 'focused_window': None,
           'seats': None}
    ver, err = niri_json(env, 'version')
    if ver is None:
        doc['error'] = err
        return doc
    doc['version'] = ver.get('compositor') if isinstance(ver, dict) else ver
    outputs, _ = niri_json(env, 'outputs')
    workspaces, _ = niri_json(env, 'workspaces')
    windows, werr = niri_json(env, 'windows')
    if windows is None:
        doc['error'] = werr
        return doc
    if isinstance(outputs, dict):            # niri 返回 {输出名: 输出对象}
        raw = []
        for name, o in outputs.items():
            if isinstance(o, dict):
                o = dict(o)
                o.setdefault('name', name)
                raw.append(o)
        outputs = raw
    for o in outputs or []:
        if not isinstance(o, dict):
            continue
        doc['outputs'].append({
            'name': o.get('name'), 'make': o.get('make'), 'model': o.get('model'),
            'logical': o.get('logical'),
        })
    ws_by_id = {}
    for w in workspaces or []:
        ws_by_id[w.get('id')] = w
        doc['workspaces'].append({
            'id': w.get('id'), 'idx': w.get('idx'), 'name': w.get('name'),
            'output': w.get('output'), 'is_active': w.get('is_active'),
            'is_focused': w.get('is_focused'), 'active_window_id': w.get('active_window_id'),
            'is_urgent': w.get('is_urgent'),
            'window_count': sum(1 for x in windows if x.get('workspace_id') == w.get('id')),
        })
    for w in windows:
        ws = ws_by_id.get(w.get('workspace_id')) or {}
        layout = w.get('layout') or {}
        doc['windows'].append({
            'id': w.get('id'),
            'app_id': w.get('app_id'),
            'title': w.get('title'),
            'pid': w.get('pid'),
            'workspace_id': w.get('workspace_id'),
            'workspace_idx': ws.get('idx'),
            'workspace_name': ws.get('name'),
            'output': ws.get('output'),
            'is_focused': w.get('is_focused'),
            'is_floating': w.get('is_floating'),
            'is_urgent': w.get('is_urgent'),
            'tile_size': layout.get('tile_size'),
            'window_size': layout.get('window_size'),
            'focus_timestamp': w.get('focus_timestamp'),
        })
    doc['focused_window'] = next((w for w in doc['windows'] if w.get('is_focused')), None)
    seats = niri_text(env, 'seats')
    doc['seats'] = seats.splitlines()[:12] if seats else None
    return doc


def _window_key(w):
    return str(w.get('id'))


def diff_events(prev, cur, ts):
    """对照上一次快照，产出开窗/关窗/改标题/搬工作区/焦点变化事件。"""
    events = []
    if not prev:
        return events
    p_win = {_window_key(w): w for w in prev.get('windows') or []}
    c_win = {_window_key(w): w for w in cur.get('windows') or []}
    for key, w in c_win.items():
        if key not in p_win:
            events.append({'ts': ts, 'kind': 'window-open', 'window': w})
    for key, w in p_win.items():
        if key not in c_win:
            events.append({'ts': ts, 'kind': 'window-close', 'window': w})
    for key, w in c_win.items():
        old = p_win.get(key)
        if not old:
            continue
        if old.get('title') != w.get('title'):
            events.append({'ts': ts, 'kind': 'window-retitle', 'window': w,
                           'old_title': old.get('title')})
        if old.get('workspace_id') != w.get('workspace_id'):
            events.append({'ts': ts, 'kind': 'window-move-workspace', 'window': w,
                           'from_workspace': old.get('workspace_id'),
                           'to_workspace': w.get('workspace_id')})
        if not old.get('is_focused') and w.get('is_focused'):
            events.append({'ts': ts, 'kind': 'focus-in', 'window': w})
        elif old.get('is_focused') and not w.get('is_focused'):
            events.append({'ts': ts, 'kind': 'focus-out', 'window': w})
    pf, cf = prev.get('focused_window'), cur.get('focused_window')
    if (pf or {}).get('id') != (cf or {}).get('id'):
        events.append({'ts': ts, 'kind': 'focus-change',
                       'from': (pf or {}).get('id'), 'to': (cf or {}).get('id'),
                       'to_app_id': (cf or {}).get('app_id'),
                       'to_title': (cf or {}).get('title')})
    if (prev.get('outputs') or []) != (cur.get('outputs') or []):
        events.append({'ts': ts, 'kind': 'outputs-changed',
                       'outputs': [o.get('name') for o in cur.get('outputs') or []]})
    return events


def prune_root(root_dir, retain_hours=RETAIN_HOURS, max_bytes=MAX_SHOT_BYTES):
    """删掉 root_dir 里过期的 .jpg/.png；仍超上限就从最旧的删起。"""
    if not os.path.isdir(root_dir):
        return 0, 0, 0
    now = now_ts()
    cutoff = now - retain_hours * 3600
    files = []
    for root, _dirs, names in os.walk(root_dir):
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
    if total > max_bytes:
        for mtime, size, path in sorted(files):
            if total <= max_bytes:
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
    for root, dirs, names in os.walk(root_dir, topdown=False):
        if root == root_dir:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass
    return removed, freed, total


def prune_all():
    removed = freed = total = 0
    for root_dir, cap in ((SHOTS, MAX_SHOT_BYTES), (WINSHOTS, MAX_WIN_BYTES)):
        r, f, t = prune_root(root_dir, RETAIN_HOURS, cap)
        removed += r
        freed += f
        total += t
    return removed, freed, total


def load_prev():
    try:
        with open(LATEST_JSON, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def cmd_snapshot(args):
    quiet = args.get('quiet')
    ts = now_ts()
    ensure_dirs()
    env = user_env()
    prev = load_prev()
    shot_rel, shot_bytes, shot_err = capture_shot(env, ts)
    doc = windows_doc(env)
    if not doc.get('error'):
        shots = capture_window_shots(env, doc.get('windows') or [], ts)
        for w in doc.get('windows') or []:
            w['shot'] = shots.get(str(w.get('id')))
        doc['window_shots'] = shots
    doc['ts'] = ts
    doc['at'] = stamp(ts)
    doc['shot'] = shot_rel
    doc['shot_bytes'] = shot_bytes
    doc['shot_error'] = shot_err
    doc['sessions'] = active_sessions()
    events = diff_events(prev, doc, ts) if not doc.get('error') else []
    append_jsonl(WINDOWS_JSONL, {
        'ts': ts, 'at': stamp(ts), 'shot': shot_rel,
        'wm': doc['wm'], 'version': doc['version'], 'error': doc['error'],
        'focused': (doc.get('focused_window') or {}).get('title'),
        'windows': doc.get('windows'), 'workspaces': doc.get('workspaces'),
        'outputs': doc.get('outputs'), 'sessions': [s['session'][:8] for s in doc['sessions']],
    })
    append_jsonl(SHOTS_JSONL, {'ts': ts, 'at': stamp(ts), 'path': shot_rel,
                               'bytes': shot_bytes, 'error': shot_err})
    for ev in events:
        append_jsonl(EVENTS_JSONL, ev)
    try:
        tmp = LATEST_JSON + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        os.replace(tmp, LATEST_JSON)
    except OSError:
        pass
    removed, freed, total = prune_all()
    if not quiet:
        print('%s windows=%d focused=%r shot=%s (%d B)%s%s' % (
            stamp(ts), len(doc.get('windows') or []),
            (doc.get('focused_window') or {}).get('title'),
            shot_rel or '-', shot_bytes,
            '' if not shot_err else ' [shot error]',
            '' if not doc.get('error') else ' [niri error: %s]' % doc['error']))
        print('events=%d pruned=%d freed=%.1fMB shots_total=%.1fMB'
              % (len(events), removed, freed / 1048576.0, total / 1048576.0))
    return 1 if doc.get('error') else 0


def cmd_status(args):
    doc = load_prev()
    if not doc:
        print('还没有快照；先跑 dsh-observe.py snapshot')
        return 1
    print('上次快照      %s (%d 秒前)' % (doc.get('at'), int(now_ts() - doc.get('ts', 0))))
    print('合成器        %s %s' % (doc.get('wm'), doc.get('version')))
    if doc.get('error'):
        print('错误          %s' % (doc.get('error'),))
    print('截图          %s (%d B)%s' % (doc.get('shot'), doc.get('shot_bytes') or 0,
                                        '' if not doc.get('shot_error')
                                        else ' 错误: %s' % (doc.get('shot_error'),)))
    outs = doc.get('outputs') or []
    print('输出          %s' % ', '.join(
        '%s %sx%s@%s' % (o.get('name'),
                         ((o.get('logical') or {}).get('width')),
                         ((o.get('logical') or {}).get('height')),
                         ((o.get('logical') or {}).get('scale')))
        for o in outs))
    print('工作区/窗口   %d 个工作区，%d 个窗口' % (len(doc.get('workspaces') or []),
                                                len(doc.get('windows') or [])))
    for ws in doc.get('workspaces') or []:
        mark = '*' if ws.get('is_focused') else (' ' if not ws.get('is_active') else '+')
        print('  %s ws%-2s %-12s %-8s 窗口%d' % (mark, ws.get('idx'), ws.get('name') or '',
                                                ws.get('output'), ws.get('window_count')))
    for w in doc.get('windows') or []:
        print('    %-6s ws%-2s %-22s %s' % (
            ('*' + str(w.get('id')) if w.get('is_focused') else w.get('id')),
            w.get('workspace_idx'), (w.get('app_id') or '')[:22], (w.get('title') or '')[:70]))
    sessions = doc.get('sessions') or []
    print('活跃会话      %d 个（快照时）' % len(sessions))
    for s in sessions:
        print('    %s/%s idle=%ss %s' % (s['home'], s['session'][:8], s.get('idle_s'), s.get('cwd')))
    try:
        for label, root in (('整屏', SHOTS), ('每窗口', WINSHOTS)):
            count = sum(len(ns) for _r, _d, ns in os.walk(root))
            total = sum(os.path.getsize(os.path.join(r, n))
                        for r, _d, ns in os.walk(root) for n in ns)
            print('%s截图      %d 张 / %.1f MB' % (label, count, total / 1048576.0))
        print('磁盘剩余      %.0f GB' % (shutil.disk_usage(WATCH).free / 1024 ** 3))
    except OSError:
        pass
    return 0


def cmd_windows(args):
    env = user_env()
    doc = windows_doc(env)
    if doc.get('error'):
        print('niri 错误: %s' % (doc.get('error'),))
        return 1
    for ws in doc.get('workspaces') or []:
        print('ws%-2s %-10s %-6s %s' % (ws.get('idx'), ws.get('name') or '', ws.get('output'),
                                       'focused' if ws.get('is_focused') else ''))
        for w in doc.get('windows') or []:
            if w.get('workspace_id') != ws.get('id'):
                continue
            print('   %s%-7s %-24s %s' % ('*' if w.get('is_focused') else ' ', w.get('id'),
                                          (w.get('app_id') or '')[:24],
                                          (w.get('title') or '')[:80]))
    return 0


def cmd_events(args):
    minutes = float(args.get('minutes') or 60)
    cutoff = now_ts() - minutes * 60
    rows = [r for r in tail_jsonl(EVENTS_JSONL, 5000) if r.get('ts', 0) >= cutoff]
    for r in rows:
        w = r.get('window') or {}
        extra = ''
        if r['kind'] == 'focus-change':
            extra = ' -> %s' % ((r.get('to_app_id') or '') + ' ' + (r.get('to_title') or ''))[:90]
        elif r['kind'] in ('window-open', 'window-close'):
            extra = ' %s ws%s %s' % (w.get('app_id'), w.get('workspace_idx'), (w.get('title') or '')[:70])
        elif r['kind'] == 'focus-in':
            extra = ' %s %s' % (w.get('app_id'), (w.get('title') or '')[:60])
        print('%s %-22s %s%s' % (datetime.fromtimestamp(r['ts']).strftime('%H:%M:%S'),
                                 r['kind'], (w.get('app_id') or ''), extra))
    print('-- %d 条（最近 %g 分钟）' % (len(rows), minutes))
    return 0


def cmd_shots(args):
    minutes = float(args.get('minutes') or 60)
    cutoff = now_ts() - minutes * 60
    rows = [r for r in tail_jsonl(SHOTS_JSONL, 3000) if r.get('ts', 0) >= cutoff]
    for r in rows:
        print('%s %-28s %8d B %s' % (r.get('at'), r.get('path'), r.get('bytes') or 0,
                                     r.get('error') or ''))
    print('-- %d 张（最近 %g 分钟）；最新: %s' % (
        len(rows), minutes, os.path.join(WATCH, 'latest.jpg')))
    return 0


def cmd_prune(args):
    removed, freed, total = prune_all()
    print('删除 %d 张，释放 %.1f MB，剩余 %.1f MB' % (removed, freed / 1048576.0, total / 1048576.0))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else 'snapshot'
    args = {}
    for i, a in enumerate(argv):
        if a in ('-m', '--minutes') and i + 1 < len(argv):
            args['minutes'] = argv[i + 1]
        if a in ('-q', '--quiet'):
            args['quiet'] = True
    if cmd == 'status':
        return cmd_status(args)
    if cmd == 'windows':
        return cmd_windows(args)
    if cmd == 'events':
        return cmd_events(args)
    if cmd == 'shots':
        return cmd_shots(args)
    if cmd == 'prune':
        return cmd_prune(args)
    return cmd_snapshot(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))

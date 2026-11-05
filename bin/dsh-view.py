#!/usr/bin/env python3
"""dsh-view.py -- 本机 Web 面板：看见"别的工作区 / 别的环境里跑的程序"，并能一键接手。

数据来自 dsh-observe.py 每分钟的产物（~/.dsh/watch/）：
  - latest.json        最新一次快照（窗口、工作区、输出、活跃会话、截图路径）
  - winshots/.../ID.jpg 每个窗口的截图（fork 的 ScopedScreenshot，别的工作区也抓得到）
  - shots/.../HHMMSS.jpg 当前工作区整屏截图
  - events.jsonl       开窗/关窗/换焦点/搬工作区事件

用法：
  dsh-view.py --port 8793        # 常驻服务，仅监听 127.0.0.1
  → 浏览器打开 http://127.0.0.1:8793/
"""

import argparse
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from string import Template
from urllib.parse import unquote, urlparse

HOME = os.path.expanduser('~')
DSH = os.path.join(HOME, '.dsh')
WATCH = os.path.join(DSH, 'watch')
LATEST = os.path.join(WATCH, 'latest.json')
SHOTS_JSONL = os.path.join(WATCH, 'shots.jsonl')
EVENTS_JSONL = os.path.join(WATCH, 'events.jsonl')
OBSERVE = os.path.join(DSH, 'bin', 'dsh-observe.py')
DESKTOPS_BIN = os.path.join(DSH, 'bin', 'dsh-desktops.py')
DESKTOPS_JSON = os.path.join(WATCH, 'desktops.json')
NIRI = '/usr/local/bin/niri'


def user_env():
    env = dict(os.environ)
    try:
        out = subprocess.run(['systemctl', '--user', 'show-environment'],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ''
    for line in out.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            if k in ('WAYLAND_DISPLAY', 'NIRI_SOCKET', 'XDG_RUNTIME_DIR', 'DISPLAY'):
                env[k] = v
    env.setdefault('XDG_RUNTIME_DIR', '/run/user/%d' % os.getuid())
    return env


def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def tail_jsonl(path, n):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()[-n:]
    except OSError:
        return []
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def niri_action(env, *args, timeout=10):
    try:
        res = subprocess.run([NIRI, 'msg', 'action', *args], env=env,
                             capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {'ok': False, 'error': str(exc)}
    return {'ok': res.returncode == 0,
            'detail': (res.stdout or res.stderr or '').strip()[:300]}


def focused_workspace_idx(env):
    try:
        res = subprocess.run([NIRI, 'msg', '-j', 'workspaces'], env=env,
                             capture_output=True, text=True, timeout=10)
        for ws in json.loads(res.stdout):
            if ws.get('is_focused'):
                return ws.get('idx')
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def run_observe(env):
    try:
        res = subprocess.run([sys.executable, OBSERVE, 'snapshot', '--quiet'], env=env,
                             capture_output=True, text=True, timeout=60)
        return {'ok': res.returncode == 0,
                'detail': (res.stdout or res.stderr or '').strip()[:300]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {'ok': False, 'error': str(exc)}


def run_desktops(env, *args, timeout=90):
    try:
        res = subprocess.run([sys.executable, DESKTOPS_BIN, *args], env=env,
                             capture_output=True, text=True, timeout=timeout)
        return {'ok': res.returncode == 0,
                'detail': (res.stdout or res.stderr or '').strip()[:300]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {'ok': False, 'error': str(exc)}


def desktop_action(payload):
    """把面板上的操作转给 dsh-desktops.py action（往"别的桌面"里送输入）。"""
    env = dict(os.environ)
    op = (payload or {}).get('op')
    if op == 'snapshot':
        return run_desktops(env, 'snapshot', '--quiet')
    key = (payload or {}).get('desktop')
    if not key:
        return {'ok': False, 'error': 'missing desktop'}
    argv = [key, op]
    try:
        if op in ('focus-window', 'close-window'):
            argv += ['--window', str(int(payload.get('window')))]
        elif op == 'type':
            argv += ['--text', str(payload.get('text') or '')]
        elif op == 'key':
            argv += ['--combo', str(payload.get('combo') or 'Return')]
        elif op == 'click':
            argv += ['--x', str(int(payload.get('x'))), '--y', str(int(payload.get('y')))]
        else:
            return {'ok': False, 'error': 'unknown op: %s' % (op,)}
    except (TypeError, ValueError) as exc:
        return {'ok': False, 'error': 'bad request: %s' % exc}
    return run_desktops(env, 'action', *argv)


def unit_state(name):
    try:
        return subprocess.run(['systemctl', '--user', 'is-active', name],
                              capture_output=True, text=True, timeout=5).stdout.strip() or 'unknown'
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def state_payload():
    doc = read_json(LATEST) or {}
    now = time.time()
    return {
        'now': now,
        'age_s': int(now - doc.get('ts', 0)) if doc.get('ts') else None,
        'latest': doc,
        'shots': tail_jsonl(SHOTS_JSONL, 200)[-160:],
        'events': tail_jsonl(EVENTS_JSONL, 160)[-80:],
        'desktops': read_json(DESKTOPS_JSON) or {'desktops': []},
        'units': {'observe_timer': unit_state('dsh-observe.timer'),
                  'view_service': unit_state('dsh-view.service')},
    }


def do_action(payload):
    kind = (payload or {}).get('type')
    env = user_env()
    if kind == 'snapshot':
        return run_observe(env)
    if kind == 'focus-window':
        wid = int(payload.get('window'))
        return niri_action(env, 'focus-window', '--id', str(wid))
    if kind == 'focus-workspace':
        idx = int(payload.get('idx'))
        return niri_action(env, 'focus-workspace', str(idx))
    if kind == 'move-to-current':
        wid = int(payload.get('window'))
        idx = focused_workspace_idx(env)
        if idx is None:
            return {'ok': False, 'error': '找不到当前工作区'}
        return niri_action(env, 'move-window-to-workspace', '--window-id', str(wid), str(idx))
    return {'ok': False, 'error': 'unknown action: %s' % (kind,)}


PAGE = Template('''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>DSH 观察台</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e6e9ef;--dim:#8b93a1;--acc:#4c9aff;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 -apple-system,"Segoe UI","Noto Sans CJK SC",sans-serif}
a{color:var(--acc)}
header{position:sticky;top:0;z-index:5;display:flex;gap:14px;align-items:center;padding:10px 16px;background:#12151c;border-bottom:1px solid var(--line)}
header h1{font-size:15px;margin:0;font-weight:600}
.pill{padding:1px 8px;border:1px solid var(--line);border-radius:99px;color:var(--dim);font-size:12px}
.pill.ok{color:var(--ok);border-color:#1f3d26}
.pill.warn{color:var(--warn);border-color:#3d3313}
button{background:#1f242e;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer}
button:hover{border-color:var(--acc);color:#fff}
button.primary{background:#173a63;border-color:#2b5f9e}
main{padding:14px 16px 40px;max-width:1800px;margin:0 auto}
section{margin-bottom:18px}
h2{font-size:13px;color:var(--dim);font-weight:600;margin:0 0 8px;text-transform:uppercase;letter-spacing:.04em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.card.focused{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc) inset}
.card img{width:100%;height:190px;object-fit:cover;object-position:top left;background:#0b0d11;cursor:zoom-in;display:block}
.card .meta{padding:8px 10px;display:flex;flex-direction:column;gap:4px}
.card .t{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card .s{color:var(--dim);font-size:12px;display:flex;gap:8px;flex-wrap:wrap}
.card .row{display:flex;gap:6px;margin-top:4px}
.badge{font-size:11px;padding:0 6px;border-radius:4px;background:#202634;color:var(--dim)}
.badge.f{background:#173a63;color:#9cc7ff}
.badge.ws{background:#232b1f;color:#a6d189}
.strip{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px}
.strip figure{margin:0;flex:0 0 auto;width:190px}
.strip img{width:190px;height:110px;object-fit:cover;object-position:top left;border:1px solid var(--line);border-radius:6px;cursor:zoom-in;background:#0b0d11}
.strip figcaption{color:var(--dim);font-size:11px;padding-top:2px;display:flex;justify-content:space-between}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:3px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:500}
td.dim{color:var(--dim)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{border:1px solid var(--line);border-radius:8px;padding:5px 9px;background:var(--card);font-size:12px}
.chip b{font-weight:600}
.chip span{color:var(--dim)}
#modal{position:fixed;inset:0;background:#000d;display:none;align-items:center;justify-content:center;z-index:50;padding:24px;flex-direction:column;gap:8px}
#modal.on{display:flex}
#modal img{max-width:96vw;max-height:86vh;object-fit:contain;border:1px solid var(--line);border-radius:8px;background:#fff}
#modal .cap{color:#ccd;font-size:12px}
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#1c2433;border:1px solid var(--line);padding:8px 14px;border-radius:8px;opacity:0;transition:opacity .2s;z-index:60;font-size:12px}
#toast.on{opacity:1}
.empty{color:var(--dim);padding:18px;border:1px dashed var(--line);border-radius:10px;text-align:center}
.card.desk img{height:300px;object-fit:contain;object-position:center}
.card.desk.click img{cursor:crosshair}
.card.desk button.win{max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card.desk button.win.f{border-color:var(--acc);color:#9cc7ff}
.card.desk input{background:#0d1015;border:1px solid var(--line);border-radius:6px;color:var(--fg);padding:4px 8px;font-size:12px}
</style></head>
<body>
<header>
  <h1>DSH 观察台</h1>
  <span id="ver" class="pill">—</span>
  <span id="age" class="pill">—</span>
  <span id="timer" class="pill">—</span>
  <span id="clock" class="pill">—</span>
  <button class="primary" onclick="act('snapshot')">立即截一张</button>
  <button onclick="refresh()">刷新</button>
  <span class="pill" style="margin-left:auto">只读展示 · 除“切过去/搬过来”按钮外不改桌面</span>
</header>
<main>
  <section><h2>活跃会话</h2><div id="sessions" class="chips"></div></section>
  <section><h2>其他桌面（agent 在嵌套环境里跑的 · 点图看大图，开“点击接管”后点图就是点它）</h2><div id="desktops" class="grid"></div></section>
  <section><h2>窗口（每个窗口单独截图，别的工作区也在内）</h2><div id="windows" class="grid"></div></section>
  <section><h2>工作区</h2><div id="workspaces" class="chips"></div></section>
  <section><h2>整屏时间轴（每分钟一张，点开看大图）</h2><div id="strip" class="strip"></div></section>
  <section><h2>事件（开窗 / 关窗 / 换焦点 / 搬工作区）</h2><div id="events"></div></section>
</main>
<div id="modal" onclick="closeModal()"><img id="mimg" alt=""><div class="cap" id="mcap"></div></div>
<div id="toast"></div>
<script>
var S = null;
function esc(v){ return String(v == null ? '' : v).replace(/[&<>"]/g, function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]; }); }
function ago(ts){ var d = Date.now()/1000 - ts; if (d < 0) d = 0; if (d < 60) return Math.round(d) + ' 秒前'; if (d < 3600) return Math.round(d/60) + ' 分钟前'; return Math.round(d/3600) + ' 小时前'; }
function clock(){ document.getElementById('clock').textContent = new Date().toLocaleTimeString('zh-CN', {hour12:false}); }
function openModal(src, cap){ document.getElementById('mimg').src = src; document.getElementById('mcap').textContent = cap || ''; document.getElementById('modal').classList.add('on'); }
function closeModal(){ document.getElementById('modal').classList.remove('on'); }
function toast(msg, bad){ var t = document.getElementById('toast'); t.textContent = msg; t.style.color = bad ? '#ff8a8a' : '#cfe6ff'; t.classList.add('on'); setTimeout(function(){ t.classList.remove('on'); }, 2200); }
async function act(type, extra){
  var body = Object.assign({type: type}, extra || {});
  try {
    var r = await fetch('/api/action', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    var j = await r.json();
    toast((j.ok ? '已执行: ' : '失败: ') + (j.detail || j.error || ''), !j.ok);
  } catch (e) { toast('请求失败: ' + e, true); }
  setTimeout(refresh, 400);
}
var clickMode = {};
async function dact(key, op, extra){
  var body = Object.assign({desktop: key, op: op}, extra || {});
  try {
    var r = await fetch('/api/desktop', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    var j = await r.json();
    toast((j.ok ? '已执行: ' : '失败: ') + (j.detail || j.error || ''), !j.ok);
  } catch (e) { toast('请求失败: ' + e, true); }
  setTimeout(refresh, 400);
}
function dtype(key){
  var i = document.getElementById('ti-' + key);
  if (!i || !i.value) { toast('先输入点东西', true); return; }
  var v = i.value; i.value = '';
  dact(key, 'type', {text: v});
}
function dkey(key, combo){ dact(key, 'key', {combo: combo}); }
function dclickmode(key){
  clickMode[key] = !clickMode[key];
  var c = document.getElementById('desk-' + key);
  if (c) c.className = 'card desk' + (clickMode[key] ? ' click' : '');
  var b = document.getElementById('cm-' + key);
  if (b) b.className = clickMode[key] ? 'primary' : '';
  toast(clickMode[key] ? '点击接管已打开：在截图上点就是点那个桌面' : '点击接管已关闭');
}
function deskClick(ev, img){
  var key = img.getAttribute('data-key');
  if (!clickMode[key]) { openModal(img.src, '桌面截图'); return; }
  var rect = img.getBoundingClientRect();
  var nw = img.naturalWidth || rect.width, nh = img.naturalHeight || rect.height;
  var scale = Math.min(rect.width / nw, rect.height / nh);
  var ox = (rect.width - nw * scale) / 2, oy = (rect.height - nh * scale) / 2;
  var x = Math.round((ev.clientX - rect.left - ox) / scale * 2);
  var y = Math.round((ev.clientY - rect.top - oy) / scale * 2);
  if (x < 0 || y < 0) { toast('点在图外了', true); return; }
  dact(key, 'click', {x: x, y: y});
}
function render(s){
  S = s;
  var L = s.latest || {};
  document.getElementById('ver').textContent = (L.wm || 'niri') + ' ' + (L.version || '?');
  document.getElementById('age').textContent = s.age_s == null ? '还没有快照' : ('快照 ' + s.age_s + ' 秒前');
  var tm = document.getElementById('timer'); tm.textContent = '每分钟采集: ' + (s.units && s.units.observe_timer || '?');
  tm.className = 'pill ' + ((s.units && s.units.observe_timer == 'active') ? 'ok' : 'warn');
  var ses = L.sessions || [];
  document.getElementById('sessions').innerHTML = ses.length ? ses.map(function(x){
    return '<div class="chip"><b>' + esc(x.session.slice(0,8)) + '</b> <span>' + esc(x.home) + ' · ' + esc(x.cwd) + ' · idle ' + esc(x.idle_s) + 's</span></div>';
  }).join('') : '<span class="empty">最近 5 分钟没有活跃会话</span>';
  var ws = L.windows || [];
  var grid = document.getElementById('windows');
  grid.innerHTML = ws.length ? ws.map(function(w){
    var img = (w.shot && w.shot.path) ? '/img/' + encodeURI(w.shot.path) + '?t=' + Math.round(L.ts || 0) : '';
    var bad = (w.shot && w.shot.error) ? '<span class="badge">截图失败</span>' : '';
    return '<div class="card' + (w.is_focused ? ' focused' : '') + '">' +
      (img ? '<img src="' + img + '" onclick="openModal(this.src, ' + JSON.stringify((w.title || '') + ' · ' + (w.app_id || '')).replace(/"/g, '&quot;') + ')">' : '<div class="empty">没有截图</div>') +
      '<div class="meta"><div class="t">' + esc(w.title) + '</div>' +
      '<div class="s"><span>' + esc(w.app_id) + '</span><span>ws' + esc(w.workspace_idx) + '</span><span>id ' + esc(w.id) + '</span>' + (w.pid ? '<span>pid ' + esc(w.pid) + '</span>' : '') + bad + '</div>' +
      '<div class="row"><button onclick="act(&#39;focus-window&#39;,{window:' + w.id + '})">切过去</button>' +
      '<button onclick="act(&#39;move-to-current&#39;,{window:' + w.id + '})">搬到我这边</button>' +
      (w.is_floating ? '<span class="badge">浮动</span>' : '') + (w.is_focused ? '<span class="badge f">当前焦点</span>' : '') + '</div></div></div>';
  }).join('') : '<div class="empty">没有可见窗口</div>';
  var wss = L.workspaces || [];
  document.getElementById('workspaces').innerHTML = wss.map(function(x){
    return '<div class="chip">' + (x.is_focused ? '<b>ws' + esc(x.idx) + '</b>' : 'ws' + esc(x.idx)) +
      ' <span>' + esc(x.output) + ' · ' + esc(x.window_count) + ' 窗口' + (x.window_count ? '' : '（空）') + '</span>' +
      (x.window_count ? '' : ' <button onclick="act(&#39;focus-workspace&#39;,{idx:' + x.idx + '})">切过去</button>') + '</div>';
  }).join('');
  var sh = s.shots || [];
  document.getElementById('strip').innerHTML = sh.length ? sh.slice().reverse().slice(0, 120).map(function(x){
    var u = x.path ? '/img/' + encodeURI(x.path) : '';
    return '<figure>' + (u ? '<img src="' + u + '" onclick="openModal(this.src, ' + JSON.stringify(x.at || '').replace(/"/g, '&quot;') + ')">' : '') +
      '<figcaption><span>' + esc((x.at || '').slice(11)) + '</span><span>' + Math.round((x.bytes || 0)/1024) + ' KB</span></figcaption></figure>';
  }).join('') : '<span class="empty">还没有整屏截图</span>';
  var ev = s.events || [];
  document.getElementById('events').innerHTML = ev.length ? '<table><tr><th>时间</th><th>事件</th><th>窗口</th><th>细节</th></tr>' + ev.slice().reverse().slice(0,60).map(function(e){
    var w = e.window || {};
    var det = '';
    if (e.kind == 'focus-change') det = (e.to_app_id || '') + ' ' + (e.to_title || '');
    else if (e.kind == 'window-open' || e.kind == 'window-close') det = 'ws' + (w.workspace_idx || '?') + ' · ' + (w.title || '');
    else if (e.kind == 'window-move-workspace') det = 'ws' + (e.from_workspace || '?') + ' → ws' + (e.to_workspace || '?') + ' · ' + (w.title || '');
    else if (e.kind == 'window-retitle') det = (e.old_title || '') + ' → ' + (w.title || '');
    else det = JSON.stringify(e).slice(0, 140);
    return '<tr><td class="dim">' + esc(new Date((e.ts || 0) * 1000).toLocaleTimeString('zh-CN', {hour12:false})) + '</td><td>' + esc(e.kind) +
      '</td><td>' + esc(w.app_id || e.to_app_id || '') + '</td><td class="dim">' + esc(det) + '</td></tr>';
  }).join('') + '</table>' : '<span class="empty">还没有事件（开始采集后，打开/关闭窗口会记一条）</span>';
  var ds = (s.desktops && s.desktops.desktops) || [];
  document.getElementById('desktops').innerHTML = ds.length ? ds.map(function(d){
    var key = d.key;
    var shot = (d.shot && d.shot.path) ? '/img/' + encodeURI(d.shot.path) + '?t=' + Math.round(d.ts || 0) : '';
    var err = (d.shot && d.shot.error) ? '<span class="badge">截图失败</span>' : '';
    var wins = d.windows || [];
    var winbtns = wins.map(function(w){
      var lab = (w.title || w.app_id || '窗口');
      return '<button class="win' + (w.is_focused ? ' f' : '') + '" title="' + esc(lab) + '" onclick="dact(' + JSON.stringify(key) + ',&#39;focus-window&#39;,{window:' + w.id + '})">' + esc(lab.slice(0, 16)) + '</button>';
    }).join('');
    return '<div class="card desk' + (clickMode[key] ? ' click' : '') + '" id="desk-' + esc(key) + '">' +
      (shot ? '<img src="' + shot + '" data-key="' + esc(key) + '" onclick="deskClick(event, this)">'
            : '<div class="empty">还没有截图</div>') +
      '<div class="meta">' +
        '<div class="t">' + esc(d.label) + ' <span class="badge">' + esc(d.kind) + '</span>' + err + '</div>' +
        '<div class="s"><span>' + wins.length + ' 窗口</span><span>X ' + esc(d.x_display || '-') + '</span><span>' + esc((d.version || '').slice(0, 30)) + '</span><span>' + esc((d.at || '').slice(11)) + '</span></div>' +
        (winbtns ? '<div class="row">' + winbtns + '</div>' : '') +
        '<div class="row"><input id="ti-' + esc(key) + '" placeholder="往这个桌面里打字…"><button onclick="dtype(' + JSON.stringify(key) + ')">发送</button>' +
          '<button onclick="dkey(' + JSON.stringify(key) + ',&#39;Return&#39;)">回车</button></div>' +
        '<div class="row"><button onclick="dact(' + JSON.stringify(key) + ',&#39;snapshot&#39;,null)">立即截一张</button>' +
          '<button id="cm-' + esc(key) + '" onclick="dclickmode(' + JSON.stringify(key) + ')">点击接管</button></div>' +
      '</div></div>';
  }).join('') : '<div class="empty">现在没有别的桌面（agent 在嵌套环境里跑程序时，这里会出现它的实时画面和窗口）</div>';
}
async function refresh(){
  try {
    var r = await fetch('/api/state', {cache:'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    render(await r.json());
  } catch (e) {
    document.getElementById('age').textContent = '拉取失败: ' + e;
  }
}
clock(); setInterval(clock, 1000); refresh(); setInterval(refresh, 4000);
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeModal(); });
</script>
</body></html>
''')


class Handler(BaseHTTPRequestHandler):
    server_version = 'dsh-view/1.0'

    def _send(self, code, body, ctype='text/html; charset=utf-8', extra=None):
        data = body if isinstance(body, bytes) else body.encode('utf-8', 'replace')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8')

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html'):
            return self._send(200, PAGE.substitute())
        if path == '/api/state':
            return self._json(state_payload())
        if path.startswith('/img/'):
            return self._serve_image(unquote(path[5:]))
        return self._send(404, 'not found', 'text/plain; charset=utf-8')

    def _serve_image(self, rel):
        rel = os.path.normpath(rel).lstrip('/')
        full = os.path.normpath(os.path.join(WATCH, rel))
        if not full.startswith(WATCH + os.sep) or not os.path.isfile(full):
            return self._send(404, 'no such image', 'text/plain; charset=utf-8')
        ext = os.path.splitext(full)[1].lower()
        ctype = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}.get(ext, 'application/octet-stream')
        try:
            with open(full, 'rb') as fh:
                data = fh.read()
        except OSError:
            return self._send(404, 'unreadable', 'text/plain; charset=utf-8')
        return self._send(200, data, ctype)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ('/api/action', '/api/desktop'):
            return self._json({'ok': False, 'error': 'not found'}, 404)
        try:
            length = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError, OSError):
            return self._json({'ok': False, 'error': 'bad json'}, 400)
        try:
            fn = desktop_action if path == '/api/desktop' else do_action
            return self._json(fn(payload))
        except (TypeError, ValueError) as exc:
            return self._json({'ok': False, 'error': 'bad request: %s' % exc}, 400)

    def log_message(self, fmt, *args):
        sys.stderr.write('%s %s\n' % (time.strftime('%H:%M:%S'), fmt % args))


def main(argv):
    ap = argparse.ArgumentParser(description='DSH 观察台')
    ap.add_argument('--port', type=int, default=8793)
    ap.add_argument('--bind', default='127.0.0.1')
    args = ap.parse_args(argv[1:])
    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    print('dsh-view 监听 http://%s:%d/' % (args.bind, args.port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

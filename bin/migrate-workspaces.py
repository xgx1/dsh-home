#!/usr/bin/env python3
"""把历史会话按 cwd 归进工作区，清掉 GUI 侧栏的「未分组」（2026-11-17 用户要求）。

DSH 的 GUI 只有"工作区"这一层分组：会话的 header cwd 等于某个工作区的 path，它才挂得进去；
以前任务台起的会话坐在 `<DSH_HOME>/task-manager/{console,exec}` 这种临时目录里，没登记工作区，
于是全部堆在「未分组」。这个一次性脚本按 header 里的 cwd 给每组会话建一个工作区并挂上去。

用法：
  python3 migrate-workspaces.py --home ~/.dsh-dev --dry-run
  python3 migrate-workspaces.py --home ~/.dsh-dev          # 写文件（先停实例）

工作区的成员校验在加载时会按 cwd 过滤，所以挂错的条目会被 DSH 自己剔掉，不会留下坏数据。
"""
import argparse, json, os, subprocess, sys, time, uuid

def read_header(path):
    try:
        raw = subprocess.run(['zstd','-dc',path], capture_output=True, timeout=60).stdout
    except Exception:
        return None
    first = raw.split(b'\n', 1)[0]
    try:
        event = json.loads(first)
    except Exception:
        return None
    if event.get('type') != 'session':
        return None
    cwd = event.get('cwd')
    sid = event.get('id')
    if not isinstance(cwd, str) or not isinstance(sid, str):
        return None
    return sid, cwd, event.get('createdAt', 0)

def title_for(cwd):
    if cwd.endswith('/task-manager/console') or cwd.endswith('/task-manager/manager'):
        return '任务台·管理器'
    if cwd.endswith('/task-manager/exec'):
        return '任务台·执行位'
    parts = [p for p in cwd.split('/') if p]
    return parts[-1] if parts else cwd

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--home', default=os.path.expanduser('~/.dsh-dev'))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    store = os.path.join(args.home, 'storages', 'workspace.json')
    data = json.load(open(store, encoding='utf-8'))
    table = data['tables']['workspaces']
    global_ = data['global']
    by_path = {v['path']: wid for wid, v in table.items()}
    attached = {sid for v in table.values() for sid in (v.get('sessionIds') or [])}

    groups, unknown = {}, 0
    sessions_root = os.path.join(args.home, 'sessions')
    for dirpath, _dirs, files in os.walk(sessions_root, topdown=True):
        if 'session.v4.jsonl.zstd' not in files:
            continue
        header = read_header(os.path.join(dirpath, 'session.v4.jsonl.zstd'))
        if header is None:
            unknown += 1
            continue
        sid, cwd, created = header
        if sid in attached:
            continue
        groups.setdefault(cwd, []).append((created, sid))

    created_ids = []
    for cwd, items in sorted(groups.items()):
        if not os.path.isdir(cwd):
            unknown += len(items)
            continue
        wid = by_path.get(cwd)
        if wid is None:
            wid = str(uuid.uuid4())
            now = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
            table[wid] = {'path': cwd, 'title': title_for(cwd), 'sessionIds': [],
                          'createdAt': now, 'updatedAt': now}
            by_path[cwd] = wid
            created_ids.append(wid)
        items.sort(reverse=True)
        target = table[wid]
        existing = set(target.get('sessionIds') or [])
        added = [sid for _c, sid in items if sid not in existing]
        target['sessionIds'] = added + list(target.get('sessionIds') or [])
        print('%-40s %s: +%d 会话' % (title_for(cwd)[:40], cwd[-46:], len(added)))

    if created_ids:
        global_['workspaceIds'] = created_ids + list(global_.get('workspaceIds') or [])
    print('新工作区 %d 个；跳过 %d 个（目录不存在或日志读不出）' % (len(created_ids), unknown))
    if args.dry_run:
        print('（dry-run，没有写文件）')
        return
    tmp = store + '.tmp'
    json.dump(data, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(tmp, store)
    print('已写入', store)

if __name__ == '__main__':
    main()

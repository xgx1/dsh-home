#!/usr/bin/env node
// 只读查询 Turso 会话库。writer 进程对库文件持排他锁（python sqlite3 打不开），
// 所以只能经 turso 驱动以 readonly 打开：并发可读，每次新开都能看到最新已提交事件。
// 用法：
//   dsh-sessions-db.mjs list   <db> <since-ms>                 # 活跃会话一行一条 JSON
//   dsh-sessions-db.mjs events <db> <session-id> <after-seq> <since-ms>  # 事件一行一条 JSON
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
const roots = [process.env.DSH_TURSO_ROOT, '/home/sx/projects/MyAI/deepseek-harness',
  '/home/sx/projects/MyAI/deepseek-harness-dev'].filter(Boolean)
let mod
for (const root of roots) {
  try {
    mod = await import(pathToFileURL(require.resolve('@tursodatabase/database', { paths: [root] })).href)
    break
  } catch { /* try the next checkout */ }
}
if (!mod) {
  console.error('dsh-sessions-db: cannot resolve @tursodatabase/database')
  process.exit(2)
}

const [mode, dbPath, ...rest] = process.argv.slice(2)
if (!dbPath || !mode) {
  console.error('usage: dsh-sessions-db.mjs <list|events> <db> ...')
  process.exit(2)
}

const db = await mod.connect(dbPath, { readonly: true, fileMustExist: true })
const emit = row => process.stdout.write(JSON.stringify(row) + '\n')

try {
  if (mode === 'list') {
    const since = Number(rest[0] ?? 0)
    const rows = await db.prepare(`SELECT s.id AS id, s.header AS header,
      (SELECT COUNT(*) FROM events e WHERE e.session_id = s.id) AS n,
      (SELECT e.seq FROM events e WHERE e.session_id = s.id ORDER BY e.seq DESC LIMIT 1) AS lastSeq,
      (SELECT e.event FROM events e WHERE e.session_id = s.id ORDER BY e.seq DESC LIMIT 1) AS lastEvent
      FROM sessions s`).all()
    for (const row of rows) {
      const header = JSON.parse(row.header)
      const last = row.lastEvent === null ? undefined : JSON.parse(row.lastEvent)
      const lastTime = last ? (last.time ?? 0) : (header.createdAt ?? 0)
      const lastEventSeq = last ? (last.seq ?? row.lastSeq) : -1
      if (lastTime < since) continue
      emit({ id: row.id, cwd: header.cwd ?? '', createdAt: header.createdAt ?? 0,
        eventCount: row.n, lastSeq: lastEventSeq, lastTime })
    }
  } else if (mode === 'events') {
    const [id, afterSeqRaw, sinceRaw] = rest
    const afterSeq = Number(afterSeqRaw ?? -1)
    const since = Number(sinceRaw ?? 0)
    const rows = await db.prepare('SELECT event FROM events WHERE session_id = ? AND seq > ? ORDER BY seq').all(id, afterSeq)
    for (const row of rows) {
      const event = JSON.parse(row.event)
      if (since && (event.time ?? 0) < since) continue
      emit(event)
    }
  } else {
    console.error('dsh-sessions-db: unknown mode ' + mode)
    process.exit(2)
  }
} finally {
  await db.close()
}
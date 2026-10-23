#!/usr/bin/env node
/**
 * zg-autoidx —— zvec-grep MCP 的 stdio 代理，给「工作区没有索引」自动补建索引。
 *
 * 背景（2026-10-23 事故）：zvec-grep 的语义检索（zvec_grep_search）要求工作区已建
 * 索引，未建时 daemon 抛 INDEX_MISSING，模型只能退到 rg。可用的 `zg index` 手建索引
 * 从来没人触发过，于是每个新仓库都白瞎一轮。用户 2026-10-23 授权：调用时自动建。
 *
 * 做法：本进程原样转发 dsh ⇄ `zg server --stdio` 的全部 JSON-RPC 行；只在
 * **响应**里看到 INDEX_MISSING 时拦一下：解析出工作区根，后台起 `zg index`
 * （同一根单飞行、带锁、日志入 /tmp/zvec-autoidx.log），最多等 AUTOIDX_WAIT_MS，
 * 然后在返回给模型的文本里追加一句「索引已建好，重试本查询」/「索引构建中」。
 *
 * 不改 npm 包、不 fork daemon，改一行 MCP command 即可启用/回滚。
 */
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { appendFileSync, existsSync, mkdirSync, openSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const ZG_CLI = '/home/sx/.npm-global/lib/node_modules/@zvec/zvec-grep/dist/cli/index.js'
const LOG_PATH = '/tmp/zvec-autoidx.log'
const LOCK_DIR = '/tmp/zvec-autoidx-locks'
const EMBEDDING = 'local/potion-code-16m-v2'
const DEFAULT_DEVICE = 'cpu'
const AUTOIDX_WAIT_MS = Number(process.env.ZG_AUTOIDX_WAIT_MS ?? 40_000)

/** @param {...unknown} parts */
function log(...parts) {
  const line = `${new Date().toISOString()} ${parts.map(p => typeof p === 'string' ? p : JSON.stringify(p)).join(' ')}\n`
  try { appendFileSync(LOG_PATH, line) } catch {}
}

/** 正在构建中的工作区根 → 完成信号 */
const inflight = new Map()

/**
 * 后台为一个工作区建索引（同根单飞行 + 跨进程锁）。
 * @param {string} root 工作区绝对路径
 * @returns {Promise<'built'|'failed'|'busy'>} 本次是否等到构建结束
 */
function buildIndex(root) {
  const existing = inflight.get(root)
  if (existing) return existing

  const key = createHash('sha1').update(root).digest('hex').slice(0, 16)
  const lock = join(LOCK_DIR, `${key}.lock`)
  try { mkdirSync(LOCK_DIR, { recursive: true }) } catch {}

  const promise = (async () => {
    if (existsSync(lock)) {
      let holder
      try { holder = Number.parseInt(readFileSync(lock, 'utf8').trim(), 10) } catch {}
      const alive = Number.isFinite(holder) && holder > 0 && (() => {
        try { process.kill(holder, 0); return true } catch { return false }
      })()
      if (alive) {
        log('skip', root, 'locked by live builder', `pid=${String(holder)}`)
        return 'busy'
      }
      log('stale lock removed', lock, `pid=${String(holder)}`)
      try { rmSync(lock, { force: true }) } catch {}
    }
    try { writeFileSync(lock, `${process.pid}\n`) } catch {}

    const started = Date.now()
    log('build start', root, `embedding=${EMBEDDING}`, `device=${DEFAULT_DEVICE}`)
    // 用 bash 包一层：构建进程独立于 dsh 会话（detached+unref），并且**由它自己**把退出码
    // 追加进日志 —— 代理退出后没人能替它记录结果。nice/ionice 让索引构建不跟 UE 构建、
    // 编译抢 CPU/IO。
    const script = [
      'nice -n 10 ionice -c2 -n7 "$ZG_NODE" "$ZG_CLI" index "$ZG_ROOT" --embedding "$ZG_EMBEDDING" --device "$ZG_DEVICE"',
      'code=$?',
      'printf "%s build exit %s code=%s elapsed=%ss\\n" "$(date -Is)" "$ZG_ROOT" "$code" "$SECONDS" >> "$ZG_LOG"',
    ].join('\n')
    const child = spawn('/bin/bash', ['-c', script], {
      cwd: root,
      env: {
        ...process.env,
        ZG_NODE: process.execPath,
        ZG_CLI,
        ZG_ROOT: root,
        ZG_EMBEDDING: EMBEDDING,
        ZG_DEVICE: DEFAULT_DEVICE,
        ZG_LOG: LOG_PATH,
      },
      stdio: 'ignore',
      detached: true,
    })
    child.unref()
    const outcome = await new Promise((resolve) => {
      child.once('error', (error) => { log('build spawn error', root, String(error)); resolve('failed') })
      child.once('exit', (code, signal) => {
        log('build exit', root, `code=${String(code)}`, `signal=${String(signal)}`, `${Math.round((Date.now() - started) / 1000)}s`)
        resolve(code === 0 ? 'built' : 'failed')
      })
    })
    try { rmSync(lock, { force: true }) } catch {}
    return outcome
  })()

  inflight.set(root, promise)
  void promise.finally(() => { inflight.delete(root) })
  return promise
}

/** @param {string} text */
function extractRoot(text) {
  const match = /built zvec-grep index for (.+?)\. (?:Use|Creating)/s.exec(text)
  if (!match) return undefined
  const root = match[1].trim()
  if (!root.startsWith('/') || root === '/' || root === '/home/sx') return undefined
  try { if (!statSync(root).isDirectory()) return undefined } catch { return undefined }
  return root
}

/** 一行一条 JSON-RPC；返回改写后的行（未命中则原样）。 */
async function rewriteResponseLine(line) {
  if (!line.includes('INDEX_MISSING')) return line
  let message
  try { message = JSON.parse(line) } catch { return line }
  const raw = JSON.stringify(message)
  if (!raw.includes('INDEX_MISSING')) return line
  const root = extractRoot(raw)
  if (root === undefined) return line

  const build = buildIndex(root)
  const settled = await Promise.race([
    build,
    new Promise((resolve) => setTimeout(() => resolve('timeout'), AUTOIDX_WAIT_MS)),
  ])

  const note = settled === 'built'
    ? `[zg-autoidx] 已自动为该工作区建好索引（${root}）。直接重试同一次 zvec_grep_search 即可。`
    : settled === 'failed'
      ? `[zg-autoidx] 自动建索引失败（${root}），详情见 ${LOG_PATH}。请改用 zvec_grep_rg 做精确检索。`
      : settled === 'busy'
        ? `[zg-autoidx] 该工作区的索引正在由另一个进程构建（${root}），请稍后重试，期间用 zvec_grep_rg。`
        : `[zg-autoidx] 已自动在后台为该工作区建索引（${root}），构建进程独立于本会话、不会被会话结束杀掉。期间请用 zvec_grep_rg 做精确检索；等日志 ${LOG_PATH} 出现 build exit 后，再重试一次 zvec_grep_search 即可。`

  if (Array.isArray(message?.result?.content)) {
    message.result.content.push({ type: 'text', text: note })
    return JSON.stringify(message)
  }
  if (typeof message?.error?.message === 'string') {
    message.error.message += `\n${note}`
    return JSON.stringify(message)
  }
  if (Array.isArray(message?.result?.tools) === false && typeof message?.result?.content === 'undefined') {
    message.result = { content: [{ type: 'text', text: note }] }
    return JSON.stringify(message)
  }
  return line
}

const child = spawn(process.execPath, [ZG_CLI, ...process.argv.slice(2)], {
  env: process.env,
  stdio: ['pipe', 'pipe', 'inherit'],
})
log('proxy start', process.argv.slice(2).join(' '), `pid=${process.pid}`, `child=${child.pid}`)

/** 按 \n 切行，把整行交给回调；未完片段留在 buffer。 */
function lineSplitter(onLine) {
  let buffer = ''
  return {
    push(chunk) {
      buffer += chunk
      let index
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index)
        buffer = buffer.slice(index + 1)
        onLine(line)
      }
    },
    flush() {
      if (buffer.length > 0) onLine(buffer)
      buffer = ''
    },
  }
}

const stdoutSplitter = lineSplitter((line) => {
  const trimmed = line.trim()
  if (trimmed.length === 0) { process.stdout.write('\n'); return }
  rewriteResponseLine(trimmed)
    .then((rewritten) => { process.stdout.write(`${rewritten}\n`) })
    .catch((error) => { log('rewrite failed', String(error)); process.stdout.write(`${trimmed}\n`) })
})
child.stdout.setEncoding('utf8')
child.stdout.on('data', (chunk) => { stdoutSplitter.push(chunk) })
child.stdout.on('end', () => { stdoutSplitter.flush() })

process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk) => { child.stdin.write(chunk) })
process.stdin.on('end', () => { try { child.stdin.end() } catch {} })

child.on('exit', (code, signal) => {
  log('child exit', `code=${String(code)}`, `signal=${String(signal)}`)
  process.exit(code ?? (signal === null ? 0 : 1))
})
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => { try { child.kill(signal) } catch {} })
}

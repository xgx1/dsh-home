#!/usr/bin/env node
/**
 * ego 标签页看门狗（2026-11-17 用户要求「提高 ego 的并发」）。
 *
 * ego 跑在用户共享的 Helium 上：多个 agent 各开一个任务空间标签页，3080/3081 上攒到二十几个时，
 * 渲染进程被拖死 —— 表现就是 Page.navigate / Runtime.evaluate 全部超时、新标签停在 about:blank。
 *
 * 这里只做一件事：CDP 上看本站点标签页数量，超过上限就关掉**最旧的**几个，
 * 保留最新的 MAX 个。只碰 3080/3081（生产/开发实例），别的标签一概不动。
 *
 * 用法：node ego-tab-janitor.mjs [--dry-run] [--max N]
 */
const MAX = (() => {
  const index = process.argv.indexOf('--max')
  const raw = index === -1 ? process.env['EGO_TAB_MAX'] : process.argv[index + 1]
  const parsed = Number.parseInt(raw ?? '', 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 6
})()
const DRY = process.argv.includes('--dry-run')
const ENDPOINT = process.env['EGO_CDP_ENDPOINT'] ?? 'http://127.0.0.1:9222'

/** 只有这两个端口的标签属于"agent 自己的任务台/控制台"。 */
const OURS = [':3080', ':3081']

const response = await fetch(`${ENDPOINT}/json/list`, { signal: AbortSignal.timeout(8000) }).catch(() => undefined)
if (response === undefined || !response.ok) {
  console.error(`ego-tab-janitor: CDP 不可达（${ENDPOINT}），跳过`)
  process.exit(0)
}
const targets = await response.json().catch(() => [])
const pages = (Array.isArray(targets) ? targets : []).filter(
  (target) => target?.type === 'page' && typeof target.url === 'string' && OURS.some((port) => target.url.includes(port)),
)
const excess = pages.slice(0, Math.max(0, pages.length - MAX))
if (excess.length === 0) {
  console.log(`ego-tab-janitor: ${pages.length} 个任务台标签，未超上限 ${MAX}`)
  process.exit(0)
}
for (const target of excess) {
  const id = String(target.id)
  if (DRY) {
    console.log(`would close ${id} ${target.url.slice(0, 70)}`)
    continue
  }
  const closed = await fetch(`${ENDPOINT}/json/close/${id}`, { signal: AbortSignal.timeout(8000) })
    .then((r) => r.ok)
    .catch(() => false)
  console.log(`${closed ? 'closed' : 'failed'} ${id} ${target.url.slice(0, 70)}`)
}

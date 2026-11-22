/**
 * Fail fast for the "tui" profile: it intentionally has no interactive front
 * door since @deepseek-ai/dsh-tui (turtle-ui) was removed on 2026-11-22
 * (the plugin predates dsh 0.2.2's tools/subagent APIs and cannot boot).
 *
 * Booting the base bundle alone would leave the process alive with no UI, which
 * looks like a hang; exit with an actionable message instead.
 */
const MESSAGE = [
  'dsh: profile "tui" has no front door — @deepseek-ai/dsh-tui (turtle-ui) is not installed.',
  'dsh: use "dsh web" or "dsh headless"; to bring the TUI back:',
  'dsh:   cd ~/.dsh && git checkout -- profiles/tui && dsh plugin --profile tui install',
  '',
].join('\n')

export function apply() {
  process.stderr.write(MESSAGE)
  process.exit(1)
}

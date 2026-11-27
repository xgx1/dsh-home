#!/usr/bin/env node
/**
 * Cross-platform dispatcher for the ponytail Claude Code hooks.
 *
 * Why this exists: DSH runs a hook command through bash on Linux and through
 * pwsh on Windows. The upstream hook snippets use `<VAR>=<value> node <path>`
 * with OS-specific absolute paths (e.g. `/home/sx/projects/...`,
 * `PLUGIN_DATA=/tmp/...`). Neither the POSIX env-prefix syntax nor those paths
 * work under PowerShell. This dispatcher keeps the JSON command shell- and
 * OS-neutral:
 *
 *     node "${CLAUDE_PLUGIN_ROOT}/dsh-skill-hooks.mjs" <hook-id>
 *
 * `${CLAUDE_PLUGIN_ROOT}` is substituted at config-parse time from the plugin's
 * `pluginRoot` (set in the home-level cordis.patch.toml to `dshHomePath('hooks')`),
 * so it resolves per platform. This script then sets the required env vars and
 * spawns the real hook script, forwarding stdin/stdout/stderr verbatim.
 *
 * Skills layout: `<home>/projects/MyAI/dsh-extensions/skills/<skill>`.
 * Override with DSH_SKILLS_ROOT if the checkout lives elsewhere.
 *
 * History: the two caveman hooks were dropped on 2026-11-24 together with the
 * caveman skill group (removed from dsh-extensions/skills on 2026-10-26). They
 * had kept failing with `Cannot find module .../caveman/src/hooks/*.js` on every
 * session start and every prompt. Re-add the targets together with the skill,
 * not before (see skill-context-hooks.json `_removed`).
 */

import { spawnSync } from 'node:child_process'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'

const skills = process.env.DSH_SKILLS_ROOT
  || join(homedir(), 'projects', 'MyAI', 'dsh-extensions', 'skills')
const ponytail = join(skills, 'dietrichgebert-ponytail')
const ponytailState = join(tmpdir(), 'ponytail-state')

/** hook id → the real script, its argv tail, and the env it needs. */
const targets = {
  'ponytail-activate': {
    script: join(ponytail, 'hooks', 'ponytail-activate.js'),
    env: {
      PONYTAIL_DEFAULT_MODE: process.env.PONYTAIL_DEFAULT_MODE || 'ultra',
      PLUGIN_DATA: process.env.PLUGIN_DATA || ponytailState,
    },
  },
  'ponytail-mode-tracker': {
    script: join(ponytail, 'hooks', 'ponytail-mode-tracker.js'),
    env: {
      PONYTAIL_DEFAULT_MODE: process.env.PONYTAIL_DEFAULT_MODE || 'ultra',
      PLUGIN_DATA: process.env.PLUGIN_DATA || ponytailState,
    },
  },
}

const hook = process.argv[2]
const target = Object.hasOwn(targets, hook) ? targets[hook] : undefined
if (target === undefined) {
  process.stderr.write(`dsh-skill-hooks: unknown hook ${JSON.stringify(hook)}; known: ${Object.keys(targets).join(', ')}\n`)
  process.exit(0)
}

// Inherit all three stdio handles: the bridge writes the JSON payload to this
// process's stdin and captures stdout, so the child must read/write the same fds.
const result = spawnSync(process.execPath, [target.script, ...(target.args ?? [])], {
  stdio: ['inherit', 'inherit', 'inherit'],
  env: { ...process.env, ...target.env },
})

if (result.error !== undefined) {
  process.stderr.write(`dsh-skill-hooks: could not run ${hook}: ${result.error.message}\n`)
  process.exit(1)
}
process.exit(result.status ?? 0)

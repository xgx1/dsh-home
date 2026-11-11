#!/usr/bin/env node
/**
 * Cross-platform dispatcher for the ponytail / caveman Claude Code hooks.
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
 * `pluginRoot` (set in ~/.dsh/cordis.patch.yml to `dshHomePath('hooks')`), so it
 * resolves per platform. This script then sets the required env vars and spawns
 * the real hook script, forwarding stdin/stdout/stderr verbatim.
 *
 * Skills layout: `<home>/projects/MyAI/dsh-extensions/skills/<skill>`.
 * Override with DSH_SKILLS_ROOT if the checkout lives elsewhere.
 */

import { spawnSync } from 'node:child_process'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'

const home = process.env.DSH_HOME || join(homedir(), '.dsh')
const skills = process.env.DSH_SKILLS_ROOT
  || join(homedir(), 'projects', 'MyAI', 'dsh-extensions', 'skills')
const ponytail = join(skills, 'dietrichgebert-ponytail')
const caveman = join(skills, 'caveman')
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
  // The shim wraps caveman's plain-stdout SessionStart in the JSON envelope DSH
  // expects; it wants the caveman repo root as argv[2].
  'caveman-session-context': {
    script: join(home, 'hooks', 'caveman-session-context.js'),
    args: [caveman],
    env: {
      CAVEMAN_DEFAULT_MODE: process.env.CAVEMAN_DEFAULT_MODE || 'wenyan-ultra',
      CLAUDE_PLUGIN_ROOT: caveman,
    },
  },
  'caveman-mode-tracker': {
    script: join(caveman, 'src', 'hooks', 'caveman-mode-tracker.js'),
    env: {
      CAVEMAN_DEFAULT_MODE: process.env.CAVEMAN_DEFAULT_MODE || 'wenyan-ultra',
      CLAUDE_PLUGIN_ROOT: caveman,
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

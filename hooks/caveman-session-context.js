#!/usr/bin/env node
// DSH hooks-bridge shim for caveman's SessionStart.
//
// Why this exists: caveman-activate.js writes the ruleset as PLAIN STDOUT
// (Claude Code injects SessionStart stdout verbatim), while the DSH bridge
// (packages/hooks/hook-protocol/src/codec.ts — parseHookOutput) only reads
// `hookSpecificOutput.additionalContext` out of a JSON object on stdout.
// caveman ships no JSON dialect for SessionStart (its Codex hook in
// .codex/hooks.json is a static `echo`), so the envelope is built here.
//
// It also drops caveman's trailing "STATUSLINE SETUP NEEDED" nudge: that advice
// is meaningless in DSH and would otherwise make the model offer to edit
// ~/.claude/settings.json once per session. (The nudge marker file cannot be
// written from inside the sandbox, so it would never be suppressed upstream.)
//
// Usage from hooks.json:
//   CAVEMAN_DEFAULT_MODE=wenyan-ultra \
//     node ~/.dsh/hooks/caveman-session-context.js <caveman-repo-root>
// The root is passed as argv[2] because the bridge substitutes
// ${CLAUDE_PLUGIN_ROOT} in the command string but only sets CLAUDE_PROJECT_DIR
// as an env var; the shim sets CLAUDE_PLUGIN_ROOT for the child itself, which
// is where caveman-activate.js looks for skills/caveman/SKILL.md.

const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const root = process.argv[2] || process.env.CLAUDE_PLUGIN_ROOT
if (!root) {
  process.stderr.write('caveman-session-context: no caveman root given\n')
  process.exit(0)
}

let stdin = ''
try {
  stdin = fs.readFileSync(0, 'utf8')
} catch {
  /* no payload: caveman degrades to its machine-wide fallback */
}

let out = ''
try {
  out = execFileSync(process.execPath, [path.join(root, 'src', 'hooks', 'caveman-activate.js')], {
    input: stdin,
    encoding: 'utf8',
    maxBuffer: 1 << 24,
    env: { ...process.env, CLAUDE_PLUGIN_ROOT: root },
  })
} catch (e) {
  // Non-blocking by contract: a broken caveman install must not break session start.
  process.stderr.write('caveman-session-context: ' + String(e.message).split('\n')[0] + '\n')
  process.exit(0)
}

out = out.split('\n\nSTATUSLINE SETUP NEEDED:')[0].trim()
if (!out) process.exit(0)

process.stdout.write(
  JSON.stringify({ hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: out } }),
)

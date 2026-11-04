import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import * as plugin from './opencode-go-headers.mjs';
const require = createRequire(process.argv[2] + '/packages/llm/llm-pi-ai/package.json');
const { Context } = await import(require.resolve('@deepseek-ai/cordis'));
const ctx = new Context();
const fork = await ctx.plugin(plugin);
const prepare = (request) => {
  const headers = new Headers({ existing: 'kept' });
  return ctx.waterfall('llm-pi-ai/request-headers', request, headers, () => headers);
};
try {
  assert.equal(prepare({ provider: 'opencode-go', sessionId: 'first' }).get('x-opencode-session'), 'first');
  assert.equal(prepare({ provider: 'opencode-go', sessionId: 'second' }).get('x-opencode-session'), 'second');
  assert.equal(prepare({ provider: 'opencode-go' }).get('x-opencode-session'), null);
  assert.equal(prepare({ provider: 'other', sessionId: 'first' }).get('x-opencode-session'), null);
  assert.equal(prepare({ provider: 'opencode-go', sessionId: 'first' }).get('existing'), 'kept');
  await fork.dispose();
  assert.equal(prepare({ provider: 'opencode-go', sessionId: 'first' }).get('x-opencode-session'), null);
  console.log('PASS: per-session identity, route isolation, existing headers and disposal');
} finally { await ctx.fiber.dispose(); }

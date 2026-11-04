/** Preserve Go session identity when an explicit protocol bypasses pi-ai's catalog wrapper. */
export const name = 'opencode-go-headers';
export function apply(ctx) {
  ctx.on('llm-pi-ai/request-headers', (request, headers, next) => {
    if (request.provider === 'opencode-go' && request.sessionId !== undefined)
      headers.set('x-opencode-session', String(request.sessionId));
    return next();
  });
}

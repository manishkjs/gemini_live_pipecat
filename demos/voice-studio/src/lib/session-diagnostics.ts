/** Capabilities stay in memory and HTTP headers, outside settings and URLs. */
const access = new Map<string, string>();

export function createDiagnosticAccess(sessionId: string) {
  const token = crypto.randomUUID();
  access.set(sessionId, token);
  if (access.size > 100) access.delete(access.keys().next().value!);
  return token;
}

export function diagnosticHeaders(sessionId?: string): Record<string, string> {
  const token = sessionId ? access.get(sessionId) : undefined;
  return token ? { "X-Session-Token": token } : {};
}

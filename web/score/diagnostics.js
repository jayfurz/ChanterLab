export const DIAGNOSTIC_SEVERITY = Object.freeze({
  ERROR: 'error',
  WARNING: 'warning',
  REVIEW: 'review',
  INFO: 'info',
});

export function createDiagnostic({
  severity = DIAGNOSTIC_SEVERITY.ERROR,
  code = 'chant-script',
  message,
  line,
  column,
  endColumn,
  source,
  detail,
} = {}) {
  return {
    severity,
    code,
    message: String(message ?? 'Unknown chant script diagnostic'),
    ...(Number.isInteger(line) ? { line } : {}),
    ...(Number.isInteger(column) ? { column } : {}),
    ...(Number.isInteger(endColumn) ? { endColumn } : {}),
    ...(source ? { source } : {}),
    ...(detail !== undefined ? { detail } : {}),
  };
}

export function pushDiagnostic(diagnostics, diagnostic) {
  const next = createDiagnostic(diagnostic);
  diagnostics.push(next);
  return next;
}

export function tokenLocation(token) {
  if (!token) return {};
  return {
    ...(Number.isInteger(token.line) ? { line: token.line } : {}),
    ...(Number.isInteger(token.column) ? { column: token.column } : {}),
    ...(Number.isInteger(token.endColumn) ? { endColumn: token.endColumn } : {}),
  };
}

export function hasErrorDiagnostics(diagnostics) {
  return diagnostics.some(diagnostic => diagnostic.severity === DIAGNOSTIC_SEVERITY.ERROR);
}

export function formatDiagnostic(diagnostic) {
  const place = Number.isInteger(diagnostic.line)
    ? `${diagnostic.line}:${diagnostic.column ?? 1}: `
    : '';
  return `${place}${diagnostic.severity ?? DIAGNOSTIC_SEVERITY.ERROR} ${diagnostic.code}: ${diagnostic.message}`;
}

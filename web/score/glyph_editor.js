import { listMinimalGlyphImportTokens } from './glyph_import.js';

const GLYPH_IMPORT_TOKENS = listMinimalGlyphImportTokens();
const TOKEN_BY_NAME = new Map(GLYPH_IMPORT_TOKENS.map(token => [token.glyphName, token]));
const TOKEN_BY_TEXT = buildTokenTextMap(GLYPH_IMPORT_TOKENS);
const EXCLUSIVE_ROLE_GROUP = Object.freeze({
  temporal: 'temporal',
  duration: 'duration',
  pthora: 'mode-sign',
  qualitative: 'mode-sign',
});

export function editGlyphImportText(text, options = {}) {
  const value = String(text ?? '');
  const token = TOKEN_BY_NAME.get(options.glyphName);
  const tokenText = glyphImportTokenText(options.glyphName, options.source);
  if (!tokenText) {
    return collapsedEdit(value, selectionStart(value, options), selectionEnd(value, options));
  }

  const start = selectionStart(value, options);
  const end = selectionEnd(value, { ...options, selectionStart: start });
  const exclusiveGroup = exclusiveGroupForToken(token);
  if (exclusiveGroup) {
    const target = targetEditorGroupForSelection(groupEditorTokens(value), start, end);
    if (target) {
      const existing = target.tokens
        .filter(item => exclusiveGroupForToken(item.token) === exclusiveGroup)
        .sort((a, b) => a.start - b.start);
      if (existing.length) return replaceExclusiveTokenItems(value, existing, tokenText);
      if (target.tokens.some(item => isAnchorRole(item.token?.role))) {
        return insertTokenText(value, target.end, target.end, tokenText);
      }
    }
  }

  return insertTokenText(value, start, end, tokenText);
}

export function glyphImportTokenText(glyphName, source) {
  const token = TOKEN_BY_NAME.get(glyphName);
  if (!token) return glyphName;
  if (source === 'sbmufl') return characterForCodepoint(token.codepoint) ?? token.glyphName;
  if (source === 'unicode') return characterForCodepoint(token.alternateCodepoint) ?? token.glyphName;
  return token.glyphName;
}

export function characterForCodepoint(codepoint) {
  if (typeof codepoint !== 'string') return undefined;
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(codepoint.trim());
  if (!match) return undefined;
  return String.fromCodePoint(Number.parseInt(match[1], 16));
}

function buildTokenTextMap(tokens) {
  const map = new Map();
  for (const token of tokens) {
    map.set(token.glyphName, token);
    if (token.codepoint) map.set(token.codepoint, token);
    if (token.alternateCodepoint) map.set(token.alternateCodepoint, token);
    const display = characterForCodepoint(token.codepoint);
    if (display) map.set(display, token);
    const alternate = characterForCodepoint(token.alternateCodepoint);
    if (alternate) map.set(alternate, token);
  }
  return map;
}

function selectionStart(text, options) {
  return clampIndex(
    Number.isInteger(options.selectionStart) ? options.selectionStart : text.length,
    text
  );
}

function selectionEnd(text, options) {
  return clampIndex(
    Number.isInteger(options.selectionEnd) ? options.selectionEnd : options.selectionStart,
    text
  );
}

function clampIndex(index, text) {
  return Math.max(0, Math.min(index, text.length));
}

function collapsedEdit(text, start, end) {
  return {
    text,
    selectionStart: start,
    selectionEnd: end,
    changed: false,
  };
}

function replaceExclusiveTokenItems(text, items, tokenText) {
  const [first, ...rest] = items;
  let next = `${text.slice(0, first.start)}${tokenText}${text.slice(first.end)}`;
  const offset = tokenText.length - (first.end - first.start);
  for (const item of rest.sort((a, b) => b.start - a.start)) {
    const span = expandedDeleteSpan(next, item.start + offset, item.end + offset);
    const start = span.start;
    const end = span.end;
    next = `${next.slice(0, start)}${next.slice(end)}`;
  }
  const cursor = first.start + tokenText.length;
  return {
    text: next,
    selectionStart: cursor,
    selectionEnd: cursor,
    changed: next !== text,
  };
}

function expandedDeleteSpan(text, start, end) {
  if (start > 0 && /[ \t,]/.test(text[start - 1])) return { start: start - 1, end };
  if (end < text.length && /[ \t,]/.test(text[end])) return { start, end: end + 1 };
  return { start, end };
}

function insertTokenText(text, start, end, tokenText) {
  const before = text.slice(0, start);
  const after = text.slice(end);
  const prefix = before && !/\s$/.test(before) ? ' ' : '';
  const suffix = after && !/^\s/.test(after) ? ' ' : '';
  const insert = `${prefix}${tokenText}${suffix}`;
  const next = `${before}${insert}${after}`;
  const cursor = start + prefix.length + tokenText.length;
  return {
    text: next,
    selectionStart: cursor,
    selectionEnd: cursor,
    changed: next !== text,
  };
}

function targetEditorGroupForSelection(groups, start, end) {
  if (!groups.length) return undefined;
  if (end > start) {
    return groups
      .map(group => ({
        group,
        overlap: Math.max(0, Math.min(end, group.end) - Math.max(start, group.start)),
      }))
      .filter(item => item.overlap > 0)
      .sort((a, b) => b.overlap - a.overlap)[0]?.group;
  }

  let previous;
  for (const group of groups) {
    if (start < group.start) return previous;
    if (start <= group.end) return group;
    previous = group;
  }
  return previous;
}

function groupEditorTokens(text) {
  const groups = [];
  let current = [];
  let pending = [];

  const flushCurrent = () => {
    if (current.length) groups.push(editorGroup(current));
    current = [];
  };

  for (const item of tokenizeEditorGlyphText(text)) {
    if (item.type === 'separator') {
      flushCurrent();
      if (pending.length) {
        groups.push(editorGroup(pending));
        pending = [];
      }
      continue;
    }

    const token = {
      ...item,
      token: TOKEN_BY_TEXT.get(item.raw),
    };

    if (isAnchorRole(token.token?.role)) {
      flushCurrent();
      current = [...pending, token];
      pending = [];
      continue;
    }

    if (isModifierRole(token.token?.role)) {
      if (current.length && current.some(item => isAnchorRole(item.token?.role))) current.push(token);
      else pending.push(token);
      continue;
    }

    flushCurrent();
    groups.push(editorGroup([...pending, token]));
    pending = [];
  }

  flushCurrent();
  if (pending.length) groups.push(editorGroup(pending));
  return groups;
}

function editorGroup(tokens) {
  return {
    tokens,
    start: Math.min(...tokens.map(token => token.start)),
    end: Math.max(...tokens.map(token => token.end)),
  };
}

function tokenizeEditorGlyphText(text) {
  const tokens = [];
  let cursor = 0;
  while (cursor < text.length) {
    const char = String.fromCodePoint(text.codePointAt(cursor));
    const width = char.length;
    if (char === '\n' || char === '\r' || char === '|') {
      tokens.push({ type: 'separator', raw: char, start: cursor, end: cursor + width });
      cursor += width;
      continue;
    }
    if (/\s|,/.test(char)) {
      cursor += width;
      continue;
    }
    if (/[A-Za-z_]/.test(char)) {
      const start = cursor;
      cursor += width;
      while (cursor < text.length) {
        const next = String.fromCodePoint(text.codePointAt(cursor));
        if (!/[A-Za-z0-9_+\-]/.test(next)) break;
        cursor += next.length;
      }
      tokens.push({ type: 'glyph', raw: text.slice(start, cursor), start, end: cursor });
      continue;
    }
    tokens.push({ type: 'glyph', raw: char, start: cursor, end: cursor + width });
    cursor += width;
  }
  return tokens;
}

function exclusiveGroupForToken(token) {
  return EXCLUSIVE_ROLE_GROUP[token?.role];
}

function isAnchorRole(role) {
  return role === 'quantity' || role === 'rest' || role === 'tempo';
}

function isModifierRole(role) {
  return role === 'temporal'
    || role === 'duration'
    || role === 'pthora'
    || role === 'qualitative';
}

import { DIAGNOSTIC_SEVERITY, pushDiagnostic } from './diagnostics.js';

const ATTACHMENT_COLUMN_PADDING = 0.35;
const PTHORA_PREFIX_X_RATIO = 0.5;

export function resolveGlyphGroups(tokens, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const list = Array.isArray(tokens) ? tokens : [];
  if (!list.length) return [];

  const mode = options.mode ?? detectResolverMode(list);
  if (mode === 'spatial') {
    return resolveSpatialGroups(list, diagnostics);
  }
  return resolveLinearGroups(list, diagnostics);
}

export function detectResolverMode(tokens) {
  const meaningful = tokens.filter(token => token?.kind !== 'separator');
  if (!meaningful.length) return 'linear';
  const withRegion = meaningful.filter(token => tokenRegion(token));
  if (withRegion.length === meaningful.length) return 'spatial';
  return 'linear';
}

function resolveLinearGroups(tokens, diagnostics) {
  const groups = [];
  let current = [];
  let pending = [];

  const flushCurrent = () => {
    if (current.length) groups.push(current);
    current = [];
  };

  for (const token of tokens) {
    if (token?.kind === 'separator') {
      flushCurrent();
      if (pending.length) {
        groups.push(pending);
        pending = [];
      }
      continue;
    }

    if (isGroupAnchor(token)) {
      flushCurrent();
      current = [...pending, token];
      pending = [];
      continue;
    }

    if (isGroupModifier(token)) {
      if (current.length && current.some(isGroupAnchor)) current.push(token);
      else pending.push(token);
      continue;
    }

    flushCurrent();
    groups.push([...pending, token]);
    pending = [];
  }

  flushCurrent();
  if (pending.length) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-unattached-modifier',
      message: 'Glyph modifiers without a quantity or rest sign cannot be imported unambiguously.',
      source: groupSource(pending),
    });
    groups.push(pending);
  }

  return groups;
}

function resolveSpatialGroups(tokens, diagnostics) {
  const lines = partitionByLine(tokens);
  const out = [];
  for (const line of lines) {
    out.push(...resolveSpatialLine(line, diagnostics));
  }
  return out;
}

function resolveSpatialLine(tokens, diagnostics) {
  const sorted = [...tokens].sort((a, b) => centerX(a) - centerX(b));
  const anchors = sorted.filter(isGroupAnchor);
  if (!anchors.length) {
    return resolveLinearGroups(sorted, diagnostics);
  }

  const groupsByAnchor = new Map(anchors.map(anchor => [anchor, [anchor]]));

  for (const token of sorted) {
    if (token === undefined || isGroupAnchor(token)) continue;
    if (!isGroupModifier(token)) continue;

    const anchor = chooseAnchorForModifier(token, anchors);
    if (!anchor) {
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.ERROR,
        code: 'glyph-import-unattached-modifier',
        message: 'Glyph modifier has no spatially adjacent quantity, rest, or martyria anchor.',
        source: groupSource([token]),
      });
      continue;
    }
    groupsByAnchor.get(anchor).push(token);
  }

  return anchors.map(anchor => groupsByAnchor.get(anchor));
}

function partitionByLine(tokens) {
  const explicit = tokens.every(token => Number.isInteger(tokenRegion(token)?.line));
  if (!explicit) return [tokens];
  const buckets = new Map();
  for (const token of tokens) {
    const line = tokenRegion(token).line;
    if (!buckets.has(line)) buckets.set(line, []);
    buckets.get(line).push(token);
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([, list]) => list);
}

function chooseAnchorForModifier(modifier, anchors) {
  const containing = anchors.filter(anchor => anchorColumnContains(anchor, modifier));
  if (containing.length) {
    return nearestAnchorByCenterX(modifier, containing);
  }

  if (modifier.kind === 'pthora') {
    const ahead = anchors.filter(anchor => centerX(anchor) >= centerX(modifier) - pthoraPrefixGap(modifier));
    if (ahead.length) return nearestAnchorByCenterX(modifier, ahead);
  }

  if (anchors.length) return nearestAnchorByCenterX(modifier, anchors);
  return undefined;
}

function nearestAnchorByCenterX(modifier, anchors) {
  let best;
  let bestDistance = Infinity;
  for (const anchor of anchors) {
    const distance = Math.abs(centerX(anchor) - centerX(modifier));
    if (distance < bestDistance) {
      best = anchor;
      bestDistance = distance;
    }
  }
  return best;
}

function anchorColumnContains(anchor, modifier) {
  const anchorBox = tokenBBox(anchor);
  const modifierBox = tokenBBox(modifier);
  if (!anchorBox || !modifierBox) return false;
  const padding = anchorBox.w * ATTACHMENT_COLUMN_PADDING;
  const left = anchorBox.x - padding;
  const right = anchorBox.x + anchorBox.w + padding;
  const center = modifierBox.x + modifierBox.w / 2;
  return center >= left && center <= right;
}

function pthoraPrefixGap(modifier) {
  const box = tokenBBox(modifier);
  if (!box) return 0;
  return box.w * PTHORA_PREFIX_X_RATIO;
}

function centerX(token) {
  const bbox = tokenBBox(token);
  if (!bbox) return Number.POSITIVE_INFINITY;
  return bbox.x + bbox.w / 2;
}

function tokenBBox(token) {
  return tokenRegion(token)?.bbox;
}

function tokenRegion(token) {
  return token?.source?.[0]?.region;
}

function isGroupAnchor(token) {
  return token?.kind === 'quantity'
    || token?.kind === 'rest'
    || token?.kind === 'tempo'
    || token?.kind === 'martyria-note';
}

function isGroupModifier(token) {
  return token?.kind === 'temporal'
    || token?.kind === 'duration'
    || token?.kind === 'pthora'
    || token?.kind === 'qualitative'
    || token?.kind === 'martyria-sign';
}

function groupSource(group) {
  return {
    source: {
      kind: 'glyph-import',
      tokens: group.flatMap(token => token?.source ?? []),
    },
  };
}

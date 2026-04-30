import { glyphImportTokenText } from './glyph_editor.js';
import { listMinimalGlyphImportTokens } from './glyph_import.js';

const IMPORT_TOKENS = listMinimalGlyphImportTokens();
const TOKEN_BY_NAME = new Map(IMPORT_TOKENS.map(token => [token.glyphName, token]));
const ANCHOR_ROLES = new Set(['quantity', 'rest', 'tempo']);
const MODIFIER_ROLES = new Set(['temporal', 'duration', 'pthora', 'qualitative']);
const EXCLUSIVE_ROLE_GROUP = Object.freeze({
  temporal: 'temporal',
  duration: 'duration',
  pthora: 'mode-sign',
  qualitative: 'mode-sign',
});

export function createGlyphScoreEditorState(options = {}) {
  const groups = Array.isArray(options.groups)
    ? options.groups.map(normalizeGroup).filter(group => group.tokenNames.length)
    : [];
  return {
    groups,
    selectedIndex: validGroupIndex(options.selectedIndex, groups)
      ? options.selectedIndex
      : groups.length ? groups.length - 1 : -1,
    status: options.status ?? '',
  };
}

export function glyphScoreClusterInfo(cluster) {
  const components = Array.isArray(cluster?.components) ? cluster.components : [];
  const componentTokens = components.map(component => ({
    component,
    token: TOKEN_BY_NAME.get(component.glyphName),
  }));
  const missing = componentTokens
    .filter(item => !item.token)
    .map(item => item.component?.glyphName)
    .filter(Boolean);
  const tokenNames = componentTokens
    .map(item => item.token?.glyphName)
    .filter(Boolean);
  const roles = componentTokens
    .map(item => item.token?.role)
    .filter(Boolean);
  const anchorCount = roles.filter(role => ANCHOR_ROLES.has(role)).length;
  const modifierCount = roles.filter(role => MODIFIER_ROLES.has(role)).length;
  const hasUnknownRole = roles.some(role => !ANCHOR_ROLES.has(role) && !MODIFIER_ROLES.has(role));
  const importable = components.length > 0
    && missing.length === 0
    && !hasUnknownRole
    && anchorCount <= 1
    && (anchorCount > 0 || modifierCount > 0);

  return {
    id: cluster?.id,
    label: cluster?.label,
    category: cluster?.category,
    importable,
    insertion: anchorCount > 0 ? 'group' : 'modifier',
    tokenNames,
    missing,
    anchorCount,
    modifierCount,
    reason: importable
      ? ''
      : nonImportableReason({ components, missing, anchorCount, hasUnknownRole }),
  };
}

export function applyGlyphScoreCluster(state, cluster) {
  const current = createGlyphScoreEditorState(state);
  const info = glyphScoreClusterInfo(cluster);
  if (!info.importable) {
    return {
      ...current,
      changed: false,
      status: info.reason || 'That atlas glyph is visual-only for now.',
    };
  }

  if (info.insertion === 'group') {
    const groups = current.groups.slice();
    const insertAfter = validGroupIndex(current.selectedIndex, groups)
      ? current.selectedIndex
      : groups.length - 1;
    const insertIndex = Math.max(0, Math.min(groups.length, insertAfter + 1));
    groups.splice(insertIndex, 0, normalizeGroup({ tokenNames: info.tokenNames }));
    return {
      groups,
      selectedIndex: insertIndex,
      changed: true,
      status: `${cluster.label ?? 'Glyph'} added`,
    };
  }

  const selectedIndex = validGroupIndex(current.selectedIndex, current.groups)
    && groupCanAcceptModifierTokens(current.groups[current.selectedIndex], info.tokenNames)
    ? current.selectedIndex
    : lastCompatibleGroupIndex(current.groups, info.tokenNames);
  if (!validGroupIndex(selectedIndex, current.groups)) {
    return {
      ...current,
      changed: false,
      status: 'Add a compatible quantity or rest before attaching this sign.',
    };
  }

  const groups = current.groups.slice();
  const applied = applyModifierTokens(groups[selectedIndex], info.tokenNames);
  if (!applied.changed) {
    return {
      ...current,
      changed: false,
      status: 'That sign cannot attach to the selected group.',
    };
  }
  groups[selectedIndex] = applied.group;
  return {
    groups,
    selectedIndex,
    changed: true,
    status: `${cluster.label ?? 'Sign'} attached`,
  };
}

export function removeGlyphScoreGroup(state, index) {
  const current = createGlyphScoreEditorState(state);
  if (!validGroupIndex(index, current.groups)) return current;
  const groups = current.groups.slice();
  groups.splice(index, 1);
  return {
    groups,
    selectedIndex: groups.length ? Math.min(index, groups.length - 1) : -1,
    status: groups.length ? 'Group removed' : 'Score cleared',
  };
}

export function clearGlyphScoreEditorState() {
  return createGlyphScoreEditorState({ status: 'Score cleared' });
}

export function serializeGlyphScoreEditorState(state, options = {}) {
  const source = options.source ?? 'glyph';
  return createGlyphScoreEditorState(state).groups
    .map(group => group.tokenNames
      .map(glyphName => glyphImportTokenText(glyphName, source))
      .join(' ')
      .trim())
    .filter(Boolean)
    .join(' | ');
}

export function glyphScoreGroupHasAnchor(group) {
  return normalizeGroup(group).tokenNames
    .some(glyphName => ANCHOR_ROLES.has(TOKEN_BY_NAME.get(glyphName)?.role));
}

export function glyphScoreGroupLabel(group) {
  const normalized = normalizeGroup(group);
  const anchor = normalized.tokenNames.find(glyphName => (
    ANCHOR_ROLES.has(TOKEN_BY_NAME.get(glyphName)?.role)
  ));
  const modifiers = normalized.tokenNames.filter(glyphName => glyphName !== anchor);
  return [anchor, ...modifiers].filter(Boolean).join(' + ') || 'empty';
}

function normalizeGroup(group) {
  const tokenNames = Array.isArray(group?.tokenNames)
    ? group.tokenNames
    : Array.isArray(group) ? group : [];
  return {
    tokenNames: tokenNames.filter(glyphName => TOKEN_BY_NAME.has(glyphName)),
  };
}

function applyModifierTokens(group, tokenNames) {
  let next = normalizeGroup(group).tokenNames.slice();
  let changed = false;
  for (const glyphName of tokenNames) {
    const role = TOKEN_BY_NAME.get(glyphName)?.role;
    if (!MODIFIER_ROLES.has(role)) continue;
    if (!modifierCanAttachToGroup(glyphName, group)) continue;
    const exclusiveGroup = EXCLUSIVE_ROLE_GROUP[role];
    if (exclusiveGroup) {
      next = next.filter(name => EXCLUSIVE_ROLE_GROUP[TOKEN_BY_NAME.get(name)?.role] !== exclusiveGroup);
    }
    next.push(glyphName);
    changed = true;
  }
  return { group: normalizeGroup({ tokenNames: next }), changed };
}

function lastCompatibleGroupIndex(groups, tokenNames) {
  for (let index = groups.length - 1; index >= 0; index -= 1) {
    if (groupCanAcceptModifierTokens(groups[index], tokenNames)) return index;
  }
  return -1;
}

function validGroupIndex(index, groups) {
  return Number.isInteger(index) && index >= 0 && index < groups.length;
}

function groupCanAcceptModifierTokens(group, tokenNames) {
  return tokenNames.some(glyphName => modifierCanAttachToGroup(glyphName, group));
}

function modifierCanAttachToGroup(glyphName, group) {
  const role = TOKEN_BY_NAME.get(glyphName)?.role;
  const anchorRole = groupAnchorRole(group);
  if (role === 'temporal' || role === 'duration') {
    return anchorRole === 'quantity' || anchorRole === 'rest';
  }
  if (role === 'pthora' || role === 'qualitative') {
    return anchorRole === 'quantity';
  }
  return false;
}

function groupAnchorRole(group) {
  const anchorName = normalizeGroup(group).tokenNames.find(glyphName => (
    ANCHOR_ROLES.has(TOKEN_BY_NAME.get(glyphName)?.role)
  ));
  return TOKEN_BY_NAME.get(anchorName)?.role;
}

function nonImportableReason({ components, missing, anchorCount, hasUnknownRole }) {
  if (!components.length) return 'This atlas cell has no glyph components.';
  if (missing.length) return `Visual-only: ${missing.join(', ')} is not mapped in the importer yet.`;
  if (anchorCount > 1) return 'Visual-only: compound quantity interpretation is not mapped yet.';
  if (hasUnknownRole) return 'Visual-only: this glyph role is not mapped in the importer yet.';
  return 'Visual-only: this glyph is not mapped in the importer yet.';
}

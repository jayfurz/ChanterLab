export function generatedGlyphNamesForNeume(neume) {
  if (!neume || neume.type !== 'neume') return [];

  const glyphs = [];
  const { movement } = neume;

  if (movement?.direction === 'same') {
    glyphs.push('ison');
  } else if (movement?.direction === 'up' && movement.steps === 1) {
    glyphs.push('oligon');
  } else if (movement?.direction === 'down' && movement.steps === 1) {
    glyphs.push('apostrofos');
  }

  for (const sign of neume.temporal ?? []) {
    if (sign.type === 'quick') glyphs.push('gorgon');
    if (sign.type === 'divide' && sign.divide === 3) glyphs.push('digorgon');
    if (sign.type === 'divide' && sign.divide === 4) glyphs.push('trigorgon');
  }

  return glyphs;
}

export function displayForNeume(neume, orthography = 'generated') {
  const existing = neume.display ?? {};
  const generatedGlyphNames = orthography === 'generated'
    ? generatedGlyphNamesForNeume(neume)
    : [];

  return {
    ...existing,
    orthography: existing.orthography ?? orthography,
    ...(generatedGlyphNames.length
      ? {
          generatedGlyphName: generatedGlyphNames[0],
          generatedGlyphNames,
        }
      : {}),
  };
}

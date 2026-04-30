import {
  createChantScore,
  createTempoEvent,
  degreeFromLinearIndex,
  degreeIndex,
  normalizeDegree,
  normalizeScaleName,
  positiveModulo,
  scaleDefinition,
} from './chant_score.js';
import { compileChantScore } from './compiler.js?v=chant-script-engine-phase6w';
import { DIAGNOSTIC_SEVERITY, pushDiagnostic } from './diagnostics.js';

const UNICODE_BYZANTINE_START = 0x1D000;
const UNICODE_BYZANTINE_END = 0x1D0FF;
const PUA_START = 0xE000;
const PUA_END = 0xF8FF;
const GLYPH_TEXT_GROUP_SEPARATORS = new Set(['|']);
const MINIMAL_GLYPH_IMPORT_NAMES = Object.freeze([
  'ison',
  'oligon',
  'apostrofos',
  'yporroi',
  'elafron',
  'chamili',
  'leimma1',
  'leimma2',
  'leimma3',
  'leimma4',
  'gorgonAbove',
  'digorgon',
  'trigorgon',
  'argon',
  'apli',
  'klasma',
  'dipli',
  'tripli',
  'agogiMetria',
  'agogiGorgi',
  'fthoraHardChromaticPaAbove',
  'fthoraHardChromaticDiAbove',
  'fthoraSoftChromaticDiAbove',
  'fthoraSoftChromaticKeAbove',
  'chroaZygosAbove',
  'chroaKlitonAbove',
  'chroaSpathiAbove',
]);

const GLYPH_METADATA = Object.freeze({
  ison: quantity('ison', 'U+E000', 'U+1D046', 'same', 0),
  oligon: quantity('oligon', 'U+E001', 'U+1D047', 'up', 1),
  apostrofos: quantity('apostrofos', 'U+E021', 'U+1D051', 'down', 1),
  yporroi: quantity('yporroi', 'U+E023', 'U+1D053', 'down', 2),
  elafron: quantity('elafron', 'U+E024', 'U+1D055', 'down', 2),
  chamili: quantity('chamili', 'U+E027', 'U+1D056', 'down', 4),
  oligonKentimaMiddle: quantity('oligonKentimaMiddle', 'U+E002', undefined, 'up', 3, { quality: 'kentima' }),
  oligonKentimaBelow: quantity('oligonKentimaBelow', 'U+E003', undefined, 'up', 3, { quality: 'kentima' }),
  oligonKentimaAbove: quantity('oligonKentimaAbove', 'U+E004', undefined, 'up', 3, { quality: 'kentima' }),
  oligonYpsiliRight: quantity('oligonYpsiliRight', 'U+E005', undefined, 'up', 4, { quality: 'ypsili' }),
  oligonYpsiliLeft: quantity('oligonYpsiliLeft', 'U+E006', undefined, 'up', 5, { quality: 'ypsili' }),
  oligonKentimaYpsiliRight: quantity('oligonKentimaYpsiliRight', 'U+E007', undefined, 'up', 6, { quality: 'kentima-ypsili' }),
  oligonKentimaYpsiliMiddle: quantity('oligonKentimaYpsiliMiddle', 'U+E008', undefined, 'up', 7, { quality: 'kentima-ypsili' }),
  oligonDoubleYpsili: quantity('oligonDoubleYpsili', 'U+E009', undefined, 'up', 5, { quality: 'double-ypsili' }),
  oligonKentimataDoubleYpsili: quantity('oligonKentimataDoubleYpsili', 'U+E00A', undefined, 'up', 5, { quality: 'kentimata-double-ypsili' }),
  oligonKentimaDoubleYpsiliRight: quantity('oligonKentimaDoubleYpsiliRight', 'U+E00B', undefined, 'up', 6, { quality: 'kentima-double-ypsili' }),
  oligonKentimaDoubleYpsiliLeft: quantity('oligonKentimaDoubleYpsiliLeft', 'U+E00C', undefined, 'up', 7, { quality: 'kentima-double-ypsili' }),
  oligonTripleYpsili: quantity('oligonTripleYpsili', 'U+E00D', undefined, 'up', 6, { quality: 'triple-ypsili' }),
  oligonKentimataTripleYpsili: quantity('oligonKentimataTripleYpsili', 'U+E00E', undefined, 'up', 6, { quality: 'kentimata-triple-ypsili' }),
  oligonKentimaTripleYpsili: quantity('oligonKentimaTripleYpsili', 'U+E00F', undefined, 'up', 7, { quality: 'kentima-triple-ypsili' }),
  oligonIson: quantity('oligonIson', 'U+E010', undefined, 'same', 0, { quality: 'oligon-support' }),
  oligonApostrofos: quantity('oligonApostrofos', 'U+E011', undefined, 'down', 1, { quality: 'oligon-support' }),
  oligonYporroi: quantity('oligonYporroi', 'U+E012', undefined, 'down', 2, { quality: 'oligon-support' }),
  oligonElafron: quantity('oligonElafron', 'U+E013', undefined, 'down', 2, { quality: 'oligon-support' }),
  oligonElafronApostrofos: quantity('oligonElafronApostrofos', 'U+E014', undefined, 'down', 3, { quality: 'oligon-support' }),
  oligonChamili: quantity('oligonChamili', 'U+E015', undefined, 'down', 4, { quality: 'oligon-support' }),
  isonApostrofos: quantity('isonApostrofos', 'U+E020', undefined, 'down', 1, { quality: 'ison-support' }),
  petastiIson: quantity('petastiIson', 'U+E040', undefined, 'same', 0, { quality: 'petasti' }),
  petasti: quantity('petasti', 'U+E041', 'U+1D049', 'up', 1, { quality: 'petasti' }),
  petastiOligon: quantity('petastiOligon', 'U+E042', undefined, 'up', 2, { quality: 'petasti' }),
  petastiKentima: quantity('petastiKentima', 'U+E043', undefined, 'up', 3, { quality: 'petasti-kentima' }),
  petastiYpsiliRight: quantity('petastiYpsiliRight', 'U+E044', undefined, 'up', 4, { quality: 'petasti-ypsili' }),
  petastiYpsiliLeft: quantity('petastiYpsiliLeft', 'U+E045', undefined, 'up', 5, { quality: 'petasti-ypsili' }),
  petastiKentimaYpsiliRight: quantity('petastiKentimaYpsiliRight', 'U+E046', undefined, 'up', 6, { quality: 'petasti-kentima-ypsili' }),
  petastiKentimaYpsiliMiddle: quantity('petastiKentimaYpsiliMiddle', 'U+E047', undefined, 'up', 7, { quality: 'petasti-kentima-ypsili' }),
  petastiDoubleYpsili: quantity('petastiDoubleYpsili', 'U+E048', undefined, 'up', 5, { quality: 'petasti-double-ypsili' }),
  petastiKentimataDoubleYpsili: quantity('petastiKentimataDoubleYpsili', 'U+E049', undefined, 'up', 5, { quality: 'petasti-kentimata-double-ypsili' }),
  petastiKentimaDoubleYpsiliRight: quantity('petastiKentimaDoubleYpsiliRight', 'U+E04A', undefined, 'up', 6, { quality: 'petasti-kentima-double-ypsili' }),
  petastiKentimaDoubleYpsiliLeft: quantity('petastiKentimaDoubleYpsiliLeft', 'U+E04B', undefined, 'up', 7, { quality: 'petasti-kentima-double-ypsili' }),
  petastiTripleYpsili: quantity('petastiTripleYpsili', 'U+E04C', undefined, 'up', 6, { quality: 'petasti-triple-ypsili' }),
  petastiKentimataTripleYpsili: quantity('petastiKentimataTripleYpsili', 'U+E04D', undefined, 'up', 6, { quality: 'petasti-kentimata-triple-ypsili' }),
  petastiKentimaTripleYpsili: quantity('petastiKentimaTripleYpsili', 'U+E04E', undefined, 'up', 7, { quality: 'petasti-kentima-triple-ypsili' }),
  petastiApostrofos: quantity('petastiApostrofos', 'U+E060', undefined, 'down', 1, { quality: 'petasti' }),
  petastiYporroi: quantity('petastiYporroi', 'U+E061', undefined, 'down', 2, { quality: 'petasti' }),
  petastiElafron: quantity('petastiElafron', 'U+E062', undefined, 'down', 2, { quality: 'petasti' }),
  petastiRunningElafron: quantity('petastiRunningElafron', 'U+E063', undefined, 'down', 2, { quality: 'petasti-running-elafron' }),
  petastiElafronApostrofos: quantity('petastiElafronApostrofos', 'U+E064', undefined, 'down', 3, { quality: 'petasti' }),
  petastiChamili: quantity('petastiChamili', 'U+E065', undefined, 'down', 4, { quality: 'petasti' }),
  petastiChamiliApostrofos: quantity('petastiChamiliApostrofos', 'U+E066', undefined, 'down', 5, { quality: 'petasti' }),
  petastiChamiliElafron: quantity('petastiChamiliElafron', 'U+E067', undefined, 'down', 6, { quality: 'petasti' }),
  petastiChamiliElafronApostrofos: quantity('petastiChamiliElafronApostrofos', 'U+E068', undefined, 'down', 7, { quality: 'petasti' }),
  petastiDoubleChamili: quantity('petastiDoubleChamili', 'U+E069', undefined, 'down', 8, { quality: 'petasti' }),
  petastiDoubleChamiliApostrofos: quantity('petastiDoubleChamiliApostrofos', 'U+E06A', undefined, 'down', 9, { quality: 'petasti' }),
  kentima: quantity('kentima', 'U+E080', undefined, 'up', 2, { quality: 'kentima' }),
  kentimata: quantity('kentimata', 'U+E081', 'U+1D04E', 'up', 1, { quality: 'kentimata' }),
  oligonKentimataBelow: quantity('oligonKentimataBelow', 'U+E082', undefined, 'up', 1, { quality: 'kentimata' }),
  oligonKentimataAbove: quantity('oligonKentimataAbove', 'U+E083', undefined, 'up', 1, { quality: 'kentimata' }),
  oligonIsonKentimata: quantity('oligonIsonKentimata', 'U+E084', undefined, 'same', 0, { quality: 'kentimata' }),
  oligonKentimaMiddleKentimata: quantity('oligonKentimaMiddleKentimata', 'U+E085', undefined, 'up', 3, { quality: 'kentima-kentimata' }),
  oligonYpsiliRightKentimata: quantity('oligonYpsiliRightKentimata', 'U+E086', undefined, 'up', 4, { quality: 'kentimata-ypsili' }),
  oligonYpsiliLeftKentimata: quantity('oligonYpsiliLeftKentimata', 'U+E087', undefined, 'up', 5, { quality: 'kentimata-ypsili' }),
  oligonApostrofosKentimata: quantity('oligonApostrofosKentimata', 'U+E088', undefined, 'down', 1, { quality: 'kentimata' }),
  oligonYporroiKentimata: quantity('oligonYporroiKentimata', 'U+E089', undefined, 'down', 2, { quality: 'kentimata' }),
  oligonElafronKentimata: quantity('oligonElafronKentimata', 'U+E08A', undefined, 'down', 2, { quality: 'kentimata' }),
  oligonRunningElafronKentimata: quantity('oligonRunningElafronKentimata', 'U+E08B', undefined, 'down', 2, { quality: 'kentimata-running-elafron' }),
  oligonElafronApostrofosKentimata: quantity('oligonElafronApostrofosKentimata', 'U+E08C', undefined, 'down', 3, { quality: 'kentimata' }),
  oligonChamiliKentimata: quantity('oligonChamiliKentimata', 'U+E08D', undefined, 'down', 4, { quality: 'kentimata' }),

  leimma1: rest('leimma1', 'U+E0E0', 'U+1D08A', 1),
  leimma2: rest('leimma2', 'U+E0E1', 'U+1D08B', 2),
  leimma3: rest('leimma3', 'U+E0E2', 'U+1D08C', 3),
  leimma4: rest('leimma4', 'U+E0E3', 'U+1D08D', 4),

  gorgonAbove: temporal('gorgonAbove', 'U+E0F0', 'U+1D08F', { type: 'quick', sign: 'gorgon' }),
  gorgonBelow: temporal('gorgonBelow', 'U+E0F1', undefined, { type: 'quick', sign: 'gorgon' }),
  gorgonDottedLeft: temporal('gorgonDottedLeft', 'U+E0F2', undefined, { type: 'quick', sign: 'gorgonDottedLeft', weights: [2, 1] }),
  gorgonDottedRight: temporal('gorgonDottedRight', 'U+E0F3', undefined, { type: 'quick', sign: 'gorgonDottedRight', weights: [1, 2] }),
  digorgon: temporal('digorgon', 'U+E0F4', 'U+1D092', { type: 'divide', divide: 3, sign: 'digorgon' }),
  digorgonDottedLeftBelow: temporal('digorgonDottedLeftBelow', 'U+E0F5', undefined, { type: 'divide', divide: 3, sign: 'digorgonDottedLeftBelow', weights: [2, 1, 1] }),
  digorgonDottedLeftAbove: temporal('digorgonDottedLeftAbove', 'U+E0F6', undefined, { type: 'divide', divide: 3, sign: 'digorgonDottedLeftAbove', weights: [1, 2, 1] }),
  digorgonDottedRight: temporal('digorgonDottedRight', 'U+E0F7', undefined, { type: 'divide', divide: 3, sign: 'digorgonDottedRight', weights: [1, 1, 2] }),
  trigorgon: temporal('trigorgon', 'U+E0F8', 'U+1D096', { type: 'divide', divide: 4, sign: 'trigorgon' }),
  trigorgonDottedLeftBelow: temporal('trigorgonDottedLeftBelow', 'U+E0F9', undefined, { type: 'divide', divide: 4, sign: 'trigorgonDottedLeftBelow', weights: [2, 1, 1, 1] }),
  trigorgonDottedLeftAbove: temporal('trigorgonDottedLeftAbove', 'U+E0FA', undefined, { type: 'divide', divide: 4, sign: 'trigorgonDottedLeftAbove', weights: [1, 2, 1, 1] }),
  trigorgonDottedRight: temporal('trigorgonDottedRight', 'U+E0FB', undefined, { type: 'divide', divide: 4, sign: 'trigorgonDottedRight', weights: [1, 1, 1, 2] }),
  argon: temporal('argon', 'U+E0FC', 'U+1D097', { type: 'unsupported', sign: 'argon' }),
  gorgonSecondary: temporal('gorgonSecondary', 'U+E100', undefined, { type: 'quick', sign: 'gorgonSecondary' }),
  gorgonDottedLeftSecondary: temporal('gorgonDottedLeftSecondary', 'U+E101', undefined, { type: 'quick', sign: 'gorgonDottedLeftSecondary', weights: [2, 1] }),
  gorgonDottedRightSecondary: temporal('gorgonDottedRightSecondary', 'U+E102', undefined, { type: 'quick', sign: 'gorgonDottedRightSecondary', weights: [1, 2] }),
  digorgonSecondary: temporal('digorgonSecondary', 'U+E103', undefined, { type: 'divide', divide: 3, sign: 'digorgonSecondary' }),
  digorgonDottedLeftBelowSecondary: temporal('digorgonDottedLeftBelowSecondary', 'U+E104', undefined, { type: 'divide', divide: 3, sign: 'digorgonDottedLeftBelowSecondary', weights: [2, 1, 1] }),
  digorgonDottedRightSecondary: temporal('digorgonDottedRightSecondary', 'U+E105', undefined, { type: 'divide', divide: 3, sign: 'digorgonDottedRightSecondary', weights: [1, 1, 2] }),
  trigorgonSecondary: temporal('trigorgonSecondary', 'U+E106', undefined, { type: 'divide', divide: 4, sign: 'trigorgonSecondary' }),
  trigorgonDottedLeftBelowSecondary: temporal('trigorgonDottedLeftBelowSecondary', 'U+E107', undefined, { type: 'divide', divide: 4, sign: 'trigorgonDottedLeftBelowSecondary', weights: [2, 1, 1, 1] }),
  trigorgonDottedRightSecondary: temporal('trigorgonDottedRightSecondary', 'U+E108', undefined, { type: 'divide', divide: 4, sign: 'trigorgonDottedRightSecondary', weights: [1, 1, 1, 2] }),
  digorgonDottedLeftSecondary: temporal('digorgonDottedLeftSecondary', 'U+E109', undefined, { type: 'divide', divide: 3, sign: 'digorgonDottedLeftSecondary', weights: [1, 2, 1] }),
  trigorgonDottedLeftSecondary: temporal('trigorgonDottedLeftSecondary', 'U+E10A', undefined, { type: 'divide', divide: 4, sign: 'trigorgonDottedLeftSecondary', weights: [1, 2, 1, 1] }),

  apli: duration('apli', 'U+E0D2', 'U+1D085', 2),
  klasma: duration('klasma', 'U+E0D0', 'U+1D07F', 2),
  klasmaBelow: duration('klasmaBelow', 'U+E0D1', undefined, 2),
  dipli: duration('dipli', 'U+E0D3', 'U+1D086', 3),
  tripli: duration('tripli', 'U+E0D4', undefined, 4),
  tetrapli: duration('tetrapli', 'U+E0D5', undefined, 5),

  agogiMetria: tempo('agogiMetria', 'U+E123', 'U+1D09D', 'moderate'),
  agogiGorgi: tempo('agogiGorgi', 'U+E125', 'U+1D09F', 'swift'),

  fthoraDiatonicNiLowAbove: pthora('fthoraDiatonicNiLowAbove', 'U+E190', undefined, 'diatonic', 'Ni'),
  fthoraDiatonicPaAbove: pthora('fthoraDiatonicPaAbove', 'U+E191', undefined, 'diatonic', 'Pa'),
  fthoraDiatonicVouAbove: pthora('fthoraDiatonicVouAbove', 'U+E192', undefined, 'diatonic', 'Vou'),
  fthoraDiatonicGaAbove: pthora('fthoraDiatonicGaAbove', 'U+E193', undefined, 'diatonic', 'Ga'),
  fthoraDiatonicDiAbove: pthora('fthoraDiatonicDiAbove', 'U+E194', undefined, 'diatonic', 'Di'),
  fthoraDiatonicKeAbove: pthora('fthoraDiatonicKeAbove', 'U+E195', undefined, 'diatonic', 'Ke'),
  fthoraDiatonicZoAbove: pthora('fthoraDiatonicZoAbove', 'U+E196', undefined, 'diatonic', 'Zo'),
  fthoraDiatonicNiHighAbove: pthora('fthoraDiatonicNiHighAbove', 'U+E197', undefined, 'diatonic', 'Ni'),
  fthoraHardChromaticPaAbove: pthora('fthoraHardChromaticPaAbove', 'U+E198', undefined, 'hard-chromatic', 'Pa'),
  fthoraHardChromaticDiAbove: pthora('fthoraHardChromaticDiAbove', 'U+E199', undefined, 'hard-chromatic', 'Di'),
  fthoraSoftChromaticDiAbove: pthora('fthoraSoftChromaticDiAbove', 'U+E19A', undefined, 'soft-chromatic', 'Di'),
  fthoraSoftChromaticKeAbove: pthora('fthoraSoftChromaticKeAbove', 'U+E19B', undefined, 'soft-chromatic', 'Ke'),
  fthoraEnharmonicAbove: qualitative('fthoraEnharmonicAbove', 'U+E19C', undefined, 'enharmonic'),

  chroaZygosAbove: qualitative('chroaZygosAbove', 'U+E19D', undefined, 'zygos'),
  chroaKlitonAbove: qualitative('chroaKlitonAbove', 'U+E19E', undefined, 'kliton'),
  chroaSpathiAbove: qualitative('chroaSpathiAbove', 'U+E19F', undefined, 'spathi'),

  martyriaNoteNiLow: martyriaNote('martyriaNoteNiLow', 'U+E131', 'Ni', -1),
  martyriaNotePaLow: martyriaNote('martyriaNotePaLow', 'U+E132', 'Pa', -1),
  martyriaNoteVouLow: martyriaNote('martyriaNoteVouLow', 'U+E133', 'Vou', -1),
  martyriaNoteGaLow: martyriaNote('martyriaNoteGaLow', 'U+E134', 'Ga', -1),
  martyriaNoteDiLow: martyriaNote('martyriaNoteDiLow', 'U+E135', 'Di', -1),
  martyriaNoteKeLow: martyriaNote('martyriaNoteKeLow', 'U+E136', 'Ke', -1),
  martyriaNoteZo: martyriaNote('martyriaNoteZo', 'U+E137', 'Zo', 0),
  martyriaNoteNi: martyriaNote('martyriaNoteNi', 'U+E138', 'Ni', 0),
  martyriaNotePa: martyriaNote('martyriaNotePa', 'U+E139', 'Pa', 0),
  martyriaNoteVou: martyriaNote('martyriaNoteVou', 'U+E13A', 'Vou', 0),
  martyriaNoteGa: martyriaNote('martyriaNoteGa', 'U+E13B', 'Ga', 0),
  martyriaNoteDi: martyriaNote('martyriaNoteDi', 'U+E13C', 'Di', 0),
  martyriaNoteKe: martyriaNote('martyriaNoteKe', 'U+E13D', 'Ke', 0),
  martyriaNoteZoHigh: martyriaNote('martyriaNoteZoHigh', 'U+E13E', 'Zo', 1),
  martyriaNoteNiHigh: martyriaNote('martyriaNoteNiHigh', 'U+E13F', 'Ni', 1),
  martyriaTick: qualitative('martyriaTick', 'U+E145', undefined, 'martyria-tick'),
  martyriaZoBelow: martyriaSign('martyriaZoBelow', 'U+E150', 'diatonic', 'Zo'),
  martyriaDeltaBelow: martyriaSign('martyriaDeltaBelow', 'U+E151', 'diatonic', 'Di'),
  martyriaAlphaBelow: martyriaSign('martyriaAlphaBelow', 'U+E152', 'diatonic', 'Pa'),
  martyriaLegetosBelow: martyriaSign('martyriaLegetosBelow', 'U+E153', 'diatonic', 'Vou'),
  martyriaNanaBelow: martyriaSign('martyriaNanaBelow', 'U+E154', 'diatonic', 'Ga'),
  martyriaHardChromaticPaBelow: martyriaSign('martyriaHardChromaticPaBelow', 'U+E157', 'hard-chromatic', 'Pa'),
  martyriaHardChromaticDiBelow: martyriaSign('martyriaHardChromaticDiBelow', 'U+E158', 'hard-chromatic', 'Di'),
  martyriaSoftChromaticDiBelow: martyriaSign('martyriaSoftChromaticDiBelow', 'U+E159', 'soft-chromatic', 'Di'),
  martyriaSoftChromaticKeBelow: martyriaSign('martyriaSoftChromaticKeBelow', 'U+E15A', 'soft-chromatic', 'Ke'),
  martyriaZygosBelow: martyriaQuality('martyriaZygosBelow', 'U+E15B', 'zygos'),
  martyriaZoAbove: martyriaSign('martyriaZoAbove', 'U+E170', 'diatonic', 'Zo'),
  martyriaDeltaAbove: martyriaSign('martyriaDeltaAbove', 'U+E171', 'diatonic', 'Di'),
  martyriaAlphaAbove: martyriaSign('martyriaAlphaAbove', 'U+E172', 'diatonic', 'Pa'),
  martyriaLegetosAbove: martyriaSign('martyriaLegetosAbove', 'U+E173', 'diatonic', 'Vou'),
  martyriaNanaAbove: martyriaSign('martyriaNanaAbove', 'U+E174', 'diatonic', 'Ga'),
  martyriaHardChromaticPaAbove: martyriaSign('martyriaHardChromaticPaAbove', 'U+E177', 'hard-chromatic', 'Pa'),
  martyriaHardChromaticDiAbove: martyriaSign('martyriaHardChromaticDiAbove', 'U+E178', 'hard-chromatic', 'Di'),
  martyriaSoftChromaticDiAbove: martyriaSign('martyriaSoftChromaticDiAbove', 'U+E179', 'soft-chromatic', 'Di'),
  martyriaSoftChromaticKeAbove: martyriaSign('martyriaSoftChromaticKeAbove', 'U+E17A', 'soft-chromatic', 'Ke'),
  martyriaZygosAbove: martyriaQuality('martyriaZygosAbove', 'U+E17B', 'zygos'),
});

const GLYPH_BY_NAME = new Map(Object.entries(GLYPH_METADATA));
const GLYPH_BY_CODEPOINT = new Map();
for (const metadata of Object.values(GLYPH_METADATA)) {
  for (const codepoint of [metadata.codepoint, metadata.alternateCodepoint]) {
    if (codepoint && !GLYPH_BY_CODEPOINT.has(codepoint)) {
      GLYPH_BY_CODEPOINT.set(codepoint, metadata);
    }
  }
}

export function semanticTokensFromGlyphs(inputs, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const tokens = Array.isArray(inputs) ? inputs : [inputs];
  return tokens.map((input, index) => semanticTokenFromGlyph(input, {
    diagnostics,
    index,
    source: options.source,
  }));
}

export function semanticTokenFromGlyph(input, options = {}) {
  if (input?.kind && input?.value && Array.isArray(input?.source)) {
    return input;
  }

  const diagnostics = options.diagnostics ?? [];
  const sourceToken = normalizeGlyphSourceToken(input, {
    index: options.index,
    source: options.source,
  });
  const metadata = glyphMetadataForSource(sourceToken);
  if (!metadata) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-unknown',
      message: `Unknown glyph token "${sourceToken.raw}".`,
      source: sourceToken,
    });
    return {
      kind: 'unknown',
      value: {},
      source: [sourceToken],
    };
  }

  const enrichedSource = {
    ...sourceToken,
    glyphName: sourceToken.glyphName ?? metadata.glyphName,
    codepoint: sourceToken.codepoint ?? metadata.codepoint,
    alternateCodepoint: sourceToken.alternateCodepoint ?? metadata.alternateCodepoint,
  };

  if (metadata.role === 'quantity') {
    return semanticToken('quantity', {
      glyphName: metadata.glyphName,
      movement: { ...metadata.movement },
      ...(metadata.quality ? { quality: metadata.quality } : {}),
    }, enrichedSource);
  }
  if (metadata.role === 'rest') {
    return semanticToken('rest', {
      sign: metadata.glyphName,
      beats: metadata.beats,
    }, enrichedSource);
  }
  if (metadata.role === 'temporal') {
    return semanticToken('temporal', { ...metadata.temporal }, enrichedSource);
  }
  if (metadata.role === 'duration') {
    return semanticToken('duration', {
      sign: metadata.glyphName,
      beats: metadata.beats,
    }, enrichedSource);
  }
  if (metadata.role === 'tempo') {
    return semanticToken('tempo', {
      tempoName: metadata.tempoName,
    }, enrichedSource);
  }
  if (metadata.role === 'pthora') {
    return semanticToken('pthora', {
      glyphName: metadata.glyphName,
      scale: metadata.scale,
      glyphDegree: metadata.glyphDegree,
      generatorRoot: chromaticGeneratorRoot(metadata.scale),
    }, enrichedSource);
  }
  if (metadata.role === 'qualitative') {
    return semanticToken('qualitative', {
      glyphName: metadata.glyphName,
      name: metadata.quality,
    }, enrichedSource);
  }
  if (metadata.role === 'martyria-note') {
    return semanticToken('martyria-note', {
      glyphName: metadata.glyphName,
      degree: metadata.degree,
      register: metadata.register,
    }, enrichedSource);
  }
  if (metadata.role === 'martyria-sign') {
    return semanticToken('martyria-sign', {
      glyphName: metadata.glyphName,
      scale: metadata.scale,
      glyphDegree: metadata.glyphDegree,
      ...(metadata.quality ? { quality: metadata.quality } : {}),
    }, enrichedSource);
  }

  pushDiagnostic(diagnostics, {
    severity: DIAGNOSTIC_SEVERITY.ERROR,
    code: 'glyph-import-role-unsupported',
    message: `Unsupported glyph role "${metadata.role}" for "${metadata.glyphName}".`,
    source: enrichedSource,
  });
  return {
    kind: 'unknown',
    value: {},
    source: [enrichedSource],
  };
}

export function normalizeGlyphSourceToken(input, options = {}) {
  if (input?.source && input?.raw && (input?.glyphName || input?.codepoint)) {
    return input;
  }

  const raw = rawGlyphText(input);
  const explicitCodepoint = normalizeCodepoint(input?.codepoint);
  const rawCodepoint = normalizeCodepoint(raw);
  const sourceCodepoint = explicitCodepoint ?? rawCodepoint ?? codepointFromCharacter(raw);
  const explicitGlyphName = typeof input?.glyphName === 'string'
    ? input.glyphName
    : undefined;
  const metadataByCodepoint = sourceCodepoint ? GLYPH_BY_CODEPOINT.get(sourceCodepoint) : undefined;
  const glyphName = explicitGlyphName ?? metadataByCodepoint?.glyphName ?? glyphNameFromRaw(raw);
  const metadataByName = glyphName ? GLYPH_BY_NAME.get(glyphName) : undefined;
  const codepoint = sourceCodepoint ?? metadataByName?.codepoint;
  const source = input?.source ?? options.source ?? inferSourceKind(sourceCodepoint);

  return {
    source,
    raw,
    ...(codepoint ? { codepoint } : {}),
    ...(glyphName ? { glyphName } : {}),
    ...(metadataByName?.alternateCodepoint || metadataByCodepoint?.alternateCodepoint
      ? { alternateCodepoint: metadataByName?.alternateCodepoint ?? metadataByCodepoint?.alternateCodepoint }
      : {}),
    ...(input?.span
      ? { span: input.span }
      : Number.isInteger(options.index) ? { span: { start: options.index, end: options.index + 1 } } : {}),
  };
}

export function sourceTokensFromGlyphText(text, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  if (typeof text !== 'string') {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-text-invalid',
      message: 'Glyph text import requires a string input.',
    });
    return [];
  }

  return tokenizeGlyphText(text)
    .filter(token => token.type === 'glyph')
    .map((token, index) => normalizeGlyphSourceToken({
      raw: token.raw,
      ...(options.source ? { source: options.source } : {}),
      span: token.span,
    }, { index }));
}

export function semanticTokenGroupsFromGlyphText(text, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const items = tokenizeGlyphText(text);
  const semanticItems = [];
  let glyphIndex = 0;

  for (const item of items) {
    if (item.type === 'separator') {
      semanticItems.push({ kind: 'separator', source: item });
      continue;
    }
    if (item.type !== 'glyph') continue;
    semanticItems.push(semanticTokenFromGlyph({
      raw: item.raw,
      ...(options.source ? { source: options.source } : {}),
      span: item.span,
    }, {
      diagnostics,
      index: glyphIndex,
    }));
    glyphIndex += 1;
  }

  return groupSemanticGlyphTokens(semanticItems, diagnostics);
}

export function chantScoreFromGlyphGroups(groups, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const semanticGroups = normalizeGlyphGroups(groups, diagnostics);
  const score = createChantScore();
  score.title = options.title ?? 'Imported Glyph Score';
  score.timingMode = options.timingMode ?? 'symbolic';
  score.orthography = options.orthography ?? 'generated';
  score.initialMartyria = {
    type: 'martyria',
    degree: normalizeDegree(options.startDegree) ?? 'Ni',
    source: importSource({ kind: 'initial-martyria' }),
  };
  score.initialScale = scaleSpec(options.scale ?? 'diatonic', {
    phase: options.phase,
    source: importSource({ kind: 'initial-scale' }),
  });

  const initialTempo = createTempoEvent({
    tempoName: options.tempoName ?? 'moderate',
    bpm: Number.isFinite(options.bpm) ? options.bpm : undefined,
    source: importSource({ kind: 'initial-tempo' }),
  });
  score.defaultTempoBpm = Number.isFinite(initialTempo.workingBpm)
    ? initialTempo.workingBpm
    : score.defaultTempoBpm;
  score.defaultAgogi = initialTempo.agogi;
  score.tempoPolicy = {
    source: 'glyph-import',
    bpm: score.defaultTempoBpm,
    ...(initialTempo.tempoName ? { tempoName: initialTempo.tempoName } : {}),
  };

  const defaultDrone = normalizeDegree(options.defaultDrone);
  if (defaultDrone) {
    score.defaultDrone = defaultDrone;
    score.defaultDroneRegister = Number.isInteger(options.defaultDroneRegister)
      ? options.defaultDroneRegister
      : 0;
  }

  let currentLinear = degreeIndex(score.initialMartyria.degree);
  for (const group of semanticGroups) {
    const event = scoreEventFromSemanticGroup(group, {
      diagnostics,
      currentLinear,
    });
    if (!event) continue;
    if (event.type === 'neume') {
      currentLinear += movementDelta(event.movement);
    }
    score.events.push(event);
  }

  return { score, semanticGroups, diagnostics };
}

export function compileGlyphGroups(groups, options = {}) {
  const imported = chantScoreFromGlyphGroups(groups, options);
  const compiled = compileChantScore(imported.score, {
    ...options,
    diagnostics: [...imported.diagnostics],
  });
  return {
    ...compiled,
    imported,
  };
}

export function compileGlyphText(text, options = {}) {
  const diagnostics = options.diagnostics ?? [];
  const semanticGroups = semanticTokenGroupsFromGlyphText(text, {
    ...options,
    diagnostics,
  });
  return compileGlyphGroups(semanticGroups, {
    ...options,
    diagnostics,
  });
}

export function compileSbmuflGlyphText(text, options = {}) {
  return compileGlyphText(text, {
    ...options,
    source: options.source ?? 'sbmufl-pua',
  });
}

export function compileUnicodeByzantineText(text, options = {}) {
  return compileGlyphText(text, {
    ...options,
    source: options.source ?? 'unicode-byzantine',
  });
}

export function listMinimalGlyphImportTokens() {
  return MINIMAL_GLYPH_IMPORT_NAMES
    .map(name => GLYPH_METADATA[name])
    .filter(Boolean)
    .map(publicGlyphImportToken);
}

export function listGlyphImportTokens() {
  return Object.values(GLYPH_METADATA).map(publicGlyphImportToken);
}

function scoreEventFromSemanticGroup(group, context) {
  const diagnostics = context.diagnostics;
  const quantityTokens = group.filter(token => token.kind === 'quantity');
  const restTokens = group.filter(token => token.kind === 'rest');
  const tempoTokens = group.filter(token => token.kind === 'tempo');
  const pthoraTokens = group.filter(token => token.kind === 'pthora');
  const temporalTokens = group.filter(token => token.kind === 'temporal');
  const durationTokens = group.filter(token => token.kind === 'duration');
  const qualitativeTokens = group.filter(token => token.kind === 'qualitative');
  const martyriaNoteTokens = group.filter(token => token.kind === 'martyria-note');
  const martyriaSignTokens = group.filter(token => token.kind === 'martyria-sign');
  const unknown = group.find(token => token.kind === 'unknown');
  if (unknown) return undefined;

  if (martyriaNoteTokens.length || martyriaSignTokens.length) {
    if (martyriaNoteTokens.length !== 1 || martyriaSignTokens.length > 1 || quantityTokens.length || restTokens.length || tempoTokens.length) {
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.ERROR,
        code: 'glyph-import-martyria-ambiguous',
        message: 'A martyria glyph group needs one martyria note and at most one martyria sign.',
        source: groupSource(group),
      });
      return undefined;
    }
    return martyriaEventFromTokens({
      noteToken: martyriaNoteTokens[0],
      signToken: martyriaSignTokens[0],
      pthoraToken: pthoraTokens.at(-1),
      qualitativeTokens,
      source: groupSource(group),
    });
  }

  if (quantityTokens.length > 1 || restTokens.length > 1) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-group-ambiguous',
      message: 'A glyph group may contain only one quantity or rest sign in this importer phase.',
      source: groupSource(group),
    });
    return undefined;
  }
  if (quantityTokens.length && restTokens.length) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-group-ambiguous',
      message: 'A glyph group cannot contain both a quantity sign and a rest sign.',
      source: groupSource(group),
    });
    return undefined;
  }

  if (tempoTokens.length && !quantityTokens.length && !restTokens.length) {
    return createTempoEvent({
      tempoName: tempoTokens.at(-1).value.tempoName,
      source: groupSource(group),
    });
  }

  if (restTokens.length) {
    return {
      type: 'rest',
      rest: { type: 'rest', sign: restTokens[0].value.sign },
      temporal: temporalEvents(temporalTokens, diagnostics),
      baseBeats: durationTokens.at(-1)?.value.beats ?? restTokens[0].value.beats,
      source: groupSource(group),
    };
  }

  if (!quantityTokens.length) {
    if (pthoraTokens.length) {
      const currentDegree = degreeFromLinearIndex(context.currentLinear);
      return pthoraEventFromToken(pthoraTokens.at(-1), currentDegree);
    }
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.ERROR,
      code: 'glyph-import-group-missing-quantity',
      message: 'A glyph group needs a quantity, rest, tempo, or pthora sign.',
      source: groupSource(group),
    });
    return undefined;
  }

  const quantity = quantityTokens[0];
  const nextLinear = context.currentLinear + movementDelta(quantity.value.movement);
  const attachedDegree = degreeFromLinearIndex(nextLinear);
  const pthoraToken = pthoraTokens.at(-1);
  const temporal = temporalEvents(temporalTokens, diagnostics);
  const unsupportedTemporal = temporal.find(sign => sign.type === 'unsupported');
  if (unsupportedTemporal) {
    pushDiagnostic(diagnostics, {
      severity: DIAGNOSTIC_SEVERITY.WARNING,
      code: 'glyph-import-temporal-unsupported',
      message: `${unsupportedTemporal.sign} is preserved as a qualitative sign; timing rewrite is not implemented yet.`,
      source: groupSource(group),
    });
  }

  return {
    type: 'neume',
    movement: { ...quantity.value.movement },
    temporal: temporal.filter(sign => sign.type !== 'unsupported'),
    qualitative: [
      ...(quantity.value.quality
        ? [{
            type: 'quality',
            name: quantity.value.quality,
            source: tokenSource(quantity),
          }]
        : []),
      ...qualitativeTokens.map(token => ({
        type: 'quality',
        name: token.value.name,
        source: tokenSource(token),
      })),
      ...temporal
        .filter(sign => sign.type === 'unsupported')
        .map(sign => ({
          type: 'quality',
          name: sign.sign,
          source: groupSource(group),
        })),
    ],
    ...(durationTokens.length ? { baseBeats: durationTokens.at(-1).value.beats } : {}),
    ...(pthoraToken ? { pthora: pthoraSpecFromToken(pthoraToken, attachedDegree) } : {}),
    display: {
      preferredGlyphName: quantity.value.glyphName,
    },
    source: groupSource(group),
  };
}

function martyriaEventFromTokens({ noteToken, signToken, pthoraToken, qualitativeTokens, source }) {
  const signScale = signToken?.value?.scale;
  const signDegree = normalizeDegree(signToken?.value?.glyphDegree);
  const degree = normalizeDegree(noteToken?.value?.degree) ?? signDegree ?? 'Ni';
  const scaleSourceToken = pthoraToken ?? (
    signScale
      ? {
          kind: 'pthora',
          value: {
            glyphName: signToken.value.glyphName,
            scale: signScale,
            glyphDegree: signToken.value.glyphDegree ?? degree,
          },
          source: signToken.source,
        }
      : undefined
  );
  return {
    type: 'martyria',
    degree,
    ...(Number.isInteger(noteToken?.value?.register) ? { register: noteToken.value.register } : {}),
    ...(scaleSourceToken ? { pthora: pthoraSpecFromToken(scaleSourceToken, degree) } : {}),
    qualitative: [
      ...(signToken?.value?.quality
        ? [{
            type: 'quality',
            name: signToken.value.quality,
            source: tokenSource(signToken),
          }]
        : []),
      ...qualitativeTokens.map(token => ({
        type: 'quality',
        name: token.value.name,
        source: tokenSource(token),
      })),
    ],
    source,
  };
}

function temporalEvents(tokens, diagnostics) {
  return tokens.map(token => {
    const temporal = { ...token.value };
    if (temporal.type === 'unsupported') return temporal;
    if (temporal.type !== 'quick' && temporal.type !== 'divide') {
      pushDiagnostic(diagnostics, {
        severity: DIAGNOSTIC_SEVERITY.ERROR,
        code: 'glyph-import-temporal-invalid',
        message: `Unsupported temporal token "${temporal.sign}".`,
        source: tokenSource(token),
      });
    }
    return {
      ...temporal,
      source: tokenSource(token),
    };
  });
}

function pthoraEventFromToken(token, attachedDegree) {
  const spec = pthoraSpecFromToken(token, attachedDegree);
  return {
    ...spec,
    degree: attachedDegree,
  };
}

function pthoraSpecFromToken(token, attachedDegree) {
  const scale = normalizeScaleName(token.value.scale) ?? 'diatonic';
  const definition = scaleDefinition(scale);
  const phase = inferPthoraPhase(token.value, attachedDegree);
  return {
    type: 'pthora',
    scale,
    genus: definition.genus,
    ...(Number.isInteger(phase) ? { phase } : {}),
    source: tokenSource(token),
  };
}

export function inferPthoraPhase(pthoraValue, attachedDegree) {
  const definition = scaleDefinition(pthoraValue?.scale);
  if (!definition?.cycle) return undefined;
  const root = chromaticGeneratorRoot(pthoraValue?.scale);
  const rootIndex = degreeIndex(root);
  const attachedIndex = degreeIndex(attachedDegree);
  if (rootIndex < 0 || attachedIndex < 0) return undefined;
  return positiveModulo(attachedIndex - rootIndex, 4);
}

function normalizeGlyphGroups(groups, diagnostics) {
  return (Array.isArray(groups) ? groups : [])
    .map(group => {
      const inputs = Array.isArray(group) ? group : [group];
      return semanticTokensFromGlyphs(inputs, { diagnostics });
    });
}

function groupSemanticGlyphTokens(tokens, diagnostics) {
  const groups = [];
  let current = [];
  let pending = [];

  const flushCurrent = () => {
    if (current.length) groups.push(current);
    current = [];
  };

  for (const token of tokens) {
    if (token.kind === 'separator') {
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

function tokenizeGlyphText(text) {
  const chars = Array.from(text ?? '');
  const tokens = [];
  let cursor = 0;

  const pushWord = start => {
    let end = start;
    while (end < chars.length && isWordGlyphChar(chars[end])) end += 1;
    tokens.push({
      type: 'glyph',
      raw: chars.slice(start, end).join(''),
      span: { start, end },
    });
    return end;
  };

  while (cursor < chars.length) {
    const char = chars[cursor];
    if (char === '\n' || char === '\r' || GLYPH_TEXT_GROUP_SEPARATORS.has(char)) {
      tokens.push({ type: 'separator', raw: char, span: { start: cursor, end: cursor + 1 } });
      cursor += 1;
      continue;
    }
    if (/\s|,/.test(char)) {
      cursor += 1;
      continue;
    }
    if (isGlyphTextWordStart(char)) {
      cursor = pushWord(cursor);
      continue;
    }
    tokens.push({
      type: 'glyph',
      raw: char,
      span: { start: cursor, end: cursor + 1 },
    });
    cursor += 1;
  }

  return tokens;
}

function isGlyphTextWordStart(char) {
  return /[A-Za-z_]/.test(char);
}

function isWordGlyphChar(char) {
  return /[A-Za-z0-9_+\-]/.test(char);
}

function glyphMetadataForSource(sourceToken) {
  if (sourceToken.glyphName && GLYPH_BY_NAME.has(sourceToken.glyphName)) {
    return GLYPH_BY_NAME.get(sourceToken.glyphName);
  }
  if (sourceToken.codepoint && GLYPH_BY_CODEPOINT.has(sourceToken.codepoint)) {
    return GLYPH_BY_CODEPOINT.get(sourceToken.codepoint);
  }
  return undefined;
}

function scaleSpec(scaleName, { phase, source } = {}) {
  const scale = normalizeScaleName(scaleName) ?? 'diatonic';
  const definition = scaleDefinition(scale);
  return {
    type: 'pthora',
    scale,
    genus: definition.genus,
    ...(Number.isInteger(phase) ? { phase } : {}),
    ...(source ? { source } : {}),
  };
}

function movementDelta(movement) {
  if (movement?.direction === 'up') return movement.steps ?? 1;
  if (movement?.direction === 'down') return -(movement.steps ?? 1);
  return 0;
}

function groupSource(group) {
  return importSource({
    tokens: group.flatMap(token => token.source ?? []),
  });
}

function tokenSource(token) {
  return importSource({
    tokens: token?.source ?? [],
  });
}

function importSource(detail) {
  return {
    source: {
      kind: 'glyph-import',
      ...detail,
    },
  };
}

function semanticToken(kind, value, sourceToken) {
  return {
    kind,
    value,
    source: [sourceToken],
  };
}

function quantity(glyphName, codepoint, alternateCodepoint, direction, steps, options = {}) {
  return {
    role: 'quantity',
    glyphName,
    codepoint,
    alternateCodepoint,
    movement: { direction, steps },
    ...(options.quality ? { quality: options.quality } : {}),
  };
}

function rest(glyphName, codepoint, alternateCodepoint, beats) {
  return { role: 'rest', glyphName, codepoint, alternateCodepoint, beats };
}

function temporal(glyphName, codepoint, alternateCodepoint, value) {
  return { role: 'temporal', glyphName, codepoint, alternateCodepoint, temporal: value };
}

function duration(glyphName, codepoint, alternateCodepoint, beats) {
  return { role: 'duration', glyphName, codepoint, alternateCodepoint, beats };
}

function tempo(glyphName, codepoint, alternateCodepoint, tempoName) {
  return { role: 'tempo', glyphName, codepoint, alternateCodepoint, tempoName };
}

function pthora(glyphName, codepoint, alternateCodepoint, scale, glyphDegree) {
  return { role: 'pthora', glyphName, codepoint, alternateCodepoint, scale, glyphDegree };
}

function qualitative(glyphName, codepoint, alternateCodepoint, quality) {
  return { role: 'qualitative', glyphName, codepoint, alternateCodepoint, quality };
}

function martyriaNote(glyphName, codepoint, degree, register) {
  return { role: 'martyria-note', glyphName, codepoint, degree, register };
}

function martyriaSign(glyphName, codepoint, scale, glyphDegree) {
  return { role: 'martyria-sign', glyphName, codepoint, scale, glyphDegree };
}

function martyriaQuality(glyphName, codepoint, quality) {
  return { role: 'martyria-sign', glyphName, codepoint, quality };
}

function chromaticGeneratorRoot(scale) {
  const normalized = normalizeScaleName(scale);
  if (normalized === 'hard-chromatic') return 'Pa';
  return 'Ni';
}

function rawGlyphText(input) {
  if (typeof input === 'string') return input;
  if (typeof input?.raw === 'string') return input.raw;
  if (typeof input?.glyphName === 'string') return input.glyphName;
  if (typeof input?.codepoint === 'string') return input.codepoint;
  return String(input ?? '');
}

function glyphNameFromRaw(raw) {
  return GLYPH_BY_NAME.has(raw) ? raw : undefined;
}

function normalizeCodepoint(value) {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim().toUpperCase();
  if (!/^U\+[0-9A-F]{4,6}$/.test(trimmed)) return undefined;
  return trimmed;
}

function codepointFromCharacter(raw) {
  if (typeof raw !== 'string') return undefined;
  const chars = Array.from(raw);
  if (chars.length !== 1) return undefined;
  const value = chars[0].codePointAt(0);
  if (!Number.isInteger(value)) return undefined;
  return `U+${value.toString(16).toUpperCase().padStart(4, '0')}`;
}

function inferSourceKind(codepoint) {
  const value = numericCodepoint(codepoint);
  if (value >= UNICODE_BYZANTINE_START && value <= UNICODE_BYZANTINE_END) return 'unicode-byzantine';
  if (value >= PUA_START && value <= PUA_END) return 'sbmufl-pua';
  return 'glyph-name';
}

function numericCodepoint(codepoint) {
  const normalized = normalizeCodepoint(codepoint);
  return normalized ? Number.parseInt(normalized.slice(2), 16) : NaN;
}

function publicGlyphImportToken(metadata) {
  return {
    glyphName: metadata.glyphName,
    role: metadata.role,
    ...(metadata.codepoint ? { codepoint: metadata.codepoint } : {}),
    ...(metadata.alternateCodepoint ? { alternateCodepoint: metadata.alternateCodepoint } : {}),
    ...(metadata.movement ? { movement: { ...metadata.movement } } : {}),
    ...(Number.isFinite(metadata.beats) ? { beats: metadata.beats } : {}),
    ...(metadata.temporal ? { temporal: { ...metadata.temporal } } : {}),
    ...(metadata.tempoName ? { tempoName: metadata.tempoName } : {}),
    ...(metadata.scale ? { scale: metadata.scale } : {}),
    ...(metadata.glyphDegree ? { glyphDegree: metadata.glyphDegree } : {}),
    ...(metadata.quality ? { quality: metadata.quality } : {}),
  };
}

export const MINIMAL_GLYPH_IMPORT_METADATA = GLYPH_METADATA;

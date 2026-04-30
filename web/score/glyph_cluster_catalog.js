import { listMinimalGlyphImportTokens } from './glyph_import.js';

const MINIMAL_CODEPOINTS = listMinimalGlyphImportTokens()
  .filter(token => token.codepoint)
  .map(token => [token.glyphName, token.codepoint]);

const EXTRA_GLYPH_CODEPOINTS = [
  ['oligonKentimaMiddle', 'U+E002'],
  ['oligonKentimaBelow', 'U+E003'],
  ['oligonKentimaAbove', 'U+E004'],
  ['oligonYpsiliRight', 'U+E005'],
  ['oligonYpsiliLeft', 'U+E006'],
  ['oligonKentimaYpsiliRight', 'U+E007'],
  ['oligonKentimaYpsiliMiddle', 'U+E008'],
  ['oligonDoubleYpsili', 'U+E009'],
  ['oligonKentimataDoubleYpsili', 'U+E00A'],
  ['oligonKentimaDoubleYpsiliRight', 'U+E00B'],
  ['oligonKentimaDoubleYpsiliLeft', 'U+E00C'],
  ['oligonTripleYpsili', 'U+E00D'],
  ['oligonKentimataTripleYpsili', 'U+E00E'],
  ['oligonKentimaTripleYpsili', 'U+E00F'],
  ['oligonIson', 'U+E010'],
  ['oligonApostrofos', 'U+E011'],
  ['oligonYporroi', 'U+E012'],
  ['oligonElafron', 'U+E013'],
  ['oligonElafronApostrofos', 'U+E014'],
  ['oligonChamili', 'U+E015'],
  ['isonApostrofos', 'U+E020'],
  ['petastiIson', 'U+E040'],
  ['petasti', 'U+E041'],
  ['petastiOligon', 'U+E042'],
  ['petastiKentima', 'U+E043'],
  ['petastiYpsiliRight', 'U+E044'],
  ['petastiYpsiliLeft', 'U+E045'],
  ['petastiKentimaYpsiliRight', 'U+E046'],
  ['petastiKentimaYpsiliMiddle', 'U+E047'],
  ['petastiDoubleYpsili', 'U+E048'],
  ['petastiKentimataDoubleYpsili', 'U+E049'],
  ['petastiKentimaDoubleYpsiliRight', 'U+E04A'],
  ['petastiKentimaDoubleYpsiliLeft', 'U+E04B'],
  ['petastiTripleYpsili', 'U+E04C'],
  ['petastiKentimataTripleYpsili', 'U+E04D'],
  ['petastiKentimaTripleYpsili', 'U+E04E'],
  ['petastiApostrofos', 'U+E060'],
  ['petastiYporroi', 'U+E061'],
  ['petastiElafron', 'U+E062'],
  ['petastiRunningElafron', 'U+E063'],
  ['petastiElafronApostrofos', 'U+E064'],
  ['petastiChamili', 'U+E065'],
  ['petastiChamiliApostrofos', 'U+E066'],
  ['petastiChamiliElafron', 'U+E067'],
  ['petastiChamiliElafronApostrofos', 'U+E068'],
  ['petastiDoubleChamili', 'U+E069'],
  ['petastiDoubleChamiliApostrofos', 'U+E06A'],
  ['kentima', 'U+E080'],
  ['kentimata', 'U+E081'],
  ['oligonKentimataBelow', 'U+E082'],
  ['oligonKentimataAbove', 'U+E083'],
  ['oligonIsonKentimata', 'U+E084'],
  ['oligonKentimaMiddleKentimata', 'U+E085'],
  ['oligonYpsiliRightKentimata', 'U+E086'],
  ['oligonYpsiliLeftKentimata', 'U+E087'],
  ['oligonApostrofosKentimata', 'U+E088'],
  ['oligonYporroiKentimata', 'U+E089'],
  ['oligonElafronKentimata', 'U+E08A'],
  ['oligonRunningElafronKentimata', 'U+E08B'],
  ['oligonElafronApostrofosKentimata', 'U+E08C'],
  ['oligonChamiliKentimata', 'U+E08D'],
  ['klasmaBelow', 'U+E0D1'],
  ['tetrapli', 'U+E0D5'],
  ['gorgonBelow', 'U+E0F1'],
  ['gorgonDottedLeft', 'U+E0F2'],
  ['gorgonDottedRight', 'U+E0F3'],
  ['digorgonDottedLeftBelow', 'U+E0F5'],
  ['digorgonDottedLeftAbove', 'U+E0F6'],
  ['digorgonDottedRight', 'U+E0F7'],
  ['trigorgonDottedLeftBelow', 'U+E0F9'],
  ['trigorgonDottedLeftAbove', 'U+E0FA'],
  ['trigorgonDottedRight', 'U+E0FB'],
  ['gorgonSecondary', 'U+E100'],
  ['gorgonDottedLeftSecondary', 'U+E101'],
  ['gorgonDottedRightSecondary', 'U+E102'],
  ['digorgonSecondary', 'U+E103'],
  ['digorgonDottedLeftBelowSecondary', 'U+E104'],
  ['digorgonDottedRightSecondary', 'U+E105'],
  ['trigorgonSecondary', 'U+E106'],
  ['trigorgonDottedLeftBelowSecondary', 'U+E107'],
  ['trigorgonDottedRightSecondary', 'U+E108'],
  ['digorgonDottedLeftSecondary', 'U+E109'],
  ['trigorgonDottedLeftSecondary', 'U+E10A'],
  ['martyriaNoteNiLow', 'U+E131'],
  ['martyriaNotePaLow', 'U+E132'],
  ['martyriaNoteVouLow', 'U+E133'],
  ['martyriaNoteGaLow', 'U+E134'],
  ['martyriaNoteDiLow', 'U+E135'],
  ['martyriaNoteKeLow', 'U+E136'],
  ['martyriaNoteZo', 'U+E137'],
  ['martyriaNoteNi', 'U+E138'],
  ['martyriaNotePa', 'U+E139'],
  ['martyriaNoteVou', 'U+E13A'],
  ['martyriaNoteGa', 'U+E13B'],
  ['martyriaNoteDi', 'U+E13C'],
  ['martyriaNoteKe', 'U+E13D'],
  ['martyriaNoteZoHigh', 'U+E13E'],
  ['martyriaNoteNiHigh', 'U+E13F'],
  ['martyriaTick', 'U+E145'],
  ['martyriaZoBelow', 'U+E150'],
  ['martyriaDeltaBelow', 'U+E151'],
  ['martyriaAlphaBelow', 'U+E152'],
  ['martyriaLegetosBelow', 'U+E153'],
  ['martyriaNanaBelow', 'U+E154'],
  ['martyriaHardChromaticPaBelow', 'U+E157'],
  ['martyriaHardChromaticDiBelow', 'U+E158'],
  ['martyriaSoftChromaticDiBelow', 'U+E159'],
  ['martyriaSoftChromaticKeBelow', 'U+E15A'],
  ['martyriaZygosBelow', 'U+E15B'],
  ['martyriaZoAbove', 'U+E170'],
  ['martyriaDeltaAbove', 'U+E171'],
  ['martyriaAlphaAbove', 'U+E172'],
  ['martyriaLegetosAbove', 'U+E173'],
  ['martyriaNanaAbove', 'U+E174'],
  ['martyriaHardChromaticPaAbove', 'U+E177'],
  ['martyriaHardChromaticDiAbove', 'U+E178'],
  ['martyriaSoftChromaticDiAbove', 'U+E179'],
  ['martyriaSoftChromaticKeAbove', 'U+E17A'],
  ['martyriaZygosAbove', 'U+E17B'],
  ['fthoraDiatonicNiLowAbove', 'U+E190'],
  ['fthoraDiatonicPaAbove', 'U+E191'],
  ['fthoraDiatonicVouAbove', 'U+E192'],
  ['fthoraDiatonicGaAbove', 'U+E193'],
  ['fthoraDiatonicDiAbove', 'U+E194'],
  ['fthoraDiatonicKeAbove', 'U+E195'],
  ['fthoraDiatonicZoAbove', 'U+E196'],
  ['fthoraDiatonicNiHighAbove', 'U+E197'],
  ['fthoraEnharmonicAbove', 'U+E19C'],
];

export const GLYPH_CODEPOINTS = Object.freeze(Object.fromEntries([
  ...MINIMAL_CODEPOINTS,
  ...EXTRA_GLYPH_CODEPOINTS,
]));

export const GLYPH_CLUSTER_CATALOG = Object.freeze([
  ...basicQuantityClusters(),
  ...precomposedClusters('oligon-compounds', 'Oligon Compounds', [
    'oligonKentimaMiddle',
    'oligonKentimaBelow',
    'oligonKentimaAbove',
    'oligonYpsiliRight',
    'oligonYpsiliLeft',
    'oligonKentimaYpsiliRight',
    'oligonKentimaYpsiliMiddle',
    'oligonDoubleYpsili',
    'oligonKentimataDoubleYpsili',
    'oligonKentimaDoubleYpsiliRight',
    'oligonKentimaDoubleYpsiliLeft',
    'oligonTripleYpsili',
    'oligonKentimataTripleYpsili',
    'oligonKentimaTripleYpsili',
    'oligonIson',
    'oligonApostrofos',
    'oligonYporroi',
    'oligonElafron',
    'oligonElafronApostrofos',
    'oligonChamili',
    'isonApostrofos',
  ], { semantic: pendingSemantic('precomposed oligon-family quantity cluster') }),
  ...precomposedClusters('petasti-compounds', 'Petasti Compounds', [
    'petastiIson',
    'petasti',
    'petastiOligon',
    'petastiKentima',
    'petastiYpsiliRight',
    'petastiYpsiliLeft',
    'petastiKentimaYpsiliRight',
    'petastiKentimaYpsiliMiddle',
    'petastiDoubleYpsili',
    'petastiKentimataDoubleYpsili',
    'petastiKentimaDoubleYpsiliRight',
    'petastiKentimaDoubleYpsiliLeft',
    'petastiTripleYpsili',
    'petastiKentimataTripleYpsili',
    'petastiKentimaTripleYpsili',
    'petastiApostrofos',
    'petastiYporroi',
    'petastiElafron',
    'petastiRunningElafron',
    'petastiElafronApostrofos',
    'petastiChamili',
    'petastiChamiliApostrofos',
    'petastiChamiliElafron',
    'petastiChamiliElafronApostrofos',
    'petastiDoubleChamili',
    'petastiDoubleChamiliApostrofos',
  ], { semantic: pendingSemantic('precomposed petasti-family quantity cluster') }),
  ...precomposedClusters('kentimata-compounds', 'Kentimata Compounds', [
    'kentima',
    'kentimata',
    'oligonKentimataBelow',
    'oligonKentimataAbove',
    'oligonIsonKentimata',
    'oligonKentimaMiddleKentimata',
    'oligonYpsiliRightKentimata',
    'oligonYpsiliLeftKentimata',
    'oligonApostrofosKentimata',
    'oligonYporroiKentimata',
    'oligonElafronKentimata',
    'oligonRunningElafronKentimata',
    'oligonElafronApostrofosKentimata',
    'oligonChamiliKentimata',
  ], { semantic: pendingSemantic('precomposed kentimata-family quantity cluster') }),
  ...restClusters(),
  ...durationClusters(),
  ...timingClusters(),
  ...modeSignClusters(),
  ...martyriaClusters(),
  ...attachmentExampleClusters(),
]);

export function listGlyphClusterCatalog() {
  return GLYPH_CLUSTER_CATALOG;
}

export function glyphCodepoint(glyphName) {
  return GLYPH_CODEPOINTS[glyphName];
}

export function glyphCharacter(glyphName) {
  const codepoint = glyphCodepoint(glyphName);
  if (!codepoint) return undefined;
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(codepoint);
  return match ? String.fromCodePoint(Number.parseInt(match[1], 16)) : undefined;
}

function basicQuantityClusters() {
  return [
    cluster('quantity-ison', 'Basic Quantities', 'ison', [main('ison', 'quantity')], {
      semantic: { kind: 'neume', movement: { direction: 'same', steps: 0 } },
    }),
    cluster('quantity-oligon', 'Basic Quantities', 'oligon', [main('oligon', 'quantity')], {
      semantic: { kind: 'neume', movement: { direction: 'up', steps: 1 } },
    }),
    cluster('quantity-apostrofos', 'Basic Quantities', 'apostrofos', [main('apostrofos', 'quantity')], {
      semantic: { kind: 'neume', movement: { direction: 'down', steps: 1 } },
    }),
    cluster('quantity-yporroi', 'Basic Quantities', 'yporroi', [main('yporroi', 'quantity')], {
      semantic: { kind: 'neume', movement: { direction: 'down', steps: 2 } },
    }),
    cluster('quantity-elafron', 'Basic Quantities', 'elafron', [main('elafron', 'quantity')], {
      semantic: { kind: 'neume', movement: { direction: 'down', steps: 2 } },
    }),
    cluster('quantity-chamili', 'Basic Quantities', 'chamili', [main('chamili', 'quantity')], {
      semantic: { kind: 'neume', movement: { direction: 'down', steps: 4 } },
    }),
  ];
}

function restClusters() {
  return ['leimma1', 'leimma2', 'leimma3', 'leimma4'].map((glyphName, index) => (
    cluster(`rest-${glyphName}`, 'Rests', glyphName, [main(glyphName, 'rest')], {
      semantic: { kind: 'rest', beats: index + 1 },
    })
  ));
}

function durationClusters() {
  return [
    ['apli', 2],
    ['klasma', 2],
    ['dipli', 3],
    ['tripli', 4],
    ['tetrapli', 5],
  ].map(([glyphName, beats]) => cluster(`duration-${glyphName}`, 'Duration Signs', glyphName, [
    above(glyphName, 'duration'),
  ], {
    semantic: { kind: 'duration', beats },
  }));
}

function timingClusters() {
  return [
    timing('gorgonAbove', [1, 1]),
    timing('gorgonDottedLeft', [2, 1]),
    timing('gorgonDottedRight', [1, 2]),
    timing('digorgon', [1, 1, 1]),
    timing('digorgonDottedLeftBelow', [2, 1, 1]),
    timing('digorgonDottedLeftAbove', [1, 2, 1]),
    timing('digorgonDottedRight', [1, 1, 2]),
    timing('trigorgon', [1, 1, 1, 1]),
    timing('trigorgonDottedLeftBelow', [2, 1, 1, 1]),
    timing('trigorgonDottedLeftAbove', [1, 2, 1, 1]),
    timing('trigorgonDottedRight', [1, 1, 1, 2]),
    timing('gorgonSecondary', [1, 1], 'secondary'),
    timing('digorgonSecondary', [1, 1, 1], 'secondary'),
    timing('trigorgonSecondary', [1, 1, 1, 1], 'secondary'),
  ];
}

function modeSignClusters() {
  return [
    'fthoraDiatonicNiLowAbove',
    'fthoraDiatonicPaAbove',
    'fthoraDiatonicVouAbove',
    'fthoraDiatonicGaAbove',
    'fthoraDiatonicDiAbove',
    'fthoraDiatonicKeAbove',
    'fthoraDiatonicZoAbove',
    'fthoraDiatonicNiHighAbove',
    'fthoraHardChromaticPaAbove',
    'fthoraHardChromaticDiAbove',
    'fthoraSoftChromaticDiAbove',
    'fthoraSoftChromaticKeAbove',
    'fthoraEnharmonicAbove',
    'chroaZygosAbove',
    'chroaKlitonAbove',
    'chroaSpathiAbove',
  ].map(glyphName => cluster(`mode-${glyphName}`, 'Pthora And Chroa', glyphName, [
    above(glyphName, glyphName.startsWith('chroa') ? 'qualitative' : 'pthora'),
  ], {
    semantic: pendingSemantic('mode sign attachment; compiler meaning depends on attached degree'),
  }));
}

function martyriaClusters() {
  return [
    cluster('martyria-di-diatonic', 'Martyria Checkpoints', 'Di diatonic martyria', [
      main('martyriaNoteDi', 'martyria-note'),
      below('martyriaDeltaBelow', 'martyria-sign'),
    ], {
      semantic: { kind: 'martyria', degree: 'Di', scale: 'diatonic' },
    }),
    cluster('martyria-di-soft-chromatic', 'Martyria Checkpoints', 'Di soft chromatic martyria', [
      main('martyriaNoteDi', 'martyria-note'),
      below('martyriaSoftChromaticDiBelow', 'martyria-sign'),
    ], {
      semantic: { kind: 'martyria', degree: 'Di', scale: 'soft-chromatic' },
    }),
    cluster('martyria-pa-hard-chromatic', 'Martyria Checkpoints', 'Pa hard chromatic martyria', [
      main('martyriaNotePa', 'martyria-note'),
      below('martyriaHardChromaticPaBelow', 'martyria-sign'),
    ], {
      semantic: { kind: 'martyria', degree: 'Pa', scale: 'hard-chromatic' },
    }),
  ];
}

function attachmentExampleClusters() {
  return [
    cluster('example-oligon-gorgon', 'Attachment Examples', 'oligon + gorgon', [
      above('gorgonAbove', 'temporal'),
      main('oligon', 'quantity'),
    ], {
      semantic: { kind: 'neume', movement: { direction: 'up', steps: 1 }, timingWeights: [1, 1] },
    }),
    cluster('example-oligon-klasma', 'Attachment Examples', 'oligon + klasma', [
      above('klasma', 'duration'),
      main('oligon', 'quantity'),
    ], {
      semantic: { kind: 'neume', movement: { direction: 'up', steps: 1 }, beats: 2 },
    }),
    cluster('example-apostrofos-digorgon-dotted', 'Attachment Examples', 'apostrofos + dotted digorgon', [
      above('digorgonDottedLeftAbove', 'temporal'),
      main('apostrofos', 'quantity'),
    ], {
      semantic: { kind: 'neume', movement: { direction: 'down', steps: 1 }, timingWeights: [1, 2, 1] },
    }),
    cluster('example-oligon-soft-di', 'Attachment Examples', 'oligon + soft Di pthora', [
      above('fthoraSoftChromaticDiAbove', 'pthora'),
      main('oligon', 'quantity'),
    ], {
      semantic: { kind: 'neume', movement: { direction: 'up', steps: 1 }, modeSign: 'soft-chromatic' },
    }),
  ];
}

function precomposedClusters(category, categoryLabel, glyphNames, options = {}) {
  return glyphNames.map(glyphName => cluster(`${category}-${glyphName}`, categoryLabel, glyphName, [
    main(glyphName, 'precomposed-quantity'),
  ], options));
}

function timing(glyphName, weights, variant = 'primary') {
  return cluster(`timing-${glyphName}`, 'Timing Signs', glyphName, [above(glyphName, 'temporal')], {
    semantic: {
      kind: 'temporal',
      variant,
      timingWeights: weights,
    },
  });
}

function pendingSemantic(note) {
  return {
    kind: 'pending-interpretation',
    note,
  };
}

function cluster(id, category, label, components, options = {}) {
  return Object.freeze({
    id,
    category,
    label,
    components: Object.freeze(components.map(component => Object.freeze(component))),
    semantic: Object.freeze(options.semantic ?? pendingSemantic('not yet mapped')),
    tags: Object.freeze(options.tags ?? []),
  });
}

function main(glyphName, role) {
  return component(glyphName, 'main', role);
}

function above(glyphName, role) {
  return component(glyphName, 'above', role);
}

function below(glyphName, role) {
  return component(glyphName, 'below', role);
}

function component(glyphName, slot, role) {
  return { glyphName, slot, role };
}

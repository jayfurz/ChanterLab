import {
  glyphCodepoint,
  listGlyphClusterCatalog,
} from './score/glyph_cluster_catalog.js?v=chant-script-engine-phase6p';
import {
  createGlyphClusterElement,
  formatGlyphClusterSemantic,
  glyphClusterRenderModel,
} from './score/glyph_cluster_render.js?v=chant-script-engine-phase6p';

const GLYPH_ATLAS_RUNTIME_BUILD = 'phase6p renderer-module-cache-bust';
const root = document.getElementById('glyph-atlas-root');
const summary = document.getElementById('glyph-atlas-summary');
const build = document.querySelector('.glyph-atlas-build');
if (build) build.textContent = `${build.textContent} | ${GLYPH_ATLAS_RUNTIME_BUILD}`;
const params = new URLSearchParams(window.location.search);
const categoryFilter = params.get('category')?.trim().toLowerCase();
const clusters = categoryFilter
  ? listGlyphClusterCatalog().filter(cluster => cluster.category.toLowerCase() === categoryFilter)
  : listGlyphClusterCatalog();
const groups = groupByCategory(clusters);

for (const [category, items] of groups) {
  const section = document.createElement('section');
  section.className = 'glyph-atlas-section';

  const header = document.createElement('div');
  header.className = 'glyph-atlas-section-header';
  const title = document.createElement('h2');
  title.textContent = category;
  const count = document.createElement('span');
  count.textContent = `${items.length} clusters`;
  header.append(title, count);
  section.appendChild(header);

  const grid = document.createElement('div');
  grid.className = 'glyph-atlas-grid';
  for (const cluster of items) {
    grid.appendChild(createAtlasCell(cluster));
  }
  section.appendChild(grid);
  root.appendChild(section);
}

const missingGlyphs = clusters
  .flatMap(cluster => glyphClusterRenderModel(cluster).missing)
  .filter((glyphName, index, all) => all.indexOf(glyphName) === index);

summary.textContent = [
  `${clusters.length} clusters`,
  `${groups.size} groups`,
  missingGlyphs.length ? `${missingGlyphs.length} missing glyphs` : 'all glyphs mapped',
].join(' | ');
summary.classList.toggle('has-warnings', missingGlyphs.length > 0);

function createAtlasCell(cluster) {
  const model = glyphClusterRenderModel(cluster);
  const cell = document.createElement('article');
  cell.className = 'glyph-atlas-cell';
  cell.dataset.clusterId = cluster.id;
  if (model.missing.length) cell.classList.add('has-warnings');

  const visual = document.createElement('div');
  visual.className = 'glyph-atlas-visual';
  visual.appendChild(createGlyphClusterElement(cluster));

  const label = document.createElement('h3');
  label.textContent = cluster.label;

  const id = document.createElement('div');
  id.className = 'glyph-atlas-id';
  id.textContent = cluster.id;

  const semantic = document.createElement('div');
  semantic.className = 'glyph-atlas-semantic';
  semantic.textContent = formatGlyphClusterSemantic(cluster.semantic);

  const codepoints = document.createElement('div');
  codepoints.className = 'glyph-atlas-codepoints';
  codepoints.textContent = cluster.components
    .map(component => `${component.glyphName} ${glyphCodepoint(component.glyphName) ?? 'missing'}`)
    .join(' / ');

  cell.append(visual, label, id, semantic, codepoints);
  return cell;
}

function groupByCategory(items) {
  const map = new Map();
  for (const item of items) {
    if (!map.has(item.category)) map.set(item.category, []);
    map.get(item.category).push(item);
  }
  return map;
}

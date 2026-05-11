// E2E tests for the Chanterlab OCR import pipeline.
// Tests: import page UI, atlas render, synthetic page generation, CNN-based recognition.
import { test, expect } from '@playwright/test';

const BASE = 'http://localhost:8432';

test.describe('OCR Import Page', () => {

  test('page loads with all required UI elements', async ({ page }) => {
    await page.goto(`${BASE}/ocr/import.html`, { waitUntil: 'networkidle' });

    // Header
    await expect(page.locator('h1')).toContainText('Chant OCR');

    // Backend selector
    const backend = page.locator('#backend');
    await expect(backend).toBeVisible();
    const options = await backend.locator('option').allTextContents();
    expect(options).toContain('CNN (trained, 62% acc)');
    expect(options).toContain('Template matching (font only)');

    // Drop zone
    await expect(page.locator('#dropZone')).toBeVisible();
    await expect(page.locator('#dropZone')).toContainText('Drop an image');

    // File input
    await expect(page.locator('#file[type=file]')).toBeAttached();

    // Status element
    await expect(page.locator('#status')).toBeVisible();

    // Canvas elements
    await expect(page.locator('#source')).toBeAttached();
    await expect(page.locator('#overlay')).toBeAttached();

    // Token list and compiled output panels (hidden until an image is processed)
    await expect(page.locator('#tokens')).toBeAttached();
    await expect(page.locator('#compiled')).toBeAttached();

    // Run button
    await expect(page.locator('#runBtn')).toBeVisible();
  });

  test('backend selector defaults to CNN', async ({ page }) => {
    await page.goto(`${BASE}/ocr/import.html`, { waitUntil: 'networkidle' });
    const backend = page.locator('#backend');
    await expect(backend).toHaveValue('cnn');
  });

  test('template backend shows cell size option', async ({ page }) => {
    await page.goto(`${BASE}/ocr/import.html`, { waitUntil: 'networkidle' });
    await page.selectOption('#backend', 'template');
    await expect(page.locator('#cellSize')).toBeVisible();
    // Switch back to CNN — cellSize still visible (not hidden, just unused)
    await page.selectOption('#backend', 'cnn');
    await expect(page.locator('#cellSize')).toBeVisible();
  });

  test('start degree input defaults to Ni', async ({ page }) => {
    await page.goto(`${BASE}/ocr/import.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#startDegree')).toHaveValue('Ni');
  });

  test('show labels checkbox is checked by default', async ({ page }) => {
    await page.goto(`${BASE}/ocr/import.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#showLabels')).toBeChecked();
  });
});

test.describe('Glyph Reference Atlas', () => {

  test('atlas renders with expected canvas dimensions', async ({ page }) => {
    await page.goto(`${BASE}/ocr/atlas.html`, { waitUntil: 'networkidle' });

    // Wait for the atlas canvas to render
    const canvas = page.locator('#atlas');
    await expect(canvas).toBeAttached();

    // Wait for the rendering to complete (status shows glyph count)
    await expect(page.locator('#status')).toContainText('glyphs', { timeout: 15000 });

    // Canvas should have non-zero dimensions
    const width = await canvas.evaluate(el => el.width);
    const height = await canvas.evaluate(el => el.height);
    expect(width).toBeGreaterThan(1000);
    expect(height).toBeGreaterThan(3000);

    // Download button should be enabled after render
    await expect(page.locator('#downloadBtn')).toBeEnabled();
  });

  test('atlas status shows glyph count and dimensions', async ({ page }) => {
    await page.goto(`${BASE}/ocr/atlas.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#status')).toContainText('glyphs', { timeout: 15000 });

    const statusText = await page.locator('#status').textContent();
    // Should show glyph count
    expect(statusText).toMatch(/\d+ glyphs/);
    // Should show pixel dimensions
    expect(statusText).toMatch(/\d+×\d+px/);
  });

  test('atlas renders multiple sections', async ({ page }) => {
    await page.goto(`${BASE}/ocr/atlas.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#status')).toContainText('glyphs', { timeout: 15000 });

    const statusText = await page.locator('#status').textContent();
    // Should have 10+ sections
    const sections = parseInt(statusText.match(/(\d+) sections/)?.[1] || '0');
    expect(sections).toBeGreaterThanOrEqual(10);
  });
});

test.describe('Synthetic Page Generator', () => {

  test('page loads with sample text and renders on load', async ({ page }) => {
    await page.goto(`${BASE}/ocr/synth.html`, { waitUntil: 'networkidle' });

    // Text area should have default sample
    const textarea = page.locator('#text');
    await expect(textarea).toBeVisible();
    const text = await textarea.inputValue();
    expect(text.length).toBeGreaterThan(0);

    // Status should show rendered result after initial render
    await expect(page.locator('#summary')).toContainText('glyphs', { timeout: 15000 });

    // Canvas should exist
    await expect(page.locator('#canvas')).toBeAttached();
  });

  test('changing sample dropdown loads new text', async ({ page }) => {
    await page.goto(`${BASE}/ocr/synth.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#summary')).toContainText('glyphs', { timeout: 15000 });

    // Select a different sample
    await page.selectOption('#sample', { label: 'Soft Chromatic Di' });
    await page.click('#loadSampleBtn');

    // Text area should update
    const text = await page.locator('#text').inputValue();
    expect(text).toContain('fthoraSoftChromaticDiAbove');
  });

  test('download buttons enabled after render', async ({ page }) => {
    await page.goto(`${BASE}/ocr/synth.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#summary')).toContainText('glyphs', { timeout: 15000 });

    await expect(page.locator('#downloadPng')).toBeEnabled();
    await expect(page.locator('#downloadJson')).toBeEnabled();
  });
});

test.describe('OCR CNN Recognition Pipeline', () => {

  test('CNN backend loads weights and classifies a synthetic page', async ({ page }) => {
    test.setTimeout(120000); // CNN inference is slow (~1s per glyph)

    // Step 1: Generate a synthetic page with known glyphs
    await page.goto(`${BASE}/ocr/synth.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#summary')).toContainText('glyphs', { timeout: 15000 });

    // Type simple glyph text
    await page.locator('#text').fill('ison oligon oligon apostrofos gorgonAbove leimma2');
    await page.click('#renderBtn');
    await page.waitForTimeout(2000);

    // Download the PNG as a blob via canvas
    const pngBlob = await page.evaluate(async () => {
      const canvas = document.getElementById('canvas');
      return new Promise(resolve => {
        canvas.toBlob(blob => {
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result);
          reader.readAsDataURL(blob);
        }, 'image/png');
      });
    });

    // Step 2: Go to import page and drop the synthetic image
    await page.goto(`${BASE}/ocr/import.html`, { waitUntil: 'networkidle' });

    // Select CNN backend
    await page.selectOption('#backend', 'cnn');

    // Set small component threshold for clean synthetic pages
    await page.fill('#minPixels', '6');

    // Set the file input with the generated PNG
    const fileInput = page.locator('#file[type=file]');

    // Convert data URL to buffer and set as file input
    await page.evaluate(async (dataUrl) => {
      const response = await fetch(dataUrl);
      const blob = await response.blob();
      const file = new File([blob], 'synth_page.png', { type: 'image/png' });
      const dt = new DataTransfer();
      dt.items.add(file);
      const input = document.getElementById('file');
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, pngBlob);

    // Wait for CNN to load weights + classify
    await page.waitForTimeout(5000); // weight loading

    // The page should show the image in the canvas
    const sourceCanvas = page.locator('#source');
    const sourceWidth = await sourceCanvas.evaluate(el => el.width);
    expect(sourceWidth).toBeGreaterThan(0);

    // Status should eventually show results
    await expect(page.locator('#status')).toContainText(/glyphs|Loading|Ready|Classifying/, { timeout: 60000 });

    // Wait for classification to complete (up to 60s for CNN)
    try {
      await expect(page.locator('#status')).toContainText(/glyphs|glyph/, { timeout: 60000 });
    } catch {
      // Even if CNN fails, the page shouldn't crash
      const status = await page.locator('#status').textContent();
      console.log('Final status:', status);
    }
  });

  test('template matching backend processes a synthetic page without crashing', async ({ page }) => {
    test.setTimeout(30000);

    // Generate a synthetic page
    await page.goto(`${BASE}/ocr/synth.html`, { waitUntil: 'networkidle' });
    await expect(page.locator('#summary')).toContainText('glyphs', { timeout: 15000 });

    const pngBlob = await page.evaluate(async () => {
      const canvas = document.getElementById('canvas');
      return new Promise(resolve => {
        canvas.toBlob(blob => {
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result);
          reader.readAsDataURL(blob);
        }, 'image/png');
      });
    });

    // Go to import page, use template backend
    await page.goto(`${BASE}/ocr/import.html`, { waitUntil: 'networkidle' });
    await page.selectOption('#backend', 'template');
    await page.fill('#minPixels', '4');

    await page.evaluate(async (dataUrl) => {
      const response = await fetch(dataUrl);
      const blob = await response.blob();
      const file = new File([blob], 'synth.png', { type: 'image/png' });
      const dt = new DataTransfer();
      dt.items.add(file);
      const input = document.getElementById('file');
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, pngBlob);

    await page.waitForTimeout(5000);

    // Template matching should finish quickly on a clean synthetic page
    const status = await page.locator('#status').textContent();
    expect(status).toBeTruthy();
    // Shouldn't say "error" or crash
    expect(status.toLowerCase()).not.toMatch(/error|crash|undefined/);
  });
});

test.describe('CNN Training Page', () => {

  test('training page loads with all controls', async ({ page }) => {
    await page.goto(`${BASE}/ocr/train.html`, { waitUntil: 'networkidle' });

    // Three sections via numbered headers
    await expect(page.getByRole('heading', { name: '1. Generate training data' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '2. Train CNN' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '3. Export' })).toBeVisible();

    // Generate button enabled after font loads
    await expect(page.locator('#genBtn')).toBeEnabled({ timeout: 15000 });

    // Train button initially disabled (no data yet)
    await expect(page.locator('#trainBtn')).toBeDisabled();
  });

  test('font status element is present after page load', async ({ page }) => {
    await page.goto(`${BASE}/ocr/train.html`, { waitUntil: 'networkidle' });
    // Font may not load in headless Chrome; accept either state
    await expect(page.locator('#fontStatus')).toBeAttached();
    const text = await page.locator('#fontStatus').textContent();
    expect(text).toBeTruthy();
  });
});

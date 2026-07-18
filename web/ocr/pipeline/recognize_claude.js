// Claude Vision API recognizer for Byzantine chant notation.
// Replaces template matching with a vision-language model.
// Same output shape as recognize.js → tokens flow into the existing pipeline.

const CLAUDE_API = 'https://api.anthropic.com/v1/messages';
const MODEL = 'claude-sonnet-4-6';  // fast, good vision, cheap

const SYSTEM_PROMPT = `You are a Byzantine chant notation OCR engine. You identify neume symbols in printed chant scores.

You receive two images:
1. A reference atlas showing every neume glyph with its name, shape, and codepoint.
2. A chant score page or line to transcribe.

Your task: identify every neume symbol in the neume row (the musical notation above the lyrics), NOT the lyric text beneath.

For each identified symbol, return:
- glyphName: the exact name from the atlas (e.g. "oligon", "ison", "kentima", "apostrofos", "gorgonAbove")
- bbox: {x, y, w, h} in pixel coordinates within the source image
- confidence: 0.0–1.0

Read symbols left to right within the neume row.
Include ALL visible neume marks: body signs, kentima/kentimata dots, ypsili curls, gorgon marks, phthora signs, martyria, duration signs (klasma, apli, dipli), rests (leimma).

Skip: lyrics, page numbers, decorative drop-caps, red editorial marks, barlines.

IMPORTANT: Describe each mark as a SEPARATE entry. An oligon with a kentima dot above it is TWO entries: one for "oligon" and one for "kentima". Do not combine them.`;

const USER_PROMPT = `Transcribe all neume symbols in the chant page above. Return a JSON array of objects, each with:
- "glyphName": exact name from the atlas
- "bbox": {"x": number, "y": number, "w": number, "h": number}
- "confidence": number 0-1

Image 1 is the reference atlas. Image 2 is the page to transcribe.`;

export async function recognizePageClaude(imageBitmap, atlasBlob, options = {}) {
  const apiKey = options.apiKey;
  if (!apiKey) throw new Error('API key required for Claude recognition.');

  const imageB64 = await bitmapToBase64(imageBitmap, 'image/png');
  const atlasB64 = atlasBlob
    ? await blobToBase64(atlasBlob)
    : await imageToBase64(options.atlasImageBitmap);

  const body = {
    model: MODEL,
    max_tokens: 4096,
    system: SYSTEM_PROMPT,
    messages: [{
      role: 'user',
      content: [
        {
          type: 'image',
          source: { type: 'base64', media_type: 'image/png', data: atlasB64 },
        },
        {
          type: 'image',
          source: { type: 'base64', media_type: 'image/png', data: imageB64 },
        },
        { type: 'text', text: USER_PROMPT },
      ],
    }],
    tools: [{
      name: 'report_glyphs',
      description: 'Report identified Byzantine chant neume symbols with their positions.',
      input_schema: {
        type: 'object',
        properties: {
          glyphs: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                glyphName: { type: 'string' },
                bbox: {
                  type: 'object',
                  properties: {
                    x: { type: 'number' },
                    y: { type: 'number' },
                    w: { type: 'number' },
                    h: { type: 'number' },
                  },
                  required: ['x', 'y', 'w', 'h'],
                },
                confidence: { type: 'number' },
              },
              required: ['glyphName', 'bbox', 'confidence'],
            },
          },
        },
        required: ['glyphs'],
      },
    }],
    tool_choice: { type: 'tool', name: 'report_glyphs' },
  };

  const response = await fetch(CLAUDE_API, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Claude API error ${response.status}: ${err}`);
  }

  const data = await response.json();

  // Extract tool-use result
  const toolBlock = data.content?.find(block => block.type === 'tool_use' && block.name === 'report_glyphs');
  if (!toolBlock) {
    console.warn('Claude did not use report_glyphs tool. Raw response:', data);
    return { tokens: [], raw: data };
  }

  const glyphs = toolBlock.input?.glyphs ?? [];

  // Convert to SourceToken-compatible format matching recognize.js output
  const tokens = glyphs.map((g, index) => ({
    glyphName: g.glyphName,
    confidence: g.confidence ?? 0.9,
    source: 'ocr',
    region: {
      bbox: { x: g.bbox.x, y: g.bbox.y, w: g.bbox.w, h: g.bbox.h },
      line: 0,
      role: 'neume',
    },
  }));

  return {
    tokens,
    usage: data.usage ?? null,
  };
}

async function bitmapToBase64(bitmap, format = 'image/png') {
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(bitmap, 0, 0);
  const blob = await canvas.convertToBlob({ type: format });
  return blobToBase64(blob);
}

async function imageToBase64(bitmap) {
  if (!bitmap) return '';
  return bitmapToBase64(bitmap);
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result === 'string') {
        resolve(result.split(',')[1]);
      } else {
        reject(new Error('Failed to read blob'));
      }
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// Pre-load the atlas as a Blob for reuse across calls.
export async function loadAtlasBlob(atlasUrl) {
  const response = await fetch(atlasUrl);
  if (!response.ok) throw new Error(`Failed to load atlas: ${response.status}`);
  return response.blob();
}

import js from '@eslint/js';
import globals from 'globals';

// AudioWorkletGlobalScope globals (not provided by the `globals` package).
const audioWorkletGlobals = {
  AudioWorkletProcessor: 'readonly',
  registerProcessor: 'readonly',
  sampleRate: 'readonly',
  currentTime: 'readonly',
  currentFrame: 'readonly',
};

export default [
  {
    ignores: ['web/pkg/**', 'web/pkg-worklet/**'],
  },

  js.configs.recommended,

  // Browser ES modules: app entry + UI + main-thread audio + score engine.
  {
    files: ['web/**/*.js', 'web/**/*.mjs'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser },
    },
    rules: {
      // Unused symbols are worth surfacing but shouldn't fail the build;
      // allow intentional throwaways via leading underscore.
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // Empty catch is an accepted idiom for best-effort cleanup (e.g.
      // node.disconnect() on an already-disconnected graph).
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },

  // Audio worklets are classic scripts in AudioWorkletGlobalScope.
  {
    files: ['web/audio/voice_worklet.js', 'web/audio/synth_worklet.js'],
    languageOptions: {
      sourceType: 'script',
      globals: { ...globals.worker, ...audioWorkletGlobals },
    },
  },

  // Node test runner files.
  {
    files: ['web/score/tests/**/*.mjs'],
    languageOptions: {
      sourceType: 'module',
      globals: { ...globals.node },
    },
  },
];

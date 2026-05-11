import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.mjs',
  timeout: 120000,
  retries: 1,
  workers: 1,
  use: {
    baseURL: 'http://localhost:8432',
    headless: true,
    viewport: { width: 1280, height: 800 },
    actionTimeout: 15000,
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
  reporter: [
    ['list'],
    ['html', { outputFolder: '/mnt/data/code/chanterlab-score-engine/test-results/e2e' }],
  ],
});

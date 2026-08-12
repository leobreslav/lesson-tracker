import { defineConfig, devices } from '@playwright/test'

/**
 * Browser tests against a production-shaped stack.
 *
 * The point of these is the class of failure the unit tests cannot see: a
 * ReferenceError in a render path, a grid that stopped laying out, a page
 * that only breaks once the bundle is built. So they run against nginx
 * serving a real build, not against the dev server.
 *
 * No retries. A flaky e2e suite that goes green on the second attempt
 * teaches people to press the button again, which is how a real regression
 * gets waved through.
 */
export default defineConfig({
  testDir: './tests',
  // every test reseeds the database, so they cannot share one
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],

  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8080',
    // a screenshot of the moment it broke; the trace covers the road there
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})

import { expect, test as base } from '@playwright/test'

/**
 * What every test starts from: a clean database, a signed-in person, and a
 * microphone held up to the browser console.
 *
 * The console listener is the reason these tests exist. Twice now a page has
 * shipped with a ReferenceError that rendered a blank section while every
 * unit test stayed green — `vite build` does not evaluate the code, so only
 * a browser can catch it. Any console error or uncaught exception fails the
 * test that produced it, whatever else that test was checking.
 */

// Noise that is not the application's fault. Anything added here needs a
// reason next to it, or the listener quietly stops being a safety net.
const IGNORED = [
  // no favicon in the bundle; the browser asks anyway
  /favicon\.ico/,
  // Google Identity Services is not reachable from the test network, and the
  // sign-in page is only visited to check it renders
  /accounts\.google\.com|gsi\/client/,
]

function interesting(text) {
  return !IGNORED.some((pattern) => pattern.test(text))
}

export const test = base.extend({
  /** A database in exactly the state `seed_demo` leaves it. */
  seeded: [
    async ({ request }, use) => {
      const response = await request.post('/api/test/reset/')
      expect(
        response.ok(),
        `сброс базы не удался: ${response.status()} ${await response.text()}`,
      ).toBeTruthy()
      await use(true)
    },
    { auto: true },
  ],

  page: async ({ page }, use) => {
    const problems = []

    page.on('console', (message) => {
      if (message.type() !== 'error') return
      const text = message.text()
      if (interesting(text)) problems.push(`console: ${text}`)
    })

    page.on('pageerror', (error) => {
      problems.push(`pageerror: ${error.message}`)
    })

    await use(page)

    expect(problems, 'браузер сообщил об ошибках').toEqual([])
  },

  /**
   * Sign in as one of the seeded people, by email.
   *
   * Through the flagged test endpoint, not through Google — a headless
   * browser cannot pass that, and the alternative would be mocking the
   * provider, which tests the mock. The token goes into localStorage exactly
   * where `App.jsx` reads it, before the first script runs.
   */
  signIn: async ({ page, request }, use) => {
    await use(async (email) => {
      const response = await request.post('/api/test/login/', { data: { email } })
      expect(
        response.ok(),
        `вход как ${email} не удался: ${response.status()}`,
      ).toBeTruthy()

      const { key } = await response.json()
      await page.addInitScript(
        ([token]) => window.localStorage.setItem('authToken', token),
        [key],
      )
      return key
    })
  },

  /** Call the API as somebody, for arranging state a test needs. */
  api: async ({ request }, use) => {
    await use(async (email) => {
      const response = await request.post('/api/test/login/', { data: { email } })
      const { key } = await response.json()

      const call = async (method, path, data) => {
        const answer = await request.fetch(path, {
          method,
          headers: { Authorization: `Token ${key}` },
          ...(data ? { data } : {}),
        })
        return { status: answer.status(), body: await answer.json().catch(() => null) }
      }

      return {
        get: (path) => call('GET', path),
        post: (path, data) => call('POST', path, data),
        patch: (path, data) => call('PATCH', path, data),
        delete: (path) => call('DELETE', path),
      }
    })
  },
})

export { expect }

/**
 * Число в плашке плана — «в плане» по умолчанию.
 *
 * По тексту плашку не поймать: подписи переводятся, а якорь `data-card`
 * от языка не зависит.
 */
export const lessonCount = (page, card = 'lessons') =>
  page.locator(`[data-card="${card}"] h2`)

/** The seeded cast, so tests name people rather than addresses. */
export const PEOPLE = {
  admin: 'director@example.com',
  ivanova: 'ivanova@example.com',
  petrov: 'petrov@example.com',
}

/**
 * Wait for the interface to have finished talking to the server.
 *
 * Pages load their data in `useEffect`, so «the heading is there» does not
 * mean «the list is». Waiting on a visible consequence beats any sleep, and
 * this helper keeps the wait in one place.
 */
export async function ready(page) {
  await expect(page.locator('.topbar')).toBeVisible()
  await page.waitForLoadState('networkidle')
}

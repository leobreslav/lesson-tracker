import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenario 1: walk every section and let the console listener judge.
 *
 * The assertions here are almost beside the point — the harness fails the
 * test on any console error, and that is what has actually broken twice.
 * Visiting each page under an administrator covers the most sections in one
 * pass, since they see the two extra ones.
 */

const SECTIONS = [
  ['/', 'main'],
  ['/schedule', 'schedule'],
  ['/progress', 'progress'],
  ['/plan', 'plan'],
  ['/classes', 'courses'],
  ['/library', 'library'],
  ['/year', 'calendar'],
  ['/school', 'school'],
  ['/school/schedule', 'timetable'],
  ['/profile', 'profile'],
]

test('администратор обходит все разделы без ошибок в консоли', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)

  for (const [path, name] of SECTIONS) {
    await test.step(name, async () => {
      await page.goto(path)
      await ready(page)
      // a page that rendered has a heading; a page that threw has a trap
      await expect(page.locator('h1')).toBeVisible()
      await expect(page.locator('.page, .card')).toBeVisible()
    })
  }
})

test('обычный учитель обходит свои разделы без ошибок', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)

  for (const [path, name] of SECTIONS.filter(([url]) => !url.startsWith('/school'))) {
    await test.step(name, async () => {
      await page.goto(path)
      await ready(page)
      await expect(page.locator('h1')).toBeVisible()
    })
  }
})

test('разделы школы учителю не показываются', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/')
  await ready(page)

  await expect(page.locator('.topbar-nav a[href="/school"]')).toHaveCount(0)
  await expect(page.locator('.topbar-nav a[href="/schedule"]')).toBeVisible()
})

test('неизвестный адрес показывает страницу «не найдено», а не пустоту', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)

  await page.goto('/nope/deep')
  await ready(page)

  await expect(page.locator('h1')).toHaveText(/не найдена|not found/i)
  // внутри main: ссылка на главную есть ещё и в баре
  await expect(page.locator('main a[href="/"]')).toBeVisible()
})

test('переключение языка меняет интерфейс и переживает перезагрузку', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/')
  await ready(page)

  await page.locator('.user-menu > button').click()
  // язык применяется сразу, а сохраняется вдогонку — интерфейс ответа не
  // ждёт. Тест обязан дождаться, иначе перезагрузка обгонит запись
  const saved = page.waitForResponse(
    (response) =>
      response.url().includes('/api/me/') && response.request().method() === 'PATCH',
  )
  await page.getByRole('menuitem', { name: 'English' }).click()

  await expect(page.locator('.topbar-nav a[href="/schedule"]')).toHaveText('My schedule')
  await saved

  await page.reload()
  await ready(page)
  await expect(page.locator('.topbar-nav a[href="/schedule"]')).toHaveText('My schedule')
})

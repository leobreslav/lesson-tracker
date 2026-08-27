import { PEOPLE, expect, expectConsoleError, ready, test } from './harness.js'

/**
 * Scenario 1: walk every section and let the console listener judge.
 *
 * The assertions here are almost beside the point — the harness fails the
 * test on any console error, and that is what has actually broken twice.
 * Visiting each page under an administrator covers the most sections in one
 * pass, since they see the two extra ones.
 */

const SECTIONS = [
  // корень — расписание: с него заходят в занятие, а обзор рядом
  ['/', 'main'],
  ['/schedule', 'schedule'],
  ['/plan', 'plan'],
  ['/works', 'works'],
  // личный стол: раздел есть у любого сотрудника, и у обоих людей обхода
  ['/bookmarks', 'bookmarks'],
  // экрана «Классы» больше нет, а «Учебный год» ушёл из бара — он
  // открывается из раздела «Школа», но обойти его всё равно надо
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

  await expect(page.locator('.topbar-nav a[href="/schedule"]')).toHaveText('Schedule')
  await saved

  await page.reload()
  await ready(page)
  await expect(page.locator('.topbar-nav a[href="/schedule"]')).toHaveText('Schedule')
})

test('пропавшего куска бандла на месте index.html не оказывается', async ({
  page,
}) => {
  // Имена кусков несут хэш содержимого, и после выкатки прежних на сервере
  // нет. Общий SPA-фолбэк отдавал на такой запрос index.html: браузер
  // получал HTML вместо модуля, отказывался его исполнять и ронял ленивый
  // импорт. Честный 404 читается однозначно — и человеком, и логом.
  const answer = await page.request.get('/assets/LessonPanel-DEADBEEF.js')

  // 404, а не 200 с телом приложения. Тип содержимого у самой страницы
  // ошибки при этом html, и это ни на что не влияет: код ответа браузер
  // смотрит первым и модуль из отказа исполнять не пытается
  expect(answer.status()).toBe(404)
  expect(await answer.text()).not.toContain('<div id="root">')
})

test('вкладка, пережившая выкатку, чинит себя перезагрузкой', async ({
  page,
  signIn,
}) => {
  // Так это и выглядело на проде: открытая до выкатки вкладка просит кусок
  // со старым именем, получает отказ и показывает «страница не
  // отрисовалась». Лечится перезагрузкой — она берёт свежий index.html с
  // новыми именами, — и делать это должно приложение, а не человек.
  expectConsoleError(page, /LessonPanel|dynamically imported module|Failed to load/)

  let refused = 0
  await page.route(/\/assets\/LessonPanel.*\.js$/, async (route) => {
    if (refused === 0) {
      refused += 1
      // ровно то, чем теперь отвечает nginx на кусок, которого нет
      await route.fulfill({ status: 404, contentType: 'text/plain', body: 'gone' })
    } else {
      await route.continue()
    }
  })

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })
  await expect(page.locator('.plan-cards')).toBeVisible()

  // открываем панель урока — её код и лежит в пропавшем куске
  await page.locator('.plan-row.lesson .title').first().click()

  // экрана ошибки быть не должно: страница перезагрузилась и работает
  await expect(page.locator('.plan-cards')).toBeVisible()
  await expect(page.getByText(/страница не отрисовалась|failed to render/i)).toHaveCount(0)
  expect(refused).toBe(1)

  // а со свежим бандлом панель открывается как ни в чём не бывало
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })
  await expect(page.locator('.plan-cards')).toBeVisible()
  await page.locator('.plan-row.lesson .title').first().click()
  await expect(page.locator('dialog.modal')).toBeVisible()
})

test('сервер не ответил — так и написано, по-человечески', async ({
  page,
  signIn,
}) => {
  // Выкатка перезапускает nginx, и на секунду 443 не слушает никто: браузер
  // отвечает ERR_CONNECTION_REFUSED, а `fetch` бросает «Failed to fetch» —
  // строку, в которой человеку нет ничего. Поймано на проде: английский
  // «Failed to fetch» в русском интерфейсе посреди работы.
  expectConsoleError(page, /Failed to load resource|net::ERR|api\/plan/)

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })
  await expect(page.locator('.plan-cards')).toBeVisible()

  // роняем сеть под уже открытой страницей
  await page.route('**/api/plan/**', (route) => route.abort('connectionrefused'))
  await page.locator('.plan-row.lesson .title').first().click()

  const panel = page.locator('dialog.modal.sheet')
  await expect(panel).toContainText('Сервер не ответил')
  await expect(panel).not.toContainText('Failed to fetch')
})

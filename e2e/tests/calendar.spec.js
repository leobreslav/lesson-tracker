import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenario 3: mark a break by dragging across days, and watch the counter.
 *
 * The drag is the interesting part. It is `mousedown` on one cell and
 * `mouseenter` on the rest, with the `mouseup` handler living on `window` —
 * a shape that has broken before and that no unit test exercises.
 */

/** The study-day counter in the side panel. */
function studyDays(page) {
  return page.locator('.calendar-side .panel h2').first()
}

/** Drag from one date to another across the month grid. */
async function selectRange(page, from, to) {
  const first = page.locator(`[data-date="${from}"]`)
  const last = page.locator(`[data-date="${to}"]`)

  await first.hover()
  await page.mouse.down()
  await last.hover()
  await page.mouse.up()
}

test('каникулы выделением мышью уменьшают счётчик учебных дней', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await page.goto('/year')
  await ready(page)

  const counter = studyDays(page)
  await expect(counter).not.toHaveText('—')
  const before = Number(await counter.textContent())

  // a full working week in the middle of a quarter, seeded as study days
  await selectRange(page, '2026-09-21', '2026-09-25')

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('textbox').fill('Осенний карантин')
  await dialog.getByRole('button', { name: 'Добавить' }).click()

  await expect(dialog).toBeHidden()
  await expect(counter).toHaveText(String(before - 5))

  // and the days themselves changed colour, which is what a teacher sees
  await expect(page.locator('[data-date="2026-09-23"]')).toHaveClass(/vacation/)

  // the markup survives a reload: it went to the server, not just to state
  await page.reload()
  await ready(page)
  await expect(studyDays(page)).toHaveText(String(before - 5))
  await expect(page.getByText('Осенний карантин').first()).toBeVisible()
})

test('клик по учебному дню делает его праздником и обратно', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await page.goto('/year')
  await ready(page)

  const counter = studyDays(page)
  const before = Number(await counter.textContent())
  const day = page.locator('[data-date="2026-09-24"]')

  await day.click()
  await expect(day).toHaveClass(/holiday/)
  await expect(counter).toHaveText(String(before - 1))

  await day.click()
  await expect(day).toHaveClass(/study/)
  await expect(counter).toHaveText(String(before))
})

test('учитель видит календарь, но не правит его', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/year')
  await ready(page)

  await expect(studyDays(page)).not.toHaveText('—')
  await expect(page.getByRole('button', { name: '+ Новый год' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Удалить год' })).toHaveCount(0)

  // the grid is there to read, and its buttons do nothing
  await expect(page.locator('[data-date="2026-09-24"]')).toBeDisabled()
})

test('термы показаны и считают свои учебные дни', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await page.goto('/year')
  await ready(page)

  const terms = page.locator('.panel', { hasText: 'Термы' })

  await expect(terms.locator('.terms li')).toHaveCount(4)
  await expect(terms.getByText('1 четверть')).toBeVisible()
  await expect(terms.locator('.terms li').first()).toContainText(/учебн/)
})

/**
 * Удаление года: окно называет цену, а чужая работа его останавливает.
 *
 * Каскад года уносит курсы школы, а с ними назначения. Раньше
 * подтверждение обещало «разметку», а на школе с расписанием приходила
 * пятисотка.
 */
test('окно удаления года перечисляет, что уйдёт вместе с ним', async ({
  page,
  signIn,
  api,
}) => {
  const admin = await api(PEOPLE.admin)
  const year = await admin.post('/api/calendar/years/', {
    name: '2030/2031',
    start_date: '2030-09-02',
    end_date: '2031-05-31',
  })
  const course = await admin.post('/api/courses/', {
    year: year.body.id,
    name: 'Пробный курс',
  })
  const members = await admin.get('/api/school/members/')
  const her = members.body.find((item) => item.email === PEOPLE.ivanova)
  await admin.post('/api/school/assignments/', {
    course: course.body.id,
    teacher: her.id,
  })

  await signIn(PEOPLE.admin)
  await page.goto('/year')
  await ready(page)
  await page.getByRole('button', { name: '2030/2031', exact: true }).click()
  await page.getByRole('button', { name: 'Удалить год' }).click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toContainText('1 курс школы')
  await expect(dialog).toContainText('1 назначение')

  await dialog.getByRole('button', { name: 'Удалить год' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: '2030/2031', exact: true })).toHaveCount(0)
})

test('год с чужими уроками не удаляется, и окно объясняет почему', async ({
  page,
  signIn,
}) => {
  // у засеянного года уроки уже есть — их поставила Иванова
  await signIn(PEOPLE.admin)
  await page.goto('/year')
  await ready(page)
  await page.getByRole('button', { name: 'Удалить год' }).click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toContainText('чужая работа')
  // подтверждения в этом окне нет вовсе: нажимать нечего
  await expect(dialog.getByRole('button', { name: 'Удалить год' })).toHaveCount(0)

  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()
  await expect(page.locator('.calendar-side')).toBeVisible()
})

test('праздник и каникулы можно переименовать', async ({ page, signIn }) => {
  // Название праздника спросить было негде вовсе: клик по дню создавал его
  // с именем по умолчанию, и поменять это имя не давал ни один экран.
  await signIn(PEOPLE.admin)
  await page.goto('/year')
  await ready(page)

  // помечаем учебный день праздником — имя пока по умолчанию
  await page.locator('[data-date="2026-11-04"]').click()
  const item = page.locator('.exceptions li', { hasText: 'Праздник' }).first()
  await expect(item).toBeVisible()

  // имя кнопки — само название пометки; «Переименовать» живёт в подсказке
  await item.locator('button.title').click()
  const field = item.getByRole('textbox')
  await field.fill('День народного единства')
  await field.press('Enter')

  await expect(
    page.locator('.exceptions li', { hasText: 'День народного единства' }),
  ).toBeVisible()

  // и переживает перезагрузку: имя ушло на сервер
  await page.reload()
  await ready(page)
  await expect(
    page.locator('.exceptions li', { hasText: 'День народного единства' }),
  ).toBeVisible()
})

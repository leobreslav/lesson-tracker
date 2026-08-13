import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenarios 8 and 9: the layout shifting, and one teacher's work staying
 * out of another's sight.
 */

const MONDAY = '2026-09-07'

async function openLayout(page, course) {
  await page.goto('/layout')
  await ready(page)
  await page.getByRole('button', { name: course, exact: true }).click()
  await expect(page.locator('.layout-feed').first()).toBeVisible()
}

/** The first rows of the feed, as {date, slot, title}. */
async function feed(page, count = 6) {
  return page.locator('.layout-row').evaluateAll(
    (rows, limit) =>
      rows.slice(0, limit).map((row) => ({
        date: row.querySelector('.layout-date')?.textContent.trim() ?? '',
        slot: row.querySelector('.slot')?.textContent.trim() ?? '',
        title: row.querySelector('.layout-title')?.textContent.trim() ?? '',
      })),
    count,
  )
}

/** The n-th lesson of a course that is still standing, straight from the API. */
async function nthSlot(api, courseId, index) {
  const { body } = await api.get(`/api/slots/?course=${courseId}`)
  const live = body
    .filter((slot) => !slot.is_cancelled)
    .sort((a, b) =>
      a.date === b.date ? a.lesson_number - b.lesson_number : a.date < b.date ? -1 : 1,
    )
  return live[index]
}

test('отмена урока сдвигает даты в раскладке', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const algebra = courses.body.find((item) => item.name === 'Grade 6 Algebra')

  await signIn(PEOPLE.ivanova)
  await openLayout(page, 'Grade 6 Algebra')

  const before = await feed(page)
  expect(before.length).toBeGreaterThan(3)

  // cancel the earliest lesson of the course — the one the first topic sits
  // on. The seeded year starts before the first full week, so «the Monday of
  // week one» is not it
  const first = await nthSlot(teacher, algebra.id, 0)
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(first.date)

  const lesson = page.locator(`[data-lesson="${first.date}:${first.lesson_number}"]`)
  await expect(lesson).toBeVisible()
  await lesson.click()

  const menu = page.locator('dialog.modal')
  await menu.getByRole('button', { name: 'Отменить', exact: true }).click()
  await menu.getByPlaceholder('Причина отмены').fill('Болезнь')
  await menu.getByRole('button', { name: 'Отменить урок' }).click()
  await expect(menu).toBeHidden()

  // a cancelled lesson leaves the layout entirely, so the whole tape slides
  // one date earlier: the first topic now falls on what was the second date
  await openLayout(page, 'Grade 6 Algebra')
  const after = await feed(page)

  expect(after[0].date).toBe(before[1].date)
  expect(after[0].title).toBe(before[0].title)
  expect(after[1].title).toBe(before[1].title)
})

test('в сводке раскладки виден баланс', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openLayout(page, 'Grade 6 Algebra')

  const cards = page.locator('.card-stat')
  await expect(cards.first()).toBeVisible()
  await expect(page.locator('.cards')).toContainText('слотов осталось')
})

test('второй учитель не видит ни уроков, ни планов первого', async ({
  page,
  signIn,
  api,
}) => {
  // Ivanova has a plan in Grade 6 Algebra; Petrov shares no course with it
  const ivanova = await api(PEOPLE.ivanova)
  const hers = await ivanova.get('/api/slots/')
  expect(hers.body.length).toBeGreaterThan(0)

  await signIn(PEOPLE.petrov)
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(MONDAY)

  // her Monday lesson sits at number 1; his week has nothing there
  await expect(page.locator(`[data-lesson="${MONDAY}:1"]`)).toHaveCount(0)
  await expect(page.locator('.week-grid').getByText('Grade 6 Algebra')).toHaveCount(0)

  // a course nobody assigned him is not even offered: «what do I teach» is
  // now a table of its own, and hers is not in it
  await page.goto('/plan')
  await ready(page)
  await expect(
    page.getByRole('button', { name: 'Grade 6 Algebra', exact: true }),
  ).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Grade 9 Algebra', exact: true })).toBeVisible()

  // and the API says the same, so it is not the interface hiding things
  const petrov = await api(PEOPLE.petrov)
  const his = await petrov.get('/api/slots/')
  const hisIds = new Set(his.body.map((slot) => slot.id))
  expect(hers.body.some((slot) => hisIds.has(slot.id))).toBe(false)
})

test('черновик чужого шаблона не виден в библиотеке', async ({ page, signIn }) => {
  // the seeded draft belongs to Petrov
  await signIn(PEOPLE.ivanova)
  await page.goto('/library')
  await ready(page)

  await expect(page.getByText('Алгебра 6, по учебнику')).toBeVisible()
  await expect(page.getByText('Алгебра 9, черновик')).toHaveCount(0)
})

test('автор свой черновик видит и помечен меткой', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await page.goto('/library')
  await ready(page)

  const draft = page.locator('li', { hasText: 'Алгебра 9, черновик' })
  await expect(draft).toBeVisible()
  await expect(draft.locator('.badge')).toHaveText('черновик')
})

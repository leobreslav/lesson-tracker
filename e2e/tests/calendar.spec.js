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

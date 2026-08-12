import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenarios 6 and 7: the plan tree, dragging, and CSV.
 *
 * Petrov's Grade 9 Geometry is seeded with no plan at all, which makes it
 * the course to build one in from scratch without fighting existing rows.
 */

const EMPTY_COURSE = 'Grade 9 Geometry'

async function openPlan(page, course) {
  await page.goto('/plan')
  await ready(page)
  await page.getByRole('button', { name: course, exact: true }).click()
  await expect(page.locator('.plan-counts')).toBeVisible()
}

/**
 * The plan as «number title» pairs.
 *
 * Read field by field rather than from textContent: the number and the title
 * are separate elements with no whitespace between them, so the flat text
 * comes out as «1Первый признак» with the drag handle glued to the front.
 */
async function structure(page) {
  return page.locator('.plan-row').evaluateAll((rows) =>
    rows.map((row) => {
      const number = row.querySelector('.plan-number')?.textContent.trim() ?? ''
      const title = row.querySelector('.title')?.textContent.trim() ?? ''
      return `${number} ${title}`.trim()
    }),
  )
}

/** The title of a row, without the number or the buttons around it. */
async function titleOf(row) {
  return (await row.locator('.title').textContent()).trim()
}

test('блок и уроки добавляются, нумерация сквозная', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: '+ папка' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Треугольники')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByText('Треугольники')).toBeVisible()

  // two lessons inside the block, through its own «+»
  for (const title of ['Первый признак', 'Второй признак']) {
    await page.locator('.plan-section').getByTitle('Добавить урок в папку').click()
    const inner = page.locator('.plan-add-form')
    await inner.getByLabel('Название').fill(title)
    await inner.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.getByText(title)).toBeVisible()
  }

  // and one at the top level, after the block
  await page.getByRole('button', { name: '+ урок' }).click()
  const top = page.locator('.plan-add-form')
  await top.getByLabel('Название').fill('Итоговый урок')
  await top.getByRole('button', { name: 'Добавить' }).click()
  // wait for the row before reading the tree: the form stays open for fast
  // entry, so there is no other signal that the write landed
  await expect(page.locator('.plan-row', { hasText: 'Итоговый урок' })).toBeVisible()

  const rows = await structure(page)
  expect(rows.join(' | ')).toContain('1 Первый признак')
  expect(rows.join(' | ')).toContain('2 Второй признак')
  expect(rows.join(' | ')).toContain('3 Итоговый урок')

  // the counter agrees with the tree
  await expect(page.locator('.plan-counts')).toContainText('Уроков: 3')
})

test('перетаскивание меняет порядок и пересчитывает номера', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  const lessons = page.locator('.plan-row.lesson')
  const firstBefore = await titleOf(lessons.first())
  const secondBefore = await titleOf(lessons.nth(1))
  expect(firstBefore).not.toBe(secondBefore)

  // drag the second lesson above the first, by its handle: dnd-kit only
  // listens there, and the pointer sensor needs a few steps to engage
  const handle = lessons.nth(1).getByTitle('Перетащить')
  const target = lessons.first()

  const from = await handle.boundingBox()
  const to = await target.boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + 2, { steps: 12 })
  await page.mouse.up()

  // the row that was second now stands first, and carries number 1
  await expect(lessons.first().locator('.title')).toHaveText(secondBefore)
  await expect(lessons.first().locator('.plan-number')).toHaveText('1')

  // and the server agrees after a reload
  await page.reload()
  await ready(page)
  await openPlan(page, 'Grade 6 Algebra')
  await expect(page.locator('.plan-row.lesson').first().locator('.title')).toHaveText(
    secondBefore,
  )
})

test('импорт CSV разбирает файл и строит блоки', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Импорт CSV' }).click()

  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'plan.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'Тема,Урок,Заметка\n' +
        'Векторы,,\n' +
        ',Понятие вектора,\n' +
        ',Сложение векторов,со звёздочкой\n' +
        'Окружность,,\n' +
        ',Касательная,\n',
      'utf-8',
    ),
  })

  // the preview is parsed in the browser, before anything is sent
  await expect(dialog).toContainText('Распознано строк: 5')
  await expect(dialog).toContainText('тем 2')

  await dialog.getByRole('button', { name: 'Импортировать' }).click()
  await expect(dialog).toBeHidden()

  await expect(page.locator('.plan-counts')).toContainText('Уроков: 3')
  await expect(page.getByText('Векторы')).toBeVisible()
  await expect(page.getByText('Окружность')).toBeVisible()

  const rows = await structure(page)
  expect(rows.join(' | ')).toContain('1 Понятие вектора')
  expect(rows.join(' | ')).toContain('3 Касательная')
})

test('импорт из библиотеки наполняет пустой план', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Импорт из библиотеки' }).click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('combobox').selectOption({ index: 0 })
  await dialog.getByRole('button', { name: 'Импортировать в курс' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.locator('.plan-counts')).not.toContainText('Уроков: 0')
})

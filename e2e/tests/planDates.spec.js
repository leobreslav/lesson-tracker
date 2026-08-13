import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Даты прямо в таблице плана.
 *
 * Смысл раздела — не в самих датах, а в пересчёте: тема должна кончиться до
 * каникул, и чтобы это увидеть, нужно править план, глядя, как он ложится на
 * календарь. Поэтому почти каждый тест здесь — «сделали правку и сразу
 * посмотрели, что сдвинулось», без перезагрузки страницы.
 */

const COURSE = 'Grade 6 Algebra'

const openPlan = async (page, course = COURSE) => {
  await page.goto('/plan')
  await ready(page)
  await page.getByRole('button', { name: course, exact: true }).click()
  await expect(page.locator('.plan-cards')).toBeVisible()
}

/** Дата в строке урока с этим номером. */
const dateOf = (page, number) =>
  page
    .locator('.plan-row.lesson', {
      has: page.locator('.plan-number', { hasText: new RegExp(`^${number}$`) }),
    })
    .first()
    .locator('.plan-date')
    .textContent()

/** Дата урока с таким названием — движется именно она, а не номер строки. */
const dateOfLesson = (page, title) =>
  page
    .locator('.plan-row.lesson', { hasText: title })
    .first()
    .locator('.plan-date')
    .textContent()

/** Название первого урока следующей четверти — того, что под её заголовком. */
async function firstOfSecondTerm(page) {
  return page.evaluate(() => {
    const heads = [...document.querySelectorAll('.plan-term')]
    const second = heads[1]
    if (!second) return null
    let next = second.nextElementSibling
    while (next && !next.querySelector?.('.title')) next = next.nextElementSibling
    return next?.querySelector('.title')?.textContent.trim() ?? null
  })
}

test('даты видны, сводка сходится с раскладкой', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const number = async (card) =>
    Number(await page.locator(`[data-card="${card}"] h2`).textContent())

  const slots = await number('slots')
  const lessons = await number('lessons')
  const balance = await number('balance')

  // плашки сходятся между собой и с таблицей
  expect(slots - lessons).toBe(balance)
  await expect(page.locator('.plan-row.lesson .plan-date')).toHaveCount(lessons)
})

test('добавление урока сдвигает даты ниже, удаление возвращает', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const lessons = page.locator('.plan-row.lesson')
  const second = (await lessons.nth(1).locator('.title').textContent()).trim()
  const dateOfSecond = await dateOfLesson(page, second)
  const thirdSlot = await dateOf(page, 3)
  expect(dateOfSecond).not.toBe(thirdSlot)

  // вставляем урок после первого — второй уезжает на слот вперёд
  // кнопки строки появляются при наведении
  await lessons.first().hover()
  await lessons.first().getByTitle('Вставить урок после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Вставка')
  await form.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toBeVisible()
  await expect.poll(() => dateOfLesson(page, second)).toBe(thirdSlot)
  // а сама вставка встала на освободившуюся дату
  expect(await dateOfLesson(page, 'Вставка')).toBe(dateOfSecond)

  // и обратно: удалили — даты вернулись
  page.once('dialog', (dialog) => dialog.accept())
  const inserted = page.locator('.plan-row', { hasText: 'Вставка' })
  await inserted.hover()
  await inserted.getByTitle('Удалить').click()

  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toHaveCount(0)
  await expect.poll(() => dateOfLesson(page, second)).toBe(dateOfSecond)
})

test('граница четверти приходится на другой урок, когда выше добавили', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const heads = page.locator('.plan-term')
  await expect(heads.first()).toContainText('четверть')
  const before = await firstOfSecondTerm(page)

  const first = page.locator('.plan-row.lesson').first()
  await first.hover()
  await first.getByTitle('Вставить урок после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Ещё один урок')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Ещё один урок' })).toBeVisible()

  // заголовок четверти остался на своём слоте, а первым её уроком стал другой
  await expect.poll(() => firstOfSecondTerm(page)).not.toBe(before)
})

test('каникулы отмечены между уроками', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const holidays = page.locator('.plan-divider.break').first()

  await expect(holidays).toContainText('каникулы')
})

test('перетаскивание пересчитывает даты сразу', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const lessons = page.locator('.plan-row.lesson')
  const secondTitle = await lessons.nth(1).locator('.title').textContent()
  const firstDate = await dateOf(page, 1)

  await lessons.nth(1).hover()
  const handle = lessons.nth(1).getByTitle('Перетащить')
  const target = lessons.first()
  const from = await handle.boundingBox()
  const to = await target.boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + 2, { steps: 12 })
  await page.mouse.up()

  // урок переехал наверх и взял дату первого слота — до ответа сервера
  await expect(lessons.first().locator('.title')).toHaveText(secondTitle)
  await expect(lessons.first().locator('.plan-date')).toHaveText(firstDate)
})

test('уроки без слота помечены, а темы показывают диапазон', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === COURSE)
  // оставляем расписание только на сентябрь: план сорока уроков перестаёт
  // помещаться, и это ровно тот случай, ради которого даты и нужны
  await teacher.delete(
    `/api/slots/bulk/?course=${course.id}&start=2026-10-01&end=2027-08-01`,
  )

  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const missing = page.locator('.plan-row.lesson.no-slot')
  await expect(missing.first()).toBeVisible()
  await expect(missing.first().locator('.plan-date')).toHaveText('не помещается')

  // баланс отрицательный, вместо даты последнего урока — «план не помещается»
  await expect(page.locator('[data-card="balance"].bad')).toBeVisible()
  await expect(page.locator('[data-card="last"]')).toContainText('не помещается')
  // и отдельная плашка со счётчиком непоместившихся, она ведёт на раскладку
  await expect(page.locator('[data-card="missing"]')).toBeVisible()

  // тема, часть которой не поместилась, так и говорит
  await expect(
    page.locator('.section-head .block-count', { hasText: 'не помещается' }).first(),
  ).toBeVisible()
})

test('переключатель дат запоминается и не двигает названия', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // колонка дат жёсткой ширины и стоит первой: строки выстраиваются в
  // столбец, как бы ни различались названия и пометки
  const widths = await page
    .locator('.plan-row.lesson .plan-date')
    .evaluateAll((cells) => [...new Set(cells.map((cell) => cell.clientWidth))])
  expect(widths).toHaveLength(1)

  const lefts = await page
    .locator('.plan-row.lesson .plan-date')
    .evaluateAll((cells) => [
      ...new Set(cells.map((cell) => Math.round(cell.getBoundingClientRect().left))),
    ])
  expect(lefts).toHaveLength(1)

  // названия тоже стоят столбцом: колонка дат одной ширины у всех строк
  const titles = await page
    .locator('.plan-row.lesson .title')
    .evaluateAll((cells) => [
      ...new Set(cells.map((cell) => Math.round(cell.getBoundingClientRect().left))),
    ])
  expect(titles).toHaveLength(1)

  await page.getByLabel('Даты').uncheck()
  await expect(page.locator('.plan-date')).toHaveCount(0)

  // и переживает перезагрузку
  await page.reload()
  await ready(page)
  await expect(page.getByLabel('Даты')).not.toBeChecked()
  await expect(page.locator('.plan-date')).toHaveCount(0)
})

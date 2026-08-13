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
  await expect(page.locator('.plan-counts')).toBeVisible()
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

/** Название урока, после которого стоит черта конца четверти. */
async function beforeTermLine(page) {
  return page.evaluate(() => {
    const line = document.querySelector('.plan-divider.term')
    if (!line) return null
    let previous = line.previousElementSibling
    while (previous && !previous.querySelector?.('.title')) {
      previous = previous.previousElementSibling
    }
    return previous?.querySelector('.title')?.textContent.trim() ?? null
  })
}

test('даты видны, сводка сходится с раскладкой', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const summary = page.locator('.plan-summary')
  await expect(summary).toBeVisible()

  // числа сводки — те же, что видно в таблице
  const text = await summary.textContent()
  const [slots, lessons, balance] = text.match(/-?\d+/g).map(Number)
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
  await page.locator('.plan-row', { hasText: 'Вставка' }).getByTitle('Удалить').click()

  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toHaveCount(0)
  await expect.poll(() => dateOfLesson(page, second)).toBe(dateOfSecond)
})

test('граница четверти приходится на другой урок, когда выше добавили', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const line = page.locator('.plan-divider.term').first()
  await expect(line).toContainText('заканчивается')
  const before = await beforeTermLine(page)

  const first = page.locator('.plan-row.lesson').first()
  await first.getByTitle('Вставить урок после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Ещё один урок')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Ещё один урок' })).toBeVisible()

  // черта осталась на своём слоте, а под ней теперь предыдущий урок темы
  await expect.poll(() => beforeTermLine(page)).not.toBe(before)
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
  // у непоместившегося урока даты нет вовсе, только пометка
  await expect(missing.first().locator('.plan-weekday')).toHaveCount(0)

  // баланс отрицательный, «последнего урока» нет: план не влезает
  const summary = page.locator('.plan-summary')
  await expect(summary.locator('.balance.short')).toBeVisible()
  await expect(summary).not.toContainText('последний урок')

  // тема, часть которой не поместилась, так и говорит
  await expect(
    page.locator('.plan-section', { has: page.locator('.plan-range.missing') }).first(),
  ).toBeVisible()
})

test('переключатель дат запоминается и не двигает названия', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // колонки дат жёсткой ширины: они выстраиваются в столбец, как бы ни
  // различались строки — с пометками, с заметкой, с длинным названием
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

  const title = page.locator('.plan-row.lesson .title').first()
  const left = (await title.boundingBox()).x

  await page.getByLabel('Даты').uncheck()
  await expect(page.locator('.plan-date')).toHaveCount(0)
  // название осталось на месте: даты стоят справа от него и его не двигают
  expect(Math.abs((await title.boundingBox()).x - left)).toBeLessThan(1)

  // и переживает перезагрузку
  await page.reload()
  await ready(page)
  await expect(page.getByLabel('Даты')).not.toBeChecked()
  await expect(page.locator('.plan-date')).toHaveCount(0)
})

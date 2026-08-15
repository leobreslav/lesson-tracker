import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenarios 4 and 5: living with a personal schedule.
 *
 * The seeded week is Ivanova's, so the tests drive her. Dates are fixed by
 * `seed_demo` — the year is 2026/2027 and the first full week starts on
 * Monday 7 September — which is why they can be written down here.
 */

const MONDAY = '2026-09-07'
const FRIDAY = '2026-09-11'
// inside the seeded autumn break: 26 October — 3 November
const IN_BREAK = '2026-10-28'

/** Point the agenda at a week without clicking through the arrows. */
async function openWeek(page, date) {
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(date)
  await expect(page.locator(`[data-day-head="${date}"]`)).toBeVisible()
}

test('урок добавляется, отменяется с причиной и возвращается', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  // an hour the seeded week leaves free
  const cell = page.locator(`[data-add="${MONDAY}:6"]`)
  await cell.click()

  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  await add.getByRole('button', { name: 'Добавить' }).click()

  const lesson = page.locator(`[data-lesson="${MONDAY}:6"]`)
  await expect(lesson).toBeVisible()
  await expect(lesson).toContainText('Grade 6 Algebra')

  // cancel it, with a reason
  await lesson.click()
  const menu = page.locator('dialog.modal')
  await menu.getByRole('button', { name: 'Отменить', exact: true }).click()
  await menu.getByPlaceholder('Причина отмены').fill('Болезнь')
  await menu.getByRole('button', { name: 'Отменить урок' }).click()

  await expect(menu).toBeHidden()
  await expect(lesson).toHaveClass(/cancelled/)

  // and put it back
  await lesson.click()
  await page.locator('dialog.modal').getByRole('button', { name: 'Вернуть' }).click()

  await expect(lesson).not.toHaveClass(/cancelled/)

  // the round trip survived a reload, so it reached the server. The agenda
  // opens on today's week after a reload, so the week has to be asked for
  // again — the anchor is view state, not something worth persisting
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:6"]`)).toBeVisible()
})

test('копирование недели на месяц не ставит уроки в каникулы', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  // select the week by its day headers: Monday, then Shift+click on Friday
  await page.locator(`[data-day-head="${MONDAY}"]`).click()
  await page.locator(`[data-day-head="${FRIDAY}"]`).click({ modifiers: ['Shift'] })

  await expect(page.locator('.selection-bar')).toBeVisible()
  await page.getByRole('button', { name: 'Скопировать на период' }).click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('С', { exact: true }).fill('2026-10-19')
  await dialog.getByLabel('по', { exact: true }).fill('2026-11-06')
  await dialog.getByRole('button', { name: 'Скопировать' }).click()

  await expect(dialog).toBeHidden()

  // the week of the break must have stayed empty — the calendar is what the
  // copy asks, and this is the assertion that proves it did
  const teacher = await api(PEOPLE.ivanova)
  const during = await teacher.get(
    `/api/slots/?start=${IN_BREAK}&end=${IN_BREAK}`,
  )
  expect(during.body).toEqual([])

  // while the working weeks on either side did receive lessons
  const after = await teacher.get('/api/slots/?start=2026-11-04&end=2026-11-06')
  expect(after.body.length).toBeGreaterThan(0)
})

test('сводка за неделю считает уроки и отмены', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const summary = page.locator('.agenda-summary')
  await expect(summary).toContainText('За неделю')
  await expect(summary).toContainText(/\d+ урок/)
})

test('неучебные дни в сетке приглушены и подписаны', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, IN_BREAK)

  const head = page.locator(`[data-day-head="${IN_BREAK}"]`)
  await expect(head).toHaveClass(/locked/)
  await expect(head).toContainText('Осенние каникулы')
})

/**
 * Экран «Сегодня»: день учителя одним местом.
 *
 * Главное здесь — разница между подсказкой и записью. Раскладка позиционная
 * и съезжает от любой правки плана, поэтому «что прошли» она предлагает, а
 * записывает человек.
 *
 * Записать можно только то, что уже случилось: кнопка, нажатая накануне,
 * стала бы ложью после утренней пожарной тревоги, и заметить это было бы
 * некому. Учебный год демо-данных весь в будущем, поэтому здесь проверяется
 * именно эта половина правила — подсказка есть, кнопки нет; саму запись
 * проверяют питоновские тесты, которым дата не мешает.
 */
test('на «Сегодня» видно урок, а подтвердить будущее нельзя', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/today')
  await ready(page)
  await page.getByRole('button', { name: 'Grade 6 Algebra' }).click()

  // листаем к дню с уроком: «сегодня» в демо-данных до начала учебного года
  const card = page.locator('.lesson-card')
  for (let step = 0; step < 40 && !(await card.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(120)
  }

  await expect(card.first()).toBeVisible()
  await expect(page.getByText('Раскладка предполагает эту тему.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'занятие проведено' })).toHaveCount(0)
})

test('перенос оставляет отмену на прежнем месте и занятие на новом', async ({
  page,
  signIn,
}) => {
  // Перенос — не правка даты: календарной оси нужен след срыва и его
  // компенсации, иначе год к маю выглядит идеально ровным.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const cell = page.locator(`[data-add="${MONDAY}:7"]`)
  await cell.click()
  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  await add.getByRole('button', { name: 'Добавить' }).click()

  const source = page.locator(`[data-lesson="${MONDAY}:7"]`)
  await expect(source).toBeVisible()

  await source.click()
  const menu = page.locator('dialog.modal')
  await menu.getByRole('button', { name: 'Перенести…' }).click()
  await menu.getByLabel('Новая дата').fill(FRIDAY)
  await menu.getByLabel('Номер урока').fill('7')
  await menu.getByRole('button', { name: 'Перенести', exact: true }).click()

  await expect(menu).toBeHidden()
  await expect(source).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${FRIDAY}:7"]`)).toBeVisible()

  // обе половины уехали на сервер, а не только нарисовались
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:7"]`)).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${FRIDAY}:7"]`)).toBeVisible()
})

/** Долистать «Сегодня» до дня, в котором есть занятия. */
async function firstDayWithLessons(page) {
  await page.goto('/today')
  await ready(page)

  const cards = page.locator('.lesson-card')
  for (let step = 0; step < 40 && !(await cards.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(120)
  }
  await expect(cards.first()).toBeVisible()
  return cards
}

test('«Сегодня» показывает день целиком, а курс — это фильтр', async ({
  page,
  signIn,
}) => {
  // Утренний вопрос — «что у меня сегодня», а это занятия разных курсов.
  // Экран, устроенный курсом вперёд, заставлял переключать их по одному.
  await signIn(PEOPLE.ivanova)
  const cards = await firstDayWithLessons(page)

  // у каждой карточки в шапке назван курс: иначе они неразличимы
  await expect(cards.first().locator('.section-title')).toContainText('Grade')

  // чип курса сужает день, «Все» возвращает его целиком
  const shown = await cards.count()
  await page.getByRole('button', { name: 'Grade 6 Algebra' }).click()
  await expect
    .poll(async () => {
      const names = await cards.locator('.section-title').allTextContents()
      return names.every((name) => name.includes('Grade 6 Algebra'))
    })
    .toBe(true)

  await page.getByRole('button', { name: 'Все', exact: true }).click()
  await expect.poll(() => cards.count()).toBe(shown)
})

test('план правится прямо с карточки дня', async ({ page, signIn }) => {
  // Расхождение замечают накануне, когда готовятся, а не после урока.
  // Уходить за правкой в «Учебный план» и искать строку среди сорока —
  // ровно та заминка, из-за которой готовиться будут не здесь.
  await signIn(PEOPLE.ivanova)
  await page.goto('/today')
  await ready(page)
  await page.getByRole('button', { name: 'Grade 6 Algebra' }).click()

  const card = page.locator('.lesson-card')
  for (let step = 0; step < 40 && !(await card.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(120)
  }
  await expect(card.first()).toBeVisible()

  await card.first().getByRole('button', { name: 'Переименовать…' }).click()
  await card.first().getByLabel('Новое название').fill('Синус суммы, разбор')
  await card.first().getByRole('button', { name: 'Сохранить' }).click()

  await expect(card.first().locator('.section-title')).toContainText(
    'Синус суммы, разбор',
  )

  // «дописать урок сюда» кладёт строку **перед** предложенной: «мы всё ещё
  // на синусе» значит, что сегодняшнее занятие идёт до неё, — и карточка
  // тут же начинает предлагать новую
  await card.first().getByRole('button', { name: 'Дописать урок сюда…' }).click()
  await card.first().getByLabel('Что было на самом деле').fill('Повторение формул')
  await card.first().getByRole('button', { name: 'Сохранить' }).click()

  await expect(card.first().locator('.section-title')).toContainText(
    'Повторение формул',
  )

  // и правки настоящие: в плане обе строки стоят рядом и в этом порядке
  await page.goto('/plan')
  await ready(page)
  await page.getByRole('button', { name: 'Grade 6 Algebra', exact: true }).click()
  const titles = await page.locator('.plan-row.lesson .title').allTextContents()
  expect(titles.indexOf('Повторение формул')).toBeGreaterThanOrEqual(0)
  expect(titles.indexOf('Повторение формул')).toBeLessThan(
    titles.indexOf('Синус суммы, разбор'),
  )
})

import { PEOPLE, expect, planMenu, ready, test } from './harness.js'

/**
 * Scenarios 8 and 9: the layout shifting, and one teacher's work staying
 * out of another's sight.
 */

const MONDAY = '2026-09-07'

async function openPlan(page, course) {
  await page.goto('/plan')
  await ready(page)
  // курс выбирают селектом в строке заголовка: чипы не пережили
  // учителя музыки с полутора десятками курсов
  await page.getByLabel('Курс').selectOption({ label: course })
  await expect(page.locator('.plan-cards')).toBeVisible()
}

/** Даты первых строк плана — по ним и видно, что раскладка съехала. */
async function dates(page, count = 4) {
  const all = await page
    .locator('.plan-row.lesson .plan-date')
    .evaluateAll((cells) => cells.map((cell) => cell.textContent.trim()))
  return all.slice(0, count)
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

test('отмена урока сдвигает даты в плане', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const algebra = courses.body.find((item) => item.name === 'Grade 6 Algebra')

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  const before = await dates(page)
  expect(before.length).toBeGreaterThan(3)

  // cancel the earliest lesson of the course. The seeded year starts before
  // the first full week, so «the Monday of week one» is not it
  const first = await nthSlot(teacher, algebra.id, 0)
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(first.date)

  const lesson = page.locator(`[data-lesson="${first.date}:${first.lesson_number}"]`)
  await expect(lesson).toBeVisible()
  // меню урока — правой кнопкой: левая ведёт в само занятие
  await lesson.click({ button: 'right' })

  const menu = page.locator('.context-menu')
  await menu.getByRole('button', { name: 'Отменить' }).click()
  await menu.getByPlaceholder('Причина отмены').fill('Болезнь')
  await menu.getByRole('button', { name: 'Отменить урок' }).click()
  await expect(menu).toHaveCount(0)

  // отменённый урок уходит из раскладки целиком, и вся лента съезжает на
  // одну дату назад: первый урок плана встаёт на вторую дату
  await openPlan(page, 'Grade 6 Algebra')
  const after = await dates(page)

  expect(after[0]).toBe(before[1])
  expect(after[1]).toBe(before[2])
})

test('второй учитель не видит уроков первого, а план его только читает', async ({
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

  /*
   * А вот план её курса ему предлагается — и это перемена, а не дыра.
   *
   * Тут стояло обратное утверждение: «курс, который ему не поручали, даже не
   * предлагается». Оно было правдой ровно до того дня, когда живой план
   * школы стал общим чтением: чужую программу открывают не затем, чтобы её
   * подписать, — смежник сверяет, заменяющий смотрит, на чём остановились.
   * Селект и есть то место, где чужой план ищут.
   *
   * Изоляция от этого не исчезла, она переехала в правку: читать — да,
   * править — нет.
   */
  await page.goto('/plan')
  await ready(page)
  const picker = page.getByLabel('Курс')
  const offered = await picker.locator('option').allTextContents()
  expect(offered).toContain('Grade 9 Algebra')
  expect(offered).toContain('Grade 6 Algebra')

  await picker.selectOption({ label: 'Grade 6 Algebra' })
  await expect(page.locator('.plan .plan-row').first()).toBeVisible()
  // Таблица та же, что у автора, — и только на чтение.
  //
  // Раньше тут стояло «таблицы нет вовсе»: чужой план показывали отдельным
  // списком названий. Теперь список и таблица — одно, а изоляция переехала
  // туда, где ей и место: в органы правки, которых у читателя нет.
  await expect(page.locator('ul.plan button.handle')).toHaveCount(0)
  await expect(page.locator('ul.plan .row-actions button')).toHaveCount(0)
  await expect(page.locator('ul.plan input[type="checkbox"]')).toHaveCount(0)
  await expect(page.locator('.plan-tools')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Утвердить' })).toHaveCount(0)

  // and the API says the same, so it is not the interface hiding things
  const petrov = await api(PEOPLE.petrov)
  const his = await petrov.get('/api/slots/')
  const hisIds = new Set(his.body.map((slot) => slot.id))
  expect(hers.body.some((slot) => hisIds.has(slot.id))).toBe(false)
})

/** Полка открывается с плана: отдельного раздела у неё больше нет. */
async function openShelf(page, course) {
  await page.goto('/plan')
  await ready(page)
  // курс выбирают селектом в строке заголовка: чипы не пережили
  // учителя музыки с полутора десятками курсов
  await page.getByLabel('Курс').selectOption({ label: course })
  await expect(page.locator('.plan-cards')).toBeVisible()
  await planMenu(page, 'Открыть библиотеку')
  await expect(page.locator('dialog.modal')).toBeVisible()
  // Тело окна — колонка, а не сетка. Проверяется потому, что однажды
  // сломалось молча: страница личного стола завела класс `.shelf`, а
  // `Modal.jsx` вешает свой className и на диалог, и на тело — окно
  // библиотеки объявлено тем же словом и получило чужой `display: grid`.
  // Ни один тест этого не заметил, и правка уехала на прод.
  await expect(page.locator('dialog.modal .modal-body')).toHaveCSS('display', 'flex')
  // И окно не прилипает к верхнему краю. Тоже проверено поломкой: `.page > *`
  // обнуляет вертикальные отступы у детей страницы, а окно — её прямой
  // ребёнок, и `margin: auto`, которым `<dialog>` центрируется, пропадал.
  // Выглядит это как «окно не помещается», хотя места вдвое больше нужного
  await expect(page.locator('dialog.modal')).not.toHaveCSS('margin-top', '0px')
  return page.locator('dialog.modal')
}

test('черновик чужого шаблона не виден на полке', async ({ page, signIn }) => {
  // the seeded draft belongs to Petrov
  await signIn(PEOPLE.ivanova)
  const shelf = await openShelf(page, 'Grade 6 Algebra')

  await expect(shelf.getByText('Алгебра 6, по учебнику')).toBeVisible()
  await expect(shelf.getByText('Алгебра 9, черновик')).toHaveCount(0)
})

test('автор свой черновик видит и помечен меткой', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  const shelf = await openShelf(page, 'Grade 9 Algebra')

  const draft = shelf.locator('li', { hasText: 'Алгебра 9, черновик' })
  await expect(draft).toBeVisible()
  // меток в строке бывает две: «черновик» и «веду». Этот шаблон петров и
  // ведёт, поэтому спрашиваем про нужную, а не про единственную
  await expect(draft.locator('.badge', { hasText: 'черновик' })).toBeVisible()
  await expect(draft.locator('.badge', { hasText: 'веду' })).toBeVisible()
})


import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Сводная таблица и проверка.
 *
 * Через браузер это стоит гонять из-за трёх вещей, которых иначе не
 * увидеть: таблица читается цветом (а цвет — это класс ячейки), проверка
 * идёт столбцом в отдельном окне, и таблица сама обновляется опросом.
 */

const openTable = async (page, title) => {
  await page.goto('/works')
  await ready(page)
  const work = page.locator('.work-list .course-row', { hasText: title })
  await work.locator('.toggle').click()
  await work.getByRole('button', { name: 'Проверка' }).click()
  await expect(page.locator('.work-table')).toBeVisible()
}

/** Задача работы по её названию — чтобы ученик отвечал через API. */
const taskOf = async (api, title, index = 0) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const works = await teacher.get(`/api/works/?course=${course.id}`)
  const work = works.body.find((item) => item.title.startsWith(title))
  const tasks = await teacher.get(`/api/works/tasks/?work=${work.id}`)

  return tasks.body[index]
}

test('таблица показывает состояние каждой ячейки и снятого ученика', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Контрольная')

  const rows = page.locator('.work-table tbody tr')
  await expect(rows).toHaveCount(6)
  // снятая с курса остаётся строкой: её ответы никуда не делись
  await expect(rows.filter({ hasText: 'Ева Морозова' })).toHaveClass(/past/)

  // в демо есть все состояния сразу, иначе таблицу не на чем проверить
  await expect(page.locator('.work-table td.correct')).not.toHaveCount(0)
  await expect(page.locator('.work-table td.wrong')).not.toHaveCount(0)
  await expect(page.locator('.work-table td.sent')).not.toHaveCount(0)
  await expect(page.locator('.work-table td.empty')).not.toHaveCount(0)
})

test('проверка столбцом ставит отметку, и таблица её показывает', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Контрольная')

  const before = await page.locator('.work-table td.sent').count()
  await page.locator('.work-table thead button.link').first().click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toContainText('ждёт проверки')
  // непроверенные идут первыми — ради них сюда и заходят
  await dialog.locator('.attempt-list li').first().getByTitle(/Отметить «верно»/).click()
  await dialog.getByRole('button', { name: 'Закрыть' }).click()

  await expect(page.locator('.work-table td.sent')).toHaveCount(before - 1)
})

test('история ячейки открывается кликом и отмечается оттуда же', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Контрольная')

  await page.locator('.work-table td.wrong .cell').first().click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog.locator('.attempt-list li')).toHaveCount(1)
  // повторное нажатие на ту же отметку снимает её: третьей кнопки нет
  await dialog.getByTitle(/Отметить «неверно»/).click()
  await dialog.getByRole('button', { name: 'Закрыть' }).click()

  await expect(page.locator('.work-table td.sent')).not.toHaveCount(0)
})

test('таблица обновляется сама, а переделанный ответ помечен', async ({
  page,
  signIn,
  api,
}) => {
  const task = await taskOf(api, 'Проверочная')
  const student = await api(PEOPLE.student)

  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Проверочная')

  const cell = page.locator('.work-table tbody tr', { hasText: 'Артём Степанов' })
  await expect(cell.locator('td').first()).toHaveClass(/empty/)

  await student.post(`/api/student/tasks/${task.id}/answer/`, { answer: 'первый' })

  // опрос: ничего не нажимаем, ячейка меняется сама
  await expect(cell.locator('td').first()).toHaveClass(/sent/, { timeout: 15000 })

  await cell.locator('td .cell').first().click()
  const dialog = page.locator('dialog.modal')
  await dialog.getByTitle(/Отметить «верно»/).click()
  await dialog.getByRole('button', { name: 'Закрыть' }).click()
  await expect(cell.locator('td').first()).toHaveClass(/correct/)

  await student.post(`/api/student/tasks/${task.id}/answer/`, { answer: 'передумал' })

  // отметка осталась на прошлой строке, ячейка вернулась в «не проверено»
  // и говорит, что смотрели не то
  await expect(cell.locator('td').first()).toHaveClass(/redone/, { timeout: 15000 })
})

test('сводка над таблицей считает то, чего в ней не видно взглядом', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Контрольная')

  const card = (name) => page.locator(`[data-card="${name}"]`)
  // пятеро действующих начали, никто не прошёл целиком: снятая с курса в
  // знаменатель не входит — она не «не закончила», она ушла
  await expect(card('started')).toContainText('5/5')
  await expect(card('finished')).toContainText('0')
  await expect(card('unchecked')).toContainText('2')

  // самая трудная кликабельна и ведёт в проверку своего столбца
  await card('hardest').getByRole('button').click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toContainText('Проверка задачи')
  await expect(dialog).toContainText('Решите уравнение')
})

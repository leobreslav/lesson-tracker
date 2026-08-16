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
  await expect(rows).toHaveCount(14)
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
  await expect(dialog).toContainText(/ждёт проверки|ждут проверки/)
  // непроверенные идут первыми — ради них сюда и заходят
  await dialog.locator('.attempt-list li').first().getByTitle(/Отметить «верно»/).click()
  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()

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
  // сверху видно, что проверяем: условие и эталоны
  await expect(dialog.locator('.task-brief .katex').first()).toBeVisible()
  await expect(dialog.locator('.task-brief .tag').first()).toBeVisible()
  await expect(dialog.locator('.attempt-list li')).toHaveCount(1)
  // повторное нажатие на ту же отметку снимает её: третьей кнопки нет
  await dialog.getByTitle(/Отметить «неверно»/).click()
  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()

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
  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()
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
  // тринадцать действующих начали, один прошёл целиком: снятая с курса в
  // знаменатель не входит — она не «не закончила», она ушла
  await expect(card('started')).toContainText('начали')
  await expect(card('started')).toContainText('прошли целиком')
  // знаменатель — один на обе строки и стоит внизу мелким
  await expect(card('started')).toContainText('13 учеников в курсе')
  await expect(card('unchecked')).not.toContainText('0')

  // «на проверку» кликабельна и ведёт в столбец, где эти ответы лежат
  await card('unchecked').getByRole('button').click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toContainText('Проверка задачи')
  await expect(dialog.locator('.task-question')).not.toBeEmpty()
})

/**
 * Оценки: шкала настраивается там же, где проверяют.
 *
 * Проверять в браузере стоит потому, что три состояния оценивания —
 * «не оценивается», «отметка», «по критериям» — это одни и те же данные с
 * разным видом, и вид выбирается по правилу «один безымянный критерий».
 * Ошибка в правиле не роняет ничего, просто экран показывает не то.
 */
test('шкала настраивается, и оценка попадает в таблицу и к ученику', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Проверочная')

  await expect(page.getByText('Работа не оценивается.')).toBeVisible()

  await page.getByRole('button', { name: 'настроить' }).click()
  const scale = page.locator('dialog.modal')
  await scale.getByRole('button', { name: 'отметка', exact: true }).click()
  await scale.getByLabel('Максимум').fill('5')
  await scale.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.getByText('Оценивается из 5.')).toBeVisible()

  // колонка появилась вместе со шкалой, и в ней пока прочерки
  const row = page.locator('.work-table tbody tr', { hasText: 'Артём Степанов' })
  await row.locator('td.mark button').click()

  const grade = page.locator('dialog.modal')
  await grade.getByLabel('Оценка из 5').fill('4')
  await grade.getByLabel('Комментарий учителя').fill('Разобрался с формулой')
  await grade.getByRole('button', { name: 'Сохранить' }).click()

  await expect(row.locator('td.mark')).toContainText('4')

  // ученик видит свою оценку и слова учителя
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)
  await page.getByRole('link', { name: 'Проверочная: формулы сложения' }).click()
  await ready(page)

  await expect(page.getByText('Разобрался с формулой')).toBeVisible()
})

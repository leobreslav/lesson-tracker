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

  // пятнадцатый — приглашённый: приглашение заводит учётку сразу, и он
  // такой же ученик курса, просто ещё ни разу не входивший
  const rows = page.locator('.work-table tbody tr')
  await expect(rows).toHaveCount(15)
  // снятая с курса остаётся строкой: её ответы никуда не делись
  await expect(rows.filter({ hasText: 'Ева Морозова' })).toHaveClass(/past/)

  // в демо есть все состояния сразу, иначе таблицу не на чем проверить
  await expect(page.locator('.work-table td.correct')).not.toHaveCount(0)
  await expect(page.locator('.work-table td.wrong')).not.toHaveCount(0)
  await expect(page.locator('.work-table td.sent')).not.toHaveCount(0)
  await expect(page.locator('.work-table td.empty')).not.toHaveCount(0)
})

test('подпись «(макс.)» стоит на той же строке, что и сами максимумы', async ({
  page,
  signIn,
}) => {
  /*
   * Шапка таблицы — два этажа: имена столбцов и стоимость вопроса под ними.
   * Столбец-пояснение называет **второй** этаж, и стоять он обязан на нём же.
   *
   * Ломается это молча и незаметно для кода: пустая первая строка схлопывается
   * в ноль высоты, подпись поднимается этажом выше и оказывается на одной
   * линии с номерами вопросов — то есть подписывает не ту строку, которую
   * называет. Глазами это видно, а разметка при этом верная.
   */
  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Контрольная')

  const label = await page.locator('.work-table thead th.who .head-max').boundingBox()
  const first = await page
    .locator('.work-table thead th:not(.who) .head-max')
    .first()
    .boundingBox()

  expect(Math.abs(label.y - first.y)).toBeLessThan(3)

  /*
   * И тем же шагом, что столбцы задач.
   *
   * Мерка тут не «на глаз просторно», а **между серединами**: числа в столбцах
   * стоят по центру широких клеток, и ритм задают их середины. Подгонялось это
   * дважды и дважды мимо — сперва по зазору между клетками (десять пикселей
   * против двадцати двух, вроде и просторно), потом по зазору между надписями
   * (девяносто три против девяноста пяти, тоже вроде верно), — а глазу
   * неправильно было и то и другое: подпись шире числа, и при равных зазорах
   * её середина уезжает. Поэтому сравниваются середины, и порог мягкий:
   * правило про ритм, а не про пиксели.
   */
  const middles = (locator) =>
    locator.evaluate((node) => {
      const range = document.createRange()
      range.selectNodeContents(node)
      const box = range.getBoundingClientRect()
      return (box.left + box.right) / 2
    })

  const cells = page.locator('.work-table thead th:not(.who) .head-max')
  const [atLabel, atFirst, atSecond] = await Promise.all([
    middles(page.locator('.work-table thead th.who .head-max')),
    middles(cells.nth(0)),
    middles(cells.nth(1)),
  ])

  /*
   * Требование мягкое и намеренно одностороннее: подпись не должна отстоять
   * **дальше**, чем максимумы стоят друг от друга. Точного равенства не
   * добиться — подпись шире числа, и совпало бы оно только при равной ширине,
   * — а вот «значительно дальше остальных» это ровно та жалоба, из-за которой
   * отдельный столбец с заданным отступом и не подошёл: отступ не следит за
   * шириной колонок, а та меняется от числа вопросов.
   */
  const pitch = atSecond - atFirst
  expect(atFirst - atLabel).toBeLessThan(pitch * 1.1)
})

test('проверка столбцом ставит отметку, и таблица её показывает', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openTable(page, 'Контрольная')

  const before = await page.locator('.work-table td.sent').count()
  // номер вопроса открывает **вопрос**: что спрашивали и что верно. Проверка
  // столбцом — оттуда же, соседней кнопкой: столбец проверяют подряд по
  // вопросу, и терять этот путь нельзя, но условие смотрят чаще
  await page.locator('.work-table thead button.link').first().click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog).toContainText('Правильный ответ')
  await dialog.getByRole('button', { name: 'Проверить столбец' }).click()
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

test('таблица обновляется сама, а новый ответ помечен без потери балла', async ({
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

  // Балл остался за тем ответом, за который поставлен, и **виден**: гасить
  // оценку самим фактом новой отправки значило бы стирать работу учителя.
  // Рядом встаёт точка «надо посмотреть», а решает человек.
  await expect(cell.locator('td').first()).toHaveClass(/stale/, { timeout: 15000 })
  await expect(cell.locator('td .cell').first()).toHaveText('✓')
  await expect(cell.locator('td .review').first()).toBeVisible()
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
  // четырнадцать действующих: тринадцать вошедших плюс приглашённый,
  // снятая с курса в это число не входит
  await expect(card('started')).toContainText('14 учеников в курсе')
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
  // отметка — выбор из шкалы, а не набранное число
  await grade.getByLabel('Оценка из 5').selectOption('4')
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

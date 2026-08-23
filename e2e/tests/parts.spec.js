import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Задача с пунктами: сюжет, буквы и то, что видит ученик.
 *
 * Через браузер это гонять надо из-за последнего: **выключенная шапка не
 * должна доезжать до ученика ни текстом, ни пометкой**. Питоновский тест
 * проверяет ответ сервера, а тут видно готовую страницу — включая то, что на
 * ней ничего лишнего не осталось.
 */

test('вставка отступом заводит сюжет, а номер ведёт и к пункту, и ко всему', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank')
  await ready(page)
  await page.getByRole('link', { name: 'Листочки по алгебре' }).click()
  await ready(page)

  await page.getByRole('button', { name: 'Вписать задачи' }).click()
  await page.locator('.modal textarea').fill(
    '3\tДан треугольник ABC со сторонами 3, 4, 5.\n' +
      '  а)\tНайдите площадь.\n' +
      '  б)\tНайдите радиус вписанной окружности.',
  )
  await page.locator('.modal').getByRole('button', { name: 'Сохранить' }).click()

  // номер целиком — сюжет и оба пункта; «3а» — только этот пункт
  await page.getByLabel('Номер').fill('3')
  await expect(page.locator('.problem-list')).toContainText('Найдите площадь')
  await expect(page.locator('.problem-list')).toContainText('Найдите радиус')

  await page.getByLabel('Номер').fill('а)')
  await expect(page.locator('.problem-list li')).toHaveCount(1)
})

test('сюжет разворачивается по ячейкам, а шапку можно снять для ученика', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((one) => one.name === 'Grade 6 Algebra')
  const book = await teacher.post('/api/bank/sources/', {
    title: 'С сюжетом',
    level: 'personal',
  })
  await teacher.post(`/api/bank/sources/${book.body.id}/`, {
    problems:
      '3\tДан треугольник ABC со сторонами 3, 4, 5.\n' +
      '  а)\tНайдите площадь.\n' +
      '  б)\tНайдите радиус.',
  })
  expect(book.status, JSON.stringify(book.body)).toBe(201)
  const shelf = await teacher.get(`/api/bank/sources/${book.body.id}/`)
  expect(shelf.status, JSON.stringify(shelf.body)).toBe(200)
  const stem = shelf.body.entries.find((row) => !row.parent).problem

  // взяли сюжет — получили две ячейки, по одной на пункт
  const work = await teacher.post('/api/works/from-bank/', {
    course: course.id,
    title: 'С пунктами',
    problems: [stem],
  })

  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)
  // правка ячеек живёт на странице работы, а не в строке списка
  await page
    .locator('.course-row', { hasText: 'С пунктами' })
    .getByRole('button', { name: 'Править' })
    .click()
  await ready(page)

  const rows = page.locator('.task-list li')
  await expect(rows).toHaveCount(2)
  // у каждой ячейки свой вопрос и общая шапка над ним
  await expect(rows.first()).toContainText('Дан треугольник')
  await expect(rows.first()).toContainText('Найдите площадь')
  // соседний пункт в ячейку не попадает
  await expect(rows.first()).not.toContainText('Найдите радиус')

  // шапку у первой ячейки снимаем: данные будут на доске
  await rows.first().hover()
  await rows.first().getByRole('button', { name: 'Изменить' }).click()
  await page.getByLabel('Показывать общее условие ученику').uncheck()
  await page.locator('.modal').getByRole('button', { name: 'Сохранить' }).click()

  await expect(rows.first()).toContainText('Общее условие скрыто')

  // ученик не видит ни шапки, ни пометки, что это пункт
  const tasks = await teacher.get(`/api/works/tasks/?work=${work.body.id}`)
  const hidden = tasks.body.find((one) => !one.show_stem)
  expect(hidden.shown.is_part).toBe(true)

  // ученик: ни шапки, ни пометки — иначе скрытие ничего не скрывает
  const pupil = await api(PEOPLE.student)
  const seen = await pupil.get(`/api/student/works/${work.body.id}/`)
  expect(seen.status, JSON.stringify(seen.body)).toBe(200)

  const cell = seen.body.tasks.find((one) => one.id === hidden.id)
  expect(cell.shown.stem).toBe(null)
  expect(cell.shown.is_part).toBe(false)

  // а у соседней ячейки, где шапку не трогали, сюжет на месте
  const other = seen.body.tasks.find((one) => one.id !== hidden.id)
  expect(other.shown.stem.text).toContain('треугольник')
})

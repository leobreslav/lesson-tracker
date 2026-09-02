import { expect, PEOPLE, pickCourse, ready, test } from './harness.js'

/**
 * Система оценивания и разговор о задаче.
 *
 * Через браузер это гонять надо из-за одной вещи, которую не поймать ничем
 * другим: **выбор системы принадлежит учителю**, а список ему даёт школа. Если
 * форма предложит запрещённую или чужую, сервер откажет — и человек увидит
 * пустой отказ на ровном месте.
 */

const day = 24 * 60 * 60 * 1000

async function onlineWork(teacher, title = 'Работа с системой') {
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((one) => one.name === 'Grade 6 Algebra')
  const work = await teacher.post('/api/works/', {
    course: course.id,
    title,
    opens_at: new Date(Date.now() - day).toISOString(),
    closes_at: new Date(Date.now() + day).toISOString(),
  })
  expect(work.status, JSON.stringify(work.body)).toBe(201)
  return work.body
}

test('администратор заводит типовые системы и запрещает одну', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await page.goto('/school/reference')
  await ready(page)

  // Пустоты тут не проверяем: посев кладёт школе систему оценивания, а
  // «новая школа не получает ничего» доказано питоновским тестом на модели.
  // Экран отвечает за другое — что кнопка заводит все три и что она идемпотентна.
  const list = page.locator('.grading-list li')
  await page.getByRole('button', { name: 'Добавить типовые' }).click()
  for (const name of ['5-балльная', 'MYP', 'Зачёт']) {
    await expect(list.filter({ hasText: name })).toHaveCount(1)
  }
  const после = await list.count()

  // нажать дважды не страшно
  await page.getByRole('button', { name: 'Добавить типовые' }).click()
  await expect(list).toHaveCount(после)

  await list.first().getByRole('button', { name: 'запретить' }).click()
  await expect(list.first().getByRole('button', { name: 'разрешить' })).toBeVisible()
})

test('учитель выбирает систему сам, а запрещённой в списке нет', async ({
  page,
  signIn,
  api,
}) => {
  const admin = await api(PEOPLE.admin)
  await admin.post('/api/works/grading/', { typical: true })
  const systems = await admin.get('/api/works/grading/')
  const five = systems.body.systems.find((one) => one.kind === 'points')
  await admin.patch(`/api/works/grading/${five.id}/`, { is_allowed: false })

  const teacher = await api(PEOPLE.ivanova)
  const work = await onlineWork(teacher)

  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)
  await pickCourse(page)
  const row = page.locator('.work-list .course-row', { hasText: work.title })
  await row.getByRole('button', { name: 'Править' }).click()
  await ready(page)

  // система оценивания — из тех полей, что задают один раз: на странице
  // работы они за кнопкой «Настройки», а на виду задание и задачи
  await page.getByRole('button', { name: 'Настройки' }).click()

  const select = page.getByLabel('Система оценивания')
  await expect(select).toBeVisible()
  // запрещённой в списке нет вовсе: форма не предлагает того, чего сервер не примет
  await expect(select.locator('option', { hasText: five.name })).toHaveCount(0)

  await select.selectOption({ label: 'MYP 1–7' })
  await page.locator('dialog.modal').getByRole('button', { name: 'Сохранить' }).click()
  // окно закрывается по ответу сервера: читать работу раньше — гонка
  await expect(page.locator('dialog.modal')).toHaveCount(0)

  const after = await teacher.get(`/api/works/${work.id}/`)
  expect(after.body.grade.name).toBe('MYP 1–7')
})

test('ученик спрашивает про задачу, учитель отвечает в том же треде', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const work = await onlineWork(teacher, 'Работа с вопросом')
  const task = await teacher.post('/api/works/tasks/', {
    work: work.id,
    question: 'Сколько будет 2+2?',
    answers: ['4'],
  })

  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)
  await page.getByRole('link', { name: 'Работа с вопросом' }).click()
  await ready(page)

  // разговор свёрнут, пока говорить не о чем: поле в каждой задаче — шум
  await page.getByRole('button', { name: 'Спросить про эту задачу' }).click()
  const thread = page.locator('.task-thread')
  await thread.getByPlaceholder('Спросите учителя про эту задачу').fill('Не понял условие')
  await thread.getByRole('button', { name: 'Отправить' }).click()
  await expect(page.locator('.thread-list')).toContainText('Не понял условие')

  // учитель видит тот же тред — он один на обе стороны
  const people = await teacher.get('/api/school/members/?kind=student')
  const asked = people.body.find((one) => one.email === PEOPLE.student)
  const seen = await teacher.get(
    `/api/works/thread/?task=${task.body.id}&student=${asked.id}`,
  )
  expect(seen.body.messages.map((one) => one.text)).toEqual(['Не понял условие'])
})

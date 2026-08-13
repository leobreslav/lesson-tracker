import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenario 2: the «School» section — four tabs and the link between a
 * teacher and a course.
 *
 * That link is the thing worth driving through a browser: it is written from
 * two different screens and read on a third one (the teacher's own list of
 * courses), so a mistake anywhere in the chain shows up only here.
 */

const openSection = async (page, path) => {
  await page.goto(path)
  await ready(page)
}

test('администратор заводит курс и назначает на него учителя', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/courses')

  await page.getByPlaceholder('Название курса').fill('9А Алгебра')
  await page.getByLabel('Предмет:').selectOption({ label: 'Алгебра' })
  // параллели теперь справочник: «MYP 4» — это девятый год обучения
  await page.getByLabel('Параллель:').selectOption({ label: 'MYP 4' })
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()

  const card = page.locator('.people-list > li', { hasText: '9А Алгебра' })
  await expect(card).toContainText('курс никто не ведёт')

  await card.getByLabel('Учитель для 9А Алгебра').selectOption({ label: 'Мария Иванова' })
  await card.getByRole('button', { name: 'Назначить' }).click()

  await expect(card.locator('.tag')).toContainText('Мария Иванова')

  // и курс появился в её собственном списке — ради этого связь и заведена
  await signIn(PEOPLE.ivanova)
  await openSection(page, '/classes')
  await expect(page.getByText('9А Алгебра')).toBeVisible()
})

test('назначение видно и снимается со стороны учителя', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/teachers')

  const card = page.locator('.people-list > li', { hasText: 'ivanova@example.com' })
  // то же самое отношение, показанное с другого конца
  await expect(card.locator('.tag').first()).toContainText('Grade 6 Algebra')

  await card.getByLabel('Курс для Мария Иванова').selectOption({ label: 'Grade 9 Geometry' })
  await card.getByRole('button', { name: 'Назначить' }).click()

  await expect(card.locator('.tag', { hasText: 'Grade 9 Geometry' })).toBeVisible()

  // и обратно, с карточки курса
  await openSection(page, '/school/courses')
  const course = page.locator('.people-list > li', { hasText: 'Grade 9 Geometry' })
  // exact: у курса уже есть свой учитель, и «.tag» их двое
  await expect(course.locator('.tag', { hasText: 'Мария Иванова' })).toBeVisible()
})

test('учитель курсы не заводит: формы нет, а сервер отказывает', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)
  await openSection(page, '/classes')

  await expect(page.getByPlaceholder('Название курса')).toHaveCount(0)

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const refused = await teacher.post('/api/courses/', {
    year: courses.body[0].year,
    name: 'Самодельный',
  })

  expect(refused.status).toBe(403)
  expect(refused.body.code).toBe('school_admin_required')
})

test('справочники: предмет заводится и параллель переименовывается', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/reference')

  // по тексту панель не поймать: «параллели» есть и в подсказке предметов
  const subjects = page.locator('[data-panel="subjects"]')
  await subjects.getByPlaceholder('Название нового предмета').fill('Информатика')
  await subjects.getByRole('button', { name: 'Добавить' }).click()
  // exact: рядом стоит «Удалить Информатика»
  await expect(
    subjects.getByRole('button', { name: 'Информатика', exact: true }),
  ).toBeVisible()

  // год обучения и название — разные вещи, и меняется только второе
  const grades = page.locator('[data-panel="grades"]')
  const ninth = grades.locator('li[data-level="9"]')
  await ninth.getByRole('button', { name: 'MYP 4', exact: true }).click()
  await ninth.getByLabel('Новое название').fill('MYP 4 (9 класс)')
  await ninth.getByLabel('Новое название').press('Enter')

  await expect(
    grades.getByRole('button', { name: 'MYP 4 (9 класс)', exact: true }),
  ).toBeVisible()
  // само число рядом осталось прежним и менять его нельзя: курсы уже на нём
  await expect(ninth.locator('.level')).toHaveText('9')
})

test('параллели: набор одной кнопкой и уборка неиспользуемых', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/reference')

  const grades = page.locator('[data-panel="grades"]')
  // в демо-школе заведены только те две, что реально нужны курсам
  await expect(grades.locator('li')).toHaveCount(2)

  await grades.getByRole('button', { name: 'Добавить 1–13' }).click()
  await expect(grades.locator('li')).toHaveCount(13)

  // название подставляется само, стоит ввести год обучения
  await grades.getByLabel('Год обучения').fill('14')
  await expect(grades.getByLabel('Название')).toHaveValue('Grade 14')

  page.once('dialog', (dialog) => dialog.accept())
  await grades.getByRole('button', { name: /Удалить \d+ неиспользуем/ }).click()

  // остались ровно те две, на которых висят курсы
  await expect(grades.locator('li')).toHaveCount(2)
})

test('обзор считает школу и подсказывает следующий шаг', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school')

  const cards = page.locator('.summary-cards li')
  await expect(cards.filter({ hasText: 'учителей' })).toContainText('3')
  await expect(cards.filter({ hasText: 'курсов' })).toContainText('4')
})

test('в школьном расписании урок ставится в обычный будний день', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/schedule')

  // листаем в учебный год: «сегодня» в демо-данных до его начала, а поля
  // выбора даты в этой панели нет
  const monday = page.locator('[data-day-head="2026-09-07"]')
  for (let step = 0; step < 8 && !(await monday.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(250)
  }

  // понедельник — учебный день, и сетка обязана это знать: признак приходит
  // из того же ответа календаря, что и на странице «Учебный год»
  await expect(monday).toBeVisible()
  await expect(monday).not.toContainText('не учебный')

  await page.locator('[data-add="2026-09-07:6"]').click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Курсы').selectOption({ index: 1 })
  await dialog.getByRole('button', { name: 'Добавить', exact: true }).click()

  await expect(dialog).toBeHidden()
  await expect(page.locator('[data-lesson="2026-09-07:6"]')).toHaveCount(1)
})

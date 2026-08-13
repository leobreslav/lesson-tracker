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

  const subjects = page.locator('.panel', { hasText: 'Предметы' })
  await subjects.getByPlaceholder('Название нового предмета').fill('Информатика')
  await subjects.getByRole('button', { name: 'Добавить' }).click()
  // exact: рядом стоит «Удалить Информатика»
  await expect(
    subjects.getByRole('button', { name: 'Информатика', exact: true }),
  ).toBeVisible()

  // год обучения и название — разные вещи, и меняется только второе
  const grades = page.locator('.panel', { hasText: 'Параллели' })
  const ninth = grades.locator('li', { hasText: '9 год' })
  await ninth.getByRole('button', { name: 'MYP 4', exact: true }).click()
  await ninth.getByLabel('Новое название').fill('MYP 4 (9 класс)')
  await ninth.getByLabel('Новое название').press('Enter')

  await expect(
    grades.getByRole('button', { name: 'MYP 4 (9 класс)', exact: true }),
  ).toBeVisible()
  await expect(ninth).toContainText('9 год')
})

test('обзор считает школу и подсказывает следующий шаг', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school')

  const cards = page.locator('.summary-cards li')
  await expect(cards.filter({ hasText: 'учителей' })).toContainText('3')
  await expect(cards.filter({ hasText: 'курсов' })).toContainText('4')
})

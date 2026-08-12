import { PEOPLE, expect, ready, test } from './harness.js'

/** Scenario 2: an administrator adds a course and finds it in the list. */

test('администратор заводит курс и видит его в списке', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await page.goto('/school')
  await ready(page)

  const courses = page.locator('.panel', { hasText: 'Курсы' })
  await courses.getByPlaceholder('Название курса').fill('9А Алгебра')
  await courses.getByLabel('Предмет:').selectOption({ label: 'Алгебра' })
  await courses.getByLabel('Параллель:').fill('9')
  await courses.getByRole('button', { name: 'Добавить', exact: true }).click()

  // exact: кнопка удаления рядом называется «Удалить курс 9А Алгебра», и
  // подстрочное совпадение по умолчанию задело бы обе
  await expect(
    courses.getByRole('button', { name: '9А Алгебра', exact: true }),
  ).toBeVisible()

  // and the teacher's read-only list agrees, which is the point of a
  // school-wide course
  await page.goto('/classes')
  await ready(page)
  await expect(page.getByText('9А Алгебра')).toBeVisible()
})

test('учитель курсы не заводит: формы нет, а сервер отказывает', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/classes')
  await ready(page)

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

test('новый предмет заводится не покидая формы курса', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await page.goto('/school')
  await ready(page)

  const courses = page.locator('.panel', { hasText: 'Курсы' })
  await courses.getByPlaceholder('Название нового предмета').fill('Информатика')
  await courses.getByRole('button', { name: 'Добавить предмет' }).click()

  await expect(courses.getByLabel('Предмет:')).toContainText('Информатика')
})

import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Второй вид пользователя: у ученика другой интерфейс целиком.
 *
 * Проверяется не «красиво ли», а граница: учительских разделов он не видит,
 * учительские адреса ему ничего не показывают, и наоборот — учитель не
 * попадает в ученический раздел. Слушатель консоли здесь особенно к месту:
 * лишний фоновый запрос учительской половины виден именно как ошибка в
 * консоли, а не как поломка на экране.
 */

test('ученик видит свои курсы и ни одного учительского раздела', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await expect(page.getByRole('heading', { name: 'Мои курсы' })).toBeVisible()
  await expect(page.locator('.student-courses li')).toHaveCount(1)
  await expect(page.locator('.student-courses')).toContainText('Grade 6 Algebra')

  // в баре только имя и выход: разделов учителя нет ни одного
  await expect(page.locator('.nav-link')).toHaveCount(0)
  for (const section of ['Учебный план', 'Моё расписание', 'Классы', 'Школа']) {
    await expect(page.getByRole('link', { name: section })).toHaveCount(0)
  }
})

test('учительский адрес ученику ничего не показывает', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/plan')
  await ready(page)

  // своя страница «не найдено», а не чужой интерфейс и не пустой экран
  await expect(page.locator('.plan-cards')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Мои курсы' })).toBeVisible()
})

test('снятый с курса видит его отдельно и с объяснением', async ({ page, signIn }) => {
  await signIn(PEOPLE.removedStudent)
  await page.goto('/')
  await ready(page)

  await expect(page.getByText('Сейчас вы не записаны ни на один курс.')).toBeVisible()

  const past = page.locator('.panel', { hasText: 'Вы больше не в этих курсах' })
  await expect(past).toContainText('Grade 6 Algebra')
  await expect(past).toContainText('всё сделанное остаётся видно')
})

test('язык переключается и у ученика', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await page.locator('.user-menu > button').click()
  await page.getByRole('menuitem', { name: 'English' }).click()

  await expect(page.getByRole('heading', { name: 'My courses' })).toBeVisible()
})

test('ученический раздел учителю закрыт', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)

  const response = await teacher.get('/api/student/courses/')

  expect(response.status).toBe(403)
  expect(response.body.code).toBe('students_only')
})

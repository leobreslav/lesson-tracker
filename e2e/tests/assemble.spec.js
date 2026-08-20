import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Работа, собранная из банка.
 *
 * Через браузер это гонять надо из-за набора: он живёт **между экранами** —
 * задачу откладывают в поиске, другую в книге, — и переживает переход. Ни один
 * питоновский тест этого не видит: набор целиком клиентский.
 */

test('задачи отбираются на разных экранах и становятся работой', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank/search')
  await ready(page)

  // одна задача из поиска
  await page.locator('.problem-list li').first().getByRole('button', { name: 'Отложить задачу' }).click()
  await expect(page.locator('.basket')).toContainText('1')

  // вторая — из книги, и набор при переходе не теряется
  await page.goto('/bank')
  await ready(page)
  await page.getByRole('link', { name: 'Листочки по алгебре' }).click()
  await ready(page)
  await expect(page.locator('.basket')).toContainText('1')
  // берём другую задачу: первая в книге — та же, что отобрана в поиске, и
  // кнопка у неё уже называется «убрать» (набор общий на все экраны)
  await page
    .locator('.problem-list li')
    .last()
    .getByRole('button', { name: 'Отложить задачу' })
    .click()
  await expect(page.locator('.basket')).toContainText('2')

  await page.getByRole('button', { name: 'Собрать работу' }).click()
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })
  await page.getByLabel('Название').fill('Проверочная из банка')
  await page.locator('.modal').getByRole('button', { name: 'Собрать' }).click()

  // после сборки страница работы, а набор снят: та же пачка второй раз не задаётся
  await ready(page)
  await expect(page.getByRole('heading', { name: 'Проверочная из банка' })).toBeVisible()

  await page.goto('/bank/search')
  await ready(page)
  await expect(page.locator('.basket')).toHaveCount(0)
})

test('условие в работе — снимок: правка в банке его не переписывает', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  const problem = found.body.problems[0]
  const courses = await teacher.get('/api/courses/')
  const work = await teacher.post('/api/works/from-bank/', {
    course: courses.body[0].id,
    title: 'Снимок',
    problems: [problem.id],
  })

  // условие в банке уехало вперёд
  await teacher.patch(`/api/bank/problems/${problem.id}/`, {
    text: 'Совсем другое условие',
  })

  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)
  await page.getByRole('button', { name: 'Снимок' }).first().click()

  // в работе — то, что решали, а расхождение названо и предлагает обновить
  await expect(page.locator('.task-list')).toContainText('Окружность')
  await expect(page.locator('.task-list')).toContainText('условие в банке изменилось')

  await page.getByRole('button', { name: 'Обновить из банка' }).click()
  await expect(page.locator('.task-list')).toContainText('Совсем другое условие')
})

test('на странице задачи видно, где её уже спрашивали', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  const problem = found.body.problems[0]
  const courses = await teacher.get('/api/courses/')
  await teacher.post('/api/works/from-bank/', {
    course: courses.body[0].id,
    title: 'Уже задавал',
    problems: [problem.id],
  })

  await signIn(PEOPLE.ivanova)
  await page.goto(`/bank/problem/${problem.id}`)
  await ready(page)

  const asked = page.locator('.panel', { hasText: 'Где её уже спрашивали' })
  await expect(asked).toContainText('Уже задавал')
  await expect(asked).toContainText(courses.body[0].name)
})

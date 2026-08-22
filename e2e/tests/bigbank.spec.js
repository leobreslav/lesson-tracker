import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Большой банк: предмет как сквозной фильтр, семья одной строкой, импорт
 * таблицей и след ученика.
 *
 * Через браузер это гонять надо потому, что все четыре — про **выдачу**:
 * сервер отвечает правильно, а замыленный аналогами список или незакреплённый
 * предмет видно только на экране.
 */

test('семья аналогов стоит в выдаче одной строкой и говорит, сколько их ещё', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const found = await teacher.get('/api/bank/search/?text=уравнение')
  const before = found.body.total
  const [first, second] = found.body.problems
  await teacher.post('/api/bank/analogues/', {
    problem: first.id,
    other: second.id,
  })

  await signIn(PEOPLE.ivanova)
  await page.goto('/bank/search')
  await ready(page)
  await page.getByLabel('Слова из условия').fill('уравнение')

  // две задачи стали одной строкой: семья занимает место одной, а не двух
  const rows = page.locator('.problem-list li')
  await expect(rows).toHaveCount(before - 1)
  await expect(rows.filter({ hasText: 'аналог' })).toHaveCount(1)
})

test('предмет держится между экранами банка', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank')
  await ready(page)

  await page.getByLabel('Предмет').selectOption({ label: 'геометрия' })
  // книга по алгебре ушла: предмет — самый глобальный фильтр
  await expect(page.locator('.source-list li')).toHaveCount(0)

  // и он же выбран, когда открываешь поиск
  await page.goto('/bank/search')
  await ready(page)
  await expect(page.getByLabel('Предмет')).toHaveValue(/\d+/)
  await expect(page.locator('.problem-list li')).toHaveCount(1)
})

test('таблица заводит разделы, номера и пункты одним заходом', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const book = await teacher.post('/api/bank/sources/', {
    title: 'Импорт',
    level: 'personal',
  })

  await signIn(PEOPLE.ivanova)
  await page.goto(`/bank/source/${book.body.id}`)
  await ready(page)

  await page.getByRole('button', { name: 'Импорт таблицей' }).click()
  await page.locator('.modal textarea').fill(
    'Раздел\tНомер\tПункт\tУсловие\tОтвет\n' +
      'Глава 1\t14\t\tДан треугольник ABC.\t\n' +
      'Глава 1\t14\tа)\tНайдите площадь\t6\n' +
      'Глава 1\t20\t\tРешите уравнение\t2',
  )

  // предпросмотр ничего не пишет и называет, что получится
  await page.getByRole('button', { name: 'Проверить' }).click()
  await expect(page.locator('.modal')).toContainText('задач: 2')

  await page.getByRole('button', { name: 'Импортировать' }).click()
  await ready(page)

  await expect(page.locator('.outline')).toContainText('Глава 1')
  await expect(page.locator('.problem-list')).toContainText('Найдите площадь')
})

test('след ученика собран по условиям, а не по работам', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((one) => one.name === 'Grade 6 Algebra')
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  const problem = found.body.problems[0].id

  // одно условие спрошено дважды
  for (const title of ['Осенняя', 'Весенняя']) {
    await teacher.post('/api/works/from-bank/', {
      course: course.id,
      title,
      problems: [problem],
    })
  }

  const works = await teacher.get(`/api/works/?course=${course.id}`)
  const table = await teacher.get(`/api/works/${works.body[0].id}/table/`)
  const student = table.body.students.find((one) => one.active).id
  const known = await teacher.get(`/api/works/track/${student}/`)

  await signIn(PEOPLE.ivanova)
  await page.goto(`/track/${student}`)
  await ready(page)

  // строк ровно столько, сколько **условий**, а не попыток: задача, решённая
  // дважды, — одна строка с пометкой «2×»
  const rows = page.locator('.problem-list li')
  await expect(rows).toHaveCount(known.body.summary.problems)
  expect(known.body.summary.attempts).toBeGreaterThan(
    known.body.summary.problems,
  )
  await expect(rows.filter({ hasText: '2×' })).toHaveCount(1)
})

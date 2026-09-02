import { expect, PEOPLE, pickCourse, ready, test } from './harness.js'

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

test('условие ячейки — то же самое условие: правка видна везде, где его спросили', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  const problem = found.body.problems[0].id

  // одно условие в двух работах
  const first = await teacher.post('/api/works/from-bank/', {
    course: courses.body[0].id,
    title: 'Первая',
    problems: [problem],
  })
  await teacher.post('/api/works/from-bank/', {
    course: courses.body[0].id,
    title: 'Вторая',
    problems: [problem],
  })

  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)
  await pickCourse(page)
  // правят задачи на странице работы: в списке они только показаны
  await page
    .locator('.course-row', { hasText: 'Первая' })
    .getByRole('button', { name: 'Править' })
    .click()
  await ready(page)

  // кнопки строки появляются при наведении — как в таблице плана
  const row = page.locator('.task-list li').first()
  await row.hover()
  await row.getByRole('button', { name: 'Изменить' }).click()
  await expect(page.locator('.statement-cost')).toContainText('2')

  // по условию не отвечали — правка идёт везде, и выбор об этом говорит
  await expect(page.getByRole('radio', { name: 'Везде' })).toBeChecked()
  await page.locator('.modal textarea').first().fill('Поправленное условие')
  await page.locator('.modal').getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.task-list')).toContainText('Поправленное условие')

  // и во второй работе — оно же: второго текста у работы нет. Смотрим
  // списком: он для того и разворачивается, чтобы глянуть, не уходя
  await page.goto('/works')
  await ready(page)
  await pickCourse(page)
  await page.getByRole('button', { name: 'Вторая' }).first().click()
  await expect(page.locator('.task-list')).toContainText('Поправленное условие')
})

test('пустая ячейка заполняется потом — готовым условием из банка', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const work = await teacher.post('/api/works/', {
    course: courses.body[0].id,
    title: 'Пустые ячейки',
    opens_at: '2026-09-01T08:00:00Z',
    closes_at: '2026-09-08T08:00:00Z',
  })
  // три пустые ячейки: условия были на бумаге, вбивать поленились
  for (const _ of [1, 2, 3]) await teacher.post('/api/works/tasks/', { work: work.body.id })

  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)
  await pickCourse(page)
  await page
    .locator('.course-row', { hasText: 'Пустые ячейки' })
    .getByRole('button', { name: 'Править' })
    .click()
  await ready(page)

  const rows = page.locator('.task-list li')
  await expect(rows).toHaveCount(3)

  // третью заполняем не руками, а готовой задачей
  const third = rows.nth(2)
  await third.hover()
  await third.getByRole('button', { name: 'Из банка…' }).click()
  await page.locator('.modal').getByLabel('Слова из условия').fill('Окружность')
  await page.locator('.modal .problem-list li').first().getByRole('button', { name: 'Сюда' }).click()

  await expect(rows.nth(2)).toContainText('Окружность')
  // соседи как были пустыми, так и остались: названо место, а не «в конец»
  await expect(rows.nth(0)).not.toContainText('Окружность')
})

test('дописать в оценённую работу можно, но цена названа и требует галочки', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  // работа с одной задачей, ответом и отметкой
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  const work = await teacher.post('/api/works/from-bank/', {
    course: courses.body[0].id,
    title: 'Уже проверенная',
    problems: [found.body.problems[0].id],
  })
  // проверенная работа — та, где стоит балл, а не только комментарий
  const table = await teacher.get(`/api/works/${work.body.id}/table/`)
  const student = table.body.students[0].id
  await teacher.post(`/api/works/${work.body.id}/grade/`, {
    student,
    scores: { [table.body.tasks[0].id]: 1 },
  })

  await signIn(PEOPLE.ivanova)
  await page.goto('/bank/search')
  await ready(page)
  await page.locator('.problem-list li').first().getByRole('button', { name: 'Отложить задачу' }).click()
  await page.getByRole('button', { name: 'Собрать работу' }).click()

  await page.getByRole('radio', { name: 'Дописать в готовую' }).click()
  await page.getByLabel('В какую работу').selectOption({ label: 'Уже проверенная' })

  // пока не подтвердил — не даёт: знаменатель поедет у всех проверенных
  const assemble = page.locator('.modal').getByRole('button', { name: 'Собрать' })
  await expect(assemble).toBeDisabled()
  await page.locator('.modal .checkbox.danger input').check()
  await expect(assemble).toBeEnabled()
})

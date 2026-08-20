import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Задачник: источники, условия и решения.
 *
 * Через браузер это гонять надо из-за двух вещей. Первая — **номер как
 * адрес**: учитель помнит «§14, №6», и если поле номера не приводит к задаче,
 * каталогом никто не пользуется. Вторая — **уровни владения**: у чужой книги
 * не должно быть кнопок правки, и увидеть это можно только глазами.
 */

test('книга заводится вставкой, а номер ведёт прямо к задаче', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank')
  await ready(page)

  await page.getByRole('button', { name: 'Добавить источник' }).click()
  await page.getByLabel('Название').fill('Мордкович. Алгебра 9')
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()

  await page.getByRole('link', { name: 'Мордкович. Алгебра 9' }).click()
  await ready(page)

  // оглавление вписывается целиком: по одной главе его не заводит никто
  await page.getByRole('button', { name: 'Вписать оглавление' }).click()
  await page.locator('.modal textarea').fill('Глава 1\n  §14 Квадратные уравнения')
  await page.locator('.modal').getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('.outline')).toContainText('§14')

  // задачи — тоже вставкой, номером и табуляцией
  await page.getByRole('button', { name: 'Вписать задачи' }).click()
  await page.locator('.modal textarea').fill('6\t$2x^2+5x-3=0$\n7\tРешите неравенство\n14а\tДокажите тождество')
  await page.locator('.modal').getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('.problem-list li')).toHaveCount(3)

  // номер — адрес: он и есть главный путь к задаче
  await page.getByLabel('Номер').fill('14а')
  await expect(page.locator('.problem-list li')).toHaveCount(1)
  await expect(page.locator('.problem-list')).toContainText('Докажите тождество')
})

test('к чужому условию можно написать своё решение', async ({ page, signIn, api }) => {
  // системная книга: её завёл суперпользователь, править её учитель не может
  const root = await api(PEOPLE.admin)
  const teacher = await api(PEOPLE.ivanova)
  const mine = await teacher.post('/api/bank/sources/', {
    title: 'Мои листочки',
    level: 'personal',
  })
  await teacher.post(`/api/bank/sources/${mine.body.id}/`, {
    problems: '1\t$2x^2+5x-3=0$',
  })
  const book = await teacher.get(`/api/bank/sources/${mine.body.id}/`)
  const problem = book.body.entries[0].problem

  await signIn(PEOPLE.ivanova)
  await page.goto(`/bank/problem/${problem}`)
  await ready(page)

  await expect(page.getByText('Разбора пока никто не написал')).toBeVisible()

  await page.getByRole('button', { name: 'Добавить решение' }).click()
  await page.getByLabel('Метод, в двух словах').fill('Разложением на множители')
  await page.locator('.inline-form textarea').fill('$(2x-1)(x+3)=0$')
  await page.locator('.inline-form').getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.getByText('Разложением на множители')).toBeVisible()
})

test('ученику задачника нет вовсе', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await expect(page.getByRole('link', { name: 'Задачник' })).toHaveCount(0)
})

test('поиск сужается словом и гранью, и грань говорит, сколько останется', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank/search')
  await ready(page)

  // посеянный словарь: грани видно сразу, до всякого ввода
  // грань условия и грань решения — разные, и подпись их различает
  const facets = page.locator('.facet-list li')
  await expect(facets.filter({ hasText: /^алгебра/ })).toContainText('3')
  await expect(facets.filter({ hasText: 'решение: алгебра' })).toContainText('2')

  await page.getByRole('button', { name: 'геометрия' }).click()
  await expect(page.locator('.problem-list li')).toHaveCount(1)
  await expect(page.locator('.problem-list')).toContainText('Окружность')

  // снимается там же, где выбрана
  await page.locator('.chosen-facets .tag').click()
  await expect(page.locator('.problem-list li')).toHaveCount(4)

  // слово сужает так же, как грань
  await page.getByLabel('Слова из условия').fill('уравнение')
  await expect(page.locator('.problem-list li')).toHaveCount(2)
})

test('выражение отвечает на «или», и его можно сохранить под именем', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank/search')
  await ready(page)

  await page.getByRole('radio', { name: 'Выражением' }).click()

  // «алгебра или геометрия» — гранями такого не спросить: они складываются «и»
  await page.getByRole('radio', { name: 'любое' }).click()
  await page.getByRole('button', { name: '+ условие' }).click()
  await page.getByRole('button', { name: '+ условие' }).click()

  const tag = page.getByLabel('Тег')
  await tag.nth(0).selectOption({ label: 'алгебра' })
  await tag.nth(1).selectOption({ label: 'геометрия' })
  await expect(page.locator('.problem-list li')).toHaveCount(4)

  // «и» тех же двух — ни одной: задача не бывает сразу той и другой
  await page.getByRole('radio', { name: 'все' }).click()
  await expect(page.locator('.problem-list li')).toHaveCount(0)

  await page.getByRole('button', { name: 'Сохранить поиск' }).click()
  await page.getByLabel('Название').fill('Ни то ни это')
  await page.locator('.panel').getByRole('button', { name: 'Сохранить', exact: true }).click()

  await page.reload()
  await ready(page)
  await expect(page.getByLabel('Сохранённые')).toContainText('Ни то ни это')
})

test('чужая задача берётся к себе — ссылкой или своей копией', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const shelf = await teacher.post('/api/bank/sources/', {
    title: 'Полка учителя',
    level: 'personal',
  })

  // задача из посеянной книги: она личная, но берём её как чужую — путь тот же
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  const problem = found.body.problems[0].id

  await signIn(PEOPLE.ivanova)
  await page.goto(`/bank/problem/${problem}`)
  await ready(page)

  await page.getByRole('button', { name: 'Взять к себе' }).click()
  await page.getByLabel('В какую книгу').selectOption({ label: 'Полка учителя' })
  await page.locator('.modal').getByRole('button', { name: 'Взять' }).click()

  // ссылкой: задача осталась одна, просто встречается теперь в двух книгах
  await expect(page.locator('.panel', { hasText: 'Встречается в' })).toContainText(
    'Полка учителя',
  )

  const shelved = await teacher.get(`/api/bank/sources/${shelf.body.id}/`)
  expect(shelved.body.entries[0].problem).toBe(problem)
})

test('аналог объявляется поиском, и семья видна с обеих сторон', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const found = await teacher.get('/api/bank/search/?text=уравнение')
  const [first, second] = found.body.problems

  await signIn(PEOPLE.ivanova)
  await page.goto(`/bank/problem/${first.id}`)
  await ready(page)

  await expect(page.getByText('Аналогов не отмечено')).toBeVisible()
  await page.getByRole('button', { name: 'Добавить аналог' }).click()
  await page.locator('.modal').getByLabel('Слова из условия').fill('уравнение')
  await page
    .locator('.modal .problem-list li', { hasText: `#${second.id}` })
    .getByRole('button', { name: 'Это аналог' })
    .click()

  await expect(page.locator('.panel', { hasText: 'Аналоги' })).toContainText(
    `#${second.id}`,
  )

  // с другой стороны — то же самое: отношение общее, а не «у кого записано»
  await page.goto(`/bank/problem/${second.id}`)
  await ready(page)
  await expect(page.locator('.panel', { hasText: 'Аналоги' })).toContainText(
    `#${first.id}`,
  )
})

test('хронология: понятие вводится однажды и переносится, а не двоится', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank/chronology')
  await ready(page)

  const rows = page.locator('.chronology li')
  await expect(rows.first()).toContainText('теорема Виета')

  // то же понятие на другом уроке — это перенос: вводится оно один раз
  await rows.nth(2).getByRole('button', { name: '+ понятие' }).click()
  await rows.nth(2).getByLabel('Тег').selectOption({ label: 'теорема Виета' })

  await expect(rows.nth(2)).toContainText('теорема Виета')
  await expect(rows.first()).not.toContainText('теорема Виета')
})

test('закрытая тема отвечает по хронологии, открытая — по всему банку', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/bank/topics')
  await ready(page)

  // открытая тема: разбор через замену переменной в неё попадает
  await page.getByRole('button', { name: 'Квадратные уравнения' }).click()
  await expect(page.locator('.problem-list li')).toHaveCount(2)

  // закрытая: пройдена только теорема Виета, значит и задача одна
  await page.getByRole('button', { name: 'Что мы уже умеем' }).click()
  await expect(page.locator('.problem-list li')).toHaveCount(1)
  await expect(page.locator('.problem-list')).toContainText('x^2 - 5x + 6')
})

test('тег вешается на условие и на решение — у решения со знаком', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  const problem = found.body.problems[0].id

  await signIn(PEOPLE.ivanova)
  await page.goto(`/bank/problem/${problem}`)
  await ready(page)

  // на условии — вид задачи, знака у него не бывает
  await page.locator('.panel').first().getByRole('button', { name: '+ тег' }).click()
  await page.locator('.panel').first().getByLabel('Тег', { exact: true }).selectOption({ label: 'доказательство' })
  await expect(page.getByLabel('Знак')).toHaveCount(0)
  await page.getByRole('button', { name: 'Повесить' }).click()
  await expect(page.locator('.tag-strip').first()).toContainText('доказательство')

  // у разбора — со знаком: «без производной» это утверждение, а не молчание
  await page.getByRole('button', { name: 'Добавить решение' }).click()
  await page.getByLabel('Метод, в двух словах').fill('Через вписанную')
  await page.locator('.inline-form textarea').fill('$r = (a+b-c)/2$')
  await page.locator('.inline-form').getByRole('button', { name: 'Сохранить' }).click()

  // якорь у разбора свой (`data-block="solution.<id>"`) — по тексту сюда не попасть
  const solution = page.locator('[data-block^="solution."]', {
    hasText: 'Через вписанную',
  })
  await solution.locator('.panel-toggle').click()
  await solution.getByRole('button', { name: '+ тег' }).click()
  await solution.getByLabel('Тег', { exact: true }).selectOption({ label: 'замена переменной' })
  await solution.getByLabel('Знак').selectOption({ label: 'решение обходится без' })
  await solution.getByRole('button', { name: 'Повесить' }).click()

  await expect(solution.locator('.tag.avoids')).toContainText('замена переменной')
})

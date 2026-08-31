import { PEOPLE, expect, planMenu, ready, test } from './harness.js'

/**
 * План на полке правится тем же экраном, что и боевой.
 *
 * Проверяется здесь не библиотека — её видимость и копирование давно под
 * питоновскими тестами, — а ровно то, ради чего всё затевалось: программу
 * можно написать **без курса**, и пишется она обычной таблицей плана.
 *
 * Второе, что тут стережётся, — чего на этом экране быть не должно. Полка
 * не привязана к учебному году, значит на ней нет ни дат, ни утверждения
 * методистом, ни меню обмена файлами: те ручки ходят по курсу и ответили бы
 * отказом. Нарисованная кнопка, которая умеет только отказать, честнее не
 * нарисованной.
 */

test('план для класса, который не ведут, пишется без курса', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  // курс выбирают селектом: сама страница за человека больше не выбирает
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })
  // тулбар появляется вместе с деревом: кликать по меню раньше значит
  // нажать и тут же потерять его на перерисовке
  await expect(page.locator('.plan-cards')).toBeVisible()

  await planMenu(page, 'Открыть библиотеку')
  await page.getByRole('button', { name: 'Написать новый план…' }).click()

  const form = page.locator('.modal')
  await form.getByLabel('Название').fill('Алгебра 11, теоретический')
  await form.getByLabel('Параллель').fill('11')
  await form.getByRole('button', { name: 'Написать новый план…' }).click()

  // адрес — сам план на полке: экран тот же, а владелец другой
  await expect(page).toHaveURL(/\/library\/\d+$/)
  // чем занимаемся, называет селект в шапке, а не текст рядом с заголовком:
  // курсы и заготовки лежат в одном списке, и открытое — это выбранное в нём
  await expect(
    page.locator('select.course-picker option:checked'),
  ).toHaveText('Алгебра 11, теоретический')
  // и строка контекста говорит, что правки идут прямо в библиотеку
  await expect(page.locator('.plan-context')).toContainText('прямо в эту заготовку')

  await page.getByRole('button', { name: 'Добавить тему или урок' }).click()
  const row = page.locator('.plan-add-form')
  await row.getByLabel('Название').fill('Производная')
  await row.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.locator('.plan-row .title')).toHaveText(['Производная'])
})

test('у плана на полке нет ни дат, ни утверждения, ни обмена файлами', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)

  const client = await api(PEOPLE.ivanova)
  const shelf = await client.get('/api/library/templates/?mine=true')
  const template = shelf.body?.[0]
  expect(template, 'посев обязан положить на полку хотя бы один свой шаблон').toBeTruthy()

  await page.goto(`/library/${template.id}`)
  await ready(page)
  // тулбар появляется вместе с деревом: кликать по меню раньше значит
  // нажать и тут же потерять его на перерисовке
  await expect(page.locator('.plan-cards')).toBeVisible()

  // таблица без дат — то же состояние, что у курса без расписания
  await expect(page.locator('ul.plan')).toHaveClass(/no-dates/)
  await expect(page.locator('.plan-approval')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Файл', exact: true })).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Библиотека', exact: true }),
  ).toHaveCount(0)

  // а вот добавление и отмена — на месте: это и есть «тот же экран»
  await expect(
    page.getByRole('button', { name: 'Добавить тему или урок' }),
  ).toBeVisible()
})

test('взять план с полки целиком — сначала показать, что уйдёт', async ({
  page,
  signIn,
}) => {
  /*
   * Единственное действие полки, уносящее чужую работу: «заменить план»
   * стирает набранное и строит заново. Раньше оно делало это молча, и
   * молчание было безопасным ровно потому, что своей работы в шаблоне не
   * было — он был снимком плана.
   */
  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })
  await expect(page.locator('.plan-cards')).toBeVisible()

  await planMenu(page, 'Открыть библиотеку')
  const shelf = page.locator('.modal')
  await shelf.locator('.template-list .name').first().click()
  await shelf.getByRole('radio', { name: 'заменить план' }).click()
  await shelf.getByRole('button', { name: 'Импортировать в курс' }).click()

  // вопрос вместо тихой перезаписи, и в нём сказано, что именно изменится
  await expect(page.getByRole('button', { name: 'Заменить' })).toBeVisible()
})

/**
 * Чужую запись на полке читают, но не правят.
 *
 * Четвёртый вид плана, и до витрины его не существовало вовсе: селект
 * показывал только свои заготовки, а экран полки включал правку всегда —
 * то есть по прямой ссылке на чужую запись человек получал кнопки, которые
 * ответили бы отказом сервера.
 *
 * Право спрашивается у сервера (`can_edit`), а не считается на клиенте, и
 * ведёт себя чужая заготовка так же, как чужой курс: та же таблица, только
 * без кнопок, и строка, объясняющая почему.
 */
test('чужую заготовку с полки читают, но не правят', async ({
  page,
  signIn,
  api,
}) => {
  const author = await api(PEOPLE.ivanova)
  const subjects = await author.get('/api/school/subjects/')
  const subject = subjects.body?.[0]
  expect(subject, 'в школе обязан быть хотя бы один предмет').toBeTruthy()

  const made = await author.post('/api/library/templates/', {
    subject: subject.id,
    grade: 7,
    title: 'Алгебра 7, у коллеги',
    is_published: true,
  })
  expect(made.status, JSON.stringify(made.body)).toBe(201)

  // читает другой человек той же школы
  await signIn(PEOPLE.petrov)
  await page.goto('/plan')
  await ready(page)

  // запись предложена, и предложена в области чужого — а не среди своего
  const theirs = page.locator('.showcase-area', { hasText: 'Планы коллег на полке' })
  await theirs.getByRole('button', { name: /Алгебра 7, у коллеги/ }).click()

  await expect(page).toHaveURL(new RegExp(`/library/${made.body.id}$`))

  // роль названа словом, и вместе с ней — хозяин: спрашивают обычно не
  // «что нельзя», а «чей это план и к кому идти с вопросом»
  await expect(page.locator('.open-role')).toContainText('только чтение')

  // правки нет никакой: панель действий над чужой записью не рисуется вовсе
  await expect(
    page.getByRole('button', { name: 'Добавить тему или урок' }),
  ).toHaveCount(0)
  await expect(page.locator('.plan-tools')).toHaveCount(0)

  // а вместо молчания — строка о том, почему нельзя и как взять себе.
  // Выгрузку она обещать не должна: меню файлов на полке нет вовсе
  const context = page.locator('.plan-context')
  await expect(context).toContainText('читают, но не правят')
  await expect(context).toContainText('Из библиотеки')
})

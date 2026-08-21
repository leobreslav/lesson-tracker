import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Дверь в закрытый каталог: сообщить об опечатке и разобрать сообщение.
 *
 * Через браузер это гонять надо из-за двух вещей, которых не видно в ответе
 * сервера: **принятие делает дело** (текст задачи меняется на месте) и
 * **отказ требует слов** — кнопка не нажимается, пока ответа нет.
 */

test('учитель сообщает об опечатке, администратор принимает — и текст меняется', async ({
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

  // Очередь считаем от того, что есть: посев кладёт в неё свои сообщения, и
  // «На разбор: 1» было бы утверждением про пустую базу, а не про механизм.
  const admin = await api(PEOPLE.admin)
  const было = (await admin.get('/api/bank/proposals/')).body.waiting.length

  await page.getByRole('button', { name: 'Сообщить об ошибке' }).click()
  await page.getByLabel('Что не так или что предлагаете').fill('пропущена запятая')
  await page
    .getByLabel('Как должно быть (впишем сами, если примут)')
    .fill('Окружность, вписанная в прямоугольный треугольник.')
  await page.getByRole('button', { name: 'Отправить' }).click()

  // автор видит своё предложение и его состояние
  await page.goto('/bank/proposals')
  await ready(page)
  await expect(page.locator('.proposal-list')).toContainText('ждёт разбора')

  // администратор школы разбирает: задача школьная, значит его очередь
  await signIn(PEOPLE.admin)
  await page.goto('/bank/proposals')
  await ready(page)
  await expect(page.locator('.page')).toContainText(`На разбор: ${было + 1}`)

  // Кнопка берётся у своей карточки: в очереди лежат и посеянные сообщения.
  const наше = page.locator('.proposal-list li').filter({ hasText: 'пропущена запятая' })
  await наше.getByRole('button', { name: 'Принять и применить' }).click()
  await ready(page)

  // принятие сделало дело, а не пометку
  await page.goto(`/bank/problem/${problem}`)
  await ready(page)
  await expect(page.locator('.panel').first()).toContainText('вписанная в прямоугольный')
})

test('отказ без слов не отправляется', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)
  const found = await teacher.get('/api/bank/search/?text=Окружность')
  await teacher.post('/api/bank/proposals/', {
    kind: 'other',
    problem: found.body.problems[0].id,
    text: 'кажется, тут что-то не то',
  })
  const admin = await api(PEOPLE.admin)
  const было = (await admin.get('/api/bank/proposals/')).body.waiting.length

  await signIn(PEOPLE.admin)
  await page.goto('/bank/proposals')
  await ready(page)

  const наше = page.locator('.proposal-list li').filter({ hasText: 'кажется, тут что-то не то' })
  const decline = наше.getByRole('button', { name: 'Отклонить' })
  await expect(decline).toBeDisabled()

  await наше.getByLabel('Ответ').fill('всё верно, так и задумано')
  await expect(decline).toBeEnabled()
  await decline.click()
  await ready(page)

  await expect(page.locator('.page')).toContainText(`На разбор: ${было - 1}`)
})

test('ученику предложений не видно вовсе', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await expect(page.getByRole('link', { name: 'Задачник' })).toHaveCount(0)
})

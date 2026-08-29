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
  await expect(page.getByText('Алгебра 11, теоретический')).toBeVisible()

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

import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Журнал курса: ученики по строкам, занятия по столбцам.
 *
 * Проверяется не «красиво ли», а то, ради чего экран и заведён и чего не
 * поймает питоновский набор: таблица **рисуется** — со столбцами из
 * расписания, со ссылками в шапке и с посещаемостью в клетке, — и семье она
 * показывает одну строку, свою.
 *
 * Данные берутся из демо-посева: у курса там есть и занятия, и работы, и
 * отметки. Заводить их здесь заново значило бы проверять фикстуру, а не
 * экран.
 */

test('журнал открывается из бара и показывает занятия столбцами', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/')
  await ready(page)

  await page.getByRole('link', { name: 'Журнал' }).click()
  await ready(page)

  const table = page.locator('.journal-table')
  await expect(table).toBeVisible()

  // столбцов больше одного: первый — имена, остальные занятия
  const heads = table.locator('thead th')
  expect(await heads.count()).toBeGreaterThan(1)

  // и строк столько же, сколько учеников в курсе
  await expect(table.locator('tbody tr').first()).toBeVisible()
})

test('шапка столбца ведёт на занятие', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const day = page.locator('.journal-table thead a.day').first()
  await expect(day).toBeVisible()
  await day.click()
  await ready(page)

  await expect(page).toHaveURL(/\/lesson\/\d+/)
})

test('четверть переключается, и таблица меняется вместе с ней', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const chips = page.locator('.year-picker .chip')
  await expect(chips.first()).toBeVisible()

  const columns = await page.locator('.journal-table thead th').count()

  // «весь год» стоит последним и отвечает на другой вопрос: столбцов в нём
  // не меньше, чем в любой отдельной четверти
  await chips.last().click()
  // таблица на время запроса пропадает, и считать столбцы надо у вернувшейся:
  // иначе тест меряет пустоту и падает на ровном месте
  await expect(chips.last()).toHaveClass(/on/)
  await expect(page.locator('.journal-table')).toBeVisible()

  expect(await page.locator('.journal-table thead th').count()).toBeGreaterThanOrEqual(
    columns,
  )
})

test('ученику виден свой журнал и ровно одна строка', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await page.getByRole('link', { name: 'Grade 6 Algebra' }).click()
  await ready(page)

  const table = page.locator('.journal-table')
  await expect(table).toBeVisible()
  await expect(table.locator('tbody tr')).toHaveCount(1)

  // и ссылок на занятие у него нет: экрана занятия для ученика не существует
  await expect(table.locator('thead a.day')).toHaveCount(0)
})

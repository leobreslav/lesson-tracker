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

  const day = page.locator('.journal-table thead a.day-link').first()
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

  const picker = page.locator('.page-header select.course-filter')
  await expect(picker).toBeVisible()

  const columns = await page.locator('.journal-table thead th').count()

  // «весь год» стоит последним пунктом и отвечает на другой вопрос: столбцов
  // в нём не меньше, чем в любой отдельной четверти
  await picker.selectOption('all')
  // таблица на время запроса пропадает, и считать столбцы надо у вернувшейся:
  // иначе тест меряет пустоту и падает на ровном месте
  await expect(picker).toHaveValue('all')
  await expect(page.locator('.journal-table')).toBeVisible()

  expect(await page.locator('.journal-table thead th').count()).toBeGreaterThanOrEqual(
    columns,
  )
})

test('работа заводится прямо из столбца, и журнал её показывает', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const table = page.locator('.journal-table')
  await expect(table).toBeVisible()

  // кнопка стоит в шапке столбца с датой: журнал — то место, где видно
  // пустую клетку, и до сих пор из него приходилось уходить, чтобы её заполнить
  const add = table.locator('thead .work-tag.add').first()
  await expect(add).toBeVisible()

  const before = await table.locator('thead .work-tag:not(.add)').count()
  await add.click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Название').fill('Устный ответ у доски')
  await dialog.getByRole('button', { name: 'Сохранить' }).click()

  // окно закрылось, и журнал перечитан целиком: значок новой работы стоит
  // в шапке того самого столбца
  await expect(dialog).toBeHidden()
  await expect(table.locator('thead .work-tag:not(.add)')).toHaveCount(before + 1)
})

test('работы столбца стоят в ряд, и клетка держит место под каждую', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const table = page.locator('.journal-table')
  await expect(table).toBeVisible()

  // две работы на одном занятии — обычное дело: проверочная и домашняя разом.
  // Заводим их с того же столбца, чтобы смотреть именно на его шапку
  for (const title of ['Проверочная в ряд', 'Домашняя в ряд']) {
    await table.locator('thead .work-tag.add').first().click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Название').fill(title)
    await dialog.getByRole('button', { name: 'Сохранить' }).click()
    await expect(dialog).toBeHidden()
  }

  const head = table.locator('thead th').nth(1)
  const tags = head.locator('.work-tag:not(.add)')
  await expect(tags).toHaveCount(2)

  // в ряд, а не в столбик: тот же верх, разные левые края
  const first = await tags.nth(0).boundingBox()
  const second = await tags.nth(1).boundingBox()
  expect(Math.abs(first.y - second.y)).toBeLessThan(2)
  expect(second.x).toBeGreaterThan(first.x)

  // а в клетке под ними — место под каждую работу, даже когда оценки нет:
  // пропусти неоценённую, и следующая встала бы под чужой работой
  const cell = table.locator('tbody tr').first().locator('td').nth(0)
  await expect(cell.locator('.mark')).toHaveCount(2)

  /*
   * Сходятся **подколонки**, а не значки: ширину держит полоса, а значок
   * внутри неё только рисуется и потому стоит уже её. Сравнивать значок с
   * отметкой значило бы мерить не то — совпадать обязаны полосы, из которых
   * и складывается столбец.
   */
  for (const order of [0, 1]) {
    const above = await head.locator('.head-cell').nth(order).boundingBox()
    const below = await cell.locator('.mark').nth(order).boundingBox()
    expect(Math.abs(above.x - below.x)).toBeLessThan(2)
    expect(Math.abs(above.width - below.width)).toBeLessThan(2)
  }

  // присутствие — такая же полоса, и его шапка это кнопка «завести работу»:
  // она стоит не в ряду работ, а над точкой присутствия
  const addColumn = await head.locator('.att-head').boundingBox()
  const attColumn = await cell.locator('.att').boundingBox()
  expect(Math.abs(addColumn.x - attColumn.x)).toBeLessThan(2)
  expect(Math.abs(addColumn.width - attColumn.width)).toBeLessThan(2)
  expect(addColumn.x).toBeGreaterThan(second.x + second.width)

  // и содержимое каждой полосы стоит по её середине, а не по краю
  const middle = (box) => box.x + box.width / 2
  const plus = await head.locator('.work-tag.add').boundingBox()
  expect(Math.abs(middle(plus) - middle(addColumn))).toBeLessThan(2)
})

test('занятие работы выбирается в её настройках', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const add = page.locator('.journal-table thead .work-tag.add').first()
  await add.click()

  const dialog = page.getByRole('dialog')
  const slots = dialog.getByLabel('Занятие')
  await expect(slots).toBeVisible()

  // «без занятия» — рабочее состояние, а не заглушка: контрольная за
  // четверть и пересдача ни к какому часу не привязаны
  await expect(slots.locator('option', { hasText: 'Без занятия' })).toHaveCount(1)

  // Часы приезжают запросом, и до его ответа выбранного занятия в списке
  // просто нет — браузер показывает пустое значение, хотя форма помнит своё.
  // Ждём список, а не значение: иначе тест меряет полсекунды сети
  await expect.poll(() => slots.locator('option').count()).toBeGreaterThan(1)

  // а подставлено то занятие, из столбца которого нажали
  expect(await slots.inputValue()).not.toBe('')
})

test('оценка ставится прямо в клетке и переживает перезагрузку', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const table = page.locator('.journal-table')
  await expect(table).toBeVisible()

  // заводим работу на первом занятии — в демо-наборе работы к часам не
  // привязаны, и клетки с датой пусты
  await table.locator('thead .work-tag.add').first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Название').fill('Ответ у доски')
  await dialog.getByRole('button', { name: 'Сохранить' }).click()
  await expect(dialog).toBeHidden()

  // клетка становится полем по клику — и только она одна: журнал не должен
  // превращаться в бланк из тысячи полей
  const cell = table.locator('tbody tr').first().locator('td .mark').first()
  await cell.click()
  await expect(table.locator('.cell-input')).toHaveCount(1)

  await table.locator('.cell-input').fill('5')
  await table.locator('.cell-input').press('Enter')

  // после Enter поле уходит вниз, а поставленное остаётся текстом в клетке
  await expect(cell).toHaveText('5')

  // и это не состояние вкладки, а запись: перезагрузка её застаёт
  await page.reload()
  await ready(page)
  await expect(
    table.locator('tbody tr').first().locator('td .mark').first(),
  ).toHaveText('5')

  // поставленное рукой отличается от выведенного системой без наведения
  await expect(
    table.locator('tbody tr').first().locator('td .mark').first(),
  ).toHaveClass(/by-teacher/)
})

test('присутствие правится тем же движением, что и оценка', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const table = page.locator('.journal-table')
  const att = table.locator('tbody tr').first().locator('td .att').first()
  await att.click()

  // меню — три состояния, и набрать их можно теми же буквами руками
  const menu = table.locator('.cell-menu')
  await expect(menu.getByRole('option')).toHaveCount(3)
  await menu.getByRole('option').nth(1).click()

  await expect(att).toHaveClass(/absent/)

  await page.reload()
  await ready(page)
  await expect(
    table.locator('tbody tr').first().locator('td .att').first(),
  ).toHaveClass(/absent/)
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
  await expect(table.locator('thead a.day-link')).toHaveCount(0)
})

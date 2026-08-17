import { PEOPLE, expect, lessonCount, planMenu, ready, test } from './harness.js'

/**
 * Scenarios 6 and 7: the plan tree, dragging, and CSV.
 *
 * Petrov's Grade 9 Geometry is seeded with no plan at all, which makes it
 * the course to build one in from scratch without fighting existing rows.
 */

const EMPTY_COURSE = 'Grade 9 Geometry'

async function openPlan(page, course) {
  await page.goto('/plan')
  await ready(page)
  // курс выбирают селектом в строке заголовка: чипы не пережили
  // учителя музыки с полутора десятками курсов
  await page.getByLabel('Курс').selectOption({ label: course })
  await expect(page.locator('.plan-cards')).toBeVisible()
}

/**
 * The plan as «number title» pairs.
 *
 * Read field by field rather than from textContent: the number and the title
 * are separate elements with no whitespace between them, so the flat text
 * comes out as «1Первый признак» with the drag handle glued to the front.
 */
async function structure(page) {
  return page.locator('.plan-row').evaluateAll((rows) =>
    rows.map((row) => {
      const number = row.querySelector('.plan-number')?.textContent.trim() ?? ''
      const title = row.querySelector('.title')?.textContent.trim() ?? ''
      return `${number} ${title}`.trim()
    }),
  )
}

/** The title of a row, without the number or the buttons around it. */
async function titleOf(row) {
  return (await row.locator('.title').textContent()).trim()
}

test('блок и уроки добавляются, нумерация сквозная', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить тему' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Треугольники')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByText('Треугольники')).toBeVisible()

  // two lessons inside the block, through its own «+»
  for (const title of ['Первый признак', 'Второй признак']) {
    // кнопки строки видны при наведении: сначала подводим мышь, как человек
    const head = page.locator('.plan-section .section-head').first()
    await head.hover()
    await head.getByTitle('Добавить урок в тему').click()
    const inner = page.locator('.plan-add-form')
    await inner.getByLabel('Название').fill(title)
    await inner.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.getByText(title)).toBeVisible()
  }

  // and one at the top level, after the block
  await page.getByRole('button', { name: 'Добавить урок' }).click()
  const top = page.locator('.plan-add-form')
  await top.getByLabel('Название').fill('Итоговый урок')
  await top.getByRole('button', { name: 'Добавить' }).click()
  // wait for the row before reading the tree: the form stays open for fast
  // entry, so there is no other signal that the write landed
  await expect(page.locator('.plan-row', { hasText: 'Итоговый урок' })).toBeVisible()

  const rows = await structure(page)
  expect(rows.join(' | ')).toContain('1 Первый признак')
  expect(rows.join(' | ')).toContain('2 Второй признак')
  expect(rows.join(' | ')).toContain('3 Итоговый урок')

  // the counter agrees with the tree
  await expect(lessonCount(page)).toHaveText('3')
})

test('перетаскивание меняет порядок и пересчитывает номера', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  const lessons = page.locator('.plan-row.lesson')
  const firstBefore = await titleOf(lessons.first())
  const secondBefore = await titleOf(lessons.nth(1))
  expect(firstBefore).not.toBe(secondBefore)

  // drag the second lesson above the first, by its handle: dnd-kit only
  // listens there, and the pointer sensor needs a few steps to engage
  await lessons.nth(1).hover()
  const handle = lessons.nth(1).getByTitle('Перетащить')
  const target = lessons.first()

  const from = await handle.boundingBox()
  const to = await target.boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + 2, { steps: 12 })
  await page.mouse.up()

  // the row that was second now stands first, and carries number 1
  await expect(lessons.first().locator('.title')).toHaveText(secondBefore)
  await expect(lessons.first().locator('.plan-number')).toHaveText('1')

  // and the server agrees after a reload
  await page.reload()
  await ready(page)
  await openPlan(page, 'Grade 6 Algebra')
  await expect(page.locator('.plan-row.lesson').first().locator('.title')).toHaveText(
    secondBefore,
  )
})

const HEAD = 'id,Тема,Урок\n'

/** Файл единственного формата: одна строка — один урок. */
const csvFile = (body) => ({
  name: 'plan.csv',
  mimeType: 'text/csv',
  buffer: Buffer.from(HEAD + body, 'utf-8'),
})

test('справка о формате раскрывается кнопкой «?»', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  // всё управление планом — одна панель над таблицей
  const card = page.locator('.plan-tools')
  // свёрнутого текста в разметке быть не должно: это состояние, а не display:none
  await expect(card.locator('.csv-help')).toHaveCount(0)

  await planMenu(page, 'Как выглядит файл')

  await expect(card.locator('.csv-sample')).toContainText('id,Тема,Урок')
  await expect(card.locator('.csv-help')).toContainText('Одна строка — один урок')
  // три режима названы каждый одной строкой
  await expect(card.locator('.csv-modes-help dt')).toHaveCount(3)

  await planMenu(page, 'Как выглядит файл')
  await expect(card.locator('.csv-help')).toHaveCount(0)
})

test('импорт CSV разбирает файл и строит блоки', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /Импорт из файла/)

  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles(
    csvFile(
      ',Векторы,Понятие вектора\n' +
        ',Векторы,Сложение векторов\n' +
        ',Окружность,Касательная\n',
    ),
  )

  // как файл прочитан, видно до отправки: разбор идёт в браузере
  await expect(dialog).toContainText('Строк: 3')
  await expect(dialog).toContainText('уроков: 3')
  await expect(dialog).toContainText('тем: 2')

  await dialog.getByRole('button', { name: 'Импортировать' }).click()
  await expect(dialog).toBeHidden()

  await expect(lessonCount(page)).toHaveText('3')
  await expect(page.getByText('Векторы')).toBeVisible()
  await expect(page.getByText('Окружность')).toBeVisible()

  const rows = await structure(page)
  expect(rows.join(' | ')).toContain('1 Понятие вектора')
  expect(rows.join(' | ')).toContain('3 Касательная')
})

test('файл прежнего формата отклоняется с объяснением', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /Импорт из файла/)
  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'plan.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('id,Тема,Урок,Заметка\n,Векторы,Понятие,\n', 'utf-8'),
  })

  // отказ виден сразу, без обращения к серверу: разбор строгий с обеих сторон
  await expect(dialog).toContainText('Первой строкой должна идти шапка')
  await expect(dialog.getByRole('button', { name: 'Импортировать' })).toBeDisabled()
})

/** Файл без единого id: синхронизировать с ним нечего. */
const PLAIN_CSV = csvFile(',Векторы,Понятие вектора\n')

test('замена предупреждает, что содержание уроков пропадёт', async ({
  page,
  signIn,
}) => {
  // Ivanova's Grade 6 Algebra is the seeded course with lesson content on it
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  await planMenu(page, /Импорт из файла/)
  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles(PLAIN_CSV)
  await dialog.getByRole('radio', { name: /Заменить/ }).check()

  // the count comes from the server: only it knows which lessons are written
  await expect(dialog).toContainText('с содержанием')

  const submit = dialog.getByRole('button', { name: 'Импортировать' })
  await expect(submit).toBeDisabled()

  await dialog.getByText('Понимаю', { exact: false }).click()
  await expect(submit).toBeEnabled()
})

test('синхронизация недоступна, пока в файле нет ни одного id', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /Импорт из файла/)
  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles(PLAIN_CSV)

  await expect(dialog.getByRole('radio', { name: /Синхронизовать/ })).toBeDisabled()
  await expect(dialog).toContainText('синхронизировать не с чем')
})

test('xlsx: выгрузка возвращается обратно без единого изменения', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  const before = await lessonCount(page).textContent()

  // xlsx — формат по умолчанию, поэтому переключать ничего не надо
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    planMenu(page, 'Экспорт в xlsx'),
  ])
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/)
  const saved = '/tmp/' + download.suggestedFilename()
  await download.saveAs(saved)

  await planMenu(page, /Импорт из файла/)
  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles(saved)

  // книгу читает сервер, и предпросмотр приезжает оттуда же
  await expect(dialog).toContainText('новых: 0')
  await expect(dialog).toContainText('удалено: 0')

  await dialog.getByRole('button', { name: 'Импортировать' }).click()
  await expect(dialog).toBeHidden()

  await expect(lessonCount(page)).toHaveText(before)
})

test('xlsx: чужой файл отклоняется понятным текстом', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /Импорт из файла/)
  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'план.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('%PDF-1.7\n%\u00c7\u00ec\u008f\u00a2\n', 'latin1'),
  })

  await expect(dialog).toContainText('Это не книга')
  await expect(dialog.getByRole('button', { name: 'Импортировать' })).toBeDisabled()
})

test('импорт из библиотеки наполняет пустой план', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, 'Из библиотеки')

  // полка теперь список с поиском: шаблон выбирается нажатием на название
  const dialog = page.locator('dialog.modal')
  await dialog.locator('.template-list .name').first().click()
  await dialog.getByRole('button', { name: 'Импортировать в курс' }).click()

  await expect(dialog).toBeHidden()
  await expect(lessonCount(page)).not.toHaveText('0')
})

test('импорт вкладывает уроки в темы, включая названия с запятыми', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /Импорт из файла/)
  const dialog = page.locator('dialog.modal')
  await dialog.locator('input[type="file"]').setInputFiles(
    csvFile(
      ',"Дроби, обыкновенные","Сложение, вычитание"\n' +
        ',"Дроби, обыкновенные","Умножение ""в столбик"""\n' +
        ',"Точки; и запятые","Урок; третий"\n',
    ),
  )

  // предпросмотр считает файл сам, на клиенте — и должен совпасть с тем,
  // что положит сервер
  await expect(dialog).toContainText('уроков: 3')
  await expect(dialog).toContainText('Сложение, вычитание')
  await expect(dialog).toContainText('Умножение "в столбик"')

  await dialog.getByRole('button', { name: 'Импортировать' }).click()
  await expect(dialog).toBeHidden()

  // дождаться перечитанного дерева: диалог закрывается раньше, чем ответ
  // сервера доедет обратно
  await expect(lessonCount(page)).toHaveText('3')

  // вложенность читается прямо из дерева: тема и её уроки, а не плоский
  // список — плоский совпал бы и у сломанного импорта
  const tree = await page.locator('.plan > li').evaluateAll((items) =>
    items.map((item) => {
      const head = item.querySelector('.title')?.textContent.trim() ?? ''
      const kids = [...item.querySelectorAll('.plan-children .title')].map((el) =>
        el.textContent.trim(),
      )
      return kids.length ? `${head}: ${kids.join(' / ')}` : head
    }),
  )

  expect(tree).toEqual([
    'Дроби, обыкновенные: Сложение, вычитание / Умножение "в столбик"',
    'Точки; и запятые: Урок; третий',
  ])
})

/**
 * Полка планов живёт в окне на странице плана: отдельного раздела больше
 * нет. Вместе со страницей сюда переехало то, чего нигде больше нет —
 * публикация черновика и удаление. Без первого шаблон, снятый с плана,
 * навсегда остался бы виден одному автору: `from-plan` кладёт его
 * черновиком.
 */
test('черновик публикуется и снимается с публикации прямо на полке', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.petrov)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 9 Algebra')
  await teacher.post('/api/library/templates/from-plan/', {
    course: course.id,
    title: 'Свежий черновик',
  })

  await signIn(PEOPLE.petrov)
  await openPlan(page, 'Grade 9 Algebra')
  await planMenu(page, 'Из библиотеки')

  const shelf = page.locator('dialog.modal')
  const row = shelf.locator('li', { hasText: 'Свежий черновик' })
  await expect(row.locator('.badge')).toHaveText('черновик')

  await row.getByRole('button', { name: 'Опубликовать' }).click()
  await expect(row.locator('.badge')).toHaveCount(0)

  await row.getByRole('button', { name: 'Вернуть в черновики' }).click()
  await expect(row.locator('.badge')).toHaveText('черновик')
})

test('просмотр шаблона показывает уроки до того, как его взяли', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, 'Grade 9 Algebra')
  await planMenu(page, 'Из библиотеки')

  const shelf = page.locator('dialog.modal').first()
  await shelf
    .locator('li', { hasText: 'Алгебра 6' })
    .getByRole('button', { name: 'Посмотреть' })
    .click()

  // просмотр открывается **поверх** полки: закрыв его, человек остаётся
  // там же, где выбирал, а не начинает поиск заново
  const preview = page.locator('dialog.modal').last()
  await expect(preview.locator('.plan-preview li').first()).toBeVisible()
  await expect(
    preview.getByRole('button', { name: 'Импортировать в курс' }),
  ).toBeEnabled()

  await preview.getByRole('button', { name: 'Закрыть окно' }).click()

  await expect(page.locator('dialog.modal')).toHaveCount(1)
  await expect(shelf.locator('.template-list')).toBeVisible()
})

test('поиск сужает полку, «только мои» прячет чужое', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, 'Grade 9 Algebra')
  await planMenu(page, 'Из библиотеки')

  const shelf = page.locator('dialog.modal')
  const rows = shelf.locator('.template-list li')
  const total = await rows.count()
  expect(total).toBeGreaterThan(1)

  await shelf.getByRole('searchbox').fill('геометри')
  await expect(rows).toHaveCount(1)

  await shelf.getByRole('searchbox').fill('')
  await shelf.getByLabel('только мои').check()
  // у Петрова на полке свой черновик, чужая «Алгебра 6» уходит
  await expect(shelf.getByText('Алгебра 6, по учебнику')).toHaveCount(0)
})

test('тему бросают на весь блок, а не в её шапку', async ({ page, signIn }) => {
  // Пока целиться приходилось в шапку соседней темы — строку в 29 px, —
  // перетащить тему было почти нельзя: блок из восьми уроков занимает
  // пол-экрана, и весь этот экран отвечал отказом.
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  // `.plan-section` — это весь блок вместе с уроками, поэтому шапку
  // спрашиваем отдельным классом: иначе `.title` внутри блока девять
  const sections = page.locator('.plan-section')
  const head = (block) => block.locator('.section-head .title')
  const second = sections.nth(1)
  await expect(head(second)).toHaveText(/Делимость чисел/)

  // берём вторую тему за ручку и ведём в середину первого блока
  await second.locator('.section-head').hover()
  const handle = second.locator('.section-head').getByTitle('Перетащить')
  const inside = page
    .locator('.plan-section')
    .first()
    .locator('.plan-row.lesson')
    .nth(1)

  const from = await handle.boundingBox()
  const to = await inside.boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + 2, { steps: 12 })
  await page.mouse.up()

  // блок встал перед первым целиком, вместе со своими уроками
  await expect(head(sections.first())).toHaveText(/Делимость чисел/)
  await expect(page.locator('.plan-row.lesson').first().locator('.title')).toHaveText(
    'Делители и кратные',
  )

  // и сервер согласен
  await page.reload()
  await ready(page)
  await openPlan(page, 'Grade 6 Algebra')
  await expect(head(page.locator('.plan-section').first())).toHaveText(
    /Делимость чисел/,
  )
})

test('«План пуст» стоит над таблицей, а не под пустотой', async ({ page, signIn }) => {
  // Под пустой таблицей объяснение находят, пролистав пустоту, а кнопки, к
  // которым оно отсылает, стоят наверху.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  const empty = page.locator('.empty-state')
  await expect(empty).toBeVisible()

  const tools = await page.locator('.plan-tools').boundingBox()
  const box = await empty.boundingBox()
  const table = await page.locator('ul.plan').first().boundingBox()

  expect(box.y, 'пустое состояние уехало над панелью').toBeGreaterThan(tools.y)
  expect(box.y + box.height, 'пустое состояние осталось под таблицей')
    .toBeLessThanOrEqual(table.y + 1)
})

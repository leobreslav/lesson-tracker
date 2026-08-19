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

  // два урока внутри блока, через её «+»: он заводит первый урок темы, а
  // форма после него переезжает за созданную строку — дальше вводим подряд
  const head = page.locator('.plan-section .section-head').first()
  // кнопки строки видны при наведении: сначала подводим мышь, как человек
  await head.hover()
  await head.getByTitle('Добавить урок в тему').click()
  const inner = page.locator('.plan-add-form')
  for (const title of ['Первый признак', 'Второй признак']) {
    await inner.getByLabel('Название').fill(title)
    await inner.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.getByText(title)).toBeVisible()
  }
  await page.keyboard.press('Escape')

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

test('форма вставки не закрывается, а переезжает за созданную строку', async ({
  page,
  signIn,
}) => {
  // Раньше «вставить после» закрывалась после Enter, а «добавить в конец» —
  // нет, и снаружи это выглядело как две разные формы: один плюсик поле
  // оставляет, соседний убирает. Закрытие лечило настоящую беду — второй
  // урок вставал бы перед первым, — но лечится она переездом якоря.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить урок' }).click()
  const start = page.locator('.plan-add-form')
  await start.getByLabel('Название').fill('Первый')
  await start.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Первый' })).toBeVisible()
  await start.getByRole('button', { name: 'Закрыть' }).click()

  const anchor = page.locator('.plan-row', { hasText: 'Первый' })
  await anchor.hover()
  await anchor.getByTitle('Вставить после').click()

  const form = page.locator('.plan-add-form')
  for (const title of ['Второй', 'Третий']) {
    await form.getByLabel('Название').fill(title)
    await form.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
    // форма осталась на месте и пустой — можно вводить дальше
    await expect(form).toBeVisible()
    await expect(form.getByLabel('Название')).toHaveValue('')
  }

  // якорь переехал: уроки идут по порядку ввода, а не задом наперёд
  const rows = await structure(page)
  expect(rows.join(' | ')).toContain('1 Первый')
  expect(rows.join(' | ')).toContain('2 Второй')
  expect(rows.join(' | ')).toContain('3 Третий')

  // пустое поле — «Закрыть», набранное — «Готово»: кнопка называет то, что
  // сделает, а не выбрасывает набранное под именем «Готово»
  await expect(form.getByRole('button', { name: 'Закрыть' })).toBeVisible()
  await form.getByLabel('Название').fill('Четвёртый')
  await form.getByRole('button', { name: 'Готово' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Четвёртый' })).toBeVisible()
  await expect(page.locator('.plan-add-form')).toHaveCount(0)
})

test('тумблер переключается нажатием в любое место', async ({ page, signIn }) => {
  // Радиокнопки отзываются только на чужой сегмент: клик по выбранному
  // ничего не меняет и события не поднимает. Для группы из трёх вариантов
  // это верно, а тумблер выглядит одним органом управления, и нажатие по
  // нему значит «переключи», а не «выбери ровно это».
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить урок' }).click()
  const start = page.locator('.plan-add-form')
  await start.getByLabel('Название').fill('Первый')
  await start.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Первый' })).toBeVisible()
  await page.keyboard.press('Escape')

  const anchor = page.locator('.plan-row', { hasText: 'Первый' })
  await anchor.hover()
  await anchor.getByTitle('Вставить после').click()

  const form = page.locator('.plan-add-form')
  const lesson = form.getByRole('radio', { name: 'Урок', exact: true })
  const section = form.getByRole('radio', { name: 'Тема', exact: true })
  await expect(lesson).toBeChecked()

  // нажатие по уже выбранному сегменту уводит к соседнему
  await lesson.click()
  await expect(section).toBeChecked()
  await section.click()
  await expect(lesson).toBeChecked()

  // и по рамке между сегментами — тоже: это один орган управления
  const box = await form.locator('.switch').boundingBox()
  await page.mouse.click(box.x + box.width / 2, box.y + 1)
  await expect(section).toBeChecked()
})

test('пустая форма закрывается кликом мимо, а набранная — нет', async ({
  page,
  signIn,
}) => {
  // Форма остаётся открытой после добавления — ради ввода подряд. Но
  // человек уходит к другому делу, и пустая форма продолжает висеть посреди
  // плана, ожидая нажатия, о котором он уже не помнит. Ждать ей нечего.
  // Набранное при этом кликом мимо не выбрасывается: это незаконченная
  // работа, и уносить её молча нельзя.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить урок' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Первый')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Первый' })).toBeVisible()

  // форма пуста и ждёт — клик по таблице её убирает
  await expect(form).toBeVisible()
  await page.locator('h1').click()
  await expect(page.locator('.plan-add-form')).toHaveCount(0)

  // а с набранным названием остаётся: текст дороже порядка на экране
  await page.getByRole('button', { name: 'Добавить урок' }).click()
  await page.locator('.plan-add-form').getByLabel('Название').fill('Черновик')
  await page.locator('h1').click()
  await expect(page.locator('.plan-add-form')).toBeVisible()
  await expect(page.locator('.plan-add-form').getByLabel('Название')).toHaveValue(
    'Черновик',
  )
})

test('Escape закрывает форму, где бы в ней ни стоял фокус', async ({
  page,
  signIn,
}) => {
  // Форма стала оставаться открытой после добавления, и Escape из
  // запасного выхода превратился в основной. Висел он на поле, а рядом с
  // ним теперь тумблер и две кнопки: нажал не туда — и Escape молча
  // перестал работать, что читается как поломка, а не как правило.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить урок' }).click()
  const start = page.locator('.plan-add-form')
  await start.getByLabel('Название').fill('Первый')
  await start.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Первый' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('.plan-add-form')).toHaveCount(0)

  const anchor = page.locator('.plan-row', { hasText: 'Первый' })
  await anchor.hover()
  await anchor.getByTitle('Вставить после').click()

  // фокус на тумблере — не в поле
  const form = page.locator('.plan-add-form')
  await form.getByRole('radio', { name: 'Тема', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('.plan-add-form')).toHaveCount(0)

  // и с кнопки: до неё доходят Tab'ом, а закрывать надо оттуда же
  await anchor.hover()
  await anchor.getByTitle('Вставить после').click()
  await page.locator('.plan-add-form').getByLabel('Название').fill('Черновик')
  await page.locator('.plan-add-form').getByRole('button', { name: 'Готово' }).focus()
  await page.keyboard.press('Escape')
  await expect(page.locator('.plan-add-form')).toHaveCount(0)
  // Escape — это отказ: набранное не создаётся
  await expect(page.locator('.plan-row', { hasText: 'Черновик' })).toHaveCount(0)
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

  await planMenu(page, /^Импорт/)

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

  await planMenu(page, /^Импорт/)
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

  await planMenu(page, /^Импорт/)
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

  await planMenu(page, /^Импорт/)
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

  await planMenu(page, /^Импорт/)
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

  await planMenu(page, /^Импорт/)
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

  await planMenu(page, 'Открыть библиотеку')

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

  await planMenu(page, /^Импорт/)
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
  await planMenu(page, 'Открыть библиотеку')

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
  await planMenu(page, 'Открыть библиотеку')

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
  await planMenu(page, 'Открыть библиотеку')

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

/** Вставка как из Excel: браузер кладёт в буфер TSV. */
const pasteInto = (page, selector, text) =>
  page.evaluate(
    ([where, value]) => {
      const target = document.querySelector(where)
      target.focus()
      const data = new DataTransfer()
      data.setData('text/plain', value)
      target.dispatchEvent(
        new ClipboardEvent('paste', { clipboardData: data, bubbles: true }),
      )
    },
    [selector, text],
  )

test('план вставляют из таблицы, а не файлом', async ({ page, signIn }) => {
  // Скопировали кусок листа в Excel — и вставили. Колонки раскладываются
  // сами, шапку копировать не обязательно, и видно это сразу: сетка и есть
  // предпросмотр.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /^Импорт/)
  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('button', { name: 'Вставка' }).click()

  await pasteInto(
    page,
    '.paste-grid td input',
    'id\tТема\tУрок\n' +
      '\tНачальные сведения\tТочки, прямые, отрезки\n' +
      '\tНачальные сведения\tЛуч и угол\n' +
      '\tТреугольники\tПервый признак равенства\n',
  )

  // шапка узнана и в данные не попала: три строки, а не четыре
  await expect(dialog.locator('.paste-grid tbody tr')).toHaveCount(3)
  await expect(dialog.locator('.paste-grid tbody tr').first().locator('input').nth(1))
    .toHaveValue('Начальные сведения')

  // числа считает сервер, теми же правилами, что для файла
  await expect(dialog).toContainText('уроков: 3')
  await expect(dialog).toContainText('тем: 2')
  // синхронизировать не с чем — режим переключился сам
  await expect(dialog.getByRole('radio', { name: /Добавить/ })).toBeChecked()

  await dialog.getByRole('button', { name: 'Импортировать' }).click()
  await expect(dialog).toBeHidden()

  await expect(lessonCount(page)).toHaveText('3')
  const rows = await structure(page)
  expect(rows.join(' | ')).toContain('Начальные сведения')
  expect(rows.join(' | ')).toContain('3 Первый признак равенства')
})

test('вставка идёт от выбранной ячейки: таблица без столбца id', async ({
  page,
  signIn,
}) => {
  // Своя таблица из школьного шаблона: две колонки, id в ней нет и быть не
  // может. Никакого «назначения колонок» для этого не нужно — встали в
  // «Тему» и вставили туда, ровно как в Excel.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /^Импорт/)
  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('button', { name: 'Вставка' }).click()

  await pasteInto(
    page,
    '.paste-grid tbody tr:first-child td:nth-child(2) input',
    'Векторы\tПонятие вектора\nВекторы\tСложение векторов\n',
  )

  await expect(dialog).toContainText('уроков: 2')
  await expect(dialog).toContainText('тем: 1')

  await dialog.getByRole('button', { name: 'Импортировать' }).click()
  await expect(dialog).toBeHidden()
  await expect(lessonCount(page)).toHaveText('2')
})

test('в сетке вставки выделяют кусок мышью и стирают его Delete', async ({
  page,
  signIn,
}) => {
  // Единственное, что взято у настоящих таблиц: стереть кусок целиком.
  // Иначе это щелчки по ячейкам по одной.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /^Импорт/)
  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('button', { name: 'Вставка' }).click()

  await pasteInto(
    page,
    '.paste-grid td input',
    '\tВекторы\tПонятие\n\tВекторы\tСложение\n\tОкружность\tКасательная\n',
  )
  await expect(dialog.locator('.paste-grid tbody tr')).toHaveCount(3)

  // крестик стоит в самом конце строки, а не посреди широкого столбца
  const drop = await dialog.locator('.paste-grid tbody tr:first-child td.drop').boundingBox()
  const table = await dialog.locator('.paste-grid table').boundingBox()
  expect(drop.width).toBeLessThan(60)
  expect(Math.round(drop.x + drop.width)).toBe(Math.round(table.x + table.width))

  // тянем от «Темы» первой строки до «Урока» второй
  const cell = (row, column) =>
    dialog.locator(`.paste-grid tbody tr:nth-child(${row}) td:nth-child(${column})`)
  const from = await cell(1, 2).boundingBox()
  const to = await cell(2, 3).boundingBox()

  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 8 })
  await page.mouse.up()

  await expect(dialog.locator('.paste-grid td.picked')).toHaveCount(4)

  await page.keyboard.press('Delete')

  await expect(cell(1, 2).locator('input')).toHaveValue('')
  await expect(cell(2, 3).locator('input')).toHaveValue('')
  // третья строка не тронута: стёрли ровно выделенное
  await expect(cell(3, 3).locator('input')).toHaveValue('Касательная')
})

test('кусок выделяют и с клавиатуры: Shift со стрелками', async ({ page, signIn }) => {
  // Мышь есть не у всех и не всегда, а главное — после протягивания фокус
  // должен остаться в таблице: пока он уходил в body, Delete не долетал до
  // обработчика вовсе, и кнопка «не работала».
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /^Импорт/)
  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('button', { name: 'Вставка' }).click()

  await pasteInto(
    page,
    '.paste-grid td input',
    '\tВекторы\tПонятие\n\tВекторы\tСложение\n\tОкружность\tКасательная\n',
  )

  const cell = (row, column) =>
    dialog.locator(`.paste-grid tbody tr:nth-child(${row}) td:nth-child(${column})`)

  // встаём в «Тему» первой строки и тянем вправо и вниз
  await cell(1, 2).locator('input').click()
  await page.keyboard.press('Shift+ArrowRight')
  await page.keyboard.press('Shift+ArrowDown')
  await expect(dialog.locator('.paste-grid td.picked')).toHaveCount(4)

  await page.keyboard.press('Delete')

  await expect(cell(1, 3).locator('input')).toHaveValue('')
  await expect(cell(2, 2).locator('input')).toHaveValue('')
  await expect(cell(3, 2).locator('input')).toHaveValue('Окружность')

  // Escape снимает выделение, и Delete больше ничего не стирает
  await page.keyboard.press('Escape')
  await expect(dialog.locator('.paste-grid td.picked')).toHaveCount(0)
})

test('длинная вставка: сетка едет за выделением, а кнопка остаётся на виду', async ({
  page,
  signIn,
}) => {
  // Строки, выехавшие под нижний край, mouseenter не получают, а Shift со
  // стрелкой уводил подвижный конец в невидимое. И «Добавить строку»
  // пряталась вместе с таблицей, потому что скроллилась вместе с ней.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await planMenu(page, /^Импорт/)
  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('button', { name: 'Вставка' }).click()

  const rows = Array.from({ length: 40 }, (_, index) => `\tТема\tУрок ${index + 1}`)
  await pasteInto(page, '.paste-grid td input', `${rows.join('\n')}\n`)
  await expect(dialog.locator('.paste-grid tbody tr')).toHaveCount(40)

  // кнопка не уехала под нижний край таблицы
  const add = dialog.getByRole('button', { name: 'Добавить строку' })
  await expect(add).toBeInViewport()

  const box = dialog.locator('.paste-scroll')
  expect(await box.evaluate((node) => node.scrollTop)).toBe(0)

  // тянем Shift со стрелками вниз: таблица должна поехать следом
  await dialog.locator('.paste-grid tbody tr:first-child td:nth-child(3) input').click()
  for (let step = 0; step < 20; step += 1) {
    await page.keyboard.press('Shift+ArrowDown')
  }

  expect(await box.evaluate((node) => node.scrollTop)).toBeGreaterThan(0)
  await expect(dialog.locator('.paste-grid td.picked')).toHaveCount(21)
  await expect(add).toBeInViewport()
})

test('«+» в шапке темы заводит её первый урок, а не последний', async ({
  page,
  signIn,
}) => {
  // «+» везде значит одно: вставить сразу под этой строкой. У шапки темы это
  // первый урок — а до правки строка уезжала в конец блока, и вставить урок
  // в начало непустой темы было нельзя вовсе, только перетаскиванием через
  // весь блок.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить тему' }).click()
  const start = page.locator('.plan-add-form')
  await start.getByLabel('Название').fill('Треугольники')
  await start.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByText('Треугольники')).toBeVisible()
  await page.keyboard.press('Escape')

  const head = page.locator('.plan-section .section-head').first()
  for (const title of ['Второй признак', 'Третий признак']) {
    await head.hover()
    await head.getByTitle('Добавить урок в тему').click()
    const form = page.locator('.plan-add-form')
    await form.getByLabel('Название').fill(title)
    await form.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
    await page.keyboard.press('Escape')
  }

  // каждый следующий вставал первым: порядок обратный вводу
  const rows = await structure(page)
  expect(rows.join(' | ')).toContain('1 Третий признак')
  expect(rows.join(' | ')).toContain('2 Второй признак')

  // а ввод подряд идёт по порядку: форма после первой строки переезжает за неё
  await head.hover()
  await head.getByTitle('Добавить урок в тему').click()
  const form = page.locator('.plan-add-form')
  for (const title of ['Первый признак', 'Признак равенства']) {
    await form.getByLabel('Название').fill(title)
    await form.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
  }
  await page.keyboard.press('Escape')

  const after = await structure(page)
  expect(after.join(' | ')).toContain('1 Первый признак')
  expect(after.join(' | ')).toContain('2 Признак равенства')
  expect(after.join(' | ')).toContain('3 Третий признак')

  // переключателя «Урок · Тема» тут нет: тема в тему не кладётся
  await head.hover()
  await head.getByTitle('Добавить урок в тему').click()
  await expect(
    page.locator('.plan-add-form').getByRole('radio', { name: 'Тема', exact: true }),
  ).toHaveCount(0)
})

test('тема заводится в середине плана и режет блок надвое', async ({
  page,
  signIn,
}) => {
  // Тема появлялась только в конце плана и ехала наверх перетаскиванием
  // через десяток строк. Поводов завести её в середине два, и оба обычные:
  // начинается новый раздел, и надо разрезать разросшуюся тему.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить тему' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Треугольники')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByText('Треугольники')).toBeVisible()

  const head = page.locator('.plan-section .section-head').first()
  await head.hover()
  await head.getByTitle('Добавить урок в тему').click()
  const inner = page.locator('.plan-add-form')
  for (const title of ['Первый признак', 'Второй признак', 'Третий признак']) {
    await inner.getByLabel('Название').fill(title)
    await inner.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
  }
  await page.keyboard.press('Escape')

  // режем после первого признака: два последних урока должны уехать
  const anchor = page.locator('.plan-row', { hasText: 'Первый признак' })
  await anchor.hover()
  await anchor.getByTitle('Вставить после').click()

  const cut = page.locator('.plan-add-form')
  await cut.getByRole('radio', { name: 'Тема', exact: true }).click()
  // сколько уроков уедет, сказано до нажатия, а не после
  await expect(cut).toContainText('2')
  await cut.getByLabel('Название').fill('Признаки подобия')
  await cut.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.locator('.plan-section')).toHaveCount(2)
  const rows = await structure(page)
  // плоская последовательность уроков не изменилась — только заголовок над хвостом
  expect(rows.join(' | ')).toContain('1 Первый признак')
  expect(rows.join(' | ')).toContain('2 Второй признак')
  expect(rows.join(' | ')).toContain('3 Третий признак')

  const second = page.locator('.plan-section').nth(1)
  await expect(second).toContainText('Признаки подобия')
  await expect(second).toContainText('2 урока')
  await expect(page.locator('.plan-section').first()).toContainText('1 урок')
})

test('десять строк удаляются одним выбором и одним вопросом', async ({
  page,
  signIn,
}) => {
  // Раньше это было десять крестиков и десять нативных окон подтверждения,
  // каждое — у верхнего края экрана: курсор ехал туда и обратно десять раз.
  // Пачка отвечает на это не ускорением того же самого, а другой операцией.
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  // шесть уроков подряд: форма после вставки переезжает за созданную строку
  await page.getByRole('button', { name: 'Добавить урок' }).click()
  const form = page.locator('.plan-add-form')
  for (const title of ['Первый', 'Второй', 'Третий', 'Четвёртый', 'Пятый', 'Шестой']) {
    await form.getByLabel('Название').fill(title)
    await form.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
  }
  await page.keyboard.press('Escape')

  // полосы действий нет, пока ничего не выбрано: таблицу читают чаще, чем правят
  await expect(page.locator('.plan-selection')).toHaveCount(0)

  // флажок живёт в самой строке и появляется под курсором, как остальные её
  // кнопки: отдельного режима «Выбрать» нет — он был лишним знанием,
  // которое надо было сперва добыть
  const rows = page.locator('.plan-row.lesson')
  await rows.nth(1).hover()
  await rows.nth(1).locator('.plan-pick input').check()

  const bar = page.locator('.plan-selection')
  await expect(bar).toBeVisible()

  // Shift тянет диапазон от прошлого нажатия: второй–пятый одним движением
  await rows.nth(4).hover()
  await rows.nth(4).locator('.plan-pick input').click({ modifiers: ['Shift'] })
  await expect(bar).toContainText('Выбрано: 4 урока')

  await bar.getByRole('button', { name: 'Удалить' }).click()

  // один вопрос на всю пачку, и он называет число
  const ask = page.locator('dialog[open]')
  await expect(ask).toContainText('Удалить 4 урока?')
  await ask.getByRole('button', { name: 'Удалить' }).click()

  // остались крайние, и нумерация сомкнулась
  await expect(page.locator('.plan-row.lesson')).toHaveCount(2)
  expect(await structure(page)).toEqual(['1 Первый', '2 Шестой'])

  // выбор применён и сброшен, полоса ушла
  await expect(page.locator('.plan-selection')).toHaveCount(0)
})

test('у темы флажка нет: у неё спрашивают про её уроки', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await openPlan(page, EMPTY_COURSE)

  await page.getByRole('button', { name: 'Добавить тему' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Треугольники')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.getByText('Треугольники')).toBeVisible()
  await page.keyboard.press('Escape')

  const head = page.locator('.plan-section .section-head').first()
  await head.hover()
  await head.getByTitle('Добавить урок в тему').click()
  const inner = page.locator('.plan-add-form')
  await inner.getByLabel('Название').fill('Первый признак')
  await inner.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Первый признак' })).toBeVisible()
  await page.keyboard.press('Escape')

  // ячейка у темы есть — сетка одна на все строки, — а флажка в ней нет
  await expect(page.locator('.section-head .plan-pick')).toHaveCount(1)
  await expect(page.locator('.section-head .plan-pick input')).toHaveCount(0)
  await expect(page.locator('.plan-row.lesson .plan-pick input')).toHaveCount(1)

  const row = page.locator('.plan-row.lesson').first()
  await row.hover()
  await row.locator('.plan-pick input').check()

  // Escape снимает выделение: курсор в это время ходит по строкам
  await page.keyboard.press('Escape')
  await expect(page.locator('.plan-selection')).toHaveCount(0)

  // «Отмена» делает то же самое
  await row.hover()
  await row.locator('.plan-pick input').check()
  await expect(page.locator('.plan-selection')).toBeVisible()
  await page.locator('.plan-selection').getByRole('button', { name: 'Отмена' }).click()
  await expect(page.locator('.plan-selection')).toHaveCount(0)
})

test('в библиотеку кладут сразу с ответом «кому видно»', async ({
  page,
  signIn,
  api,
}) => {
  // Публикация была отдельной кнопкой в окне полки: положить на полку и
  // положить на **общую** полку были двумя действиями в разных местах, и
  // второе забывалось — на полке лежал черновик, которого никто, кроме
  // автора, не видел.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const empty = courses.body.find((item) => item.name === 'Grade 6 Geometry')
  for (const title of ['Первый урок', 'Второй урок']) {
    await teacher.post('/api/plan/', { course: empty.id, title })
  }

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Geometry' })
  await expect(page.locator('.plan-cards')).toBeVisible()

  await planMenu(page, /в библиотек/)
  const dialog = page.locator('dialog[open]')
  await dialog.getByLabel('Название').fill('Геометрия, общая полка')

  // умолчание — «всей школе»: кладут туда ради того, чтобы этим пользовались
  await expect(dialog.getByRole('radio', { name: 'Всей школе' })).toBeChecked()
  await dialog.getByRole('button', { name: /Сохранить в библиотеку/ }).click()
  await expect(dialog).toBeHidden()

  // и это настоящая публикация, а не состояние экрана
  const shelf = await teacher.get('/api/library/templates/')
  const made = shelf.body.find((item) => item.title === 'Геометрия, общая полка')
  expect(made.is_published).toBe(true)

  // а «только мне» кладёт черновиком — тем же окном, вторым ответом
  await teacher.delete(`/api/library/templates/${made.id}/`)
  await page.reload()
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Geometry' })
  await expect(page.locator('.plan-cards')).toBeVisible()

  await planMenu(page, /в библиотек/)
  await dialog.getByLabel('Название').fill('Геометрия, черновик')
  await dialog.getByRole('radio', { name: 'Только мне' }).click()
  await dialog.getByRole('button', { name: /Сохранить в библиотеку/ }).click()
  await expect(dialog).toBeHidden()

  const after = await teacher.get('/api/library/templates/')
  const draft = after.body.find((item) => item.title === 'Геометрия, черновик')
  expect(draft.is_published).toBe(false)
})

test('удаление называет цену: строка по имени, тема — числом и галочкой', async ({
  page,
  signIn,
  api,
}) => {
  // Два разрушительных нажатия стояли без цены: нативный confirm называл
  // одно название, а «Удалить вместе с уроками» и вовсе ничего — разница с
  // соседней кнопкой была в одном слове, а промах стоил шести уроков с
  // содержанием.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const tree = await teacher.get(`/api/plan/?course=${course.id}`)
  const withContent = tree.body.nodes
    .flatMap((node) => (node.is_section ? node.children : [node]))
    .find((node) => node.has_content)
  expect(withContent, 'в посеянном плане должен быть урок с содержанием').toBeTruthy()

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await expect(page.locator('.plan-cards')).toBeVisible()

  // одиночный крестик: строка названа по имени, и цена названа
  const row = page.locator('.plan-row.lesson', { hasText: withContent.title }).first()
  await row.hover()
  await row.getByTitle('Удалить').click()
  const ask = page.locator('dialog[open]')
  await expect(ask).toContainText(withContent.title)
  await expect(ask).toContainText('с содержанием')
  await page.keyboard.press('Escape')

  // тема: число уроков стоит в самой кнопке
  const head = page.locator('.plan-section .section-head').first()
  await head.hover()
  await head.getByTitle('Удалить').click()
  const drop = ask.getByRole('button', { name: /Удалить вместе с \d+ урок/ })
  await expect(drop).toBeVisible()
})

test('снос темы с содержанием требует галочки', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await expect(page.locator('.plan-cards')).toBeVisible()

  // ищем тему, внутри которой есть что терять: у неё появляется галочка
  const sections = page.locator('.plan-section')
  for (let i = 0; i < (await sections.count()); i += 1) {
    const head = sections.nth(i).locator('.section-head')
    await head.hover()
    await head.getByTitle('Удалить').click()
    const ask = page.locator('dialog[open]')
    const check = ask.locator('.checkbox.danger input')

    if (await check.count()) {
      const drop = ask.getByRole('button', { name: /Удалить вместе с/ })
      // пока не подтвердили потерю — кнопка не нажимается
      await expect(drop).toBeDisabled()
      await check.check()
      await expect(drop).toBeEnabled()
      return
    }
    await page.keyboard.press('Escape')
  }

  throw new Error('в посеянном плане нет темы с содержанием — случай не проверен')
})

test('удалённый урок возвращается отменой — вместе с содержанием', async ({
  page,
  signIn,
  api,
}) => {
  // Ради этого случая журнал и заведён: «удалил, а зря». Урок — прежде
  // всего его текст, поэтому снимок хранит содержание целиком.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Geometry')
  const made = await teacher.post('/api/plan/', {
    course: course.id,
    title: 'Пропадёт и вернётся',
  })
  await teacher.patch(`/api/plan/${made.body.id}/`, { note: 'важная заметка' })

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  const row = page.locator('.plan-row', { hasText: 'Пропадёт и вернётся' })
  await row.hover()
  await row.getByTitle('Удалить').click()
  await page
    .locator('dialog[open]')
    .getByRole('button', { name: 'Удалить', exact: true })
    .click()
  await expect(page.locator('.plan-row', { hasText: 'Пропадёт и вернётся' })).toHaveCount(0)

  // кнопка называет, что отменит: безымянная отмена страшнее, чем полезна
  const undo = page.getByRole('button', { name: /Отменить: удаление/ })
  await expect(undo).toBeVisible()
  await undo.click()

  await expect(page.locator('.plan-row', { hasText: 'Пропадёт и вернётся' })).toBeVisible()
  // строку воскресили, а не завели похожую: id и заметка те же
  const back = await teacher.get(`/api/plan/${made.body.id}/`)
  expect(back.status).toBe(200)
  expect(back.body.note).toBe('важная заметка')
})

test('учитель видит чужую правку и возвращает как было', async ({
  page,
  signIn,
  api,
}) => {
  // Администратор вправе чинить содержание курсов школы, и учитель узнаёт
  // об этом, только открыв план: изменившиеся строки без объяснения
  // читаются как поломка.
  const admin = await api(PEOPLE.admin)
  const all = await admin.get('/api/courses/?scope=school')
  const course = all.body.find((item) => item.name === 'Grade 6 Algebra')
  await admin.post('/api/plan/', { course: course.id, title: 'Дописано завучем' })

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()
  await expect(page.locator('.plan-row', { hasText: 'Дописано завучем' })).toBeVisible()

  // метка называет, кто и когда, и рядом стоит возврат
  const mark = page.locator('.plan-intervention')
  await expect(mark).toContainText('Ольга Дирекова')
  await mark.getByRole('button', { name: 'вернуть как было' }).click()

  await expect(page.locator('.plan-row', { hasText: 'Дописано завучем' })).toHaveCount(0)
  await expect(page.locator('.plan-intervention')).toHaveCount(0)
})

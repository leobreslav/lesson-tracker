import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * The lesson panel: content, maths and attachments.
 *
 * Files are not exercised here — the browser stack has no object storage, and
 * standing one up would test the storage rather than the page. What a browser
 * *can* answer is whether the Markdown renders, whether KaTeX runs at all
 * (it is a lazily loaded chunk, so a broken import shows up nowhere else),
 * and whether the unsaved-changes mark tells the truth. The file lifecycle is
 * the Django suite's job.
 */

const COURSE = 'Grade 6 Algebra'
// seeded with content: see LESSON_CONTENT in seed_demo
const WITH_CONTENT = 'Признаки делимости на 3 и 9'
const WITH_LINK = 'Длина окружности'

async function openPlan(page) {
  await page.goto('/plan')
  await ready(page)
  await page.getByRole('button', { name: COURSE, exact: true }).click()
  await expect(page.locator('.plan-cards')).toBeVisible()
}

function rowFor(page, title) {
  return page.locator('.plan-row.lesson', { hasText: title })
}

async function openLesson(page, title) {
  await rowFor(page, title).locator('.title').click()
  const panel = page.locator('dialog.modal.sheet')
  await expect(panel.locator('.lesson-title')).toHaveValue(title)
  return panel
}

test('урок с содержанием помечен в таблице и открывается панелью', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // the two marks are separate on purpose: written up, and has something with it
  await expect(rowFor(page, WITH_CONTENT).locator('.mark')).toHaveCount(1)
  await expect(rowFor(page, WITH_LINK).locator('.mark')).toHaveCount(2)
  // a lesson nobody has written up carries neither
  await expect(rowFor(page, 'Простые и составные числа').locator('.mark')).toHaveCount(0)

  const panel = await openLesson(page, WITH_CONTENT)

  // a filled field opens itself; this lesson has all four written up
  await expect(panel.locator('[data-field="body"] textarea')).toHaveValue(
    /Признак делимости на 3/,
  )
  await expect(panel.locator('.lesson-field textarea')).toHaveCount(4)
  await expect(panel.locator('.lesson-status')).toContainText('Всё сохранено')
})

test('у пустого урока раскрыт только текст урока', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)
  const panel = await openLesson(page, 'Простые и составные числа')

  // nothing to show, so nothing is unfolded except the one field a person
  // would start typing in
  await expect(panel.locator('.lesson-field textarea')).toHaveCount(1)
  await expect(panel.locator('[data-field="body"] textarea')).toBeVisible()
  await expect(panel.locator('[data-field="homework"] textarea')).toHaveCount(0)

  // and folding is a click away
  await panel.locator('[data-field="homework"] .lesson-field-head').click()
  await expect(panel.locator('[data-field="homework"] textarea')).toBeVisible()
})

test('превью отрисовывает формулы через KaTeX', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)
  const panel = await openLesson(page, WITH_CONTENT)

  await panel.getByRole('button', { name: 'Просмотр' }).click()

  const rendered = panel.locator('[data-field="body"] .markdown')
  await expect(rendered).toBeVisible()
  // the $$…$$ block became real maths, not a literal dollar sign
  await expect(rendered.locator('.katex-display')).toHaveCount(1)
  await expect(rendered.locator('.katex').first()).toBeVisible()
  await expect(rendered).not.toContainText('$$')
  // and the heading is a heading
  await expect(rendered.locator('h2')).toContainText('Признак делимости на 3')
})

test('в просмотре не правится ничего, включая название и заметку', async ({
  page,
  signIn,
}) => {
  // Режим называется «просмотр», и поле ввода в нём обещает правку, которой
  // не будет. Раньше замирало только содержание, а название с заметкой
  // оставались полями — и это читалось как поломка, а не как режим.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)
  const panel = await openLesson(page, WITH_CONTENT)

  await expect(panel.locator('input.lesson-title')).toBeVisible()
  await panel.getByRole('button', { name: 'Просмотр' }).click()

  await expect(panel.locator('input.lesson-title')).toHaveCount(0)
  await expect(panel.locator('input.lesson-note')).toHaveCount(0)
  await expect(panel.locator('.lesson-title.static')).toBeVisible()
  await expect(panel.locator('textarea')).toHaveCount(0)
  // и вложения только читаются: ни зоны перетаскивания, ни кнопок
  await expect(panel.locator('.dropzone')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: 'Добавить файл' })).toHaveCount(0)

  // а пустой раздел в просмотре и не разворачивается: каретка, за которой
  // пустота, — обещание содержимого, которого нет
  // у этого урока расписаны все четыре поля, а материалов нет
  const empty = panel.locator('[data-field="materials"]')
  await expect(empty).toHaveClass(/frozen/)
  await expect(empty.locator('.caret')).toHaveCount(0)

  // «Правка» возвращает поля
  await panel.getByRole('button', { name: 'Правка' }).click()
  await expect(panel.locator('input.lesson-title')).toBeVisible()
})

test('правка помечается несохранённой и доезжает до сервера', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)
  const panel = await openLesson(page, WITH_CONTENT)

  // already unfolded — the seeded lesson has homework written up
  const homework = panel.locator('[data-field="homework"] textarea')
  await homework.fill('№ 84–89 и разобрать $9 \\mid 4725$.')

  await expect(panel.locator('.lesson-status')).toContainText('несохранённые')
  await panel.getByRole('button', { name: 'Сохранить' }).click()
  await expect(panel.locator('.lesson-status')).toContainText('Всё сохранено')

  // reopening reads it back from the server, not from what is still on screen
  await panel.getByRole('button', { name: 'Закрыть окно' }).click()
  await expect(panel).toBeHidden()

  const again = await openLesson(page, WITH_CONTENT)
  await expect(again.locator('[data-field="homework"] textarea')).toHaveValue(
    '№ 84–89 и разобрать $9 \\mid 4725$.',
  )
})

test('материалом бывает просто строка текста', async ({ page, signIn }) => {
  // «Мордкович, §14», «принести линейку» — материал, который нечего
  // открывать: его название и есть он весь.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const panel = await openLesson(page, 'Простые и составные числа')
  await panel.getByRole('button', { name: /Материалы/ }).click()

  // поле одно на ссылку и заметку: что именно набрали, видно из набранного
  const form = panel.locator('.inline-form')
  await form.getByLabel('Ссылка или заметка').fill('Мордкович, §14')
  await form.getByRole('button', { name: 'Добавить' }).click()

  const row = panel.locator('.attachment')
  await expect(row).toHaveCount(1)
  await expect(row.locator('.title')).toHaveText('Мордкович, §14')
  // нажимать не на что: ни ссылки, ни кнопки скачивания
  await expect(row.locator('a')).toHaveCount(0)
  await expect(row.getByRole('button', { name: 'Мордкович, §14' })).toHaveCount(0)

  // поле очистилось: следующий материал набирают тут же
  await expect(form.getByLabel('Ссылка или заметка')).toHaveValue('')
  // «Название» спрашивается только у адреса — у заметки название и есть она
  await expect(form.getByLabel('Название ссылки')).toHaveCount(0)
  await expect(panel.locator('button.dropzone')).toBeVisible()

  // и это настоящая запись: пережила перезагрузку
  await page.reload()
  await ready(page)
  await openPlan(page)
  const again = await openLesson(page, 'Простые и составные числа')
  await expect(again.locator('.attachment .title')).toHaveText('Мордкович, §14')
})

test('ссылка добавляется к уроку и сразу видна значком', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const target = 'Простые и составные числа'
  const panel = await openLesson(page, target)

  // материалы теперь такой же сворачиваемый раздел, как остальные, и у
  // урока без них он закрыт
  await panel.getByRole('button', { name: /Материалы/ }).click()
  // то же поле: адрес целиком значит ссылку
  const form = panel.locator('.inline-form')

  // ряд остаётся рядом: `.modal-body form` кладёт детей колонкой, и поле с
  // `flex-basis: 8rem` вырастало вверх, а форма занимала пол-окна
  const box = await form.boundingBox()
  expect(Math.round(box.height), 'форма добавления встала столбиком').toBeLessThan(90)
  const heights = await form
    .locator('input, button')
    .evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().height)))
  expect(new Set(heights).size, `разная высота: ${heights}`).toBe(1)

  await form.getByLabel('Ссылка или заметка').fill('https://example.org/sieve')
  // поле названия появилось само, потому что в первом адрес
  await form.getByLabel('Название ссылки').fill('Решето Эратосфена')
  await form.getByRole('button', { name: 'Добавить' }).click()

  await expect(panel.locator('.attachment')).toHaveCount(1)
  await expect(panel.locator('.attachment .title')).toHaveText('Решето Эратосфена')

  await panel.getByRole('button', { name: 'Закрыть окно' }).click()
  await expect(panel).toBeHidden()

  // the table learned about it without a reload
  await expect(rowFor(page, target).locator('.mark')).toHaveCount(1)
})

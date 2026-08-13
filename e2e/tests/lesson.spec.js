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
  await panel.getByRole('button', { name: 'Закрыть' }).first().click()
  await expect(panel).toBeHidden()

  const again = await openLesson(page, WITH_CONTENT)
  await expect(again.locator('[data-field="homework"] textarea')).toHaveValue(
    '№ 84–89 и разобрать $9 \\mid 4725$.',
  )
})

test('ссылка добавляется к уроку и сразу видна значком', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const target = 'Простые и составные числа'
  const panel = await openLesson(page, target)

  await panel.getByRole('button', { name: 'Добавить ссылку…' }).click()
  // scoped to the form: the lesson title above carries the same label
  const form = panel.locator('.inline-form')
  await form.getByLabel('Адрес').fill('https://example.org/sieve')
  await form.getByLabel('Название').fill('Решето Эратосфена')
  await form.getByRole('button', { name: 'Добавить' }).click()

  await expect(panel.locator('.attachment')).toHaveCount(1)
  await expect(panel.locator('.attachment .title')).toHaveText('Решето Эратосфена')

  await panel.getByRole('button', { name: 'Закрыть' }).first().click()
  await expect(panel).toBeHidden()

  // the table learned about it without a reload
  await expect(rowFor(page, target).locator('.mark')).toHaveCount(1)
})

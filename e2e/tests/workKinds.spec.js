import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Виды работ: справочник школы и выбор учителя.
 *
 * Через браузер это гонять надо ровно по той же причине, что и системы
 * оценивания: **список даёт школа, а выбирает учитель**, и если форма
 * предложит запрещённый вид, сервер откажет — человек увидит пустой отказ на
 * ровном месте. Плюс то, чего питоновский набор не ловит по построению: что
 * значок в журнале подписан видом, а домашность показана отдельно от него.
 */

const day = 24 * 60 * 60 * 1000

test('администратор заводит типовые виды и запрещает один', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await page.goto('/school/reference')
  await ready(page)

  const list = page.locator('[data-panel="work-kinds"] .grading-list li')
  await page.locator('[data-panel="work-kinds"]').getByRole('button', {
    name: 'Типовые',
  }).click()

  for (const name of ['Контрольная', 'Проверочная', 'Проект']) {
    await expect(list.filter({ hasText: name })).toHaveCount(1)
  }
  const было = await list.count()

  // нажать дважды не страшно: заведённое не трогается
  await page.locator('[data-panel="work-kinds"]').getByRole('button', {
    name: 'Типовые',
  }).click()
  await expect(list).toHaveCount(было)

  const контрольная = list.filter({ hasText: 'Контрольная' })
  await контрольная.getByRole('button', { name: 'запретить' }).click()
  await expect(контрольная.getByRole('button', { name: 'разрешить' })).toBeVisible()
})

test('учитель выбирает вид, а запрещённого в списке нет', async ({
  page,
  signIn,
  api,
}) => {
  const admin = await api(PEOPLE.admin)
  await admin.post('/api/works/kinds/', { typical: true })
  const answer = await admin.get('/api/works/kinds/')
  const проект = answer.body.kinds.find((one) => one.name === 'Проект')
  await admin.patch(`/api/works/kinds/${проект.id}/`, { is_allowed: false })

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((one) => one.name === 'Grade 6 Algebra')
  const work = await teacher.post('/api/works/', {
    course: course.id,
    title: 'Работа с видом',
    opens_at: new Date(Date.now() - day).toISOString(),
    closes_at: new Date(Date.now() + day).toISOString(),
  })
  expect(work.status, JSON.stringify(work.body)).toBe(201)

  await signIn(PEOPLE.ivanova)
  await page.goto(`/works/${work.body.id}/edit`)
  await ready(page)
  await page.getByRole('button', { name: 'Настройки' }).click()

  const dialog = page.getByRole('dialog')
  const kinds = dialog.getByLabel('Вид работы')
  await expect(kinds).toBeVisible()

  // разрешённые есть, запрещённого нет вовсе: форма не предлагает того, чего
  // сервер не примет
  await expect(kinds.locator('option', { hasText: 'Контрольная' })).toHaveCount(1)
  await expect(kinds.locator('option', { hasText: 'Проект' })).toHaveCount(0)

  // выбор вида подставляет «идёт в итог», но не решает за учителя
  await kinds.selectOption({ label: 'Контрольная' })
  await expect(dialog.getByLabel('Идёт в итог за период')).toBeChecked()

  // домашность — отдельный признак, и ставится она тут же: домашняя
  // контрольная бывает, и одним списком она была бы невыразима
  await dialog.getByLabel('Задано на дом').check()
  await dialog.getByRole('button', { name: 'Сохранить' }).click()
  await expect(dialog).toBeHidden()

  const saved = await teacher.get(`/api/works/${work.body.id}/`)
  expect(saved.body.is_homework).toBe(true)
  expect(saved.body.kind).not.toBeNull()
})

test('значок в журнале подписан видом, а домашность стоит отдельно', async ({
  page,
  signIn,
  api,
}) => {
  const admin = await api(PEOPLE.admin)
  await admin.post('/api/works/kinds/', { typical: true })
  const answer = await admin.get('/api/works/kinds/')
  const контрольная = answer.body.kinds.find((one) => one.name === 'Контрольная')

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((one) => one.name === 'Grade 6 Algebra')
  const slots = await teacher.get(`/api/slots/?course=${course.id}`)
  const slot = slots.body.find((one) => !one.is_cancelled)

  await teacher.post('/api/works/', {
    course: course.id,
    slot: slot.id,
    title: 'Домашняя контрольная',
    kind: контрольная.id,
    is_homework: true,
    opens_at: new Date(Date.now() - day).toISOString(),
    closes_at: new Date(Date.now() + day).toISOString(),
  })

  await signIn(PEOPLE.ivanova)
  await page.goto('/journal')
  await ready(page)

  const badge = page.locator(`.journal-table thead .work-tag.kind-${контрольная.color}`)
  await expect(badge.first()).toBeVisible()
  await expect(badge.first()).toHaveText(контрольная.label)

  // домашность — пометка у значка, а не его буква: пока признаки схлопывались
  // в одну букву, домашняя контрольная выглядела просто контрольной
  await expect(badge.first()).toHaveClass(/at-home/)
})

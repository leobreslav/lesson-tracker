import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenarios 8 and 9: the layout shifting, and one teacher's work staying
 * out of another's sight.
 */

const MONDAY = '2026-09-07'

async function openPlan(page, course) {
  await page.goto('/plan')
  await ready(page)
  await page.getByRole('button', { name: course, exact: true }).click()
  await expect(page.locator('.plan-cards')).toBeVisible()
}

/** Даты первых строк плана — по ним и видно, что раскладка съехала. */
async function dates(page, count = 4) {
  const all = await page
    .locator('.plan-row.lesson .plan-date')
    .evaluateAll((cells) => cells.map((cell) => cell.textContent.trim()))
  return all.slice(0, count)
}

/** The n-th lesson of a course that is still standing, straight from the API. */
async function nthSlot(api, courseId, index) {
  const { body } = await api.get(`/api/slots/?course=${courseId}`)
  const live = body
    .filter((slot) => !slot.is_cancelled)
    .sort((a, b) =>
      a.date === b.date ? a.lesson_number - b.lesson_number : a.date < b.date ? -1 : 1,
    )
  return live[index]
}

test('отмена урока сдвигает даты в плане', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const algebra = courses.body.find((item) => item.name === 'Grade 6 Algebra')

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  const before = await dates(page)
  expect(before.length).toBeGreaterThan(3)

  // cancel the earliest lesson of the course. The seeded year starts before
  // the first full week, so «the Monday of week one» is not it
  const first = await nthSlot(teacher, algebra.id, 0)
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(first.date)

  const lesson = page.locator(`[data-lesson="${first.date}:${first.lesson_number}"]`)
  await expect(lesson).toBeVisible()
  await lesson.click()

  const menu = page.locator('dialog.modal')
  await menu.getByRole('button', { name: 'Отменить', exact: true }).click()
  await menu.getByPlaceholder('Причина отмены').fill('Болезнь')
  await menu.getByRole('button', { name: 'Отменить урок' }).click()
  await expect(menu).toBeHidden()

  // отменённый урок уходит из раскладки целиком, и вся лента съезжает на
  // одну дату назад: первый урок плана встаёт на вторую дату
  await openPlan(page, 'Grade 6 Algebra')
  const after = await dates(page)

  expect(after[0]).toBe(before[1])
  expect(after[1]).toBe(before[2])
})

test('«Состояние курсов» — строка на курс и подробности по нажатию', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/status')
  await ready(page)

  // строка на курс: где я, резерв, плашка состояния
  const rows = page.locator('.progress-list > li')
  expect(await rows.count()).toBeGreaterThan(1)
  await expect(rows.first().locator('.where')).toContainText('урок')
  await expect(rows.first().locator('.reserve')).toContainText('резерв')
  await expect(rows.first().locator('.badge.state')).toHaveText('в порядке')

  // ленты уроков здесь больше нет — она в плане
  await expect(page.locator('.layout-feed, .layout-row')).toHaveCount(0)
  // как и метрик, от которых отказались
  await expect(page.locator('.terms-table, [data-card="pace"]')).toHaveCount(0)

  await rows.first().locator('.progress-head').click()
  const details = rows.first().locator('.progress-details')
  await expect(details.locator('[data-card="reserve"]')).toContainText('свободных')
  await expect(details.locator('[data-card="changes"]')).toContainText('отменено')
  await expect(details.locator('[data-card="growth"]')).toContainText('эталон')
  // дата окончания плашки не занимает: она повторяла бы резерв
  await expect(details.locator('[data-card="ends"]')).toHaveCount(0)
  // ближайших уроков ровно два
  await expect(details.locator('.progress-next li')).toHaveCount(2)
})

test('второй учитель не видит ни уроков, ни планов первого', async ({
  page,
  signIn,
  api,
}) => {
  // Ivanova has a plan in Grade 6 Algebra; Petrov shares no course with it
  const ivanova = await api(PEOPLE.ivanova)
  const hers = await ivanova.get('/api/slots/')
  expect(hers.body.length).toBeGreaterThan(0)

  await signIn(PEOPLE.petrov)
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(MONDAY)

  // her Monday lesson sits at number 1; his week has nothing there
  await expect(page.locator(`[data-lesson="${MONDAY}:1"]`)).toHaveCount(0)
  await expect(page.locator('.week-grid').getByText('Grade 6 Algebra')).toHaveCount(0)

  // a course nobody assigned him is not even offered: «what do I teach» is
  // now a table of its own, and hers is not in it
  await page.goto('/plan')
  await ready(page)
  await expect(
    page.getByRole('button', { name: 'Grade 6 Algebra', exact: true }),
  ).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Grade 9 Algebra', exact: true })).toBeVisible()

  // and the API says the same, so it is not the interface hiding things
  const petrov = await api(PEOPLE.petrov)
  const his = await petrov.get('/api/slots/')
  const hisIds = new Set(his.body.map((slot) => slot.id))
  expect(hers.body.some((slot) => hisIds.has(slot.id))).toBe(false)
})

test('черновик чужого шаблона не виден в библиотеке', async ({ page, signIn }) => {
  // the seeded draft belongs to Petrov
  await signIn(PEOPLE.ivanova)
  await page.goto('/library')
  await ready(page)

  await expect(page.getByText('Алгебра 6, по учебнику')).toBeVisible()
  await expect(page.getByText('Алгебра 9, черновик')).toHaveCount(0)
})

test('автор свой черновик видит и помечен меткой', async ({ page, signIn }) => {
  await signIn(PEOPLE.petrov)
  await page.goto('/library')
  await ready(page)

  const draft = page.locator('li', { hasText: 'Алгебра 9, черновик' })
  await expect(draft).toBeVisible()
  await expect(draft.locator('.badge')).toHaveText('черновик')
})

test('рост к утверждённому эталону виден на «Состоянии курсов»', async ({
  page,
  signIn,
  api,
}) => {
  // методист курса — сама Иванова: самоутверждение законно и помечается
  const admin = await api(PEOPLE.admin)
  const members = await admin.get('/api/school/members/')
  const her = members.body.find((item) => item.email === PEOPLE.ivanova)
  const all = await admin.get('/api/courses/?scope=school')
  const course = all.body.find((item) => item.name === 'Grade 6 Algebra')
  await admin.post('/api/school/methodists/', { course: course.id, user: her.id })

  const teacher = await api(PEOPLE.ivanova)
  await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})
  const queue = await teacher.get('/api/plan/reviews/')
  await teacher.post(`/api/plan/reviews/${queue.body.reviews[0].id}/approve/`)

  await signIn(PEOPLE.ivanova)
  await page.goto('/status')
  await ready(page)
  const row = page.locator('.progress-list > li').first()
  await row.locator('.progress-head').click()
  // сразу после утверждения расхождения нет — и добавленных, и удалённых
  await expect(row.locator('[data-card="growth"] .pair b').first()).toHaveText('0')
  await expect(row.locator('[data-card="growth"] .pair b').last()).toHaveText('0')

  // добавили урок — план вырос ровно на него
  await page.goto('/plan')
  await ready(page)
  await page.getByRole('button', { name: 'Grade 6 Algebra', exact: true }).click()
  await expect(page.locator('.plan-cards')).toBeVisible()
  await page.getByRole('button', { name: '+ урок' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Лишний урок')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Лишний урок' })).toBeVisible()

  await page.goto('/status')
  await ready(page)
  await page.locator('.progress-list > li').first().locator('.progress-head').click()
  const growth = page.locator('.progress-list > li').first().locator('[data-card="growth"]')
  // два числа, а не сальдо: добавили один, не удаляли ни одного
  await expect(growth.locator('.pair b').first()).toHaveText('+1')
  await expect(growth.locator('.pair b').last()).toHaveText('0')
})

test('плашек четыре, и все одного роста', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/status')
  await ready(page)

  // курс с планом и курс без плана: пустые случаи ростом отличаться не должны
  for (const name of ['Grade 6 Algebra', 'Grade 6 Geometry']) {
    const row = page.locator('.progress-list > li', { hasText: name })
    await row.locator('.progress-head').click()

    const cards = row.locator('.progress-details .cards .card-stat')
    await expect(cards).toHaveCount(4)

    const heights = await cards.evaluateAll((all) =>
      all.map((card) => Math.round(card.getBoundingClientRect().height)),
    )
    expect(new Set(heights).size, `${name}: ${heights.join(', ')}`).toBe(1)
  }
})

test('прогресс по плану: три числа одной плашкой', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/status')
  await ready(page)

  const row = page.locator('.progress-list > li').first()
  await row.locator('.progress-head').click()
  const card = row.locator('[data-card="progress"]')

  // плашка стоит первой в ряду: ради неё на экран и заходят
  await expect(row.locator('.cards .card-stat').first()).toHaveAttribute(
    'data-card',
    'progress',
  )

  // год не начался: проведено ноль — это нормально
  await expect(card.locator('h2')).toHaveText('0 из 40')
  await expect(card.locator('.hint')).toHaveText('осталось 40')

  // проведено плюс осталось равно всему — числа берутся из одного ответа
  const [done, total] = (await card.locator('h2').textContent())
    .match(/\d+/g)
    .map(Number)
  const left = Number((await card.locator('.hint').textContent()).match(/\d+/)[0])
  expect(done + left).toBe(total)
})

test('дефицит виден словами в шапке, а числа плашки не меняет', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  await teacher.delete(
    `/api/slots/bulk/?course=${course.id}&start=2026-10-01&end=2027-08-01`,
  )

  await signIn(PEOPLE.ivanova)
  await page.goto('/status')
  await ready(page)

  const row = page.locator('.progress-list > li', { hasText: 'Grade 6 Algebra' })
  await expect(row.locator('.reserve.overflow')).toContainText(
    'не помещаются в учебный год',
  )
  await expect(row.locator('.badge.state')).toHaveText(/дефицит/)

  // в плашке всё те же сорок уроков плана: хватает им дней или нет —
  // отдельный вопрос, и на счёт «осталось» он не влияет
  await expect(row.locator('[data-card="progress"] h2')).toHaveText('0 из 40')
  await expect(row.locator('[data-card="progress"] .hint')).toHaveText('осталось 40')
})

test('пустой план не показывает «0 из 0»', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/status')
  await ready(page)

  const row = page.locator('.progress-list > li', { hasText: 'Grade 6 Geometry' })
  await row.locator('.progress-head').click()

  const card = row.locator('[data-card="progress"]')
  await expect(card).not.toContainText('0 из 0')
  await expect(card.getByRole('button', { name: 'Заполнить план' })).toBeVisible()
})

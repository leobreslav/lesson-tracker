import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Утверждение плана методистом.
 *
 * Проверяется процедура целиком, через две роли: учитель отправляет,
 * методист смотрит присланное и решает. Отдельно — что правка после
 * отправки отзывает запрос: состояние должно быть честным.
 */

const openPlan = async (page, course) => {
  await page.goto('/plan')
  await ready(page)
  await page.getByRole('button', { name: course, exact: true }).click()
  await expect(page.locator('.plan-cards')).toBeVisible()
}

/** Назначить человека методистом курса — руками администратора. */
async function makeMethodist(api, email, courseName) {
  const admin = await api(PEOPLE.admin)
  const members = await admin.get('/api/school/members/')
  const person = members.body.find((item) => item.email === email)
  const courses = await admin.get('/api/courses/?scope=school')
  const course = courses.body.find((item) => item.name === courseName)

  const done = await admin.post('/api/school/methodists/', {
    course: course.id,
    user: person.id,
  })
  expect(done.status).toBe(201)
  return { person, course }
}

test('учитель отправляет план, методист утверждает', async ({
  page,
  signIn,
  api,
}) => {
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await page.getByRole('button', { name: 'Отправить на утверждение' }).click()
  await expect(page.getByText(/Отправлено/)).toBeVisible()
  await expect(page.locator('.hint.approval')).toContainText('На утверждении')

  // методист видит запрос и присланный план
  await signIn(PEOPLE.petrov)
  // раздела «На утверждение» больше нет: надзор живёт на главной, под
  // своими курсами
  await page.goto('/')
  await ready(page)
  await expect(page.getByRole('heading', { name: 'На утверждение' })).toBeVisible()
  await page.getByRole('button', { name: 'Открыть' }).click()

  const dialog = page.locator('dialog.modal')
  await expect(dialog.locator('.review-plan li').first()).toBeVisible()
  await dialog.getByRole('button', { name: 'Утвердить' }).click()
  await expect(dialog).toBeHidden()

  // и учитель видит, что план утверждён
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await expect(page.locator('.hint.approval')).toContainText('Утверждён')
})

test('методист возвращает план с замечанием', async ({ page, signIn, api }) => {
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const algebra = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  await teacher.post(`/api/plan/baseline/submit/?course=${algebra.id}`, {})

  await signIn(PEOPLE.petrov)
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: 'Открыть' }).click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByRole('button', { name: 'Вернуть с замечанием' }).click()
  // без текста кнопка возврата недоступна: возврат молчком — загадка
  await expect(dialog.getByRole('button', { name: 'Вернуть', exact: true })).toBeDisabled()
  await dialog.getByLabel('Что поправить').fill('Мало часов на повторение')
  await dialog.getByRole('button', { name: 'Вернуть', exact: true }).click()
  await expect(dialog).toBeHidden()

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await expect(page.locator('.hint.approval')).toContainText('Мало часов на повторение')
})

test('правка после отправки запрос не отзывает, методист видит новое', async ({
  page,
  signIn,
  api,
}) => {
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await page.getByRole('button', { name: 'Отправить на утверждение' }).click()
  await expect(page.locator('.hint.approval')).toContainText('На утверждении')

  await page.getByRole('button', { name: '+ урок' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Урок после отправки')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Урок после отправки' })).toBeVisible()

  // запрос на месте, и методист открывает текущую версию плана
  await page.reload()
  await ready(page)
  await expect(page.locator('.hint.approval')).toContainText('На утверждении')

  await signIn(PEOPLE.petrov)
  await page.goto('/')
  await ready(page)
  await page.getByRole('button', { name: 'Открыть' }).click()
  const dialog = page.locator('dialog.modal')
  await expect(dialog.locator('.review-plan')).toContainText('Урок после отправки')
})

test('без методиста у курса отправка объясняет, почему нельзя', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  await page.getByRole('button', { name: 'Отправить на утверждение' }).click()

  await expect(page.getByText(/некому утверждать|Nobody approves/)).toBeVisible()
})

test('раздела «На утверждение» у обычного учителя нет', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)

  await expect(
    page.getByRole('link', { name: 'На утверждение' }),
  ).toHaveCount(0)
})

/**
 * Экран методиста — это надзор, а не очередь.
 *
 * Пока он показывал только присланное, про тех, кто ничего не присылал,
 * методист не знал ничего — а спрашивают с него как раз про них.
 */
test('методист видит план, который никто не присылал, с теми же числами', async ({
  page,
  signIn,
  api,
}) => {
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')

  // числа, которые видит у себя учитель
  await signIn(PEOPLE.ivanova)
  await page.goto('/')
  await ready(page)
  const hers = page.locator('.progress-list > li', { hasText: 'Grade 6 Algebra' })
  await hers.locator('.progress-head').click()
  const reserve = await hers.locator('.reserve').textContent()
  const progress = await hers.locator('[data-card="progress"] h2').textContent()

  // ничего не отправляли — и всё равно план виден методисту
  await signIn(PEOPLE.petrov)
  await page.goto('/')
  await ready(page)
  await expect(page.locator('.nav-count')).toHaveCount(0)

  const row = page.locator('.progress-list > li', { hasText: 'Grade 6 Algebra' })
  await expect(row.locator('.whose')).toContainText('Мария Иванова')
  await expect(row.locator('.badge.waiting')).toHaveCount(0)
  await row.locator('.progress-head').click()

  // те же числа: разговор про «отстаёшь» не должен начинаться со спора о них
  await expect(row.locator('.reserve')).toHaveText(reserve)
  await expect(row.locator('[data-card="progress"] h2')).toHaveText(progress)

  // чужой план — не свой: звать методиста заполнять его нечем
  await expect(row.getByRole('button', { name: 'Заполнить план' })).toHaveCount(0)
  await expect(row.getByRole('button', { name: 'Открыть план' })).toHaveCount(0)
})

test('ожидающий план помечен, остальные — нет', async ({ page, signIn, api }) => {
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Geometry')

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const algebra = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  await teacher.post(`/api/plan/baseline/submit/?course=${algebra.id}`, {})

  await signIn(PEOPLE.petrov)
  await page.goto('/')
  await ready(page)

  const rows = page.locator('.progress-list > li')
  expect(await rows.count()).toBeGreaterThan(1)
  await expect(page.locator('.badge.waiting')).toHaveCount(1)
  await expect(
    page.locator('.progress-list > li', { hasText: 'Grade 6 Algebra' }).locator(
      '.badge.waiting',
    ),
  ).toHaveText('ждёт ответа')

  // ожидающий стоит в своём списке, остальные — ниже, под надзором
  await expect(page.getByRole('heading', { name: 'На утверждение' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Под надзором' })).toBeVisible()
})

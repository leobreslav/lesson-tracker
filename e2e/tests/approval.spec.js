import { PEOPLE, expect, planMenu, ready, test } from './harness.js'

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
  // курс выбирают селектом в строке заголовка: чипы не пережили
  // учителя музыки с полутора десятками курсов
  await page.getByLabel('Курс').selectOption({ label: course })
  await expect(page.locator('.plan-cards')).toBeVisible()
}

/**
 * Открыть чужой план под надзором — тем же селектом, из другой группы.
 *
 * Раздела «Мои курсы» больше нет: надзор переехал в «Учебный план», и курс
 * выбирается там же, где свой, только группа другая.
 */
const openSupervised = async (page, course) => {
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: course })
  await expect(page.locator('.progress-list')).toBeVisible()
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
  await planMenu(page, 'На утверждение')
  await expect(page.getByText(/Отправлено/)).toBeVisible()
  await expect(page.locator('.hint.approval')).toContainText('На утверждении')

  // методист видит запрос и присланный план
  await signIn(PEOPLE.petrov)
  await openSupervised(page, 'Grade 6 Algebra')
  await expect(page.locator('.review-plan li').first()).toBeVisible()
  await page.getByRole('button', { name: 'Утвердить' }).click()
  await expect(page.locator('.review-plan')).toHaveCount(0)

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
  await openSupervised(page, 'Grade 6 Algebra')

  await page.getByRole('button', { name: 'Вернуть с замечанием' }).click()
  // без текста кнопка возврата недоступна: возврат молчком — загадка
  await expect(page.getByRole('button', { name: 'Вернуть', exact: true })).toBeDisabled()
  await page.getByLabel('Что поправить').fill('Мало часов на повторение')
  await page.getByRole('button', { name: 'Вернуть', exact: true }).click()
  await expect(page.locator('.review-plan')).toHaveCount(0)

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
  await planMenu(page, 'На утверждение')
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
  await openSupervised(page, 'Grade 6 Algebra')
  await expect(page.locator('.review-plan')).toContainText('Урок после отправки')
})

test('без методиста у курса отправка объясняет, почему нельзя', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  await planMenu(page, 'На утверждение')

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
test('методист видит курс, план которого никто не присылал', async ({
  page,
  signIn,
  api,
}) => {
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')

  await signIn(PEOPLE.petrov)
  await openSupervised(page, 'Grade 6 Algebra')

  // курс под надзором виден и без запроса — про тех, кто ничего не
  // присылал, спрашивают с методиста ровно так же
  const row = page.locator('.progress-list > li', { hasText: 'Grade 6 Algebra' })
  await expect(row.locator('.whose')).toContainText('Мария Иванова')
  await expect(page.getByText(/План на утверждение пока не присылали/)).toBeVisible()

  // читать чужую программу без запроса методист не может, и переезд новых
  // прав ему не дал
  await expect(page.locator('.review-plan')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Утвердить' })).toHaveCount(0)
})

test('ожидающий и просто поднадзорный лежат в разных группах селектора', async ({
  page,
  signIn,
  api,
}) => {
  // Три группы — это три роли человека, а не три свойства курса: свои он
  // ведёт, присланные должен утвердить, за остальными смотрит.
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Geometry')

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const algebra = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  await teacher.post(`/api/plan/baseline/submit/?course=${algebra.id}`, {})

  await signIn(PEOPLE.petrov)
  await page.goto('/plan')
  await ready(page)

  const groups = page.getByLabel('Курс').locator('optgroup')
  await expect(groups).toHaveCount(3)
  await expect(groups.nth(0)).toHaveAttribute('label', 'Мои курсы')
  await expect(groups.nth(1)).toHaveAttribute('label', 'Ждут ответа')
  await expect(groups.nth(2)).toHaveAttribute('label', 'Под надзором')

  // присланный — во второй группе, остальной надзор — в третьей
  await expect(groups.nth(1).locator('option')).toHaveText(['Grade 6 Algebra'])
  await expect(groups.nth(2).locator('option')).toHaveText(['Grade 6 Geometry'])
})

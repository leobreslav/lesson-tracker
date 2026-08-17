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
  await page.getByRole('button', { name: 'На утверждение' }).click()
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
  await page.getByRole('button', { name: 'На утверждение' }).click()
  await expect(page.locator('.hint.approval')).toContainText('На утверждении')

  await page.getByRole('button', { name: 'Добавить урок' }).click()
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

  await page.getByRole('button', { name: 'На утверждение' }).click()

  await expect(page.getByText(/некому утверждать|Nobody approves/)).toBeVisible()
})

test('утверждение целиком живёт в шапке, рядом с тумблером вида', async ({
  page,
  signIn,
  api,
}) => {
  // Разговор один — отправить, узнать, чем разошлось, — а стоял он в трёх
  // местах: кнопка под «⋯», состояние подвальной строкой панели, сравнение
  // тумблером в шапке. Чтобы отправить план, надо было вспомнить про
  // многоточие, а узнать, дошёл ли он, — посмотреть в другой конец панели.
  const { course } = await makeMethodist(api, PEOPLE.ivanova, 'Grade 6 Algebra')

  const teacher = await api(PEOPLE.ivanova)
  await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})
  const reviews = await teacher.get('/api/plan/reviews/')
  const row = reviews.body.plans.find((item) => item.id === course.id)
  await teacher.post(`/api/plan/reviews/${row.review.id}/approve/`, {})

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  const head = page.locator('.page-header .plan-approval')
  await expect(head.locator('.hint.approval')).toContainText('Утверждён')
  await expect(head.getByRole('button', { name: 'На утверждение' })).toBeVisible()
  await expect(head.getByRole('radio', { name: 'Сравнение' })).toBeVisible()

  // и в «⋯» отправки больше нет: одно действие — одно место
  await page.getByRole('button', { name: 'Ещё' }).click()
  await expect(
    page.locator('.plan-menu .dropdown').getByRole('button', { name: 'На утверждение' }),
  ).toHaveCount(0)
})

test('методист без своих курсов видит присланный план', async ({
  page,
  signIn,
  api,
}) => {
  // Курс по умолчанию выбирался только среди своих, а пустой список своих
  // сразу показывал «сначала заведите курс» — до селектора с группой «Ждут
  // ответа» дело не доходило вовсе. То есть утверждение не работало ровно
  // для того, кто только утверждает: администратор школы своих курсов не
  // ведёт, а именно он чаще всего и подписывает.
  const { course } = await makeMethodist(api, PEOPLE.admin, 'Grade 6 Algebra')

  const teacher = await api(PEOPLE.ivanova)
  const sent = await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})
  expect(sent.status, JSON.stringify(sent.body)).toBe(201)

  await signIn(PEOPLE.admin)
  await page.goto('/plan')
  await ready(page)

  // экрана «заведите курс» тут быть не должно, а присланный план — должен.
  // Курс тут один, поэтому в шапке не селект, а имя: выбирать не из чего
  await expect(page.locator('.empty-state')).toHaveCount(0)
  await expect(page.locator('.course-picked')).toContainText('Grade 6 Algebra')
  await expect(page.locator('.review-plan li').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Утвердить' })).toBeVisible()
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

test('свой курс показывает свой план, даже если методист у него ты сам', async ({
  page,
  signIn,
  api,
}) => {
  // Самоутверждение законно, и в школе, где предмет ведёт один человек, оно
  // обычное дело. Списки «мои» и «поднадзорные» при этом пересекались, а
  // страница выбирала надзор — учитель открывал «Учебный план» и не видел
  // собственного плана вовсе, только плашки чужими глазами.
  await makeMethodist(api, PEOPLE.ivanova, 'Grade 6 Algebra')

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  // это мой план: таблица на месте, панель управления тоже
  await expect(page.locator('ul.plan .plan-row.lesson').first()).toBeVisible()
  await expect(page.locator('.plan-tools')).toBeVisible()

  // и в селекте курс стоит один раз, без группы «Под надзором»
  await expect(page.getByLabel('Курс').locator('optgroup')).toHaveCount(0)
  await expect(
    page.getByLabel('Курс').locator('option', { hasText: 'Grade 6 Algebra' }),
  ).toHaveCount(1)

  // отправляем на утверждение — решать можно тут же, по ссылке
  await page.getByRole('button', { name: 'На утверждение' }).click()
  await expect(page.locator('.hint.approval.pending')).toContainText('На утверждении')
  await expect(page.locator('.hint.approval.self')).toContainText(
    'Методист этого курса — вы.',
  )

  await page.getByRole('button', { name: 'Рассмотреть запрос' }).click()
  await expect(page.locator('.review-plan li').first()).toBeVisible()
  await page.getByRole('button', { name: 'Утвердить' }).click()

  // после решения возвращаемся к своему плану, и оно уже записано
  await expect(page.locator('ul.plan .plan-row.lesson').first()).toBeVisible()
  await expect(page.locator('.hint.approval')).toContainText('Утверждён')
  await expect(page.locator('.hint.approval.self')).toHaveCount(0)
})

test('сравнение с эталоном показывает строки, а не только числа', async ({
  page,
  signIn,
  api,
}) => {
  // «+6 −2» отвечает на «сильно ли разошлось», а спрашивают «что именно я
  // поменял». Удалённые строки при этом видно призраками на их местах —
  // ради них сравнение и сделано отдельным видом, а не подкраской таблицы.
  const { course } = await makeMethodist(api, PEOPLE.ivanova, 'Grade 6 Algebra')

  const teacher = await api(PEOPLE.ivanova)
  await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})
  const reviews = await teacher.get('/api/plan/reviews/')
  const row = reviews.body.plans.find((item) => item.id === course.id)
  await teacher.post(`/api/plan/reviews/${row.review.id}/approve/`, {})

  // правим план: переименовали, удалили, добавили
  const tree = await teacher.get(`/api/plan/?course=${course.id}`)
  const section = tree.body.nodes[0]
  await teacher.patch(`/api/plan/${section.children[0].id}/`, {
    title: 'Натуральные числа и ноль',
  })
  await teacher.delete(`/api/plan/${section.children[1].id}/`)
  await teacher.post('/api/plan/', { course: course.id, title: 'Совсем новый урок' })

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await page.getByRole('radio', { name: 'Сравнение' }).click()

  const diff = page.locator('.plan-diff')
  await expect(diff).toBeVisible()
  // таблицы плана в этом виде нет вовсе: страница перерисована целиком
  await expect(page.locator('ul.plan')).toHaveCount(0)
  await expect(page.locator('.plan-tools')).toHaveCount(0)

  await expect(diff.locator('.diff-row.added')).toHaveCount(1)
  await expect(diff.locator('.diff-row.removed')).toHaveCount(1)
  await expect(diff.locator('.diff-row.changed')).toHaveCount(1)
  // переименование видно переименованием, а не парой «удалили и добавили»
  await expect(diff.locator('.diff-row.changed')).toContainText('было: Натуральные числа')
  // удалённая строка стоит там, где стояла
  await expect(diff.locator('.diff-row.removed')).toContainText('Обыкновенные дроби')

  // возвращает тот же тумблер, которым включили: второй половиной пары
  await page.getByRole('radio', { name: 'План', exact: true }).click()
  await expect(page.locator('ul.plan')).toBeVisible()
})

test('методист смотрит на то же сравнение, что и автор плана', async ({
  page,
  signIn,
  api,
}) => {
  // Сравнение — не новое право, а другой взгляд: план всё так же виден
  // только присланный. Разговор «вы переписали половину» иначе начинался
  // бы со спора о том, что у кого на экране.
  const { course } = await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')

  const teacher = await api(PEOPLE.ivanova)
  await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})

  const methodist = await api(PEOPLE.petrov)
  const reviews = await methodist.get('/api/plan/reviews/')
  const row = reviews.body.plans.find((item) => item.id === course.id)
  await methodist.post(`/api/plan/reviews/${row.review.id}/approve/`, {})

  // после утверждения учитель дописывает урок и снова шлёт на подпись
  await teacher.post('/api/plan/', { course: course.id, title: 'Дополнительный урок' })
  await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})

  await signIn(PEOPLE.petrov)
  await openSupervised(page, 'Grade 6 Algebra')
  await expect(page.locator('.review-plan li').first()).toBeVisible()

  await page.getByRole('radio', { name: 'Сравнение' }).click()
  const added = page.locator('.diff-row.added')
  await expect(added).toHaveCount(1)
  await expect(added).toContainText('Дополнительный урок')
  // список плана уступил место сравнению, а не встал рядом с ним
  await expect(page.locator('.review-plan')).toHaveCount(0)

  await page.getByRole('radio', { name: 'План', exact: true }).click()
  await expect(page.locator('.review-plan li').first()).toBeVisible()
})

test('сравнивают с любым утверждением, а не только с последним', async ({
  page,
  signIn,
  api,
}) => {
  // История снимков копилась с самого начала: каждое утверждение остаётся
  // в базе целиком. «Что изменилось с начала года» — такой же вопрос, как
  // «что с последней подписи», и до выбора версии ответить было нечем.
  const { course } = await makeMethodist(api, PEOPLE.ivanova, 'Grade 6 Algebra')
  const teacher = await api(PEOPLE.ivanova)

  const sign = async () => {
    await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})
    const reviews = await teacher.get('/api/plan/reviews/')
    const row = reviews.body.plans.find((item) => item.id === course.id)
    await teacher.post(`/api/plan/reviews/${row.review.id}/approve/`, {})
  }

  await sign()
  await teacher.post('/api/plan/', { course: course.id, title: 'Урок после первой' })
  await sign()
  await teacher.post('/api/plan/', { course: course.id, title: 'Урок после второй' })

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await page.getByRole('radio', { name: 'Сравнение' }).click()

  // по умолчанию — последнее утверждение: с него добавлен один урок
  await expect(page.locator('.diff-row.added')).toHaveCount(1)

  const versions = page.getByLabel('Сравнить с версией')
  const options = await versions.locator('option').all()
  expect(options.length).toBe(2)

  // выбираем прежнее утверждение: с него добавлены оба
  await versions.selectOption(await options[1].getAttribute('value'))
  await expect(page.locator('.diff-row.added')).toHaveCount(2)
  await expect(page.locator('.diff-row.added').first()).toContainText(
    'Урок после первой',
  )
})

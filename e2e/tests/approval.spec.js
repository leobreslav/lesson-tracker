import { PEOPLE, expect, pickPlan, ready, test } from './harness.js'

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
  // план выбирают на витрине: селекта в шапке больше нет, а у открытого
  // плана на его месте заголовок и дорога назад
  await pickPlan(page, course)
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
  await pickPlan(page, course)
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
  await expect(page.locator('.plan-approval-state .approval')).toContainText('На утверждении')

  // методист видит запрос и присланный план
  await signIn(PEOPLE.petrov)
  await openSupervised(page, 'Grade 6 Algebra')
  await expect(page.locator('.plan .plan-row').first()).toBeVisible()
  await page.getByRole('button', { name: 'Утвердить' }).click()
  // план с экрана не уходит — он виден и без запроса; уходит то, что было
  // про запрос: кнопки решения и заголовок «Присланный план»
  await expect(page.getByRole('button', { name: 'Утвердить' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'План курса' })).toBeVisible()

  // состояние утверждения методист читает теми же словами, что и автор:
  // плашкой «эталон не утверждён» это было сказано иначе, и два вида
  // одного факта разошлись бы молча. Место у строки при этом своё — экран
  // надзора, а не панель плана: панели у читателя нет
  await expect(page.locator('.hint.approval')).toContainText('Утверждён')

  // и учитель видит ровно ту же строку
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await expect(page.locator('.plan-approval-state .approval')).toContainText('Утверждён')
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
  await expect(page.getByRole('button', { name: 'Утвердить' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'План курса' })).toBeVisible()

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')
  await expect(page.locator('.plan-approval-state .approval')).toContainText('Мало часов на повторение')
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
  await expect(page.locator('.plan-approval-state .approval')).toContainText('На утверждении')

  await page.getByRole('button', { name: 'Добавить тему или урок' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Урок после отправки')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Урок после отправки' })).toBeVisible()

  // запрос на месте, и методист открывает текущую версию плана
  await page.reload()
  await ready(page)
  await expect(page.locator('.plan-approval-state .approval')).toContainText('На утверждении')

  await signIn(PEOPLE.petrov)
  await openSupervised(page, 'Grade 6 Algebra')
  await expect(page.locator('ul.plan')).toContainText('Урок после отправки')
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

test('отправка и её состояние — в панели действий, вид — в шапке', async ({
  page,
  signIn,
  api,
}) => {
  /*
   * Разговор один — отправить и узнать, что вышло, — и стоял он когда-то в
   * трёх разных концах экрана. Сведён он был в шапку, и это чинило
   * разорванность, но не место: шапка отвечает на «что открыто», а кнопка,
   * отправляющая план другому человеку, — действие, и стояла она рядом с
   * выходом из плана.
   *
   * Теперь действие и его состояние стоят там же, где остальные действия
   * над планом, а в шапке остался вид: сравнение — не действие, а другая
   * страница, и панели в ней не показывается вовсе.
   */
  const { course } = await makeMethodist(api, PEOPLE.ivanova, 'Grade 6 Algebra')

  const teacher = await api(PEOPLE.ivanova)
  await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})
  await teacher.post(`/api/plan/reviews/${course.id}/approve/`, {})

  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  const tools = page.locator('.plan-tools')
  await expect(tools.getByRole('button', { name: 'На утверждение' })).toBeVisible()
  await expect(tools.locator('.plan-approval-state')).toContainText('Утверждён')

  // в шапке от утверждения остался только вид
  const head = page.locator('.page-header')
  await expect(head.getByRole('radio', { name: 'Сравнение' })).toBeVisible()
  await expect(head.getByRole('button', { name: 'На утверждение' })).toHaveCount(0)

  // и ни в одном меню отправки нет: одно действие — одно место
  for (const menu of ['Файл', 'Библиотека']) {
    await page.getByRole('button', { name: menu, exact: true }).click()
    await expect(
      page
        .locator('.plan-menu .dropdown')
        .getByRole('button', { name: 'На утверждение' }),
    ).toHaveCount(0)
  }
})

test('шапка называет курс, год и ведущего, а у полки — автора', async ({
  page,
  signIn,
  api,
}) => {
  /*
   * Одной строкой «Курс: 7Б Физика» это было, и строка отвечала на половину
   * вопроса: у плана курса есть ещё учебный год и ведущий, и оба нужны как
   * раз тогда, когда планов много — «Grade 6 Algebra» бывает и
   * прошлогодней, и чужой.
   */
  await signIn(PEOPLE.ivanova)
  await openPlan(page, 'Grade 6 Algebra')

  await expect(page.getByRole('heading', { name: 'Учебный план' })).toBeVisible()
  const about = page.locator('.plan-about')
  await expect(about).toContainText('курс: Grade 6 Algebra')
  await expect(about).toContainText('учебный год:')
  await expect(about).toContainText('учитель: Мария Иванова')

  // у заготовки заголовок свой: она не про курс вовсе, и сказать это
  // подписью под общим заголовком мало — по ссылке читают заголовок
  const client = await api(PEOPLE.ivanova)
  const shelf = await client.get('/api/library/templates/?mine=true')
  await page.goto(`/library/${shelf.body[0].id}`)
  await ready(page)

  await expect(
    page.getByRole('heading', { name: 'Учебный план с полки (без курса)' }),
  ).toBeVisible()
  await expect(page.locator('.plan-about')).toContainText('автор: Мария Иванова')
  await expect(page.locator('.plan-about')).not.toContainText('учебный год:')
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

  // Экрана «заведите курс» тут быть не должно: присланный план — его работа,
  // и она предлагается витриной. Сам собой курс больше не открывается вовсе
  // (страница не выбирает за человека), поэтому проверяется именно то, ради
  // чего эта ветка заведена: поднадзорный курс человеку **предложен**, и
  // предложен в своей области — «Курсы коллег», а не вперемешку со своими.
  await expect(page.getByRole('heading', { name: 'Выберите план' })).toBeVisible()

  const colleagues = page.locator('.showcase-area', { hasText: 'Группы коллег' })
  const offered = colleagues.getByRole('button', { name: /Grade 6 Algebra/ })
  await expect(offered).toBeVisible()
  // и он же назван действием: этот план ждёт подписи именно этого человека
  await expect(offered.locator('.badge.waiting')).toBeVisible()

  await offered.click()

  // выбор уехал в адрес: с витрины иначе некуда уйти, а «назад» должно
  // возвращать к выбору, а не к прошлому курсу
  await expect(page).toHaveURL(new RegExp(`[?&]course=${course.id}\\b`))

  // и открытое названо словами — заголовком, а не серым контролом
  await expect(page.locator('.open-name')).toHaveText('курс: Grade 6 Algebra')
  await expect(page.locator('.plan .plan-row').first()).toBeVisible()
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

  // числа, из которых сложен резерв, — той же плашкой, что у учителя над
  // таблицей: без них минус приходится принимать на веру
  const totals = row.locator('[data-card="totals"]')
  await expect(totals.locator('[data-card="slots"] b')).not.toBeEmpty()
  await expect(totals).toContainText('уроков в плане')

  // и план тоже виден: право читать даёт назначение методистом, а очередь
  // на подпись была просто единственным входом. Заголовок при этом другой —
  // это рабочий черновик, за который автор ещё не отвечал
  await expect(page.getByRole('heading', { name: 'План курса' })).toBeVisible()
  await expect(page.locator('.plan-row.lesson').first()).not.toBeEmpty()

  // решать при этом нечего, и кнопок нет: они обещали бы то, чего сервер
  // не сделает
  await expect(page.getByRole('button', { name: 'Утвердить' })).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Вернуть с замечанием' }),
  ).toHaveCount(0)
})

test('ждущий подписи назван действием, а не спрятан среди поднадзорных', async ({
  page,
  signIn,
  api,
}) => {
  /*
   * Раньше это проверялось по группам селектора: «Ждут ответа» и «Под
   * надзором» стояли отдельными `optgroup`. Селекта на плане больше нет —
   * выбирают на витрине, — и вопрос переехал вместе с ним, но остался тем
   * же: из двух чужих курсов один требует решения, и по экрану должно быть
   * видно, какой.
   *
   * Витрина делит планы по двум осям, а «ждёт решения» — не третья ось:
   * это не свойство курса, а то, что человеку с ним делать. Поэтому оно и
   * стоит пометкой на самой записи, а не отдельной областью.
   */
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Algebra')
  await makeMethodist(api, PEOPLE.petrov, 'Grade 6 Geometry')

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const algebra = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  await teacher.post(`/api/plan/baseline/submit/?course=${algebra.id}`, {})

  await signIn(PEOPLE.petrov)
  await page.goto('/plan')
  await ready(page)

  const colleagues = page.locator('.showcase-area', { hasText: 'Группы коллег' })
  const waiting = colleagues.getByRole('button', { name: /Grade 6 Algebra/ })
  const watched = colleagues.getByRole('button', { name: /Grade 6 Geometry/ })

  // оба чужих — в одной области: разделяет их не место, а пометка
  await expect(waiting).toHaveCount(1)
  await expect(watched).toHaveCount(1)
  await expect(waiting.locator('.badge.waiting')).toHaveCount(1)
  await expect(watched.locator('.badge.waiting')).toHaveCount(0)

  // а своё и чужое разделено именно местом — это разные роли
  const mine = page.locator('.showcase-area', { hasText: 'Мои группы' })
  await expect(mine.getByRole('button', { name: /Grade 6 Algebra/ })).toHaveCount(0)
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

  // и открыт он как свой: заголовок называет курс, роль говорит «правите»
  await expect(page.locator('.open-name')).toHaveText('курс: Grade 6 Algebra')
  await expect(page.locator('.open-role')).toHaveText('правите')

  // отправляем на утверждение — решать можно тут же, по ссылке
  await page.getByRole('button', { name: 'На утверждение' }).click()
  await expect(page.locator('.plan-approval-state .approval.pending')).toContainText('На утверждении')
  await expect(page.locator('.plan-approval-state .approval.self')).toContainText(
    'Методист этого курса — вы.',
  )

  await page.getByRole('button', { name: 'Рассмотреть запрос' }).click()
  await expect(page.locator('.plan .plan-row').first()).toBeVisible()
  await page.getByRole('button', { name: 'Утвердить' }).click()

  // после решения возвращаемся к своему плану, и оно уже записано.
  // Сперва — что решать больше нечего: список надзора перечитывается
  // фоном, и это единственное утверждение здесь, которое умеет подождать
  await expect(page.locator('ul.plan .plan-row.lesson').first()).toBeVisible()
  await expect(page.locator('.plan-approval-state .approval.self')).toHaveCount(0)
  await expect(page.locator('.plan-approval-state .approval.approved')).toContainText('Утверждён')
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
  await teacher.post(`/api/plan/reviews/${course.id}/approve/`, {})

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
  await methodist.post(`/api/plan/reviews/${course.id}/approve/`, {})

  // после утверждения учитель дописывает урок и снова шлёт на подпись
  await teacher.post('/api/plan/', { course: course.id, title: 'Дополнительный урок' })
  await teacher.post(`/api/plan/baseline/submit/?course=${course.id}`, {})

  await signIn(PEOPLE.petrov)
  await openSupervised(page, 'Grade 6 Algebra')
  await expect(page.locator('.plan .plan-row').first()).toBeVisible()

  await page.getByRole('radio', { name: 'Сравнение' }).click()
  const added = page.locator('.diff-row.added')
  await expect(added).toHaveCount(1)
  await expect(added).toContainText('Дополнительный урок')
  // список плана уступил место сравнению, а не встал рядом с ним
  await expect(page.locator('ul.plan')).toHaveCount(0)

  await page.getByRole('radio', { name: 'План', exact: true }).click()
  await expect(page.locator('.plan .plan-row').first()).toBeVisible()
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
    await teacher.post(`/api/plan/reviews/${course.id}/approve/`, {})
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

test('чужой план школы открывается на чтение любому учителю', async ({
  page,
  signIn,
}) => {
  /*
   * Ради этого правило и меняли: живой план соседа читать было нечем.
   *
   * Библиотека отвечала снимком, который кто-то догадался положить на полку,
   * а сам план курса видели ровно двое — назначенный методист и
   * администратор школы. Ивановой ни та, ни другая роль не досталась: в
   * посеве методистов нет вовсе, а администратор — завуч.
   */
  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)

  // курс Петрова — в области «Курсы коллег», а не вперемешку со своими
  const colleagues = page.locator('.showcase-area', { hasText: 'Группы коллег' })
  await expect(
    colleagues.getByRole('button', { name: /Grade 9 Algebra/ }),
  ).toHaveCount(1)

  await pickPlan(page, 'Grade 9 Algebra')

  // план виден целиком, вместе с числами и именем ведущего
  await expect(page.locator('.plan .plan-row').first()).toBeVisible()
  await expect(page.locator('ul.plan')).toContainText('Точки и прямые')
  await expect(page.locator('.progress-list')).toContainText('Пётр Петров')

  // и виден он раскладкой, а не программой без дат: «когда у вас
  // производная» и «на чём вы остановились» — это и есть те вопросы, с
  // которыми приходят к чужому плану
  // у темы ячейка даты пустая по построению — её диапазон стоит в строках,
  // — поэтому спрашиваем строку урока
  await expect(
    page.locator('ul.plan .plan-row.lesson .plan-date').first(),
  ).not.toBeEmpty()

  // Таблица та же, что у автора, — и только на чтение.
  //
  // Раньше тут стояло «таблицы нет вовсе»: чужой план показывали отдельным
  // списком названий. Теперь список и таблица — одно, а разница между
  // «править» и «смотреть» это набор органов управления, и проверяется
  // именно он: ни ручки перетаскивания, ни кнопок строки, ни флажков
  // выбора, ни панели инструментов, ни решения по утверждению.
  await expect(page.locator('ul.plan button.handle')).toHaveCount(0)
  await expect(page.locator('ul.plan .row-actions button')).toHaveCount(0)
  await expect(page.locator('ul.plan input[type="checkbox"]')).toHaveCount(0)
  await expect(page.locator('.plan-tools')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Утвердить' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Вернуть' })).toHaveCount(0)

  // а свой открывается как открывался — правкой. Дорога к нему теперь через
  // витрину: у открытого плана селекта нет, есть заголовок и кнопка назад
  await page.getByRole('button', { name: /К выбору планов/ }).click()
  await ready(page)
  await pickPlan(page, 'Grade 6 Algebra')
  await expect(page.locator('ul.plan .plan-row.lesson').first()).toBeVisible()
  await expect(page.locator('.plan-tools')).toBeVisible()
})

test('чужой план ищется учителем и предметом, а не глазами', async ({
  page,
  signIn,
}) => {
  // Вся школа — это несколько десятков строк, и «найти план Петровой по
  // геометрии» в них значит прочитать весь список. Сужение по учителю
  // стояло у селекта в шапке и переехало на витрину вместе с самим поиском
  // плана: два места, спрашивающих одно и то же, заставляли бы гадать,
  // которое главное.
  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)

  await page.getByLabel('Любой учитель').selectOption({ label: 'Пётр Петров' })

  const colleagues = page.locator('.showcase-area', { hasText: 'Группы коллег' })
  await expect(
    colleagues.getByRole('button', { name: /Grade 9 Algebra/ }),
  ).toHaveCount(1)
  // курсы других учителей ушли из списка
  await expect(
    colleagues.getByRole('button', { name: /Grade 6 Physics/ }),
  ).toHaveCount(0)
  // и своё сузилось тем же вопросом: у Петрова своих курсов Ивановой нет
  const mine = page.locator('.showcase-area', { hasText: 'Мои группы' })
  await expect(mine.getByRole('button')).toHaveCount(0)
})

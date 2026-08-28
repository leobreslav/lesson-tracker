import { PEOPLE, expect, liveCourse, pickMoveMode, ready, test } from './harness.js'

/**
 * Scenarios 4 and 5: living with a personal schedule.
 *
 * The seeded week is Ivanova's, so the tests drive her. Dates are fixed by
 * `seed_demo` — the year is 2026/2027 and the first full week starts on
 * Monday 7 September — which is why they can be written down here.
 */

const MONDAY = '2026-09-07'
const THURSDAY = '2026-09-10'
const FRIDAY = '2026-09-11'
// inside the seeded autumn break: 26 October — 3 November
const IN_BREAK = '2026-10-28'

/** Point the agenda at a week without clicking through the arrows. */
async function openWeek(page, date) {
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(date)
  await expect(page.locator(`[data-day-head="${date}"]`)).toBeVisible()
}

test('урок ставится рядом и в своём расписании', async ({ page, signIn, api }) => {
  // Ряд заводится с обоих экранов: сетку рядами строит и администратор, и
  // учитель у себя. Диалоги разные, а повтор в них один и тот же блок —
  // проверяем, что учительский путь не остался без него.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await page.locator(`[data-add="${MONDAY}:7"]`).click()
  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  // кабинет спрашивают в том же окне, что и повтор, значит он свойство
  // ряда целиком. Терялся он молча и на обеих сторонах разом: занятия
  // появлялись, число в отчёте сходилось, кабинета не было ни у одного
  await add.getByLabel('Кабинет').fill('Лаборатория')
  await add.getByRole('radio', { name: 'через неделю' }).check()
  // «до» подстрокой попадает и в «дополнительный урок» — берём точное
  await add.getByLabel('до', { exact: true }).fill('2026-10-05')
  await add.getByRole('button', { name: 'Добавить', exact: true }).click()

  await expect(add).toBeHidden()
  // отчёт тот же, что у копирования периода: создано, пропущено, помехи
  await expect(page.getByText(/Создано уроков/)).toBeVisible()
  await expect(page.locator(`[data-lesson="${MONDAY}:7"]`)).toBeVisible()

  const teacher = await api(PEOPLE.ivanova)
  const slots = await teacher.get('/api/slots/?start=2026-09-01&end=2027-05-31')
  // именно наш ряд: седьмой час в демо-данных занят и дополнительным
  // уроком соседнего курса — он про другое
  const row = slots.body
    .filter(
      (slot) => slot.lesson_number === 7 && slot.course_name === 'Grade 6 Algebra',
    )
    .sort((a, b) => a.date.localeCompare(b.date))

  // «через неделю» — каждый второй понедельник, и ни одного за границей
  expect(row.map((slot) => slot.date)).toEqual([
    '2026-09-07',
    '2026-09-21',
    '2026-10-05',
  ])
  // и кабинет достался каждому часу, а не только первому
  expect(row.map((slot) => slot.room_name)).toEqual([
    'Лаборатория',
    'Лаборатория',
    'Лаборатория',
  ])
})

test('любое нажатие по уроку открывает одно и то же меню', async ({
  page,
  signIn,
}) => {
  // Разделено по частоте это было: левое вело прямо в занятие, меню висело
  // на правой кнопке. Экономия одного нажатия обошлась дороже — правая
  // кнопка ничем себя не показывает, и отмену с переносом просто не
  // находили. В занятие теперь ведёт первый пункт меню.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const lesson = page.locator(`[data-lesson="${MONDAY}:1"]`)
  const menu = page.locator('.context-menu')

  // правое — меню, и браузерного контекстного меню при этом не появляется
  await lesson.click({ button: 'right' })
  // выпадающее меню у курсора, а не окно посреди экрана
  await expect(menu).toBeVisible()
  await expect(page.locator('dialog.modal')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)

  // левое — то же самое меню
  await lesson.click()
  await expect(menu).toBeVisible()

  // клик мимо закрывает — меню не окно, затемнения у него нет
  await page.locator('h1').click()
  await expect(menu).toHaveCount(0)

  // в занятие ведёт первый пункт
  await lesson.click()
  await menu.getByRole('button', { name: 'Открыть урок' }).click()
  await ready(page)
  await expect(page).toHaveURL(/\/lesson\/\d+$/)
})

test('ряд убирается рядом, а не периодом', async ({ page, signIn, api }) => {
  // Кнопки «очистить период» больше нет: она сносила всё подряд, включая
  // чужие часы, стоящие в тех же неделях. Сетку строят рядами, разбирать
  // её надо так же — из той клетки, на которую смотрят.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  // ряд на четыре недели, чтобы было что убирать
  await page.locator(`[data-add="${MONDAY}:7"]`).click()
  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  await add.getByRole('radio', { name: 'каждую неделю' }).check()
  await add.getByLabel('до', { exact: true }).fill('2026-09-28')
  await add.getByRole('button', { name: 'Добавить', exact: true }).click()
  await expect(add).toBeHidden()

  const teacher = await api(PEOPLE.ivanova)
  const before = await teacher.get('/api/slots/?start=2026-09-01&end=2027-05-31')
  expect(
    before.body.filter(
      (slot) => slot.lesson_number === 7 && slot.course_name === 'Grade 6 Algebra',
    ),
  ).toHaveLength(4)

  // и убираем его из второй недели: этот час и все такие же дальше
  await openWeek(page, '2026-09-14')
  // меню — правой кнопкой: левая теперь ведёт в само занятие
  await page.locator('[data-lesson="2026-09-14:7"]').click({ button: 'right' })
  const menu = page.locator('.context-menu')
  await menu.getByRole('button', { name: 'Удалить весь ряд…' }).click()
  // подтверждение — отдельным шагом, но в том же меню
  await menu.getByRole('button', { name: 'Удалить ряд', exact: true }).click()

  await expect(menu).toHaveCount(0)
  await expect(page.getByText(/Удалено уроков ряда/)).toBeVisible()

  const after = await teacher.get('/api/slots/?start=2026-09-01&end=2027-05-31')
  const left = after.body
    .filter(
      (slot) => slot.lesson_number === 7 && slot.course_name === 'Grade 6 Algebra',
    )
    .map((slot) => slot.date)

  // первая неделя не тронута: убирали «этот и дальше», а не весь ряд
  expect(left).toEqual([MONDAY])
})

test('урок добавляется, отменяется с причиной и возвращается', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  // an hour the seeded week leaves free
  const cell = page.locator(`[data-add="${MONDAY}:6"]`)
  await cell.click()

  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  await add.getByRole('button', { name: 'Добавить' }).click()

  const lesson = page.locator(`[data-lesson="${MONDAY}:6"]`)
  await expect(lesson).toBeVisible()
  await expect(lesson).toContainText('Grade 6 Algebra')

  // cancel it, with a reason — меню открывает правая кнопка
  await lesson.click({ button: 'right' })
  const menu = page.locator('.context-menu')
  await menu.getByRole('button', { name: 'Отменить' }).click()
  // причину спрашивают там же, в меню: окна ради двух строк ввода нет
  await menu.getByPlaceholder('Причина отмены').fill('Болезнь')
  await menu.getByRole('button', { name: 'Отменить урок' }).click()

  await expect(menu).toHaveCount(0)
  await expect(lesson).toHaveClass(/cancelled/)

  // and put it back
  await lesson.click({ button: 'right' })
  await page.locator('.context-menu').getByRole('button', { name: 'Вернуть' }).click()

  await expect(lesson).not.toHaveClass(/cancelled/)

  // the round trip survived a reload, so it reached the server. The agenda
  // opens on today's week after a reload, so the week has to be asked for
  // again — the anchor is view state, not something worth persisting
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:6"]`)).toBeVisible()
})

test('дополнительный час возвращается в обычные из того же меню', async ({
  page,
  signIn,
}) => {
  /*
   * Пометку можно было только поставить, при создании, — снять её было
   * нечем. В шапке меню при этом стояло «Дополнительный урок.», то есть
   * единственное свойство часа, которое видно, но не правится; вернуть его
   * в сетку значило удалить и завести заново, потеряв всё накопленное.
   */
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await page.locator(`[data-add="${MONDAY}:6"]`).click()
  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  await add.getByRole('checkbox', { name: 'дополнительный урок' }).check()
  await add.getByPlaceholder('Пояснение: замена, кружок…').fill('Замена коллеги')
  await add.getByRole('button', { name: 'Добавить', exact: true }).click()

  const lesson = page.locator(`[data-lesson="${MONDAY}:6"]`)
  await expect(lesson).toHaveClass(/extra/)

  await lesson.click({ button: 'right' })
  const menu = page.locator('.context-menu')
  // и пометка, и причина видны в шапке — снимаются они вместе
  await expect(menu).toContainText('Дополнительный урок.')
  await menu.getByRole('button', { name: 'Сделать обычным' }).click()

  await expect(menu).toHaveCount(0)
  await expect(lesson).not.toHaveClass(/extra/)

  // уехало на сервер, а не нарисовалось; и пункта больше нет — снимать нечего
  await openWeek(page, MONDAY)
  const back = page.locator(`[data-lesson="${MONDAY}:6"]`)
  await expect(back).not.toHaveClass(/extra/)
  await back.click({ button: 'right' })
  await expect(
    page.locator('.context-menu').getByRole('button', { name: 'Сделать обычным' }),
  ).toHaveCount(0)
})

test('у отменённого часа пункта «Сделать обычным» нет', async ({ page, signIn }) => {
  // Причина у отменённого принадлежит отмене, а пункт стирает причину
  // вместе с пометкой. Поэтому путь назад там в два шага: сперва «Вернуть»
  // — он и причину уберёт, — и только потом снимается «дополнительный».
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await page.locator(`[data-add="${MONDAY}:6"]`).click()
  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  await add.getByRole('checkbox', { name: 'дополнительный урок' }).check()
  await add.getByRole('button', { name: 'Добавить', exact: true }).click()

  const lesson = page.locator(`[data-lesson="${MONDAY}:6"]`)
  const menu = page.locator('.context-menu')

  await lesson.click({ button: 'right' })
  await menu.getByRole('button', { name: 'Отменить' }).click()
  await menu.getByRole('button', { name: 'Отменить урок' }).click()
  await expect(lesson).toHaveClass(/cancelled/)

  // у отменённого в меню только «Вернуть»
  await lesson.click({ button: 'right' })
  await expect(menu.getByRole('button', { name: 'Сделать обычным' })).toHaveCount(0)
  await menu.getByRole('button', { name: 'Вернуть' }).click()

  // а после возврата пункт на месте
  await lesson.click({ button: 'right' })
  await expect(menu.getByRole('button', { name: 'Сделать обычным' })).toBeVisible()
})

test('из расписания открывается сам урок, а не только правка клетки', async ({
  page,
  signIn,
}) => {
  // Меню отвечало только на вопрос «что сделать с клеткой» — отменить,
  // перенести, удалить, — и попасть отсюда в занятие было нечем: шли через
  // «Сегодня» и долистывали до нужного дня.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const lesson = page.locator(`[data-lesson="${MONDAY}:1"]`)
  await expect(lesson).toContainText('Grade 6 Algebra')
  await lesson.click({ button: 'right' })

  await page.locator('.context-menu').getByRole('button', { name: 'Открыть урок' }).click()
  await ready(page)

  await expect(page).toHaveURL(/\/lesson\/\d+$/)
  await expect(page.locator('.lesson-title-head .hint').first()).toContainText(
    'Grade 6 Algebra',
  )
})

test('из клетки расписания есть путь в план, на эту самую строку', async ({
  page,
  signIn,
}) => {
  // Из клетки можно было уйти в занятие, а в программу — нет: «что мы
  // вообще проходим и где мы в ней сейчас» приходилось искать, открыв
  // занятие и оттуда перейдя в план. Меню теперь называет строку и ведёт
  // прямо на неё: на сотне уроков искать её глазами — минута.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await page.locator(`[data-lesson="${MONDAY}:1"]`).click({ button: 'right' })
  const menu = page.locator('.context-menu')
  // тема названа до нажатия: видно, куда приведут. Своим классом, а не
  // «последней подсказкой»: их в меню несколько, и приезжает она позже
  // остальных — строку плана спрашивают отдельным запросом
  const topic = await menu.locator('.menu-topic').textContent()
  await menu.getByRole('button', { name: 'Открыть в учебном плане' }).click()

  await ready(page)
  await expect(page).toHaveURL(/\/plan/)
  // строка подсвечена, и это именно она
  const spotlight = page.locator('.plan-row.spotlight')
  await expect(spotlight).toBeVisible()
  await expect(spotlight).toContainText(topic.split('·').pop().trim())
})

test('окно закрывается крестиком, а отдельной кнопки для этого нет', async ({
  page,
  signIn,
}) => {
  // «Закрыть» ничего не решала, только уводила, — и занимала место в ряду
  // рядом с настоящими действиями. Уйти можно было и до неё, но Escape с
  // кликом по фону беззвучны: ниоткуда не видно, что они есть.
  //
  // Спрашивается это у окна добавления: меню урока окном быть перестало,
  // а правило про крестик — про окна.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await page.locator(`[data-add="${MONDAY}:6"]`).click()
  const dialog = page.locator('dialog.modal')
  await expect(dialog.getByRole('button', { name: 'Добавить', exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toHaveCount(0)

  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()
  await expect(dialog).toBeHidden()
})

test('копирование недели на месяц не ставит уроки в каникулы', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  // select the week by its day headers: Monday, then Shift+click on Friday
  await page.locator(`[data-day-head="${MONDAY}"]`).click()
  await page.locator(`[data-day-head="${FRIDAY}"]`).click({ modifiers: ['Shift'] })

  await expect(page.locator('.selection-bar')).toBeVisible()
  await page.getByRole('button', { name: 'Скопировать на период' }).click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('С', { exact: true }).fill('2026-10-19')
  await dialog.getByLabel('по', { exact: true }).fill('2026-11-06')
  await dialog.getByRole('button', { name: 'Скопировать' }).click()

  await expect(dialog).toBeHidden()

  // the week of the break must have stayed empty — the calendar is what the
  // copy asks, and this is the assertion that proves it did
  const teacher = await api(PEOPLE.ivanova)
  const during = await teacher.get(
    `/api/slots/?start=${IN_BREAK}&end=${IN_BREAK}`,
  )
  expect(during.body).toEqual([])

  // while the working weeks on either side did receive lessons
  const after = await teacher.get('/api/slots/?start=2026-11-04&end=2026-11-06')
  expect(after.body.length).toBeGreaterThan(0)
})

test('«через неделю» копирует в каждую вторую', async ({ page, signIn, api }) => {
  // Курс, который идёт раз в две недели, копированием каждой недели получал
  // вдвое больше уроков, чем бывает. Курс здесь живой и пустой: у
  // посеянного расписание расписано на год вперёд, и копировать в него
  // нечего — все номера заняты.
  const { course, slots, teacher } = await liveCourse(api, { record: false })
  const monday = slots[0].date

  await signIn(PEOPLE.ivanova)
  await openWeek(page, monday)

  await page.locator(`[data-day-head="${monday}"]`).click()
  await page.getByRole('button', { name: 'Скопировать на период' }).click()

  const dialog = page.locator('dialog.modal')
  // только живой курс: у соседей та же неделя занята
  const picker = dialog.locator('.class-picker')
  // сперва дождаться, пока список курсов доедет. Пустой пикер снимать
  // нечего, а курсы, пришедшие следом, встают отмеченными — копирование
  // заберёт соседей, живой курс упрётся в занятые номера, и «уроков 0»
  // объяснить будет нечем
  await expect(picker.getByText(course.name, { exact: true })).toBeVisible()

  // «снять все», а потом отметить один: набирать нужное с пустого набора
  // дешевле, чем снимать лишнее с полного — ровно ради этого кнопки и есть
  await picker.getByRole('button', { name: 'снять все' }).click()
  await picker.getByRole('checkbox', { name: course.name, exact: true }).check()
  await expect(picker.locator('.class-items input:checked')).toHaveCount(1)

  const shift = (days) => {
    const at = new Date(`${monday}T12:00:00`)
    at.setDate(at.getDate() + days)
    return at.toISOString().slice(0, 10)
  }
  await dialog.getByLabel('С', { exact: true }).fill(shift(7))
  await dialog.getByLabel('по', { exact: true }).fill(shift(27))
  await dialog.getByRole('radio', { name: 'Через неделю' }).check()

  const preview = await dialog.locator('.copy-preview').textContent()
  await dialog.getByRole('button', { name: 'Скопировать' }).click()
  await expect(dialog).toBeHidden()

  // чётность считается от источника: заполняется вторая неделя цели
  const week = async (from) =>
    (await teacher.get(`/api/slots/?course=${course.id}&start=${shift(from)}&end=${shift(from + 6)}`))
      .body.length

  /*
   * Улики на случай падения.
   *
   * Тест изредка падает в полном наборе и ни разу — в одиночку (пять
   * прогонов подряд). «Создано 0» само по себе не говорит ничего: то ли
   * скопировали не тот курс, то ли не тот период, то ли предпросмотр
   * обещал то же самое. Поэтому в сообщение едут и он, и всё, что
   * оказалось у курса в целевом периоде.
   */
  const landed = (
    await teacher.get(
      `/api/slots/?course=${course.id}&start=${shift(7)}&end=${shift(27)}`,
    )
  ).body.map((slot) => `${slot.date}#${slot.lesson_number}`)
  const where = `источник ${monday}, цель ${shift(7)}—${shift(27)}, ` +
    `создано: ${landed.join(', ') || 'ничего'}, предпросмотр: ${preview}`

  expect(await week(7), where).toBe(0)
  expect(await week(14), where).toBeGreaterThan(0)
  expect(await week(21), where).toBe(0)
  // предпросмотр обещал ровно столько же
  expect(preview, where).toContain(String(await week(14)))
})

test('вида «месяц» нет, а сводки под сеткой — тем более', async ({
  page,
  signIn,
}) => {
  // Месяц был вторым видом той же сетки и отвечал на вопрос «в какую неделю
  // пойти», а на него отвечает поле «перейти к дате». Сводка под сеткой
  // считала уроки за период по курсам — числа, за которыми никто не
  // приходил: расписание читают клетками.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await expect(page.locator('.agenda-summary')).toHaveCount(0)
  for (const name of ['Неделя', 'Месяц']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  // сетка при этом на месте, и она недельная
  await expect(page.locator('.week-grid')).toBeVisible()
  await expect(page.locator('.agenda-months')).toHaveCount(0)
})

test('неучебные дни в сетке приглушены и подписаны', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, IN_BREAK)

  const head = page.locator(`[data-day-head="${IN_BREAK}"]`)
  await expect(head).toHaveClass(/locked/)
  await expect(head).toContainText('Осенние каникулы')
})
test('перенос оставляет отмену на прежнем месте и занятие на новом', async ({
  page,
  signIn,
}) => {
  // Перенос — не правка даты: календарной оси нужен след срыва и его
  // компенсации, иначе год к маю выглядит идеально ровным.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const cell = page.locator(`[data-add="${MONDAY}:7"]`)
  await cell.click()
  const add = page.locator('dialog.modal')
  await add.getByRole('combobox').first().selectOption({ label: 'Grade 6 Algebra' })
  await add.getByRole('button', { name: 'Добавить' }).click()

  const source = page.locator(`[data-lesson="${MONDAY}:7"]`)
  await expect(source).toBeVisible()

  await source.click({ button: 'right' })
  const menu = page.locator('.context-menu')
  await menu.getByRole('button', { name: 'Перенести…' }).click()
  await menu.getByLabel('Новая дата').fill(FRIDAY)
  await menu.getByLabel('Номер урока').fill('7')
  await menu.getByRole('button', { name: 'Перенести', exact: true }).click()

  await expect(menu).toHaveCount(0)
  await expect(source).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${FRIDAY}:7"]`)).toBeVisible()

  // обе половины уехали на сервер, а не только нарисовались
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:7"]`)).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${FRIDAY}:7"]`)).toBeVisible()
})

test('в меню переноса спрашивают, разовый он или насовсем', async ({
  page,
  signIn,
}) => {
  // Тумблер стоит внутри выпадающего меню, а не в окне, и это ровно то
  // место, где в проекте уже разъезжалась вёрстка: правило для контролов
  // формы написано потомковым селектором и достаёт до радиокнопок тумблера.
  // Поэтому тест не только выбирает режим, но и смотрит на сами сегменты.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await page.locator(`[data-lesson="${MONDAY}:1"]`).click({ button: 'right' })
  const menu = page.locator('.context-menu')
  await menu.getByRole('button', { name: 'Перенести…' }).click()

  // сегменты равной ширины и рядом, а не друг на друге
  const boxes = await menu.locator('.switch-option').evaluateAll((nodes) =>
    nodes.map((node) => node.getBoundingClientRect()),
  )
  expect(boxes).toHaveLength(2)
  expect(boxes[0].width).toBeGreaterThan(40)
  expect(boxes[1].left).toBeGreaterThanOrEqual(boxes[0].right - 1)

  // причину спрашивает только разовый: постоянной правке отменять нечего
  await expect(menu.getByPlaceholder('Почему перенесли')).toBeVisible()
  await menu.getByRole('radio', { name: 'И дальше' }).check()
  await expect(menu.getByPlaceholder('Почему перенесли')).toHaveCount(0)

  await menu.getByLabel('Новая дата').fill(THURSDAY)
  await menu.getByLabel('Номер урока').fill('4')
  await menu.getByRole('button', { name: 'Перенести', exact: true }).click()

  await expect(menu).toHaveCount(0)
  // отчёт числами — как у ряда уроков и копирования периода: часть ряда
  // могла упереться в занятый номер или каникулы
  await expect(page.getByText(/Занятий переехало/)).toBeVisible()

  // час именно переехал: на прежнем месте пусто, а не перечёркнуто
  await expect(page.locator(`[data-lesson="${THURSDAY}:4"]`)).toBeVisible()
  await expect(page.locator(`[data-lesson="${MONDAY}:1"]`)).toHaveCount(0)
})

test('перетаскивание переносит занятие так же, как меню', async ({
  page,
  signIn,
}) => {
  // Жест — второй путь к тому же переносу, и ломается он **молча**: занятие
  // поднимается, бледнеет и возвращается на место, а отличить это от
  // дрогнувшей руки нельзя. Так он и прожил всё своё время нерабочим —
  // клетка-приёмник стояла `display: contents`, то есть без прямоугольника,
  // а dnd-kit ищет приёмник пересечением прямоугольников.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  // берём посеянный первый час и целимся в середину сетки. Оба условия из
  // опыта: занятие, заведённое тут же, ещё держит сетку занятой — выключенная
  // кнопка не получает pointer-событий вовсе, — а нижние ряды при вьюпорте
  // 1280×720 лежат за краем окна, и мышь до них не доезжает. И то и другое
  // снаружи выглядит как сломанный жест, хотя сломан был бы тест
  const source = page.locator(`[data-lesson="${MONDAY}:1"]`)
  await expect(source).toBeVisible()
  await expect(source).toBeEnabled()

  const from = await source.boundingBox()
  const to = await page.locator(`[data-add="${THURSDAY}:4"]`).boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  // порог сенсора — пять пикселей, и берётся он не одним прыжком: без
  // промежуточных шагов жест не начинается вовсе
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 })

  // клетка под занятием отзывается, пока его держат. Проверяется отдельно от
  // результата: без этого «перенос не доехал» и «жест не начался» выглядят
  // одинаково, а чинятся в разных местах
  await expect(page.locator('.cell-drop.over')).toHaveCount(1)
  await page.mouse.up()

  // Бросок сам не переносит: за одним жестом два разных события — сорвался
  // час или сдвинулось расписание, — и разница вылезает к маю. Спрашивается
  // это одним нажатием там же, где отпустили.
  // меню клетки при этом не открылось: жест забирает клик себе, иначе каждый
  // перенос заканчивался бы двумя меню разом
  await expect(
    page.locator('.context-menu').getByRole('button', { name: 'Открыть урок' }),
  ).toHaveCount(0)
  await pickMoveMode(page, /Этот час/)

  await expect(source).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${THURSDAY}:4"]`)).toBeVisible()

  // обе половины уехали на сервер, как и у переноса из меню
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:1"]`)).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${THURSDAY}:4"]`)).toBeVisible()
})

test('постоянная правка расписания не оставляет ни отмены, ни лишнего часа', async ({
  page,
  signIn,
}) => {
  // Второй вид переноса, ради которого и появился выбор. Разовый пишет
  // отмену и дополнительное занятие — верно ровно тогда, когда час
  // сорвался. Расписание же меняют и насовсем, и тридцать отмен объявили бы
  // тридцать срывов, которых не было.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const source = page.locator(`[data-lesson="${MONDAY}:1"]`)
  await expect(source).toBeVisible()
  await expect(source).toBeEnabled()

  const from = await source.boundingBox()
  const to = await page.locator(`[data-add="${THURSDAY}:4"]`).boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 })
  await page.mouse.up()

  await pickMoveMode(page, /И дальше/)

  // час именно **переехал**: на прежнем месте пусто, а не перечёркнуто
  await expect(page.locator(`[data-lesson="${THURSDAY}:4"]`)).toBeVisible()
  await expect(page.locator(`[data-lesson="${MONDAY}:1"]`)).toHaveCount(0)

  // и это уехало на сервер, а не нарисовалось
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:1"]`)).toHaveCount(0)
  await expect(page.locator(`[data-lesson="${THURSDAY}:4"]`)).toBeVisible()
})


test('пока связь не записана, план со страницы урока не правится', async ({
  page,
  signIn,
}) => {
  // Своего содержания у занятия нет ни одного поля: содержание, материалы и
  // домашнее задание — это строка учебного плана, показанная отсюда. Пока
  // тема лишь подсказана раскладкой, она вполне может быть не той, и правка
  // вслепую меняла бы чужую строку молча. Поэтому кнопок нет вовсе, а выход
  // назван словами: пустое место читалось бы как поломка.
  //
  // Записанной связи браузерный набор не видит: учебный год демо-данных
  // целиком в будущем, прошедших занятий на стенде не бывает — а связать
  // можно только прошедшее. Открытый туннель проверяют питоновские тесты.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  await expect(page).toHaveURL(/\/lesson\/\d+$/)
  await expect(
    page.locator('.lesson-title-head .hint').first(),
  ).toContainText('Grade 6 Algebra')

  // записать можно только то, что уже случилось: кнопка, нажатая накануне,
  // стала бы ложью после утренней пожарной тревоги. Год демо-данных весь в
  // будущем, поэтому здесь проверяется именно эта половина правила
  await expect(page.getByRole('button', { name: 'Так и было' })).toHaveCount(0)

  // запрет объяснён словами и ссылкой в самом разделе: пустое место на
  // месте кнопки читалось бы как поломка
  await expect(
    page.getByText(/Занятие ещё не проведено/),
  ).toBeVisible()

  await expect(page.getByRole('button', { name: 'Правка…' })).toHaveCount(0)
  // и поля добавления материала нет: заводить его отсюда тоже нельзя
  await expect(page.getByLabel('Ссылка или заметка')).toHaveCount(0)

  // а на их месте — ссылка туда, где правят: полосы над блоками мало,
  // спрашивают про этот раздел и ровно там, где ищут «Правка…»
  for (const block of ['content', 'materials', 'homework'])
    await expect(
      page.locator(`[data-block="${block}"]`).getByRole('link', {
        name: 'Правка в плане…',
      }),
    ).toBeVisible()

  // и название не правится кликом: до записи это делают в плане
  await expect(page.locator('h1 button')).toHaveCount(0)

  // и ссылка приводит не «в план», а на саму строку: на сотне уроков
  // «откройте план и поищите» это минута поиска глазами
  const title = await page.locator('h1').textContent()
  await page.getByRole('link', { name: 'Открыть в учебном плане' }).click()
  await ready(page)

  // адрес вычищен: оставленный, он возил бы сюда при каждом «назад»
  await expect(page).toHaveURL(/\/plan$/)
  const row = page.locator('.plan-row.spotlight')
  await expect(row).toHaveCount(1)
  await expect(row).toContainText(title)
})

test('«Правка в плане…» открывает окно правки, а не просто план', async ({
  page,
  signIn,
}) => {
  // Приводить на подсвеченную строку и просить нажать ещё раз — лишнее
  // нажатие ради того, о чём уже попросили.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  const title = await page.locator('h1').textContent()
  await page
    .locator('[data-block="content"]')
    .getByRole('link', { name: 'Правка в плане…' })
    .click()
  await ready(page)

  await expect(page).toHaveURL(/\/plan/)
  const panel = page.locator('dialog.modal')
  await expect(panel).toBeVisible()
  await expect(panel.locator('.lesson-title')).toHaveValue(title)

  // шапка говорит, что перед вами: какая это строка программы по счёту,
  // куда она ложится по раскладке и что занятие ещё не проведено
  await expect(panel.locator('.modal-head h3')).toHaveText(
    /Урок \d+ учебного плана Grade 6 Algebra/,
  )
  await expect(panel.locator('.lesson-where')).toContainText(/По раскладке — \d+/)
  await expect(panel.locator('.lesson-where')).toContainText('ещё не проведено')

  // крестик не перекрыт прижатой шапкой панели: обе прижимаются стопкой,
  // и отрицательный отступ шапки однажды уже съел его половину
  const cross = await panel.getByRole('button', { name: 'Закрыть окно' }).boundingBox()
  const head = await panel.locator('.lesson-head').boundingBox()
  expect(
    Math.round(cross.y + cross.height),
    'шапка панели наползает на крестик',
  ).toBeLessThanOrEqual(Math.round(head.y) + 1)

  // а закрыв окно, человек возвращается в занятие, а не остаётся в плане,
  // который он и не собирался открывать
  await panel.getByRole('button', { name: 'Закрыть окно' }).click()
  await ready(page)
  await expect(page).toHaveURL(/\/lesson\/\d+$/)
  await expect(page.locator('h1')).toHaveText(title)
})

test('урок листается по своему курсу и показывает содержание', async ({
  page,
  signIn,
}) => {
  // Соседи по курсу, а не по дню: «что было на прошлом» — вопрос про этот
  // же класс, а не про то, что стояло следующим часом у другого.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  // страница про урок целиком: тема заголовком, состояние, работы
  await expect(page.getByText(/Занятие ещё не проведено/)).toBeVisible()
  await expect(page.locator('.panel-title', { hasText: 'Работы' })).toBeVisible()

  const first = await page.locator('h1').textContent()
  await page.getByRole('button', { name: '→' }).click()
  await ready(page)

  await expect(page.locator('h1')).not.toHaveText(first)
  await expect(
    page.locator('.lesson-title-head .hint').first(),
  ).toContainText('Grade 6 Algebra')

  // и обратно — тот же урок, с которого пришли
  await page.getByRole('button', { name: '←' }).click()
  await ready(page)
  await expect(page.locator('h1')).toHaveText(first)

  // содержание из плана видно прямо на странице, а не окном поверх неё:
  // расписано в демо-данных не каждое занятие, поэтому доходим до того,
  // которое расписано
  const fields = page.locator('.lesson-field')
  for (let step = 0; step < 12 && !(await fields.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(150)
  }
  await expect(fields.first()).toBeVisible()
  await expect(page.getByText('Цели')).toBeVisible()
})

/** Открыть страницу урока курса с полным планом. */
/**
 * Открыть страницу занятия так, как это делает учитель: из расписания.
 *
 * Понедельник, первый урок — «Grade 6 Algebra», курс с полным планом:
 * раскладке есть что предложить. Экрана «Сегодня» больше нет, и листать
 * дни в поисках занятия теперь не нужно: неделя видна сеткой.
 */
async function openLesson(page, cell = `${MONDAY}:1`) {
  await openWeek(page, MONDAY)
  await page.locator(`[data-lesson="${cell}"]`).click({ button: 'right' })
  await page.locator('.context-menu').getByRole('button', { name: 'Открыть урок' }).click()
  await ready(page)
  // `ready` ждёт бар и тишину в сети, а не смену страницы: заголовок
  // расписания успевает пожить на экране ещё кадр, и тест, читающий `h1`
  // сразу после, примерно раз в пять получал «Моё расписание».
  //
  // Адреса для этого мало, и это стоило второго падения: маршрутизатор
  // меняет адрес **до** того, как отрисуется новая страница, поэтому проверка
  // проходила, а `h1` ещё показывал расписание — тест шёл дальше со словом
  // «Расписание» в руках вместо названия урока. Ждать надо разметку самой
  // страницы урока, а не обещание её показать.
  await expect(page).toHaveURL(/\/lesson\/\d+$/)
  await expect(page.locator('.lesson-title-head')).toBeVisible()
}


test('страница урока идёт в порядке урока, а не наших таблиц', async ({
  page,
  signIn,
}) => {
  // Отметить пришедших, вести по содержанию, объявить работы, показать
  // материалы, задать домашнее. Экран, собранный по сущностям, заставлял бы
  // каждый раз искать глазами то, что делают следующим.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  // ждём саму страницу: `ready` возвращается до того, как приедет карточка
  await expect(page.locator('.panel-title').first()).toBeVisible()
  const blocks = await page.locator('.panel-title').allTextContents()

  expect(blocks).toEqual([
    'Посещаемость',
    'Чем занимаемся',
    'Работы',
    'Материалы',
    'Домашнее задание',
  ])
})

test('журнал ведётся кнопками, и отметка снимается повторным нажатием', async ({
  page,
  signIn,
}) => {
  // Три кнопки в строке, а не список: на двадцати учениках список это
  // двадцать открываний, а отметка ставится взглядом. Повторное нажатие
  // снимает — тот же приём, что у вердикта в проверке работ.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  // блок свёрнут: на двадцати учениках развёрнутый журнал — экран с лишним,
  // и всё остальное про урок оказывается ниже него
  const rows = page.locator('.attendance > li')
  await expect(rows).toHaveCount(0)

  await page.getByRole('button', { name: /Посещаемость/ }).click()
  await expect(rows.first()).toBeVisible()
  const total = await rows.count()
  await expect(page.getByText(`отмечено 0 из ${total}`)).toBeVisible()

  const first = rows.first()
  await first.getByRole('button', { name: 'не был' }).click()

  await expect(first).toHaveClass(/absent/)
  await expect(page.getByText(`отмечено 1 из ${total}`)).toBeVisible()

  // отметка настоящая: пережила перезагрузку. Открытым журнал тоже остался
  // — свёрнутость запоминается: закрыть или открыть раздел это привычка
  // человека, а не состояние занятия
  await page.reload()
  await ready(page)
  await expect(page.locator('.attendance > li').first()).toHaveClass(/absent/)
  await expect(page.getByText(`отмечено 1 из ${total}`)).toBeVisible()

  // повторное нажатие снимает: «не отмечен» — это отсутствие строки
  await page.locator('.attendance > li').first().getByRole('button', { name: 'не был' }).click()

  await expect(page.locator('.attendance > li').first()).toHaveClass(/unmarked/)
  await expect(page.getByText(`отмечено 0 из ${total}`)).toBeVisible()
})

test('работа заводится прямо на уроке и остаётся привязанной к нему', async ({
  page,
  signIn,
}) => {
  // Блок «Работы» до сих пор только читал: привязать работу к занятию через
  // интерфейс было нечем, и на живых данных он всегда пустовал.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  // пустой раздел — одна строка со словом «пусто», а не карточка с фразой.
  // Слово одно на все разделы: «нет» у работ рядом с «пусто» у содержания
  // читалось как разница по существу, которой нет
  const worksBlock = page.locator('[data-block="works"]')
  await expect(worksBlock).toHaveClass(/empty/)
  await expect(worksBlock).toContainText('пусто')

  // действия появляются под курсором — как кнопки строки в таблице плана
  await worksBlock.hover()
  await worksBlock.getByRole('button', { name: 'Новая работа' }).click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Название').fill('Практика по признакам делимости')
  await dialog.getByRole('button', { name: 'Сохранить' }).click()

  await expect(dialog).toBeHidden()
  const works = page.locator('.work-links > li')
  await expect(works).toHaveCount(1)
  await expect(works.first()).toContainText('Практика по признакам делимости')

  // привязка настоящая: пережила перезагрузку страницы урока
  await page.reload()
  await ready(page)
  await expect(page.locator('.work-links > li').first()).toContainText(
    'Практика по признакам делимости',
  )
})

test('домашнее задание — та же работа, только в своём разделе', async ({
  page,
  signIn,
}) => {
  // Сущность одна, разделов два: разница в том, что задали на дом, а что
  // решают в классе. Вывести это неоткуда — пустая домашняя и пустая
  // классная в данных неразличимы.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  const homework = page.locator('[data-block="homework"]')
  const works = page.locator('[data-block="works"]')

  await homework.hover()
  await homework.getByRole('button', { name: 'Создать' }).click()
  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Название').fill('Параграф 12, № 84–89')
  await dialog.getByRole('button', { name: 'Сохранить' }).click()

  // встала в свой раздел, а не в «Работы»
  await expect(homework.locator('.work-links > li')).toHaveCount(1)
  await expect(homework.locator('.work-links > li')).toContainText('Параграф 12')
  await expect(works.locator('.work-links > li')).toHaveCount(0)

  // и осталась там после перезагрузки
  await page.reload()
  await ready(page)
  await expect(
    page.locator('[data-block="homework"] .work-links > li'),
  ).toContainText('Параграф 12')
})

test('записанная связь открывает туннель, и она же снимается плашкой', async ({
  page,
  signIn,
  api,
}) => {
  // Записать можно только прошедший час, а год посеянных данных весь в
  // будущем — поэтому курс собирается живым, настоящими запросами
  const { rows, slots } = await liveCourse(api)
  const [slot] = slots

  await signIn(PEOPLE.ivanova)
  await page.goto(`/lesson/${slot.id}`)
  await ready(page)

  // туннель открыт: правка содержания и материалов доступна отсюда.
  // Действия видны под курсором — как кнопки строки в таблице плана
  const content = page.locator('[data-block="content"]')
  const materials = page.locator('[data-block="materials"]')

  await content.hover()
  await expect(content.getByRole('button', { name: 'Правка…' })).toBeVisible()
  // материал заводится одним полем — тем же, что в окне правки строки
  // плана: вид виден из написанного, кнопок «Добавить ссылку/текст» нет
  await expect(materials.getByLabel('Ссылка или заметка')).toBeVisible()
  await expect(materials.locator('button.dropzone')).toBeVisible()
  // и объяснение запрета убрано — запрещать больше нечего
  await expect(
    page.getByText(/Занятие ещё не проведено/),
  ).toHaveCount(0)

  // название правится кликом по нему, как в таблице плана
  await page.locator('h1 button').click()
  await page.getByLabel('Новое название').fill('Синус суммы. Начало')
  await page.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('h1')).toHaveText('Синус суммы. Начало')

  // и правка настоящая: это строка плана, а не поле занятия
  const after = await api(PEOPLE.ivanova)
  const tree = await after.get(`/api/plan/?course=${rows[0].course}`)
  const titles = tree.body.nodes.map((node) => node.title)
  expect(titles).toContain('Синус суммы. Начало')

  // повторное нажатие на плашку снимает запись — как отметка в журнале
  await page.getByRole('button', { name: 'урок проведён' }).click()
  await expect(page.getByText(/Занятие ещё не проведено/)).toBeVisible()
  const locked = page.locator('[data-block="content"]')
  await expect(locked.getByRole('button', { name: 'Правка…' })).toHaveCount(0)
  await expect(locked.getByRole('link', { name: 'Правка в плане…' })).toBeVisible()
})

test('записи идут подряд, и снять можно только последнюю', async ({
  page,
  signIn,
  api,
}) => {
  // Дырка посреди закрытого хвоста — два разных факта в одном виде: «провёл,
  // но не отметил» и «не было, а отменить забыл». Пока их не различили,
  // «сколько курса пройдено» неизвестно, а это читает методист.
  const { slots } = await liveCourse(api)
  const [first, second, third] = slots

  await signIn(PEOPLE.ivanova)

  // третий час записать нельзя: второй ещё не закрыт, и сказано какой
  await page.goto(`/lesson/${third.id}`)
  await ready(page)
  await expect(page.getByRole('button', { name: 'Так и было' })).toHaveCount(0)
  const hint = page.getByRole('link', { name: /сначала/ })
  await expect(hint).toBeVisible()

  // ссылка ведёт на тот самый час, и там кнопка есть
  await hint.click()
  await ready(page)
  await expect(page).toHaveURL(new RegExp(`/lesson/${second.id}$`))
  await page.getByRole('button', { name: 'Так и было' }).click()
  await expect(page.getByRole('button', { name: 'урок проведён' })).toBeVisible()

  // а у первого запись снять уже нельзя: она больше не последняя
  await page.goto(`/lesson/${first.id}`)
  await ready(page)
  await expect(page.getByText('урок проведён')).toBeVisible()
  await expect(page.getByRole('button', { name: 'урок проведён' })).toHaveCount(0)
})

test('часу без строки плана предлагают дописать её, а не тупик', async ({
  page,
  signIn,
  api,
}) => {
  // Слотов больше, чем строк: записать нечего, отменить — соврать, а
  // очередь записи стоит. «Провели то, чего в плане нет» значит дописать
  // строку — та же доктрина, что «не успели — дописывается строка».
  const { course, rows, slots, teacher } = await liveCourse(api)
  for (const [index, slot] of slots.slice(1).entries()) {
    const done = await teacher.patch(`/api/slots/${slot.id}/`, {
      lesson: rows[index + 1].id,
    })
    expect(done.status, JSON.stringify(done.body)).toBe(200)
  }
  // четвёртый час — строк на него уже не осталось
  const spare = await teacher.post('/api/slots/', {
    course: course.id,
    date: slots[2].date,
    lesson_number: 2,
  })
  expect(spare.status, JSON.stringify(spare.body)).toBe(201)

  await signIn(PEOPLE.ivanova)
  await page.goto(`/lesson/${spare.body.id}`)
  await ready(page)

  await expect(page.getByText(/в плане не осталось строки/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Так и было' })).toHaveCount(0)

  // ссылка приводит к этому самому дню в плане, а не «в план вообще»
  await page.getByRole('link', { name: 'дописать в план' }).click()
  await ready(page)
  await expect(page.locator(`[data-slot="${spare.body.id}"]`)).toBeVisible()
  await expect(page.locator(`[data-slot="${spare.body.id}"]`)).toHaveClass(/spotlight/)
})

test('у отменённого занятия остаётся журнал, а содержания нет', async ({
  page,
  signIn,
  api,
}) => {
  // Занятия не было — значит не было ни темы, ни материалов, ни домашнего
  // задания; четыре карточки со словом «нет» сообщали об этом четырежды.
  // Журнал остаётся: «кто пришёл на урок, которого не было» — вопрос
  // законный.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const slots = await teacher.get(`/api/slots/?course=${course.id}`)
  const cancelled = slots.body.find((slot) => slot.is_cancelled)

  await signIn(PEOPLE.ivanova)
  await page.goto(`/lesson/${cancelled.id}`)
  await ready(page)

  await expect(page.locator('.panel-title').first()).toBeVisible()
  expect(await page.locator('.panel-title').allTextContents()).toEqual([
    'Посещаемость',
  ])

  // причина видна, а объяснения про план нет: темы нет не потому, что план
  // кончился, — вот настоящая причина
  await expect(page.getByText(`отменён: ${cancelled.reason}`)).toBeVisible()
  await expect(page.getByText('На этот урок в плане ничего не осталось')).toHaveCount(0)
})

test('работа, заведённая до отмены, с экрана не пропадает', async ({
  page,
  signIn,
  api,
}) => {
  // Завести работу на занятии, которого не было, нельзя — а заведённую
  // раньше прятать значит потерять из виду чужие ответы.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const slots = await teacher.get(`/api/slots/?course=${course.id}`)
  const slot = slots.body.find((item) => !item.is_cancelled)

  const created = await teacher.post('/api/works/', {
    course: course.id,
    slot: slot.id,
    title: 'Самостоятельная по дробям',
    opens_at: '2026-09-01T08:00:00Z',
    closes_at: '2027-06-01T08:00:00Z',
  })
  expect(created.status, JSON.stringify(created.body)).toBe(201)
  await teacher.patch(`/api/slots/${slot.id}/`, {
    is_cancelled: true,
    reason: 'Актированный день',
  })

  await signIn(PEOPLE.ivanova)
  await page.goto(`/lesson/${slot.id}`)
  await ready(page)

  expect(await page.locator('.panel-title').allTextContents()).toEqual([
    'Посещаемость',
    'Работы',
  ])
  await expect(page.locator('.work-links > li')).toContainText('Самостоятельная')

  // а новую завести нечем: занятия не было
  const works = page.locator('[data-block="works"]')
  await works.hover()
  await expect(works.getByRole('button', { name: 'Новая работа' })).toHaveCount(0)
})

test('занятие без строки плана открывается, а не падает', async ({
  page,
  signIn,
  api,
}) => {
  // Курс без плана — обычное состояние, а не редкость: план кончился раньше
  // расписания или его не начинали вовсе. Раздел «Чем занимаемся» в этом
  // случае пуст, тело у него не рисуется — но выражение с телом JSX
  // вычисляет всё равно, и страница валилась на строке плана, которой нет.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Geometry')
  const slots = await teacher.get(`/api/slots/?course=${course.id}`)

  await signIn(PEOPLE.ivanova)
  await page.goto(`/lesson/${slots.body[0].id}`)
  await ready(page)

  await expect(page.locator('h1')).toHaveText('(тема не назначена)')
  await expect(page.locator('[data-block="content"]')).toContainText('пусто')
  // и собственное занятия на месте: журнал от плана не зависит
  await expect(page.locator('[data-block="attendance"]')).toBeVisible()
})

test('собственные блоки занятия работают независимо от связи', async ({
  page,
  signIn,
}) => {
  // Журнал, работы и домашняя работа принадлежат занятию, а не плану, и
  // туннель их не касается: их заводят и на будущем уроке.
  await signIn(PEOPLE.ivanova)
  await openLesson(page)

  await expect(page.locator('[data-block="attendance"]')).toBeVisible()

  const works = page.locator('[data-block="works"]')
  await works.hover()
  await expect(works.getByRole('button', { name: 'Новая работа' })).toBeVisible()

  const homework = page.locator('[data-block="homework"]')
  await homework.hover()
  await expect(homework.getByRole('button', { name: 'Создать' })).toBeVisible()
})

test('записанный час помечен галочкой, а занятие с записью не удаляется', async ({
  page,
  signIn,
  api,
}) => {
  // Один факт должен выглядеть одинаково везде: в таблице плана запись —
  // зелёная галочка, и в сетке расписания тоже. А удаление такой клетки
  // уносило бы запись молча: строка плана вернулась бы в общую очередь и
  // получила другую дату.
  const { course, slots } = await liveCourse(api)
  const recorded = slots[0] // фикстура записывает первый час
  const debt = slots[1]

  await signIn(PEOPLE.ivanova)
  await openWeek(page, recorded.date)

  const cell = (slot) => page.locator(`[data-lesson="${slot.date}:${slot.lesson_number}"]`)
  await expect(cell(recorded)).toHaveClass(/recorded/)

  // К соседнему часу надо перейти: часы живого курса идут подряд, а сетка
  // показывает одну неделю — во вторник эти два дня уже в разных
  await openWeek(page, debt.date)
  // он прошёл и не записан, то есть долг, и метка у него другая
  await expect(cell(debt)).toHaveClass(/debt/)

  // сервер такое занятие не отдаёт удалить
  const teacher = await api(PEOPLE.ivanova)
  const refused = await teacher.delete(`/api/slots/${recorded.id}/`)
  expect(refused.status).toBe(400)
  expect(refused.body.code).toBe('slot_delete_recorded')

  const still = await teacher.get(`/api/slots/?course=${course.id}`)
  expect(still.body.some((slot) => slot.id === recorded.id)).toBe(true)
})

test('у записанного часа в меню нет ни отмены, ни удаления', async ({
  page,
  signIn,
  api,
}) => {
  // Обе кнопки стирают запись, и сервер их отклоняет. Кнопка, умеющая
  // только отказать, честнее не рисоваться: запись снимают на странице
  // занятия, оттуда и продолжают.
  const { slots } = await liveCourse(api)
  const recorded = slots[0]

  await signIn(PEOPLE.ivanova)
  await openWeek(page, recorded.date)

  await page
    .locator(`[data-lesson="${recorded.date}:${recorded.lesson_number}"]`)
    .click({ button: 'right' })

  const menu = page.locator('.context-menu')
  await expect(menu.getByRole('button', { name: 'Открыть урок' })).toBeVisible()
  await expect(menu.getByRole('button', { name: 'Отменить' })).toHaveCount(0)
  await expect(
    menu.getByRole('button', { name: 'Удалить', exact: true }),
  ).toHaveCount(0)
  // перенос остаётся: он не стирает запись, а везёт её с собой
  await expect(menu.getByRole('button', { name: 'Перенести' })).toBeVisible()
  // и удаление ряда остаётся: оно ничего не стирает у этого часа — он
  // переживёт операцию, и в ответе будет сказано, что уцелел
  await expect(menu.getByRole('button', { name: 'Удалить весь ряд…' })).toBeVisible()
})

test('шагов первого входа на расписании нет — они на корне', async ({
  page,
  signIn,
}) => {
  // Расписание открывают каждый день и ради сетки, а карта первого входа
  // отвечает на вопрос, который задают один раз: полтора экрана поверх
  // рабочей страницы читались как реклама.
  await signIn(PEOPLE.ivanova)

  await page.goto('/schedule')
  await ready(page)
  await expect(page.locator('.week-grid')).toBeVisible()
  await expect(page.locator('.start-here')).toHaveCount(0)
})

test('листание недель не уносит страницу в начало', async ({ page, signIn }) => {
  // Сетка заменялась строкой «Загрузка…»: страница схлопывалась, браузер
  // прижимал прокрутку к её новой высоте — и вернувшаяся сетка оказывалась
  // пролистанной в начало. Пролистал вниз, нажал стрелку — и ты наверху.
  await signIn(PEOPLE.ivanova)
  await page.goto('/schedule')
  await ready(page)
  await expect(page.locator('.week-grid')).toBeVisible()

  await page.evaluate(() => window.scrollTo(0, 300))
  const before = await page.evaluate(() => window.scrollY)
  expect(before, 'странице некуда прокручиваться — тест бессмыслен').toBeGreaterThan(100)

  // Нажимаем из кода, а не `click()`: Playwright подводит элемент под
  // курсор и сам прокручивает страницу к нему — то есть проверял бы
  // собственную прокрутку, а не поведение приложения.
  const heights = await page.evaluate(async (label) => {
    const before = document.documentElement.scrollHeight
    const button = [...document.querySelectorAll('button')].find(
      (item) => item.getAttribute('aria-label') === label,
    )
    button.click()

    // даём кадр на перерисовку «пока грузится» и ждём ответа сервера
    const seen = []
    for (let i = 0; i < 60; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 10))
      seen.push(document.documentElement.scrollHeight)
    }
    return { before, min: Math.min(...seen), last: seen.at(-1) }
  }, 'Следующая неделя')

  // страница не укорачивается ни на кадр: именно из-за этого браузер и
  // прижимал прокрутку к её новой высоте
  expect(heights.min, 'страница схлопнулась на время загрузки').toBe(heights.before)
  expect(heights.last).toBe(heights.before)
  await expect(page.locator('.week-grid')).toBeVisible()
  expect(await page.evaluate(() => window.scrollY)).toBe(before)
})

test('кабинет ставится на весь ряд, а не по клетке', async ({
  page,
  signIn,
  api,
}) => {
  /*
   * Расписание строят рядами, и кабинет — свойство того же решения, что
   * день недели и номер: «алгебра по понедельникам идёт в 214» говорят один
   * раз. Пока выбора не было, это означало тридцать четыре нажатия, и
   * первая же пропущенная клетка читалась потом как ошибка расписания, а не
   * как забытое нажатие.
   */
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const lesson = page.locator(`[data-lesson="${MONDAY}:1"]`).first()
  await lesson.click()
  const menu = page.locator('.context-menu')
  await menu.getByRole('button', { name: 'Кабинет…' }).click()

  await menu.getByLabel('Кабинет').fill('Лаборатория')
  // тот же тумблер и те же слова, что у переноса: вопрос один и тот же
  await menu.getByRole('radio', { name: 'И дальше' }).check()
  await menu.getByRole('button', { name: 'Сохранить' }).click()

  // ряд считает сервер: сколько его часов несут запись, заранее не знает
  // никто, поэтому ответ — числа, а не перерисованная неделя
  await expect(page.getByText(/Часов переставлено в этот кабинет/)).toBeVisible()

  const teacher = await api(PEOPLE.ivanova)
  const slots = await teacher.get('/api/slots/?start=2026-09-01&end=2027-05-31')
  const clicked = slots.body.find(
    (slot) => slot.date === MONDAY && slot.lesson_number === 1,
  )
  // ряд — тот же день недели и тот же номер у того же курса, вперёд
  const ahead = slots.body.filter(
    (slot) =>
      slot.course === clicked.course &&
      slot.lesson_number === 1 &&
      slot.date > MONDAY &&
      new Date(slot.date).getUTCDay() === new Date(MONDAY).getUTCDay(),
  )

  expect(clicked.room_name).toBe('Лаборатория')
  expect(ahead.length).toBeGreaterThan(0)
  // переезжают обычные часы без записи; отменённый, дополнительный и
  // записанный остаются при своём — это и есть `kept` в ответе
  const travelled = ahead.filter(
    (slot) => !slot.lesson && !slot.is_cancelled && !slot.is_extra,
  )
  expect(travelled.length).toBeGreaterThan(0)
  expect(travelled.map((slot) => slot.room_name)).toEqual(
    travelled.map(() => 'Лаборатория'),
  )
})

import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenarios 4 and 5: living with a personal schedule.
 *
 * The seeded week is Ivanova's, so the tests drive her. Dates are fixed by
 * `seed_demo` — the year is 2026/2027 and the first full week starts on
 * Monday 7 September — which is why they can be written down here.
 */

const MONDAY = '2026-09-07'
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

  // cancel it, with a reason
  await lesson.click()
  const menu = page.locator('dialog.modal')
  await menu.getByRole('button', { name: 'Отменить', exact: true }).click()
  await menu.getByPlaceholder('Причина отмены').fill('Болезнь')
  await menu.getByRole('button', { name: 'Отменить урок' }).click()

  await expect(menu).toBeHidden()
  await expect(lesson).toHaveClass(/cancelled/)

  // and put it back
  await lesson.click()
  await page.locator('dialog.modal').getByRole('button', { name: 'Вернуть' }).click()

  await expect(lesson).not.toHaveClass(/cancelled/)

  // the round trip survived a reload, so it reached the server. The agenda
  // opens on today's week after a reload, so the week has to be asked for
  // again — the anchor is view state, not something worth persisting
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:6"]`)).toBeVisible()
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
  await lesson.click()

  await page.locator('dialog.modal').getByRole('button', { name: 'Открыть урок' }).click()
  await ready(page)

  await expect(page).toHaveURL(/\/lesson\/\d+$/)
  await expect(page.locator('.lesson-title-head .hint').first()).toContainText(
    'Grade 6 Algebra',
  )
})

test('окно закрывается крестиком, а отдельной кнопки для этого нет', async ({
  page,
  signIn,
}) => {
  // «Закрыть» ничего не решала, только уводила, — и занимала место в ряду
  // рядом с четырьмя настоящими действиями. Уйти можно было и до неё, но
  // Escape с кликом по фону беззвучны: ниоткуда не видно, что они есть.
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  await page.locator(`[data-lesson="${MONDAY}:1"]`).click()
  const menu = page.locator('dialog.modal')
  await expect(menu.getByRole('button', { name: 'Открыть урок' })).toBeVisible()
  await expect(menu.getByRole('button', { name: 'Закрыть', exact: true })).toHaveCount(0)

  await menu.getByRole('button', { name: 'Закрыть окно' }).click()
  await expect(menu).toBeHidden()
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

test('сводка за неделю считает уроки и отмены', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openWeek(page, MONDAY)

  const summary = page.locator('.agenda-summary')
  await expect(summary).toContainText('За неделю')
  await expect(summary).toContainText(/\d+ урок/)
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

  await source.click()
  const menu = page.locator('dialog.modal')
  await menu.getByRole('button', { name: 'Перенести…' }).click()
  await menu.getByLabel('Новая дата').fill(FRIDAY)
  await menu.getByLabel('Номер урока').fill('7')
  await menu.getByRole('button', { name: 'Перенести', exact: true }).click()

  await expect(menu).toBeHidden()
  await expect(source).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${FRIDAY}:7"]`)).toBeVisible()

  // обе половины уехали на сервер, а не только нарисовались
  await openWeek(page, MONDAY)
  await expect(page.locator(`[data-lesson="${MONDAY}:7"]`)).toHaveClass(/cancelled/)
  await expect(page.locator(`[data-lesson="${FRIDAY}:7"]`)).toBeVisible()
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

  for (const name of ['Правка…', 'Добавить ссылку'])
    await expect(page.getByRole('button', { name })).toHaveCount(0)

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
  await expect(panel.locator('.modal-head h3')).toHaveText(/Урок \d+ учебного плана/)
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
  await page.locator(`[data-lesson="${cell}"]`).click()
  await page.locator('dialog.modal').getByRole('button', { name: 'Открыть урок' }).click()
  await ready(page)
  // `ready` ждёт бар и тишину в сети, а не смену страницы: заголовок
  // расписания успевает пожить на экране ещё кадр, и тест, читающий `h1`
  // сразу после, примерно раз в пять получал «Моё расписание»
  await expect(page).toHaveURL(/\/lesson\/\d+$/)
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
  // Записать связь можно только у прошедшего занятия, а год демо-данных весь
  // в будущем — поэтому связь ставится запросом, как в planDates. Дата серверу
  // не мешает: он записывает, что ему сказали, а не предлагать кнопку — дело
  // экрана.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const ribbon = await teacher.get(`/api/plan/layout/slots/?course=${course.id}`)
  const tree = await teacher.get(`/api/plan/?course=${course.id}`)
  const rows = tree.body.nodes.flatMap((node) =>
    node.is_section ? node.children : [node],
  )
  const slot = ribbon.body.slots[0]
  await teacher.patch(`/api/slots/${slot.id}/`, { lesson: rows[0].id })

  await signIn(PEOPLE.ivanova)
  await page.goto(`/lesson/${slot.id}`)
  await ready(page)

  // туннель открыт: правка содержания и материалов доступна отсюда.
  // Действия видны под курсором — как кнопки строки в таблице плана
  const content = page.locator('[data-block="content"]')
  const materials = page.locator('[data-block="materials"]')

  await content.hover()
  await expect(content.getByRole('button', { name: 'Правка…' })).toBeVisible()
  await materials.hover()
  await expect(
    materials.getByRole('button', { name: 'Добавить ссылку' }),
  ).toBeVisible()
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
  const after = await teacher.get(`/api/plan/?course=${course.id}`)
  const titles = after.body.nodes.flatMap((node) =>
    node.is_section ? node.children.map((row) => row.title) : [node.title],
  )
  expect(titles).toContain('Синус суммы. Начало')

  // повторное нажатие на плашку снимает запись — как отметка в журнале
  await page.getByRole('button', { name: 'урок проведён' }).click()
  await expect(page.getByText(/Занятие ещё не проведено/)).toBeVisible()
  const locked = page.locator('[data-block="content"]')
  await expect(locked.getByRole('button', { name: 'Правка…' })).toHaveCount(0)
  await expect(locked.getByRole('link', { name: 'Правка в плане…' })).toBeVisible()
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

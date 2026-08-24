import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Scenario 2: the «School» section — four tabs and the link between a
 * teacher and a course.
 *
 * That link is the thing worth driving through a browser: it is written from
 * two different screens and read on a third one (the teacher's own list of
 * courses), so a mistake anywhere in the chain shows up only here.
 */

const openSection = async (page, path) => {
  await page.goto(path)
  await ready(page)
}

test('администратор заводит курс и назначает на него учителя', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/courses')

  await page.getByPlaceholder('Название курса').fill('9А Алгебра')
  await page.getByLabel('Предмет:').selectOption({ label: 'Алгебра' })
  // параллели теперь справочник: «MYP 4» — это девятый год обучения
  await page.getByLabel('Параллель:').selectOption({ label: 'MYP 4' })
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()

  // свёрнутая строка сразу говорит, чего курсу не хватает
  const card = page.locator('.course-row', { hasText: '9А Алгебра' })
  await expect(card).toContainText('курс никто не ведёт')
  await expect(card).toContainText('методист не назначен')

  await card.locator('.toggle').click()
  await card.getByLabel('Учитель для 9А Алгебра').selectOption({ label: 'Мария Иванова' })
  // подпись у кнопки короткая, а доступное имя называет роль: в карточке
  // курса две кнопки «Назначить» — ведущего и методиста
  await card.getByRole('button', { name: /Назначить ведущего/ }).click()

  await expect(card.locator('.tag')).toContainText('Мария Иванова')
  // строка осталась раскрытой: назначать людей по одному, каждый раз
  // раскрывая заново, было бы издевательством
  await expect(card.locator('.course-body')).toBeVisible()

  // и курс появился в её собственных списках — ради этого связь и
  // заведена. Своего экрана «Классы» больше нет, курсы видно чипами там,
  // где с ними работают
  await signIn(PEOPLE.ivanova)
  await openSection(page, '/plan')
  // курс появился в селекте заголовка — там теперь выбирают курс
  await expect(page.getByLabel('Курс').locator('option', { hasText: '9А Алгебра' }))
    .toHaveCount(1)
})

test('длинное название курса сохраняется целиком и не рвёт карточку', async ({
  page,
  signIn,
}) => {
  // двадцати символов не хватало: в названии пишут ещё группу и поток
  const NAME = '10 класс, группа B (углублённая математика, вторая подгруппа)'

  await signIn(PEOPLE.admin)
  await openSection(page, '/school/courses')

  await page.getByPlaceholder('Название курса').fill(NAME)
  await page.getByLabel('Предмет:').selectOption({ label: 'Алгебра' })
  await page.getByLabel('Параллель:').selectOption({ index: 1 })
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()

  // сервер принял имя целиком, а не обрезал его
  const card = page.locator('.course-row', { hasText: NAME })
  await expect(card).toBeVisible()

  // и строка осталась внутри своей рамки, а не уехала за край
  const overflow = await card.evaluate((item) => {
    const list = item.closest('.course-list')
    return item.getBoundingClientRect().right - list.getBoundingClientRect().right
  })
  expect(overflow).toBeLessThanOrEqual(1)
})

test('назначение видно и снимается со стороны учителя', async ({ page, signIn, api }) => {
  // ведущий у курса один, поэтому назначать нужно свободный курс: все
  // демонстрационные уже кем-то заняты
  const admin = await api(PEOPLE.admin)
  const years = await admin.get('/api/calendar/years/')
  const subjects = await admin.get('/api/school/subjects/')
  const grades = await admin.get('/api/school/grades/')
  await admin.post('/api/courses/', {
    year: years.body[0].id,
    subject: subjects.body[0].id,
    grade: grades.body[0].id,
    name: 'Свободный курс',
  })

  await signIn(PEOPLE.admin)
  await openSection(page, '/school/teachers')

  const card = page.locator('.people-list > li', { hasText: 'ivanova@example.com' })
  // то же самое отношение, показанное с другого конца
  await expect(card.locator('.tag').first()).toContainText('Grade 6 Algebra')

  // поиск по мере ввода вместо выпадающего списка: учителей в школе
  // бывает несколько десятков, и нужного в схлопнутом списке ищут глазами
  await card.getByLabel('Курс для Мария Иванова').fill('Свободный курс')
  await card.getByRole('button', { name: 'Назначить', exact: true }).click()

  await expect(card.locator('.tag', { hasText: 'Свободный курс' })).toBeVisible()

  // и обратно, с карточки курса
  await openSection(page, '/school/courses')
  const course = page.locator('.course-row', { hasText: 'Свободный курс' })
  // в свёрнутой строке учителя перечислены прямо, без раскрытия
  await expect(course.locator('.who')).toContainText('Мария Иванова')
})

test('семь курсов помещаются в экран, каждый одной строкой', async ({
  page,
  signIn,
  api,
}) => {
  const admin = await api(PEOPLE.admin)
  const years = await admin.get('/api/calendar/years/')
  const subjects = await admin.get('/api/school/subjects/')
  const grades = await admin.get('/api/school/grades/')
  // доводим до семи, сколько бы их ни было в наборе: набор растёт, и
  // «добавить ровно три» отстаёт от него молча — тест считал четыре, когда
  // в посеве появился пятый курс
  const seeded = (await admin.get('/api/courses/?scope=school')).body.length
  for (let index = 1; index <= 7 - seeded; index += 1) {
    await admin.post('/api/courses/', {
      year: years.body[0].id,
      subject: subjects.body[0].id,
      grade: grades.body[0].id,
      name: `Ещё курс ${index}`,
    })
  }

  await signIn(PEOPLE.admin)
  await page.setViewportSize({ width: 1280, height: 900 })
  await openSection(page, '/school/courses')

  const rows = page.locator('.course-row')
  await expect(rows).toHaveCount(7)

  const fits = await page.evaluate(() => {
    const list = [...document.querySelectorAll('.course-row')]
    return {
      visible: list.filter((row) => row.getBoundingClientRect().bottom <= innerHeight)
        .length,
      wrapped: list.filter((row) => row.getBoundingClientRect().height > 48).length,
    }
  })

  expect(fits.visible).toBe(7)
  // ни одна строка не переносится: колонки жёсткие, лишнее обрезается
  expect(fits.wrapped).toBe(0)
})

test('учитель курсы не заводит: раздела нет, а сервер отказывает', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/')
  await ready(page)

  // раздела «Школа» у него нет в баре вовсе — курсы заводит администратор
  await expect(page.getByRole('link', { name: 'Школа' })).toHaveCount(0)

  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const refused = await teacher.post('/api/courses/', {
    year: courses.body[0].year,
    name: 'Самодельный',
  })

  expect(refused.status).toBe(403)
  expect(refused.body.code).toBe('school_admin_required')
})

test('справочники: предмет заводится и параллель переименовывается', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/reference')

  // по тексту панель не поймать: «параллели» есть и в подсказке предметов
  const subjects = page.locator('[data-panel="subjects"]')
  await subjects.getByPlaceholder('Название нового предмета').fill('Информатика')
  await subjects.getByRole('button', { name: 'Добавить' }).click()
  // exact: рядом стоит «Удалить Информатика»
  await expect(
    subjects.getByRole('button', { name: 'Информатика', exact: true }),
  ).toBeVisible()

  // год обучения и название — разные вещи, и меняется только второе
  const grades = page.locator('[data-panel="grades"]')
  const ninth = grades.locator('li[data-level="9"]')
  await ninth.getByRole('button', { name: 'MYP 4', exact: true }).click()
  await ninth.getByLabel('Новое название').fill('MYP 4 (9 класс)')
  await ninth.getByLabel('Новое название').press('Enter')

  await expect(
    grades.getByRole('button', { name: 'MYP 4 (9 класс)', exact: true }),
  ).toBeVisible()
  // само число рядом осталось прежним и менять его нельзя: курсы уже на нём
  await expect(ninth.locator('.level')).toHaveText('9')
})

test('параллели: набор одной кнопкой и уборка неиспользуемых', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/reference')

  const grades = page.locator('[data-panel="grades"]')
  // в демо-школе заведены только те две, что реально нужны курсам
  await expect(grades.locator('li')).toHaveCount(2)

  await grades.getByRole('button', { name: 'Добавить 1–13' }).click()
  await expect(grades.locator('li')).toHaveCount(13)

  // название подставляется само, стоит ввести год обучения
  await grades.getByLabel('Год обучения').fill('14')
  await expect(grades.getByLabel('Название')).toHaveValue('Grade 14')

  page.once('dialog', (dialog) => dialog.accept())
  await grades.getByRole('button', { name: /Удалить \d+ неиспользуем/ }).click()

  // остались ровно те две, на которых висят курсы
  await expect(grades.locator('li')).toHaveCount(2)
})

test('обзор считает школу и подсказывает следующий шаг', async ({ page, signIn }) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school')

  const cards = page.locator('.summary-cards li')
  // четверо сотрудников и пять курсов: с тех пор как в наборе появился
  // завуч со своим курсом, «администратор» и «ведущий» — не два разных
  // человека по построению
  await expect(cards.filter({ hasText: 'учителей' })).toContainText('4')
  await expect(cards.filter({ hasText: 'курсов' })).toContainText('5')
})

test('расписание одно: вид переключается на месте', async ({ page, signIn }) => {
  // Экрана было два, и ходить между ними приходилось через раздел «Школа»:
  // завуч, глядя на свою неделю, не мог поставить час чужому курсу, не уйдя
  // со страницы и не найдя её заново. Данные у них одни и те же с тех пор,
  // как школьное расписание стало всеми расписаниями курсов.
  await signIn(PEOPLE.admin)
  await openSection(page, '/schedule')
  await expect(page.locator('h1')).toHaveText('Расписание')

  // `click`, а не `check`: переключение вида размонтирует сетку вместе с
  // её тумблером, и `check` проверял бы состояние уже отсоединённого поля.
  // Для человека это незаметно — на месте старого тумблера сразу стоит
  // новый, уже переключённый, — а тест иначе падает на здоровой странице
  await page.getByRole('radio', { name: 'Вся школа' }).click()
  await ready(page)
  await expect(page.locator('h1')).toHaveText('Расписание школы')
  await expect(page).toHaveURL(/view=school/)
  await expect(page.getByRole('radio', { name: 'Вся школа' })).toBeChecked()

  // и обратно, тем же тумблером
  await page.getByRole('radio', { name: 'Мои', exact: true }).click()
  await expect(page.locator('h1')).toHaveText('Расписание')

  // старый адрес приводит сюда же, в школьный вид
  await openSection(page, '/school/schedule')
  await expect(page.locator('h1')).toHaveText('Расписание школы')
  await expect(page).toHaveURL(/\/schedule\?view=school/)
})

test('учителю тумблера видов не показывают', async ({ page, signIn }) => {
  // Чужие часы он правит нечем, а свои и так на экране. Показанный тумблер
  // обещал бы страницу, на которой ему делать нечего.
  await signIn(PEOPLE.ivanova)
  await openSection(page, '/schedule')

  await expect(page.getByRole('radio', { name: 'Вся школа' })).toHaveCount(0)
})

test('фильтры школьного расписания сужают друг друга, а не пересекаются', async ({
  page,
  signIn,
  api,
}) => {
  // Фильтров было два, и складывались они условием: выбрав учителя и курс
  // другого, человек получал пустую неделю — а пустая неделя выглядит ровно
  // как неделя, в которую ничего не поставили. Теперь это одна цепочка:
  // предмет сужает учителей, учитель — курсы, а выбранный курс называет
  // обоих сам.
  const admin = await api(PEOPLE.admin)
  const courses = await admin.get('/api/courses/?scope=school')
  const named = (name) => courses.body.find((course) => course.name === name)

  await signIn(PEOPLE.admin)
  await openSection(page, '/school/schedule')

  const subject = page.getByLabel('Предмет:')
  const teacher = page.getByLabel('Учитель:')
  const course = page.getByLabel('Курс:')

  // выбран учитель — курсов чужих в списке больше нет, и выбрать их нечем
  await teacher.selectOption({ label: 'Мария Иванова' })
  await expect(course.locator('option')).toHaveText([
    'все курсы',
    'Grade 6 Algebra',
    'Grade 6 Geometry',
  ])

  // «все учителя» — шаг назад по цепочке, а не второе условие: курсы
  // возвращаются все
  await teacher.selectOption({ label: 'все' })
  await expect(course.locator('option')).toHaveText([
    'все курсы',
    'Grade 6 Algebra',
    'Grade 6 Geometry',
    'Grade 6 Physics',
    'Grade 9 Algebra',
    'Grade 9 Geometry',
  ])

  // выбран курс — ведущий и предмет встают сами, и это тот самый случай:
  // раньше выбранный курс молча противоречил бы выбранному учителю
  await course.selectOption({ label: 'Grade 9 Algebra' })
  await expect(teacher).toHaveValue(String(named('Grade 9 Algebra').teachers[0].id))
  await expect(subject).toHaveValue(String(named('Grade 9 Algebra').subject))

  // сменили предмет — курс другого предмета снят, а ведущий остался: он
  // ведёт и геометрию тоже
  await subject.selectOption({ label: 'Геометрия' })
  await expect(teacher).toHaveValue(String(named('Grade 9 Algebra').teachers[0].id))
  await expect(course.locator('option')).toHaveText(['все курсы', 'Grade 9 Geometry'])

  // в учителях — те, кто ведёт этот предмет; завуча, не ведущего ничего,
  // среди них нет: выбрать его значило бы получить пустую неделю
  await expect(teacher.locator('option')).toHaveText([
    'все',
    'Мария Иванова',
    'Пётр Петров',
  ])
})

test('в школьном расписании урок ставится в обычный будний день', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/schedule')

  // листаем в учебный год: «сегодня» в демо-данных до его начала, а поля
  // выбора даты в этой панели нет
  const monday = page.locator('[data-day-head="2026-09-07"]')
  for (let step = 0; step < 8 && !(await monday.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(250)
  }

  // понедельник — учебный день, и сетка обязана это знать: признак приходит
  // из того же ответа календаря, что и на странице «Учебный год»
  await expect(monday).toBeVisible()
  await expect(monday).not.toContainText('не учебный')

  await page.locator('[data-add="2026-09-07:6"]').click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Курсы').selectOption({ index: 1 })
  await dialog.getByRole('button', { name: 'Добавить', exact: true }).click()

  await expect(dialog).toBeHidden()
  await expect(page.locator('[data-lesson="2026-09-07:6"]')).toHaveCount(1)
})

test('день школы разворачивает курсы по столбцам', async ({ page, signIn, api }) => {
  // В неделе клетка — это окно «день + номер», и в школе в него попадают
  // все курсы разом: первых уроков в понедельник примерно столько же,
  // сколько курсов. Стопку из полутора десятков строк нельзя ни прочитать,
  // ни пополнить, и разворачивается она курсом в столбец.
  const admin = await api(PEOPLE.admin)
  const courses = await admin.get('/api/courses/?scope=school')

  await signIn(PEOPLE.admin)
  await openSection(page, '/school/schedule')

  // листаем в учебный год: «сегодня» в демо-данных до его начала
  const monday = page.locator('[data-day-head="2026-09-07"]')
  for (let step = 0; step < 8 && !(await monday.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(250)
  }
  await expect(monday).toBeVisible()

  // размах — тумблер, и он же адрес: ссылкой «вот этот день» делятся так же,
  // как ссылкой на школьный вид
  await page.getByRole('radio', { name: 'День', exact: true }).click()
  await ready(page)
  await expect(page).toHaveURL(/span=day/)

  // неделя и день листаются своим шагом: стрелка в дне ходит по одному дню
  const day = page.locator('[data-day="2026-09-07"]')
  for (let step = 0; step < 7 && !(await day.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(250)
  }
  await expect(day).toBeVisible()

  // столбец на каждый курс школы — включая те, у которых в этот день часов
  // нет: пустой столбец и есть то место, куда час ставят
  await expect(page.locator('[data-course-head]')).toHaveCount(courses.body.length)

  // ставим час в столбец курса: курс в окне уже выбран — переспрашивать то,
  // во что человек нажал, незачем
  const first = courses.body[0]
  await page.locator(`[data-add="2026-09-07:8:${first.id}"]`).click()
  const dialog = page.locator('dialog.modal')
  await expect(dialog.getByLabel('Курсы')).toHaveValue(String(first.id))
  await dialog.getByRole('button', { name: 'Добавить', exact: true }).click()

  await expect(dialog).toBeHidden()
  await expect(page.locator(`[data-lesson="2026-09-07:8:${first.id}"]`)).toHaveCount(1)

  // и тот же час виден в неделе: сетки две, расписание одно
  await page.getByRole('radio', { name: 'Неделя', exact: true }).click()
  await ready(page)
  await expect(page.locator('[data-lesson="2026-09-07:8"]')).toHaveCount(1)
})

test('урок ставится рядом на каждую неделю, а не по клетке', async ({
  page,
  signIn,
  api,
}) => {
  // Сетку строят рядами: «вторник, третий час, до конца года» — одно
  // решение, а не тридцать четыре. Раньше путь был один: нарисуй неделю и
  // скопируй её на период, задевая всё, что в ней уже стоит.
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/schedule')

  const monday = page.locator('[data-day-head="2026-09-07"]')
  for (let step = 0; step < 8 && !(await monday.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(250)
  }
  await expect(monday).toBeVisible()

  await page.locator('[data-add="2026-09-07:7"]').click()
  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Курсы').selectOption({ label: 'Grade 6 Algebra' })

  // граница спрашивается, а не подразумевается: конец года подставлен, но
  // «до конца четверти» встречается не реже
  await dialog.getByRole('radio', { name: 'каждую неделю' }).check()
  await dialog.getByLabel('до', { exact: true }).fill('2026-09-28')
  await dialog.getByRole('button', { name: 'Добавить', exact: true }).click()
  await expect(dialog).toBeHidden()

  // и меню у администратора — тоже выпадающее, у курсора
  await page.locator('[data-lesson="2026-09-07:7"]').click({ button: 'right' })
  const menu = page.locator('.context-menu')
  await expect(menu.getByRole('button', { name: 'Открыть урок' })).toBeVisible()
  await expect(menu.getByRole('button', { name: 'Удалить весь ряд…' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)

  // первая клетка — на экране, остальные три недели живут за краем сетки:
  // она показывает одну неделю, и листать её ради проверки незачем
  await expect(page.locator('[data-lesson="2026-09-07:7"]')).toHaveCount(1)

  const admin = await api(PEOPLE.admin)
  const slots = await admin.get(
    '/api/slots/?scope=school&start=2026-09-01&end=2027-05-31',
  )
  // именно наш ряд: седьмой час в демо-данных занят и дополнительным
  // уроком другого курса — он про другое
  const row = slots.body
    .filter(
      (slot) => slot.lesson_number === 7 && slot.course_name === 'Grade 6 Algebra',
    )
    .map((slot) => slot.date)
    .sort()

  // тот же день недели, четыре недели подряд — и ни одного за границей
  expect(row).toEqual(['2026-09-07', '2026-09-14', '2026-09-21', '2026-09-28'])
})

test('администратор отменяет час прямо в школьной сетке', async ({
  page,
  signIn,
}) => {
  // Меню у администратора было куцым — открыть, удалить, удалить ряд, — и
  // пометить час отменённым он не мог вовсе, хотя чужую неделю чинит
  // именно он: занятие сорвалось, а сказать об этом было нечем. Меню
  // теперь одно на оба расписания.
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/schedule')

  const monday = page.locator('[data-day-head="2026-09-07"]')
  for (let step = 0; step < 8 && !(await monday.count()); step += 1) {
    await page.getByRole('button', { name: '→' }).click()
    await page.waitForTimeout(250)
  }
  await expect(monday).toBeVisible()

  const lesson = page.locator('[data-lesson="2026-09-07:1"]').first()
  await lesson.click({ button: 'right' })

  const menu = page.locator('.context-menu')
  await menu.getByRole('button', { name: 'Отменить' }).click()
  await menu.getByPlaceholder('Причина отмены').fill('Карантин')
  await menu.getByRole('button', { name: 'Отменить урок' }).click()

  await expect(menu).toHaveCount(0)
  await expect(lesson).toHaveClass(/cancelled/)

  // и возвращается оттуда же
  await lesson.click({ button: 'right' })
  await page.locator('.context-menu').getByRole('button', { name: 'Вернуть' }).click()
  await expect(lesson).not.toHaveClass(/cancelled/)
})

test('курс поручают приглашённому — до его первого входа', async ({
  page,
  signIn,
  api,
}) => {
  // Нагрузку раздают в тот же день, когда вписывают адреса, а первого входа
  // ждут неделями. Приглашение заводит учётку сразу, поэтому назначение —
  // обычное: приглашённый стоит в том же списке, что и все, с пометкой.
  const admin = await api(PEOPLE.admin)
  await admin.post('/api/school/invitations/', {
    email: 'novichok@example.com',
    name: 'Новичок Новичков',
    kind: 'teacher',
  })

  // освобождаем курс: ведущий у него один, и пока он есть, формы выбора нет
  const courses = await admin.get('/api/courses/?scope=school')
  const course = courses.body[0]
  const rows = await admin.get(`/api/school/assignments/?course=${course.id}`)
  for (const row of rows.body) {
    await admin.delete(`/api/school/assignments/${row.id}/?force=true`)
  }

  await signIn(PEOPLE.admin)
  await page.goto('/school/courses')
  await ready(page)
  await page.locator('.course-row').first().locator('button').first().click()
  const body = page.locator('.course-body')
  await expect(body).toBeVisible()

  // в списке он есть, и видно, что он ещё ни разу не входил
  const picker = body.locator('select').first()
  await expect(picker).toContainText('ещё не входил')
  // подпись несёт ещё и пометку ожидания, поэтому выбираем по значению
  const invited = await admin.get('/api/school/members/')
  const newcomer = invited.body.find((item) => item.email === 'novichok@example.com')
  await picker.selectOption(String(newcomer.id))
  await body.getByRole('button', { name: /Назначить ведущего/ }).click()

  // назначение настоящее, и пометка ожидания переезжает на плашку
  const tag = body.locator('.tag.pending')
  await expect(tag).toContainText('Новичок Новичков')
  await expect(tag).toContainText('ещё не входил')

  const after = await admin.get('/api/courses/?scope=school')
  expect(after.body[0].teachers[0].arrived).toBe(false)
})

test('карточка учителя не обещает того, чего не сделает', async ({
  page,
  signIn,
  api,
}) => {
  // Три немые поломки одной панели. Пометка «ещё не входил» пропала из
  // списка, когда участников и приглашения слили в один; поле выбора курса
  // выключалось без единого слова, когда свободных курсов не осталось —
  // а выключенное поле выглядит ровно как рабочее; кнопка же смотрела на
  // набранный текст, а действие — на найденный курс, и на «Своб» она
  // загоралась и не делала ничего.
  const admin = await api(PEOPLE.admin)
  await admin.post('/api/school/invitations/', {
    email: 'tihiy@example.com',
    kind: 'teacher',
  })

  await signIn(PEOPLE.admin)
  await openSection(page, '/school/teachers')

  const invited = page.locator('.people-list > li', { hasText: 'tihiy@example.com' })

  // имени у приглашённого нет, и его адрес — это его имя: печатать адрес
  // второй раз подписью значит показывать одну строку дважды
  const shown = await invited.locator('.row').first().innerText()
  expect(shown.match(/tihiy@example\.com/g)).toHaveLength(1)
  await expect(invited.locator('.tag.pending')).toContainText('ещё не входил')

  // демонстрационные курсы уже кем-то заняты, то есть выбирать не из чего:
  // формы нет вовсе, и вместо неё сказано, почему
  await expect(invited.getByLabel(/Курс для/)).toHaveCount(0)
  await expect(invited).toContainText('Все курсы уже кому-то поручены')

  const years = await admin.get('/api/calendar/years/')
  const subjects = await admin.get('/api/school/subjects/')
  const grades = await admin.get('/api/school/grades/')
  await admin.post('/api/courses/', {
    year: years.body[0].id,
    subject: subjects.body[0].id,
    grade: grades.body[0].id,
    name: 'Свободный курс',
  })

  await openSection(page, '/school/teachers')
  const field = invited.getByLabel(/Курс для/)
  const assign = invited.getByRole('button', { name: 'Назначить', exact: true })

  // набранное, но не разрешившееся: кнопка молчит, и подпись говорит почему
  await field.fill('Своб')
  await expect(invited).toContainText('выберите из списка')
  await expect(assign).toBeDisabled()

  await field.fill('Свободный курс')
  await expect(assign).toBeEnabled()
  await assign.click()
  await expect(invited.locator('.tag', { hasText: 'Свободный курс' })).toBeVisible()
})

test('администратор чинит чужой план — из того же селектора', async ({
  page,
  signIn,
  api,
}) => {
  // Расписание и журнал занятия администратор правил всегда, а план и
  // работы оставались закрытыми — две трети курса он чинил, а треть нет.
  // Помогать учителю, который не смог или не стал, приходится в жизни.
  const admin = await api(PEOPLE.admin)
  const mine = await admin.get('/api/courses/')
  const all = await admin.get('/api/courses/?scope=school')
  const alien = all.body.find(
    (item) => !mine.body.some((own) => own.id === item.id),
  )
  expect(alien, 'в школе должен быть курс, который администратор не ведёт').toBeTruthy()

  await signIn(PEOPLE.admin)
  await page.goto('/plan')
  await ready(page)

  // чужой курс лежит в своей группе, а не вперемешку со «своими»
  const picker = page.getByLabel('Курс')
  await expect(picker.locator('optgroup[label="Курсы школы"]')).toHaveCount(1)
  await picker.selectOption(String(alien.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  // и правка проходит: строка появляется в чужом плане
  await page.getByRole('button', { name: 'Добавить урок' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Починено завучем')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Починено завучем' })).toBeVisible()

  const tree = await admin.get(`/api/plan/?course=${alien.id}`)
  expect(
    tree.body.nodes.some((node) => node.title === 'Починено завучем'),
  ).toBe(true)
})

test('занятый курс не предлагают ни на одной из двух дверей', async ({
  page,
  signIn,
  api,
}) => {
  // Назначение делается с двух сторон — из карточки учителя и из карточки
  // курса, — и обе обязаны быть одинаково честными. Карточку курса
  // починили, когда вводили правило «ведущий один», а вторую забыли: она
  // предлагала занятый курс, а сервер отвечал `course_teacher_taken`.
  const admin = await api(PEOPLE.admin)
  const courses = await admin.get('/api/courses/?scope=school')
  const busy = courses.body.find((item) => item.teachers.length > 0)
  expect(busy, 'в школе должен быть курс с ведущим').toBeTruthy()

  await signIn(PEOPLE.admin)

  // дверь первая: карточка учителя — занятого курса в списке нет
  await openSection(page, '/school/teachers')
  const options = await page
    .locator('.people-list datalist option')
    .evaluateAll((items) => items.map((item) => item.value))
  expect(options).not.toContain(busy.name)

  // дверь вторая: карточка курса — пока ведущий есть, формы нет вовсе
  await openSection(page, '/school/courses')
  const row = page.locator('.course-row', { hasText: busy.name })
  await row.locator('.course-open').click()
  const body = page.locator('.course-body')
  await expect(body).toBeVisible()
  await expect(body.getByRole('button', { name: /Назначить ведущего/ })).toHaveCount(0)
})

test('строка курса раскрывается кликом, а имя правится карандашом', async ({
  page,
  signIn,
}) => {
  // По названию открывалось переименование — самый крупный элемент строки
  // делал не то, чего от него ждут, и промах стоил открытого поля ввода.
  await signIn(PEOPLE.admin)
  await openSection(page, '/school/courses')

  const row = page.locator('.course-row').first()
  await row.locator('.course-open').click()
  await expect(page.locator('.course-body')).toBeVisible()

  // повторный клик сворачивает
  await row.locator('.course-open').click()
  await expect(page.locator('.course-body')).toHaveCount(0)

  // переименование — под карандашом, и поле появляется вместо строки
  await row.hover()

  // карандаш стоит при названии, а не в хвосте строки: рядом с крестиком,
  // у которого область действия — весь курс, он и читался как «править
  // курс», хотя правит одно название
  const name = await row.locator('.course-head .name').boundingBox()
  const pencil = await row.locator('.course-pencil').boundingBox()
  const remove = await row.locator('.course-head-actions button').boundingBox()
  expect(pencil.x).toBeGreaterThan(name.x + name.width - 1)
  expect(pencil.x - (name.x + name.width)).toBeLessThan(remove.x - pencil.x)

  await row.getByTitle('Переименовать').click()
  const field = row.locator('input.course-rename')
  await expect(field).toBeVisible()
  await field.fill('9Б Переименованный')
  await field.press('Enter')
  await expect(page.locator('.course-row', { hasText: '9Б Переименованный' })).toBeVisible()
})

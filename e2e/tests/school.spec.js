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
  await card.getByRole('button', { name: 'Назначить', exact: true }).click()

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

  await card.getByLabel('Курс для Мария Иванова').selectOption({ label: 'Свободный курс' })
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
  // в демо-школе четыре курса; доводим до семи
  for (const index of [1, 2, 3]) {
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
  await expect(cards.filter({ hasText: 'учителей' })).toContainText('3')
  await expect(cards.filter({ hasText: 'курсов' })).toContainText('4')
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

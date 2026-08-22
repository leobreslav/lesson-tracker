import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Второй вид пользователя: у ученика другой интерфейс целиком.
 *
 * Проверяется не «красиво ли», а граница: учительских разделов он не видит,
 * учительские адреса ему ничего не показывают, и наоборот — учитель не
 * попадает в ученический раздел. Слушатель консоли здесь особенно к месту:
 * лишний фоновый запрос учительской половины виден именно как ошибка в
 * консоли, а не как поломка на экране.
 */

test('ученик видит свои курсы и ни одного учительского раздела', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await expect(page.getByRole('heading', { name: 'Мои курсы' })).toBeVisible()
  // прямые дети: внутри курса теперь ещё и список его открытых работ
  await expect(page.locator('.student-courses > li')).toHaveCount(1)
  await expect(page.locator('.student-courses')).toContainText('Grade 6 Algebra')

  // в баре только имя и выход: разделов учителя нет ни одного
  await expect(page.locator('.nav-link')).toHaveCount(0)
  for (const section of ['Учебный план', 'Расписание', 'Классы', 'Школа']) {
    await expect(page.getByRole('link', { name: section })).toHaveCount(0)
  }
})

test('учительский адрес ученику ничего не показывает', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/plan')
  await ready(page)

  // своя страница «не найдено», а не чужой интерфейс и не пустой экран
  await expect(page.locator('.plan-cards')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Мои курсы' })).toBeVisible()
})

test('в курсе виден учебный план с датами и все работы', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await page.getByRole('link', { name: 'Grade 6 Algebra' }).click()
  await ready(page)

  // панели ищутся по заголовку, а не по тексту: «работы» встречается и в
  // названии урока, и фильтр по подстроке хватал обе
  const panel = (name) =>
    page.locator('.panel').filter({
      has: page.getByRole('heading', { name, exact: true }),
    })

  // план курса — тот же, что у учителя: он принадлежит курсу, и второго нет
  const plan = panel('Учебный план')
  await expect(plan.locator('.student-plan > li')).not.toHaveCount(0)
  await expect(plan.locator('.student-plan .theme').first()).toBeVisible()
  // даты берутся из расписания курса, а не подписываются вручную
  await expect(plan.locator('.student-plan .date').first()).not.toBeEmpty()

  // содержание урока остаётся учительским: на экране только названия
  await expect(page.locator('body')).not.toContainText('Домашнее задание')

  // здесь, в отличие от списка курсов, видны и закрытые работы
  const works = panel('Работы')
  await expect(works.locator('.work-links > li')).not.toHaveCount(0)
  await expect(works).toContainText('Контрольная: тригонометрия')
})

test('снятый с курса видит его отдельно и с объяснением', async ({ page, signIn }) => {
  await signIn(PEOPLE.removedStudent)
  await page.goto('/')
  await ready(page)

  await expect(page.getByText('Сейчас вы не записаны ни на один курс.')).toBeVisible()

  const past = page.locator('.panel', { hasText: 'Вы больше не в этих курсах' })
  await expect(past).toContainText('Grade 6 Algebra')
  await expect(past).toContainText('всё сделанное остаётся видно')

  // курс уехал вниз, но остался открытым: год, который человек отучился, с
  // экрана пропадать не должен
  await past.getByRole('link', { name: 'Grade 6 Algebra' }).click()
  await ready(page)

  await expect(page.locator('.student-plan > li')).not.toHaveCount(0)
})

test('язык переключается и у ученика', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  await page.locator('.user-menu > button').click()
  await page.getByRole('menuitem', { name: 'English' }).click()

  await expect(page.getByRole('heading', { name: 'My courses' })).toBeVisible()
})

test('ученический раздел учителю закрыт', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)

  const response = await teacher.get('/api/student/courses/')

  expect(response.status).toBe(403)
  expect(response.body.code).toBe('students_only')
})

test('переключатель «войти как» берёт токен нужного человека', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/')
  await ready(page)

  await page.locator('.user-menu > button').click()
  const switcher = page.locator('.dropdown-switch')
  // сотрудники первыми, ученики ниже — и у каждого написано, кто он
  await expect(switcher.getByRole('menuitem', { name: 'Ольга Дирекова' })).toContainText(
    'администратор',
  )

  // смотрим на запрос, а не на экран после перезагрузки: оснастка тестов
  // прописывает свой токен init-скриптом на **каждую** загрузку страницы и
  // вернула бы Иванову. Тело ответа тоже не прочитать — страница уходит на
  // перезагрузку раньше. Остаётся то, что и проверяем: за чьим токеном
  // переключатель пошёл
  const asked = page.waitForRequest('**/api/test/login/')
  await switcher.getByRole('menuitem', { name: 'Артём Степанов' }).click()

  expect((await asked).postDataJSON().email).toBe(PEOPLE.student)
})

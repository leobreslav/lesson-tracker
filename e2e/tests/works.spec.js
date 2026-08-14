import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Работы глазами учителя: список, окно времени, задачи с эталонами.
 *
 * Через браузер это стоит гонять из-за двух вещей, которые молча ломаются:
 * состояние работы приходит с сервера (у браузера часы свои), а условие
 * задачи — Markdown с формулами, то есть путь через KaTeX, который сборка
 * не проверяет.
 */

const openWorks = async (page, course = 'Grade 6 Algebra') => {
  await page.goto('/works')
  await ready(page)
  await page.getByRole('button', { name: course, exact: true }).click()

  return page.locator('.work-list')
}

test('в списке — имя и два действия, состояние видно в проверке', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  const list = await openWorks(page)

  // в строке только имя и то, что с работой делают: окно и попытки живут
  // в настройках, где их и правят
  await expect(list.locator('.course-row')).toHaveCount(3)
  const closed = list.locator('.course-row', { hasText: 'Контрольная' })
  await expect(closed.getByRole('button', { name: 'Настройки' })).toBeVisible()

  await closed.getByRole('button', { name: 'Проверка' }).click()

  await expect(page.locator('.page-header')).toContainText('закрыта')
})

test('задачи видны с формулами и эталонами, порядок меняется', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  const list = await openWorks(page)

  const work = list.locator('.course-row', { hasText: 'Проверочная' })
  await work.locator('.toggle').click()

  // формула отрисована KaTeX, а не осталась долларами в тексте
  await expect(work.locator('.task-question .katex').first()).toBeVisible()

  // эталоны в списке спрятаны, пока их не попросят: список читают, чтобы
  // вспомнить, что в работе, и ответы в нём шум
  const second = work.locator('.task-list li').nth(1)
  await expect(second.locator('.answers .tag')).toHaveCount(0)
  await work.getByRole('button', { name: 'Ответы' }).click()
  // два эталона у одной задачи: «x+3» и «3+x» верны одинаково
  await expect(second.locator('.answers .tag')).toHaveCount(2)

  const first = work.locator('.task-list li').first()
  await expect(first).toContainText('Раскройте скобки')
  // кнопки строки появляются при наведении: двенадцать значков разом
  // заслоняли сами условия
  await second.hover()
  await second.getByRole('button', { name: 'Ниже' }).click()

  await expect(work.locator('.task-list li').nth(2)).toContainText('Упростите')
})

test('новая работа заводится с окном времени и получает задачу', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  const list = await openWorks(page, 'Grade 6 Geometry')

  await page.getByRole('button', { name: 'Новая работа' }).click()
  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Название').fill('Проверочная по углам')
  await dialog.getByRole('button', { name: 'Сохранить' }).click()

  const work = list.locator('.course-row', { hasText: 'Проверочная по углам' })
  await work.locator('.toggle').click()
  await work.getByRole('button', { name: 'Добавить задачу' }).click()
  const task = page.locator('dialog.modal')
  await task.getByLabel('Условие').fill('Сумма углов треугольника?')
  await task.getByLabel('Ответ 1').fill('180')
  await task.getByRole('button', { name: 'Сохранить' }).click()

  await expect(work.locator('.task-list li')).toHaveCount(1)
  await work.getByRole('button', { name: 'Ответы' }).click()
  await expect(work).toContainText('180')

  // окно в будущем и есть «черновик»: работа запланирована, а не открыта
  await work.getByRole('button', { name: 'Проверка' }).click()
  await expect(page.locator('.page-header')).toContainText('запланирована')
})

test('правка работы, в которой уже отвечали, называет цену', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  const list = await openWorks(page)

  const work = list.locator('.course-row', { hasText: 'Контрольная' })
  await work.locator('.toggle').click()
  await work.getByRole('button', { name: 'Настройки' }).click()

  // не запрет, а число: правка проходит, но человек знает, чего она стоит
  const dialog = page.locator('dialog.modal')
  await expect(dialog).toContainText('уже отвечали')
  await expect(dialog.getByRole('button', { name: 'Сохранить' })).toBeEnabled()
})

/**
 * Половина ученика: что он видит и что может отправить.
 *
 * Правила подсистемы («попытка расходуется на любой отправке», «ничего не
 * перезаписывается») проверены питоновскими тестами; здесь — что они
 * доезжают до экрана и что ученику не показано лишнего.
 */

test('на главной у ученика только открытые работы, остальное — в курсе', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)

  // список курсов отвечает на вопрос «что делать сейчас»
  const links = page.locator('.work-links > li')
  await expect(links).toHaveCount(1)
  await expect(links.first()).toContainText('Проверочная')
  await expect(page.locator('body')).not.toContainText('Контрольная: тригонометрия')
  // запланированной для него не существует нигде: окно ещё не открылось
  await expect(page.locator('body')).not.toContainText('Домашняя работа на каникулы')

  await page.getByRole('link', { name: 'Grade 6 Algebra' }).click()
  await ready(page)

  // а в курсе — и закрытые: свои ответы и отметки он читает всегда
  await expect(page.locator('.work-links > li')).toHaveCount(2)
  await expect(page.locator('body')).not.toContainText('Домашняя работа на каникулы')
})

test('ответ уходит по одной задаче и попадает в историю', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)
  await page.getByRole('link', { name: 'Проверочная: формулы сложения' }).click()

  const first = page.locator('.student-task').first()
  await first.getByRole('textbox').fill('a^2+2ab+b^2')
  await first.getByRole('button', { name: 'Отправить' }).click()

  // строка журнала и есть подтверждение: ответ на сервере с этой минуты
  await expect(first.locator('.attempt-list li')).toHaveCount(1)
  await expect(first.locator('.attempt-list .answer')).toHaveText('a^2+2ab+b^2')
  await expect(first.locator('.attempt-list .verdict')).toHaveText('не проверено')
  // попытка израсходована, хотя учитель ещё ничего не смотрел
  await expect(first).toContainText('осталась 1 попытка')

  await first.getByRole('textbox').fill('передумал')
  await first.getByRole('button', { name: 'Отправить' }).click()

  // вторая попытка не затирает первую и не оставляет поля для третьей
  await expect(first.locator('.attempt-list li')).toHaveCount(2)
  await expect(first).toContainText('Попытки по этой задаче кончились')
})

test('в закрытой работе ответы видно, а поля ввода нет', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)
  // закрытые работы живут на странице курса, а не в списке курсов
  await page.getByRole('link', { name: 'Grade 6 Algebra' }).click()
  await ready(page)
  await page.getByRole('link', { name: 'Контрольная: тригонометрия' }).click()

  await expect(page.getByText('Работа закрыта')).toBeVisible()
  await expect(page.locator('.attempt-list li').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Отправить' })).toHaveCount(0)
})

test('учительский раздел работ ученику не показан', async ({ page, signIn }) => {
  await signIn(PEOPLE.student)
  await page.goto('/works')
  await ready(page)

  await expect(page.locator('.work-list')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Мои курсы' })).toBeVisible()
})

test('отметка учителя доезжает до ученика сама', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)

  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)
  await page.getByRole('link', { name: 'Проверочная: формулы сложения' }).click()

  const first = page.locator('.student-task').first()
  await first.getByRole('textbox').fill('a^2+2ab+b^2')
  await first.getByRole('button', { name: 'Отправить' }).click()
  await expect(first.locator('.attempt-list .verdict')).toHaveText('не проверено')

  // берём последнюю отправку задачи, а не «ту, где такой текст»: в демо у
  // задачи полтора десятка ответов, и верный текст встречается не раз
  const task = await firstTask(teacher)
  const answers = await teacher.get(`/api/works/submissions/?task=${task.id}`)
  const mine = answers.body.at(-1)
  expect(mine.answer).toBe('a^2+2ab+b^2')
  await teacher.patch(`/api/works/submissions/${mine.id}/`, { is_correct: true })

  // страницу не трогаем: отметка приезжает опросом
  await expect(first.locator('.attempt-list .verdict')).toHaveText('верно', {
    timeout: 15000,
  })
  await expect(first.locator('.attempt-list li')).toHaveClass(/correct/)
})

/** Первая задача «Проверочной» — в ней ученик отвечает, а учитель проверяет. */
async function firstTask(teacher) {
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const works = await teacher.get(`/api/works/?course=${course.id}`)
  const work = works.body.find((item) => item.title.startsWith('Проверочная'))
  const tasks = await teacher.get(`/api/works/tasks/?work=${work.id}`)

  return tasks.body[0]
}

import { PEOPLE, expect, expectConsoleError, ready, test } from './harness.js'

/**
 * Разбор пачки бумажных работ.
 *
 * Через браузер это гонять надо больше, чем что-либо ещё в проекте: половина
 * работы здесь — настоящий `pdfjs` и обработка пикселей, и ни один узловой
 * тест не скажет, что рендер страницы в живом браузере даёт не то, что
 * синтетический массив в node. Плюс модуль грузится лениво, а ленивый импорт
 * ломается ровно так, как его не видит сборка.
 *
 * Ключа Anthropic у стенда нет намеренно: тесты не должны звать чужой сервис и
 * тратить деньги школы. Значит проверяется всё до чтения включительно —
 * страницы отрисовались, шапки нашлись, полоски ушли на сервер — и **честный
 * отказ** вместо чтения. Отказ этот сам по себе важен: без ключа человек
 * обязан увидеть фразу, а не пустой экран.
 */

const BLANK = '/blank/blank_form.pdf'

/** Бумажная работа с заданной шкалой — тем же путём, каким её заводит учитель. */
async function paperWork(teacher, { title = 'Контрольная на бумаге', questions = 3, maximum = 3 } = {}) {
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((one) => one.name === 'Grade 6 Algebra')

  // окно времени обязательное: у работы нет состояния «черновик», её
  // видимость и есть это окно
  const day = 24 * 60 * 60 * 1000
  const work = await teacher.post('/api/works/', {
    course: course.id,
    title,
    on_paper: true,
    opens_at: new Date(Date.now() - day).toISOString(),
    closes_at: new Date(Date.now() + day).toISOString(),
  })
  expect(work.status, `работа не завелась: ${JSON.stringify(work.body)}`).toBe(201)

  if (questions) {
    await teacher.put(`/api/works/${work.body.id}/criteria/`, {
      criteria: Array.from({ length: questions }, (_, i) => ({
        name: `Q${i + 1}`,
        maximum,
      })),
    })
  }

  return work.body
}

const openScan = async (page, title = 'Контрольная на бумаге') => {
  await page.goto('/works')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })
  // в строке две кнопки с этим именем — раскрывающая и само имя; берём строку
  const row = page.locator('.work-list .course-row', { hasText: title })
  await row.locator('.name').click()
  await row.getByRole('button', { name: 'Сканы' }).click()
}

test('у онлайновой работы кнопки сканов нет вовсе', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: 'Grade 6 Algebra' })

  // раскрываем первую работу набора — она онлайновая
  const first = page.locator('.work-list .course-row').first()
  await first.locator('.name').click()

  await expect(first.getByRole('button', { name: 'Сканы' })).toHaveCount(0)
})

test('шкала спрашивается один раз, а потом сразу файл', async ({ page, signIn, api }) => {
  await signIn(PEOPLE.ivanova)
  await paperWork(await api(PEOPLE.ivanova), { title: 'Без шкалы', questions: 0 })

  await openScan(page, 'Без шкалы')

  // шкалы нет — спрашивают её
  await expect(page.getByLabel('Задач', { exact: true })).toBeVisible()
  await page.getByLabel('Задач', { exact: true }).fill('4')
  await page.getByLabel('Максимум за задачу').fill('2')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  // и сразу после — файл, без второго вопроса
  await expect(page.getByText('Выберите PDF')).toBeVisible()
  await expect(page.getByText('4 задачи')).toBeVisible()
})

test('страницы отрисовываются, шапки находятся, а без ключа отказ говорит словами', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)
  await paperWork(await api(PEOPLE.ivanova))
  await openScan(page)

  // отказ сервера мы вызываем нарочно, и он честно шумит в консоль
  expectConsoleError(page, /Failed to load resource|400/)

  // бланк из репозитория: две страницы, метки на местах
  await page.locator('.dropzone input[type=file]').setInputFiles(BLANK)

  // чтение без ключа обязано сказать это человеком, а не молчать
  await expect(page.locator('.error')).toContainText('ключ', { timeout: 30000 })
})

test('пачку можно разобрать руками и записать без единого чтения', async ({
  page,
  signIn,
  api,
}) => {
  await signIn(PEOPLE.ivanova)
  const teacher = await api(PEOPLE.ivanova)
  const work = await paperWork(teacher)

  // страница «прочитана» вручную: тем же эндпоинтом, каким правит человек
  const state = await teacher.get(`/api/works/${work.id}/scan/state/`)
  const mine = state.body.students[0]
  await teacher.post(`/api/works/${work.id}/scan/page/`, {
    index: 0,
    student: mine.id,
    cells: [3, 2, 1],
  })

  const after = await teacher.get(`/api/works/${work.id}/scan/state/`)
  expect(after.body.students.find((one) => one.id === mine.id).total).toBe(6)
  expect(after.body.doubts).toEqual([])
})


test('после разбора видно, кто что решил и что далось труднее всего', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const work = await paperWork(teacher, { questions: 3, maximum: 3 })

  // оценки ставим тем же путём, каким их пишет разбор пачки
  const state = await teacher.get(`/api/works/${work.id}/scan/state/`)
  const [first, second] = state.body.students
  const scale = await teacher.get(`/api/works/${work.id}/criteria/`)
  const marks = (values) =>
    Object.fromEntries(scale.body.criteria.map((one, n) => [one.id, values[n]]))

  await teacher.post(`/api/works/${work.id}/grade/`, {
    student: first.id,
    marks: marks([3, 1, 0]),
  })
  await teacher.post(`/api/works/${work.id}/grade/`, {
    student: second.id,
    marks: marks([3, 2, 0]),
  })

  await signIn(PEOPLE.ivanova)
  await page.goto(`/works/${work.id}`)
  await ready(page)

  // таблица: столбец на задачу, а в ячейке балл
  await expect(page.locator('.work-table th', { hasText: 'Q1' })).toBeVisible()
  await expect(page.locator('.work-table td.correct').first()).toHaveText('3')

  // сводка называет самую трудную задачу и разброс
  await expect(page.locator('[data-card="hardest"] h2')).toHaveText('Q3')
  await expect(page.locator('[data-card="graded"]')).toContainText('2')
  await expect(page.locator('[data-card="spread"]')).toBeVisible()

  // и подсвечивает её столбец
  await expect(page.locator('.work-table th.hardest')).toHaveText('Q3')
})


test('условие с листа открывается из шапки колонки', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)
  const work = await paperWork(teacher, { questions: 2, maximum: 3 })

  // условия записываем тем же путём, каким их пишет чтение листа
  const scale = await teacher.get(`/api/works/${work.id}/criteria/`)
  await teacher.put(`/api/works/${work.id}/criteria/`, {
    criteria: scale.body.criteria.map((one, n) => ({
      name: one.name,
      maximum: one.maximum,
      question: n === 0 ? 'Сколько будет $2+2$?' : 'Второе условие',
    })),
  })

  await signIn(PEOPLE.ivanova)
  await page.goto(`/works/${work.id}`)
  await ready(page)

  await page.locator('.work-table th', { hasText: 'Q1' }).getByRole('button').click()

  await expect(page.locator('.modal')).toContainText('Сколько будет')
})

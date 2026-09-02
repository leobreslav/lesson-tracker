import { expect, PEOPLE, pickCourse, ready, test } from './harness.js'

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
  // курс выбирают селектом в строке заголовка: чипы не пережили учителя
  // музыки с полутора десятками курсов, а сам экран за человека не выбирает
  await pickCourse(page, course)

  return page.locator('.work-list')
}

/**
 * Страница работы: правку унесли со списка туда.
 *
 * В списке задачи только показывают — там же, где задание, и без единой
 * кнопки. Правят их на странице, и второго места для одного действия быть
 * не должно.
 */
const openWorkPage = async (page, list, title) => {
  await list
    .locator('.course-row', { hasText: title })
    .getByRole('button', { name: 'Править' })
    .click()
  await ready(page)
}

test('курс выбирают витриной, и с работ есть дорога назад', async ({
  page,
  signIn,
}) => {
  /*
   * Курс за человека экран не подставляет, и выбирают его витриной — тем же
   * приёмом, что и план.
   *
   * Подставлялся: сперва прошлый выбор (ключ общий с планом и журналом), а
   * если его нет — первый курс списка, то есть первый по алфавиту. Опаснее
   * это здесь, чем на соседних экранах: работы заводят, правят и
   * **проверяют**, а проверенное уходит ученикам. Экран, открывшийся на чужом
   * курсе, выглядит ровно как открывшийся на своём.
   */
  await signIn(PEOPLE.ivanova)
  await page.goto('/works')
  await ready(page)

  await expect(page.locator('.work-list')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Выберите курс' })).toBeVisible()
  // селекта на экране нет вовсе: витрина и есть выбор
  await expect(page.locator('.course-picker')).toHaveCount(0)

  await pickCourse(page)
  await expect(page.locator('.work-list')).toBeVisible()

  /*
   * Выбранное уезжает **в адрес**, и это не украшение: витрина показывается
   * при каждом заходе, значит у открытого должен быть свой адрес — иначе
   * перезагрузка отправляет к выбору, а ссылкой «вот эти работы» поделиться
   * нечем. Тот же довод, что у плана.
   */
  await expect(page).toHaveURL(/[?&]course=\d+/)

  /*
   * Заголовок называет **курс**, а не раздел: на этот адрес приходят дважды —
   * к витрине и в выбранный курс, — и «Работы» у обоих читалось одинаково.
   */
  await expect(
    page.getByRole('heading', { name: 'Работы курса Grade 6 Algebra' }),
  ).toBeVisible()

  // перезагрузка не теряет открытое: адрес и есть ответ на «что открыто»
  await page.reload()
  await ready(page)
  await expect(page.locator('.work-list')).toBeVisible()

  /*
   * А дорога назад возвращает к витрине. Без неё выбор был бы билетом в один
   * конец: сменить курс можно было бы только пунктом бара, то есть выйдя из
   * раздела и зайдя обратно.
   */
  await page.getByRole('button', { name: 'К выбору курсов' }).click()
  await expect(page.locator('.work-list')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Выберите курс' })).toBeVisible()

  /*
   * И прошлый выбор экран по-прежнему не читает: ключ общий с планом и
   * журналом, те им пользуются, а этот — нет. Проверяется свежим заходом:
   * выбор только что сделан и записан, и если бы экран его читал, список
   * открылся бы сам.
   */
  await page.goto('/works')
  await ready(page)
  await expect(page.locator('.work-list')).toHaveCount(0)
})

test('в списке — имя и два действия, состояние видно в проверке', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  const list = await openWorks(page)

  // В строке только имя и то, что с работой делают: окно и попытки живут в
  // настройках, где их и правят. Числа работ тут нет: посев волен добавлять
  // свои, и «ровно три» было бы утверждением про набор, а не про строку.
  const closed = list.locator('.course-row', { hasText: 'Контрольная' })
  await expect(closed).toHaveCount(1)
  await expect(closed).not.toContainText('попыт')
  await expect(closed.getByRole('button', { name: 'Править' })).toBeVisible()

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

  // в списке задачи только показывают: ни одной кнопки правки на строке
  await expect(work.locator('.task-actions')).toHaveCount(0)

  // порядок меняют там же, где правят, — на странице работы
  await openWorkPage(page, list, 'Проверочная')

  const rows = page.locator('.task-list li')
  await expect(rows.first()).toContainText('Раскройте скобки')
  // кнопки строки появляются при наведении: двенадцать значков разом
  // заслоняли сами условия
  await rows.nth(1).hover()
  await rows.nth(1).getByRole('button', { name: 'Ниже' }).click()

  await expect(rows.nth(2)).toContainText('Упростите')
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

  await openWorkPage(page, list, 'Проверочная по углам')

  await page.getByRole('button', { name: 'Добавить задачу' }).click()
  const task = page.locator('dialog.modal')
  await task.getByLabel('Условие').fill('Сумма углов треугольника?')
  await task.getByLabel('Ответ 1').fill('180')
  await task.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.locator('.task-list li')).toHaveCount(1)
  // exact: иначе «Ответы» ловит ещё и «Закрыть ответы» в строке задачи, и
  // поиск падает неоднозначностью. Разметка от этого не зависит — она
  // одинакова, — но локатор обязан называть то, что имеет в виду: чип над
  // списком, а не переключатель у задачи
  await page.getByRole('button', { name: 'Ответы', exact: true }).click()
  await expect(page.locator('.task-list')).toContainText('180')

  // окно в будущем и есть «черновик»: работа запланирована, а не открыта
  const again = await openWorks(page, 'Grade 6 Geometry')
  await again
    .locator('.course-row', { hasText: 'Проверочная по углам' })
    .getByRole('button', { name: 'Проверка' })
    .click()
  await expect(page.locator('.page-header')).toContainText('запланирована')
})

test('задание видно над задачами, а пустая ячейка заводится обычной кнопкой', async ({
  page,
  signIn,
}) => {
  /*
   * Две правки одним тестом, потому что беда у них общая: то, что человек
   * написал в окне, должно быть видно **вне** окна.
   *
   * Текст задания жил только в настройках, куда заходят что-то поправить, —
   * и работа, ведённая без задач, выглядела на экране учителя пустой. А
   * пустую ячейку заводила вторая кнопка рядом со списком, существовавшая
   * ровно затем, чтобы обойти окно, не отпускавшее без условия.
   */
  await signIn(PEOPLE.ivanova)
  const list = await openWorks(page, 'Grade 6 Geometry')

  await page.getByRole('button', { name: 'Новая работа' }).click()
  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Название').fill('Работа без задач')
  await dialog
    .getByLabel('Пояснения к работе')
    .fill('Решите номера 12–18 из учебника, сдайте фотографией.')
  await dialog.getByRole('button', { name: 'Сохранить' }).click()

  const work = list.locator('.course-row', { hasText: 'Работа без задач' })
  await work.locator('.toggle').click()
  // задание — над списком задач, у учителя, а не только у ученика
  await expect(work.locator('.work-brief')).toContainText('номера 12–18')

  // ячейка без условия: та же кнопка, окно отпускает пустым
  await openWorkPage(page, list, 'Работа без задач')
  await page.getByRole('button', { name: 'Добавить задачу' }).click()
  const task = page.locator('dialog.modal')
  await task.getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('.task-list li')).toHaveCount(1)
})

test('правка работы, в которой уже отвечали, называет цену', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  const list = await openWorks(page)

  const work = list.locator('.course-row', { hasText: 'Контрольная' })
  await work.locator('.toggle').click()
  await work.getByRole('button', { name: 'Править' }).click()
  await ready(page)

  // правка — страница, а не окно, и это половина смысла теста: полей у
  // работы, которую уже ведут, полтора десятка, и в щёлку поверх списка их
  // не читали
  await expect(page).toHaveURL(/\/works\/\d+\/edit$/)
  await expect(page.locator('dialog.modal')).toHaveCount(0)

  // не запрет, а число: правка проходит, но человек знает, чего она стоит
  await expect(page.locator('main')).toContainText('уже отвечали')

  // название на странице одно: заголовок, а не он же плюс поле в карточке
  // под чужой подписью. Поле появляется по клику в заголовок — как тема
  // урока и строка плана
  await expect(page.getByLabel('Название')).toHaveCount(0)

  // «Сохранить» ждёт правки, а не запрещает её: пока ничего не тронуто,
  // сохранять нечего — тронули, и кнопка ожила
  const save = page.getByRole('button', { name: 'Сохранить' })
  await expect(save).toBeDisabled()
  await page.getByLabel('Пояснения к работе').fill('Решить номера 1–5.')
  await expect(save).toBeEnabled()

  // переименование — своей формой в заголовке, и применяется сразу:
  // заголовок страницы черновиком не бывает
  await page.locator('h1 button.name').click()
  await page.getByLabel('Название').fill('Контрольная (поправлено)')
  await page.locator('.lesson-title-head form').getByRole('button', { name: 'Сохранить' }).click()
  await expect(page.locator('h1')).toContainText('Контрольная (поправлено)')
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

  // Список курсов отвечает на вопрос «что делать сейчас». Считаем не сколько
  // их, а какие: посев волен добавить курсу ещё одну открытую работу.
  const links = page.locator('.work-links > li')
  await expect(links.filter({ hasText: 'Проверочная' })).toHaveCount(1)
  const открытых = await links.count()
  await expect(page.locator('body')).not.toContainText('Контрольная: тригонометрия')
  // запланированной для него не существует нигде: окно ещё не открылось
  await expect(page.locator('body')).not.toContainText('Домашняя работа на каникулы')

  await page.getByRole('link', { name: 'Grade 6 Algebra' }).click()
  await ready(page)

  // а в курсе — и закрытые: свои ответы и отметки он читает всегда
  const вКурсе = page.locator('.work-links > li')
  await expect(вКурсе.filter({ hasText: 'Контрольная: тригонометрия' })).toHaveCount(1)
  await expect(вКурсе).toHaveCount(открытых + 1)
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
  // ссылка ищется **в теле страницы**, а не где угодно: с тех пор как у
  // ученика появился бар с переписной, «Мои курсы» есть и в нём, и проверка
  // без сужения находит две и падает на строгом режиме. Утверждение при этом
  // про страницу — что вместо чужого раздела ему показали дорогу к своему
  await expect(
    page.getByRole('main').getByRole('link', { name: 'Мои курсы' }),
  ).toBeVisible()
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
  await teacher.patch(`/api/works/submissions/${mine.id}/`, { mark: 1 })

  // страницу не трогаем: отметка приезжает опросом
  await expect(first.locator('.attempt-list .verdict')).toHaveText('верно', {
    timeout: 15000,
  })
  await expect(first.locator('.attempt-list li')).toHaveClass(/correct/)
})

/*
 * Материалы задания: класс видит открытое ему и не видит спрятанного.
 *
 * Тест браузерный, и это не прихоть. Приложенное к работе сервер отдавал
 * ученику с самого начала — и права под это были написаны отдельно, — а экран
 * ученика не рисовал их вовсе: раздела не существовало. Питоновский набор
 * такое не ловит по построению, он проверяет ответ, а не показ, и дыра прожила
 * всю дорогу именно поэтому.
 *
 * Вложение заводится ссылкой: ключей R2 у стенда нет намеренно, и настоящий
 * файл сюда не загрузить. Проверяется не загрузка — её держат питоновские
 * тесты, — а то, что открытое доходит до глаз, а спрятанное не доходит.
 */
test('материалы задания: открытое видно классу, спрятанное — нет', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const work = await provingWork(teacher)

  await teacher.post('/api/attachments/', {
    work: work.id,
    url: 'https://example.com/variants.pdf',
    title: 'Условия варианта',
  })
  await teacher.post('/api/attachments/', {
    work: work.id,
    url: 'https://example.com/answers.pdf',
    title: 'Ответы к варианту',
    staff_only: true,
  })

  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)
  await page.getByRole('link', { name: 'Проверочная: формулы сложения' }).click()
  await ready(page)

  await expect(page.getByText('Условия варианта')).toBeVisible()
  await expect(page.getByText('Ответы к варианту')).toHaveCount(0)
})

/** «Проверочная» из демо: на ней проверяют и ответы, и материалы. */
async function provingWork(teacher) {
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const works = await teacher.get(`/api/works/?course=${course.id}`)

  return works.body.find((item) => item.title.startsWith('Проверочная'))
}

/** Первая задача «Проверочной» — в ней ученик отвечает, а учитель проверяет. */
async function firstTask(teacher) {
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const works = await teacher.get(`/api/works/?course=${course.id}`)
  const work = works.body.find((item) => item.title.startsWith('Проверочная'))
  const tasks = await teacher.get(`/api/works/tasks/?work=${work.id}`)

  return tasks.body[0]
}

/**
 * Бумажная работа: скан достаётся своему ученику и никому больше.
 *
 * Ключей R2 у стенда нет намеренно — тесты не пишут в чужой бакет, — поэтому
 * настоящий файл здесь не загрузить; вложение заводится ссылкой. Проверяется
 * не загрузка (её держат питоновские тесты), а граница: чужую работу не
 * видно, и ошибка в ней выглядит не отказом, а контрольной одноклассника на
 * экране.
 */
test('скан бумажной работы достаётся только своему ученику', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const work = await teacher.post('/api/works/', {
    course: course.id,
    title: 'Контрольная на бумаге',
    opens_at: new Date(Date.now() - 3600e3).toISOString(),
    closes_at: new Date(Date.now() + 3600e3).toISOString(),
  })

  // ученика берём из самой таблицы работы: там он уже есть по составу курса
  const table = await teacher.get(`/api/works/${work.body.id}/table/`)
  const mine = table.body.students.find((item) => item.email === PEOPLE.student)
  const row = await teacher.post(`/api/works/${work.body.id}/grade/`, {
    student: mine.id,
  })
  await teacher.post('/api/attachments/', {
    student_work: row.body.id,
    url: 'https://example.com/stepanov.pdf',
    title: 'stepanov.pdf',
  })

  // у учителя столбец работы есть и без задач: у бумажной в нём лежит скан
  await signIn(PEOPLE.ivanova)
  await page.goto(`/works/${work.body.id}`)
  await ready(page)

  const line = page.locator('.work-table tbody tr', { hasText: 'Артём Степанов' })
  await line.locator('td.mark button').click()
  const dialog = page.locator('dialog.modal')
  await expect(dialog.getByText('Скан работы')).toBeVisible()
  await expect(dialog.getByRole('link', { name: 'stepanov.pdf' })).toBeVisible()
  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()

  // свой ученик видит свою работу
  await signIn(PEOPLE.student)
  await page.goto('/')
  await ready(page)
  await page.getByRole('link', { name: 'Grade 6 Algebra' }).click()
  await ready(page)
  await page.getByRole('link', { name: 'Контрольная на бумаге' }).click()
  await ready(page)

  await expect(page.getByRole('link', { name: 'stepanov.pdf' })).toBeVisible()
  await expect(page.getByText('Работа написана на бумаге')).toBeVisible()

  // одноклассник — не видит ничего, и не узнаёт, что там что-то было
  await signIn(PEOPLE.otherStudent)
  await page.goto(`/works/${work.body.id}`)
  await ready(page)

  await expect(page.getByRole('link', { name: 'stepanov.pdf' })).toHaveCount(0)
})

/**
 * Экран разбора скана.
 *
 * Гонять его в браузере надо ради двух вещей, которых иначе не увидеть:
 * страницы рисует `pdfjs-dist`, подгружаемая лениво (в сборке такая ошибка
 * не видна, потому что код не выполняется), и разметка целиком живёт в
 * браузере — границы, куски, «кому какие страницы».
 *
 * До самой резки тест не доходит: у стенда нет ключей R2, и загрузка кусков
 * честно ответила бы «хранилище недоступно». Резку держат питоновские тесты.
 */
test('скан читается в браузере, и границы работ ставятся руками', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === 'Grade 6 Algebra')
  const work = await teacher.post('/api/works/', {
    course: course.id,
    title: 'Разбор пачки',
    opens_at: new Date(Date.now() - 3600e3).toISOString(),
    closes_at: new Date(Date.now() + 3600e3).toISOString(),
  })

  await signIn(PEOPLE.ivanova)
  await page.goto(`/works/${work.body.id}`)
  await ready(page)
  await page.getByRole('button', { name: 'разобрать скан' }).click()

  const dialog = page.locator('dialog.modal')
  await dialog.getByLabel('Отсканированный PDF').setInputFiles({
    name: 'class.pdf',
    mimeType: 'application/pdf',
    buffer: twoPagePdf(),
  })

  // страницы нарисовались — значит pdf.js доехала до бандла и заработала
  await expect(dialog.locator('.scan-pages > li')).toHaveCount(2)

  // первая страница всегда начало работы, вторую отмечаем сами
  await expect(dialog.locator('.scan-pages > li.starts')).toHaveCount(1)
  await dialog.locator('.scan-pages > li').nth(1).locator('.page').click()
  await expect(dialog.locator('.scan-pages > li.starts')).toHaveCount(2)

  // пока у кусков нет имён, разобрать нельзя: ошибка тут — чужая работа
  const submit = dialog.getByRole('button', { name: 'Разобрать и раздать' })
  await expect(submit).toBeDisabled()

  await dialog.getByLabel('Чья работа начинается на странице 1').selectOption({ index: 1 })
  await expect(dialog.getByText('Названо 1 из 2')).toBeVisible()
  await expect(submit).toBeDisabled()

  await dialog.getByLabel('Чья работа начинается на странице 2').selectOption({ index: 1 })
  await expect(dialog.getByText('Названо 2 из 2')).toBeVisible()
  await expect(submit).toBeEnabled()
})

/** Настоящий двухстраничный PDF: pdf.js берёт его без придирок. */
function twoPagePdf() {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] >>',
  ]

  let body = '%PDF-1.4\n'
  const offsets = []
  objects.forEach((object, index) => {
    offsets.push(body.length)
    body += `${index + 1} 0 obj\n${object}\nendobj\n`
  })

  const startxref = body.length
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  offsets.forEach((offset) => {
    body += `${String(offset).padStart(10, '0')} 00000 n \n`
  })
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n`
  body += `startxref\n${startxref}\n%%EOF\n`

  return Buffer.from(body, 'latin1')
}

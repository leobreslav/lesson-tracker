import { PEOPLE, expect, liveCourse, ready, test } from './harness.js'

/**
 * Даты прямо в таблице плана.
 *
 * Смысл раздела — не в самих датах, а в пересчёте: тема должна кончиться до
 * каникул, и чтобы это увидеть, нужно править план, глядя, как он ложится на
 * календарь. Поэтому почти каждый тест здесь — «сделали правку и сразу
 * посмотрели, что сдвинулось», без перезагрузки страницы.
 */

const COURSE = 'Grade 6 Algebra'

const openPlan = async (page, course = COURSE) => {
  await page.goto('/plan')
  await ready(page)
  // курс выбирают селектом в строке заголовка: чипы не пережили
  // учителя музыки с полутора десятками курсов
  await page.getByLabel('Курс').selectOption({ label: course })
  await expect(page.locator('.plan-cards')).toBeVisible()
}

/** Дата в строке урока с этим номером. */
const dateOf = (page, number) =>
  page
    .locator('.plan-row.lesson', {
      has: page.locator('.plan-number', { hasText: new RegExp(`^${number}$`) }),
    })
    .first()
    .locator('.plan-date')
    .textContent()

/** Дата урока с таким названием — движется именно она, а не номер строки. */
const dateOfLesson = (page, title) =>
  page
    .locator('.plan-row.lesson', { hasText: title })
    .first()
    .locator('.plan-date')
    .textContent()

/** Название первого урока следующей четверти — того, что под её заголовком. */
async function firstOfSecondTerm(page) {
  return page.evaluate(() => {
    const heads = [...document.querySelectorAll('.plan-term')]
    const second = heads[1]
    if (!second) return null
    let next = second.nextElementSibling
    while (next && !next.querySelector?.('.title')) next = next.nextElementSibling
    return next?.querySelector('.title')?.textContent.trim() ?? null
  })
}

test('даты видны, сводка сходится с раскладкой', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const number = async (card) =>
    Number(await page.locator(`[data-card="${card}"] :is(h2, b)`).textContent())

  const slots = await number('slots')
  const lessons = await number('lessons')
  const balance = await number('balance')

  // плашки сходятся между собой и с таблицей
  expect(slots - lessons).toBe(balance)
  await expect(page.locator('.plan-row.lesson .plan-date')).toHaveCount(lessons)
})

test('над таблицей одна панель управления, а под таблицей пусто', async ({
  page,
  signIn,
}) => {
  // Кнопки жили в двух карточках под таблицей, чекбоксы — полосой над ней,
  // и до «+ урок» на плане в сорок уроков надо было прокрутить полторы
  // тысячи пикселей. Теперь всё, что делают с планом целиком, — один ряд.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const tools = page.locator('.plan-tools')
  await expect(tools).toBeVisible()

  // на виду только частое — добавление и выбор; редкое под двумя меню,
  // и каждое названо своей темой: обмен файлами и полка
  for (const name of ['Добавить урок', 'Добавить тему', 'Выбрать', 'Файл', 'Библиотека']) {
    await expect(tools.getByRole('button', { name, exact: true })).toBeVisible()
  }

  await tools.getByRole('button', { name: 'Файл', exact: true }).click()
  for (const name of [/^Импорт/, /Экспорт в xlsx/, /Как выглядит файл/]) {
    await expect(
      tools.locator('.dropdown').getByRole('button', { name }),
    ).toBeVisible()
  }
  // полки в меню файла нет: темы разные, и это всё, ради чего их разделили
  await expect(
    tools.locator('.dropdown').getByRole('button', { name: /библиотек/ }),
  ).toHaveCount(0)

  await tools.getByRole('button', { name: 'Библиотека', exact: true }).click()
  for (const name of [/Загрузить из библиотеки/, /в библиотек/]) {
    await expect(
      tools.locator('.dropdown').getByRole('button', { name }),
    ).toBeVisible()
  }

  const box = await tools.boundingBox()
  expect(Math.round(box.height), 'панель разъехалась на несколько рядов').toBeLessThan(
    110,
  )

  // чекбоксов показа в ней не осталось: даты, недели и свободные слоты
  // показываются всегда, а прятать их было незачем
  await expect(tools.locator('input[type="checkbox"]')).toHaveCount(0)

  // и стоит она над таблицей, а под таблицей не осталось ни одной карточки
  const table = await page.locator('ul.plan').first().boundingBox()
  expect(box.y + box.height).toBeLessThanOrEqual(table.y + 1)
  const below = await page.evaluate(() => {
    const list = document.querySelector('ul.plan').getBoundingClientRect()
    return [...document.querySelectorAll('.page > .panel')].filter(
      (panel) => panel.getBoundingClientRect().top > list.top,
    ).length
  })
  expect(below, 'под таблицей снова что-то выросло').toBe(0)
})

test('в плане видно, какой час записан, а какой — долг', async ({
  page,
  signIn,
  api,
}) => {
  // Три состояния часа, и все три на своей строке: записан, долг, обычный.
  // По ним и видно, где учёт остановился — очередь-то строгая.
  const { course, slots } = await liveCourse(api)

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  // первый час записан фикстурой, второй прошёл и не записан. Значки
  // спрашиваем в таблице: те же ✓ и • стоят теперь в сводке легендой
  const table = page.locator('ul.plan').first()
  await expect(table.locator('.plan-state.recorded')).toHaveCount(1)
  const debts = table.locator('.plan-state.unclosed')
  await expect(debts).toHaveCount(2)

  // и оба числа стоят одной плашкой в сводке: «два не отмечено» — беда при
  // двух записанных и мелочь при сотне. Значки там же и служат легендой
  const records = page.locator('[data-card="records"]')
  await expect(records.locator('[data-card="recorded"]')).toContainText('1')
  await expect(records.locator('[data-card="recorded"] .plan-state.recorded')).toHaveText(
    '✓',
  )
  await expect(records.locator('[data-card="debts"]')).toContainText('2')
  await expect(records.locator('[data-card="debts"] .plan-state.unclosed')).toHaveText('•')

  // нажатие на число долгов открывает разбор
  await records.locator('[data-card="debts"] button').click()
  await expect(page.locator('dialog.modal')).toBeVisible()
})

test('значки состояния стоят в столбик перед датами', async ({
  page,
  signIn,
  api,
}) => {
  // Место под значок занято всегда: иначе даты у помеченных строк съезжали
  // бы относительно остальных, а значки не складывались бы в столбик.
  const { course } = await liveCourse(api)

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  // и даты, и значки: у обоих один левый край на всю таблицу
  for (const what of ['.plan-date', '.plan-state']) {
    const left = await page
      .locator(`.plan-row.lesson ${what}`)
      .evaluateAll((nodes) =>
        nodes.map((node) => Math.round(node.getBoundingClientRect().x)),
      )
    expect(new Set(left).size, `${what} съехали: ${left}`).toBe(1)
  }
})

test('в сетке расписания у долга красная точка', async ({ page, signIn, api }) => {
  // Час, который держит очередь, надо увидеть не заходя в занятие.
  const { slots } = await liveCourse(api)

  await signIn(PEOPLE.ivanova)
  await page.goto('/schedule')
  await ready(page)
  await page.getByLabel('Перейти к дате').fill(slots[1].date)

  const debt = page.locator(`[data-lesson="${slots[1].date}:1"]`)
  await expect(debt).toHaveClass(/debt/)

  // К записанному часу надо **перейти**: часы живого курса стоят на подряд
  // идущих днях, а сетка показывает одну неделю — во вторник позавчерашний
  // час лежит уже в прошлой. Пока обе клетки искали на одном экране, тест
  // падал по вторникам и средам, а по понедельникам проходил
  await page.getByLabel('Перейти к дате').fill(slots[0].date)
  await expect(page.locator(`[data-lesson="${slots[0].date}:1"]`)).not.toHaveClass(
    /debt/,
  )
})

test('дата в плане ведёт в занятие этого дня', async ({ page, signIn }) => {
  // Строка плана отвечает «что проходим», занятие — «как оно прошло»:
  // журнал, работы, отмена. Обратный путь (со страницы занятия в план) есть
  // давно, а этого не было вовсе.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const row = page.locator('.plan-row.lesson').first()
  const title = await row.locator('.title').first().textContent()
  await row.locator('.plan-date').click()
  await ready(page)

  await expect(page).toHaveURL(/\/lesson\/\d+$/)
  await expect(page.locator('h1')).toHaveText(title.trim())
})

test('добавление урока сдвигает даты ниже, удаление возвращает', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const lessons = page.locator('.plan-row.lesson')
  const second = (await lessons.nth(1).locator('.title').textContent()).trim()
  const dateOfSecond = await dateOfLesson(page, second)
  const thirdSlot = await dateOf(page, 3)
  expect(dateOfSecond).not.toBe(thirdSlot)

  // вставляем урок после первого — второй уезжает на слот вперёд
  // кнопки строки появляются при наведении
  await lessons.first().hover()
  await lessons.first().getByTitle('Вставить после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Вставка')
  await form.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toBeVisible()
  await expect.poll(() => dateOfLesson(page, second)).toBe(thirdSlot)
  // а сама вставка встала на освободившуюся дату
  expect(await dateOfLesson(page, 'Вставка')).toBe(dateOfSecond)

  // и обратно: удалили — даты вернулись. Подтверждение теперь своё окно, а
  // не нативное: оно называет строку и цену, которой у нативного не было
  const inserted = page.locator('.plan-row', { hasText: 'Вставка' })
  await inserted.hover()
  await inserted.getByTitle('Удалить').click()
  await page
    .locator('dialog[open]')
    .getByRole('button', { name: 'Удалить', exact: true })
    .click()

  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toHaveCount(0)
  await expect.poll(() => dateOfLesson(page, second)).toBe(dateOfSecond)
})

test('граница четверти приходится на другой урок, когда выше добавили', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const heads = page.locator('.plan-term')
  await expect(heads.first()).toContainText('четверть')
  const before = await firstOfSecondTerm(page)

  const first = page.locator('.plan-row.lesson').first()
  await first.hover()
  await first.getByTitle('Вставить после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Ещё один урок')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Ещё один урок' })).toBeVisible()

  // заголовок четверти остался на своём слоте, а первым её уроком стал другой
  await expect.poll(() => firstOfSecondTerm(page)).not.toBe(before)
})

test('каникулы отмечены между уроками', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const holidays = page.locator('.plan-divider.break').first()

  await expect(holidays).toContainText('каникулы')
})

test('перетаскивание пересчитывает даты сразу', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const lessons = page.locator('.plan-row.lesson')
  const secondTitle = await lessons.nth(1).locator('.title').textContent()
  const firstDate = await dateOf(page, 1)

  await lessons.nth(1).hover()
  const handle = lessons.nth(1).getByTitle('Перетащить')
  const target = lessons.first()
  const from = await handle.boundingBox()
  const to = await target.boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + 2, { steps: 12 })
  await page.mouse.up()

  // урок переехал наверх и взял дату первого слота — до ответа сервера
  await expect(lessons.first().locator('.title')).toHaveText(secondTitle)
  await expect(lessons.first().locator('.plan-date')).toHaveText(firstDate)
})

test('уроки без слота помечены', async ({
  page,
  signIn,
  api,
}) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === COURSE)
  // оставляем расписание только на сентябрь: план сорока уроков перестаёт
  // помещаться, и это ровно тот случай, ради которого даты и нужны
  await teacher.delete(
    `/api/slots/bulk/?course=${course.id}&start=2026-10-01&end=2027-08-01`,
  )

  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const missing = page.locator('.plan-row.lesson.no-slot')
  await expect(missing.first()).toBeVisible()
  await expect(missing.first().locator('.plan-date')).toHaveText('не помещается')

  // баланс отрицательный; отдельной плашки «не помещается» нет — строки
  // говорят это сами, а плашка повторяла их счётом
  await expect(page.locator('[data-card="balance"].bad')).toBeVisible()
  await expect(page.locator('[data-card="missing"]')).toHaveCount(0)

  // у главы дат нет вовсе — только число уроков: даты живут в левой зоне
  await expect(page.locator('.section-head .block-count').first()).toHaveText(
    /уроков|урока|урок/,
  )
})

test('переключатель дат запоминается и не двигает названия', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // колонка дат жёсткой ширины и стоит первой: строки выстраиваются в
  // столбец, как бы ни различались названия и пометки
  const widths = await page
    .locator('.plan-row.lesson .plan-date')
    .evaluateAll((cells) => [...new Set(cells.map((cell) => cell.clientWidth))])
  expect(widths).toHaveLength(1)

  const lefts = await page
    .locator('.plan-row.lesson .plan-date')
    .evaluateAll((cells) => [
      ...new Set(cells.map((cell) => Math.round(cell.getBoundingClientRect().left))),
    ])
  expect(lefts).toHaveLength(1)

  // названия тоже стоят столбцом: колонка дат одной ширины у всех строк
  const titles = await page
    .locator('.plan-row.lesson .title')
    .evaluateAll((cells) => [
      ...new Set(cells.map((cell) => Math.round(cell.getBoundingClientRect().left))),
    ])
  expect(titles).toHaveLength(1)

})

test('недели: подпись в первой строке и заливка через одну', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const labels = page.locator('.plan-weekmark', { hasText: 'нед' })
  await expect(labels.first()).toHaveText('нед 1')
  await expect(labels.nth(1)).toHaveText('нед 2')

  // группы задаёт заливка: чередуется через одну, и в каждой ровно одна
  // подпись — где именно, проверяет следующий тест
  const runs = await page.evaluate(() => {
    const out = []
    let previous = null
    document.querySelectorAll('.plan-row').forEach((row) => {
      const even = row.classList.contains('week-even')
      const label = row.querySelector('.plan-weekmark')?.textContent.trim()
      if (previous === null || even !== previous) out.push({ even, labels: [] })
      previous = even
      if (label) out.at(-1).labels.push(label)
    })
    return out.slice(0, 4)
  })

  expect(runs.map((run) => run.even)).toEqual([false, true, false, true])
  for (const run of runs) expect(run.labels).toHaveLength(1)
})

test('номер недели стоит у урока, а не у главы', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const carriers = await page.evaluate(() =>
    [...document.querySelectorAll('.plan-weekmark')]
      .filter((mark) => mark.textContent.trim())
      .map((mark) => {
        const row = mark.closest('.plan-row')
        return {
          section: row.classList.contains('section-head'),
          date: row.querySelector('.plan-date')?.textContent.trim() ?? '',
        }
      }),
  )

  expect(carriers.length).toBeGreaterThan(3)
  // ни одной подписи на строке главы, и у каждой рядом стоит дата
  expect(carriers.filter((row) => row.section)).toEqual([])
  expect(carriers.filter((row) => !row.date)).toEqual([])
})

test('заголовок главы не разрывает неделю', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // глава закрашена так же, как уроки вокруг неё: она внутри той же недели
  const broken = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.plan-row')]
    return rows.filter((row, index) => {
      if (!row.classList.contains('section-head')) return false
      const next = rows[index + 1]
      return (
        next &&
        !next.querySelector('.plan-weekmark')?.textContent.trim() &&
        next.classList.contains('week-even') !== row.classList.contains('week-even')
      )
    }).length
  })

  expect(broken).toBe(0)
})

test('вставленный урок переносит уроки через границу недели', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  /** Название урока, у которого стоит подпись «нед 2». */
  const labelled = () =>
    page.evaluate(() => {
      const mark = [...document.querySelectorAll('.plan-weekmark')].find(
        (item) => item.textContent.trim() === 'нед 2',
      )
      return mark?.closest('.plan-row')?.querySelector('.title')?.textContent.trim()
    })

  const before = await labelled()

  const first = page.locator('.plan-row.lesson').first()
  await first.hover()
  await first.getByTitle('Вставить после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Ещё урок')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Ещё урок' })).toBeVisible()

  // недели задаёт расписание, а не план, поэтому съехали уроки, а не недели
  await expect.poll(labelled).not.toBe(before)
})

test('недели выключаются отдельно, а без дат исчезают вместе с ними', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  await expect(page.locator('.plan-row.week-even').first()).toBeVisible()
  // подпись недели стоит в первой строке группы, и она одна на группу
  await expect(page.locator('.plan-weekmark', { hasText: 'нед' }).first()).toBeVisible()
  await expect(page.locator('.plan-row.lesson .plan-date').first()).toBeVisible()
})

test('маркеры, номера и названия стоят по вертикалям', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const columns = () =>
    page.evaluate(() => {
      const lefts = (selector) => [
        ...new Set(
          [...document.querySelectorAll(selector)].map((el) =>
            Math.round(el.getBoundingClientRect().left),
          ),
        ),
      ]
      return {
        sections: lefts('.plan-row.section-head > .handle'),
        lessons: lefts('.plan-row.lesson > .handle'),
        sectionTitles: lefts('.plan-row.section-head .title'),
        nested: lefts('.plan-title-cell.nested .title'),
        loose: lefts(
          '.plan-row.lesson .plan-title-cell:not(.nested) .title',
        ),
        numbers: [
          ...new Set(
            [...document.querySelectorAll('.plan-row.lesson .plan-number')].map((el) =>
              Math.round(el.getBoundingClientRect().right),
            ),
          ),
        ],
        dates: lefts('.plan-row.lesson .plan-date'),
      }
    })

  const before = await columns()
  // маркеры глав и уроков — одна вертикаль на всех, без исключений
  expect(before.sections).toEqual(before.lessons)
  expect(before.lessons).toHaveLength(1)
  // номера — одна вертикаль, значит названия не пляшут от числа цифр
  expect(before.numbers).toHaveLength(1)
  expect(before.dates).toHaveLength(1)
  // названий две вертикали, и это единственное, чем видна вложенность
  expect(before.sectionTitles).toHaveLength(1)
  expect(before.nested).toHaveLength(1)
  expect(before.nested[0] - before.sectionTitles[0]).toBe(20)

})

test('в правой зоне нет ни одной даты', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // дата — только в своей колонке; в строке главы её нет вовсе
  const strays = await page.evaluate(() => {
    const dateLike = /\d{2}[./]\d{2}/
    return [...document.querySelectorAll('.plan-title-cell, .row-actions')]
      .map((cell) => cell.textContent.trim())
      .filter((text) => dateLike.test(text))
  })

  expect(strays).toEqual([])
})

test('глава — только шрифт, без заливки и полос', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const looks = await page.evaluate(() => {
    const head = document.querySelector('.plan-row.section-head:not(.week-even)')
    const title = head.querySelector('.title')
    const style = getComputedStyle(title)
    const row = getComputedStyle(head)
    return {
      transform: style.textTransform,
      weight: Number(style.fontWeight),
      spacing: style.letterSpacing,
      background: row.backgroundColor,
      border: row.borderLeftWidth + row.borderBottomWidth,
    }
  })

  expect(looks.transform).toBe('uppercase')
  expect(looks.weight).toBeGreaterThanOrEqual(600)
  expect(looks.spacing).not.toBe('normal')
  // ни заливки, ни рамок — иначе они сдвинули бы маркер
  expect(looks.background).toBe('rgba(0, 0, 0, 0)')
  expect(looks.border).toBe('0px0px')
})

test('урок вне темы стоит на уровне темы, а вложенный — с отступом', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.petrov)
  await page.goto('/plan')
  await ready(page)
  // курс без плана: соберём в нём тему, урок внутри и урок вне
  await page.getByLabel('Курс').selectOption({ label: 'Grade 9 Geometry' })
  await expect(page.locator('.plan-cards')).toBeVisible()

  const add = async (button, title) => {
    await page.getByRole('button', { name: button }).click()
    const form = page.locator('.plan-add-form')
    await form.getByLabel('Название').fill(title)
    await form.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
  }

  await add('Добавить тему', 'Треугольники')
  const head = page.locator('.plan-section .section-head').first()
  await head.hover()
  await head.getByTitle('Добавить урок в тему').click()
  const inner = page.locator('.plan-add-form')
  await inner.getByLabel('Название').fill('Первый признак')
  await inner.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Первый признак' })).toBeVisible()

  await add('Добавить урок', 'Сам по себе')

  const left = (title) =>
    page
      .locator('.plan-row', { hasText: title })
      .first()
      .locator('.title')
      .evaluate((el) => Math.round(el.getBoundingClientRect().left))

  const theme = await left('Треугольники')
  expect(await left('Первый признак')).toBe(theme + 20)
  // урок вне темы — на одной вертикали с названием темы
  expect(await left('Сам по себе')).toBe(theme)
})

test('перетаскивание в тему и обратно меняет отступ сразу', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // первый урок первой темы вытаскиваем на верхний уровень, к её заголовку
  const lesson = page.locator('.plan-row.lesson').first()
  const title = await lesson.locator('.title').textContent()
  const nestedAt = await lesson
    .locator('.title')
    .evaluate((el) => Math.round(el.getBoundingClientRect().left))

  const head = page.locator('.plan-row.section-head').first()
  await lesson.hover()
  const handle = lesson.getByTitle('Перетащить')
  const from = await handle.boundingBox()
  const to = await head.boundingBox()
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(to.x + to.width / 2, to.y + 2, { steps: 12 })
  await page.mouse.up()

  // отступ пропал в том же кадре, без ответа сервера
  const moved = page.locator('.plan-row', { hasText: title }).first()
  await expect
    .poll(() =>
      moved.locator('.title').evaluate((el) => Math.round(el.getBoundingClientRect().left)),
    )
    .toBe(nestedAt - 20)
})

test('свободные слоты свёрнуты, раскрываются и помнят это', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // по умолчанию — одна строка вместо пятидесяти девяти
  const summary = page.locator('.free-summary')
  await expect(summary).toContainText('свободных уроков')
  await expect(page.locator('.plan-row.free')).toHaveCount(0)

  await summary.click()
  const free = page.locator('.plan-row.free')
  expect(await free.count()).toBeGreaterThan(5)
  // у заглушки есть дата, но нет ни ручки, ни номера
  await expect(free.first().locator('.plan-date')).not.toBeEmpty()
  await expect(free.first().locator('.handle')).toHaveCount(0)
  await expect(free.first().locator('.plan-number')).toHaveCount(0)
  await expect(free.first()).toContainText('свободный урок')

  await page.reload()
  await ready(page)
  await expect(page.locator('.plan-row.free').first()).toBeVisible()
})

test('чередование недель продолжается на свободных слотах', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)
  await page.locator('.free-summary').click()

  // полоса заливки идёт по неделе, а не по тому, план это или пустое место
  const mixed = await page.evaluate(() => {
    const marks = [...document.querySelectorAll('.plan-row.free')].map((row) => ({
      even: row.classList.contains('week-even'),
      label: row.querySelector('.plan-weekmark')?.textContent.trim() ?? '',
    }))
    // у каждой подписи чередование должно переключаться
    return marks.filter(
      (row, index) => row.label && index > 0 && marks[index - 1].even === row.even,
    ).length
  })

  expect(mixed).toBe(0)
})

test('в свободный слот вставляется урок, и остальные пересчитываются', async ({
  page,
  signIn,
}) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)
  await page.locator('.free-summary').click()

  const free = page.locator('.plan-row.free')
  const before = await free.count()
  const firstDate = await free.first().locator('.plan-date').textContent()

  await free.first().getByRole('button', { name: 'свободный урок' }).click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Занял свободный день')
  await form.getByRole('button', { name: 'Добавить' }).click()

  const added = page.locator('.plan-row', { hasText: 'Занял свободный день' })
  await expect(added).toBeVisible()
  // урок встал на первую свободную дату, а свободных стало на одну меньше
  await expect(added.locator('.plan-date')).toHaveText(firstDate.trim())
  await expect.poll(() => free.count()).toBe(before - 1)
})

test('у курса без расписания нет ни дат, ни свободных слотов', async ({
  page,
  signIn,
  api,
}) => {
  // Чекбокса «Даты» больше нет, и он не нужен: колонки появляются вместе с
  // расписанием, то есть ровно тогда, когда им есть что показывать. Нет
  // расписания — нет и «не помещается» на каждой строке.
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === COURSE)
  await teacher.delete(
    `/api/slots/bulk/?course=${course.id}&start=2026-08-01&end=2027-08-01`,
  )

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption({ label: COURSE })

  await expect(page.locator('.plan-row.lesson').first()).toBeVisible()
  await expect(page.locator('.plan-date')).toHaveCount(0)
  await expect(page.locator('.plan-weekmark', { hasText: 'нед' })).toHaveCount(0)
  await expect(page.locator('.free-summary')).toHaveCount(0)
  await expect(page.locator('.plan-row.free')).toHaveCount(0)
})

test('при дефиците свободных нет вовсе', async ({ page, signIn, api }) => {
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === COURSE)
  await teacher.delete(
    `/api/slots/bulk/?course=${course.id}&start=2026-10-01&end=2027-08-01`,
  )

  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // план не помещается — свободному месту взяться неоткуда
  await expect(page.locator('.plan-row.lesson.no-slot').first()).toBeVisible()
  await expect(page.locator('.free-summary')).toHaveCount(0)
  await expect(page.locator('.plan-row.free')).toHaveCount(0)
})

/**
 * Связь «занятие проведено»: запись сильнее позиции.
 *
 * Раскладка была чистым zip'ом и молча переписывала прошлое: вставили урок
 * в начало плана — и сентябрь съезжал вместе со всей лентой. Час со связью
 * держится за дату, а строку, которая за ним записана, больше не двигают:
 * позиция и запись иначе начинают говорить разное.
 *
 * Записать связь можно только у прошедшего занятия, но **проставить** её
 * через API дата не мешает — сервер записывает, что ему сказали. Учебный год
 * демо-данных весь в будущем, поэтому здесь связь ставится запросом.
 */
test('проведённый урок держится за дату и не переставляется', async ({
  page,
  signIn,
  api,
}) => {
  // курс живой: записать можно только прошедший час, а у посеянного года
  // прошедших нет ни одного
  const { course, rows } = await liveCourse(api)
  const anchored = rows[0]

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  // выбираем по id, а не по названию: живых годов в базе несколько, и
  // подпись курса несёт ещё и год
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  const before = await dateOfLesson(page, anchored.title)
  const row = page.locator('.plan-row.lesson', { hasText: anchored.title }).first()

  // ручки нет, а место под неё есть: строка не должна съезжать
  const handle = row.locator('.handle.locked')
  await expect(handle).toBeHidden()
  const free = page.locator('.plan-row.lesson button.handle').first()
  expect((await handle.boundingBox()).width).toBeCloseTo(
    (await free.boundingBox()).width,
    0,
  )

  // вставляем урок выше него — всё, что ниже, обычно уезжает на день
  const first = page.locator('.plan-row.lesson').first()
  const drifting = rows[1].title
  const driftingBefore = await dateOfLesson(page, drifting)

  await first.hover()
  await first.getByTitle('Вставить после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Вставка')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toBeVisible()

  // несвязанный уехал — значит правка дошла и лента пересчиталась
  await expect.poll(() => dateOfLesson(page, drifting)).not.toBe(driftingBefore)
  // а записанный стоит там же: за ним записан час
  expect(await dateOfLesson(page, anchored.title)).toBe(before)
})

test('форма, оставшаяся открытой, не лезет выше проведённой строки', async ({
  page,
  signIn,
  api,
}) => {
  // Форма «вставить после» перестала закрываться и переезжает якорем за
  // созданную строку. Проверяется здесь ровно то, что этот переезд не
  // прогрызает жёсткий порядок: вводить подряд можно только вниз, а
  // записанный час остаётся на своём дне.
  const { course, rows } = await liveCourse(api)
  const anchored = rows[0]

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  const before = await dateOfLesson(page, anchored.title)

  // единственное, что позволено проведённой строке: дописать за ней
  const taught = page.locator('.plan-row.lesson', { hasText: anchored.title }).first()
  await taught.hover()
  await taught.getByTitle('Вставить после').click()

  const form = page.locator('.plan-add-form')
  for (const title of ['Дописка А', 'Дописка Б']) {
    await form.getByLabel('Название').fill(title)
    await form.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
  }
  await page.keyboard.press('Escape')

  // обе встали ниже проведённой и в порядке ввода, а не задом наперёд
  const numbers = await page.locator('.plan-row.lesson').evaluateAll((list) =>
    list.map((row) => [
      row.querySelector('.plan-number')?.textContent.trim(),
      row.querySelector('.title')?.textContent.trim(),
    ]),
  )
  const at = (title) => Number(numbers.find((pair) => pair[1] === title)?.[0])
  expect(at(anchored.title)).toBe(1)
  expect(at('Дописка А')).toBe(2)
  expect(at('Дописка Б')).toBe(3)

  // и записанный час никуда не уехал: связь сильнее позиции. Значок
  // спрашиваем в таблице — те же ✓ стоят и в сводке, легендой
  expect(await dateOfLesson(page, anchored.title)).toBe(before)
  await expect(page.locator('ul.plan .plan-state.recorded')).toHaveCount(1)
})

test('у проведённой строки органов управления нет, кроме «+» у последней', async ({
  page,
  signIn,
  api,
}) => {
  // Сперва их прятали совсем, потом вернули бледными — и оба раза мимо.
  // Проведённой строке нечего предложить: ни двинуть, ни удалить. Дело к
  // ней остаётся ровно одно, и только к последней: провели то, чего в
  // плане нет, — строку дописывают сразу за ней.
  const { course } = await liveCourse(api)

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  const row = (number) =>
    page
      .locator('.plan-row.lesson', {
        has: page.locator('.plan-number', { hasText: new RegExp(`^${number}$`) }),
      })
      .first()

  // первая проведена: один «+», и больше ничего
  await expect(row(1).locator('.row-actions button')).toHaveCount(1)
  await expect(row(1).getByTitle('Вставить после')).toBeEnabled()

  // непроведённые строки полны кнопок, как и были
  for (const number of [2, 3]) {
    await expect(row(number).locator('.row-actions button')).toHaveCount(4)
  }

  // вторая свободна, но подниматься ей некуда: выше проведённая
  await expect(row(2).getByTitle('Перед проведённым уроком места нет')).toBeDisabled()
  await expect(row(2).getByTitle('Ниже')).toBeEnabled()
  // третья ходит в обе стороны
  await expect(row(3).getByTitle('Выше')).toBeEnabled()
  await expect(row(3).getByTitle('Ниже')).toBeEnabled()
})

test('черта «сегодня» называет и дату', async ({ page, signIn }) => {
  // Слово без числа не говорит, где именно сегодня на этой ленте: черта
  // стоит перед первым непрошедшим уроком, а какое это число — не видно.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const line = page.locator('.plan-today')
  await expect(line).toBeVisible()
  await expect(line).toContainText('Сегодня –')
  // день недели и число — рядом
  await expect(line.locator('.plan-today-date')).toHaveText(
    /(понедельник|вторник|сред|четверг|пятниц|суббот|воскресень).+\d/,
  )

  // Одна фраза — один набор: слово и дата стоят на одной линии и написаны
  // одинаково. Слово было мельче и жирнее, дата крупнее и приглушённее, а
  // сверх того у неё был свой верхний отступ, уводивший её вниз, — глазами
  // это «чуть съехало и чем-то отличается», а мерится в один вопрос.
  const same = await line.evaluate((el) => {
    const read = (selector) => {
      const node = el.querySelector(selector)
      const box = node.getBoundingClientRect()
      const style = getComputedStyle(node)
      return {
        middle: box.top + box.height / 2,
        font: `${style.fontSize} ${style.fontWeight} ${style.fontFamily}`,
        color: style.color,
        opacity: style.opacity,
      }
    }
    return { label: read('.plan-today-label'), date: read('.plan-today-date') }
  })

  expect(Math.abs(same.label.middle - same.date.middle)).toBeLessThanOrEqual(1)
  expect(same.date.font).toBe(same.label.font)
  expect(same.date.color).toBe(same.label.color)
  expect(same.date.opacity).toBe(same.label.opacity)
})

test('пока учёт не начат, плашка говорит, сколько часов прошло', async ({
  page,
  signIn,
  api,
}) => {
  // «0 не отмечено» было бы неправдой по существу: занятия прошли, просто
  // долгами они не считаются, пока учитель не начал. Поэтому вторая строка
  // здесь называет прошедшие часы и ведёт к первому из них.
  const { course, slots } = await liveCourse(api, { record: false })

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  const card = page.locator('[data-card="records"]')
  await expect(card.locator('[data-card="recorded"] b')).toHaveText('0')
  const notStarted = card.locator('[data-card="not-started"]')
  await expect(notStarted.locator('b')).toHaveText('3')
  await expect(notStarted.locator('span:not(.plan-state)')).toHaveText(
    'занятия прошли — учёт не начат',
  )
  // долгов при этом нет ни одного: счёт идёт от первой записи
  await expect(page.locator('ul.plan .plan-state.unclosed')).toHaveCount(0)

  // нажатие ведёт на первый прошедший час — там и стоит «так и было»
  await notStarted.locator('button').click()
  await expect(page).toHaveURL(new RegExp(`/lesson/${slots[0].id}$`))
})

test('пока год не начался, плашки учёта нет вовсе', async ({ page, signIn, api }) => {
  const { course, slots, teacher } = await liveCourse(api, { record: false })

  // убираем прошедшие часы и ставим только будущие: записывать нечего
  for (const slot of slots) {
    const gone = await teacher.delete(`/api/slots/${slot.id}/`)
    expect(gone.status).toBe(204)
  }
  for (const shift of [3, 5]) {
    const at = new Date()
    at.setDate(at.getDate() + shift)
    const added = await teacher.post('/api/slots/', {
      course: course.id,
      date: at.toISOString().slice(0, 10),
      lesson_number: 1,
    })
    expect(added.status, JSON.stringify(added.body)).toBe(201)
  }

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  // слоты и баланс на месте, а сообщать про учёт нечего
  await expect(page.locator('[data-card="slots"]')).toContainText('2')
  await expect(page.locator('[data-card="records"]')).toHaveCount(0)
})

test('числа в плашках стоят столбиком, а подписи склоняются', async ({
  page,
  signIn,
  api,
}) => {
  // «93 слотов» и «102 урока» считали ширину каждый сам, и подписи
  // начинались на разной вертикали. Числа теперь в общей колонке сетки, а
  // подпись знает про число, но его не печатает — склонение общее.
  const { course, teacher } = await liveCourse(api)

  // десять слотов против трёх строк плана: числа разной длины, ради них
  // проверка и заведена
  for (let shift = 1; shift <= 7; shift += 1) {
    const at = new Date()
    at.setDate(at.getDate() + shift)
    const slot = await teacher.post('/api/slots/', {
      course: course.id,
      date: at.toISOString().slice(0, 10),
      lesson_number: 1,
    })
    expect(slot.status, JSON.stringify(slot.body)).toBe(201)
  }

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  const rightEdge = async (card) => {
    const box = await page.locator(`[data-card="${card}"] b`).boundingBox()
    return Math.round(box.x + box.width)
  }

  await expect(page.locator('[data-card="slots"]')).toContainText('10')
  expect(await rightEdge('slots')).toBe(await rightEdge('lessons'))

  // и подпись согласована с числом: одно занятие — «занятие», два —
  // «занятия». Пробелов между числом и подписью в разметке нет вовсе —
  // зазор рисует сетка, — поэтому спрашиваем саму подпись
  const label = (card) =>
    page.locator(`[data-card="${card}"] span:not(.plan-state)`)
  await expect(label('recorded')).toHaveText('занятие проведено')
  await expect(label('debts')).toHaveText('занятия не отмечены')
})

test('в тему, где всё проведено, урок не вставить посреди записей', async ({
  page,
  signIn,
  api,
}) => {
  // Самая тихая из дыр: перенос строки за спину записи запрещали, а «+» в
  // шапке темы вставляла туда новую — то есть делала руками ровно ту
  // дыру, которую перенос делать не даёт.
  const { course, rows, slots, teacher } = await liveCourse(api)

  // заводим тему с одним уроком и записываем его вторым часом; за ней
  // остаётся третья строка плана — непроведённая
  const section = await teacher.post('/api/plan/', {
    course: course.id,
    title: 'Тема с записью',
    is_section: true,
    before: rows[1].id,
  })
  expect(section.status, JSON.stringify(section.body)).toBe(201)
  const inside = await teacher.post('/api/plan/', {
    course: course.id,
    parent: section.body.id,
    title: 'Единственный урок темы',
  })
  expect(inside.status, JSON.stringify(inside.body)).toBe(201)
  const done = await teacher.patch(`/api/slots/${slots[1].id}/`, {
    lesson: inside.body.id,
  })
  expect(done.status, JSON.stringify(done.body)).toBe(200)

  await signIn(PEOPLE.ivanova)
  await page.goto('/plan')
  await ready(page)
  await page.getByLabel('Курс').selectOption(String(course.id))
  await expect(page.locator('.plan-cards')).toBeVisible()

  // «+» в шапке заводит **первый** урок темы, а первый урок тут записан —
  // новая строка встала бы перед записью, и кнопки нет
  const head = page.locator('.plan-section .section-head', { hasText: 'Тема с записью' })
  await head.hover()
  await expect(head.getByTitle('Добавить урок в тему')).toHaveCount(0)

  // дописать в конец темы при этом можно, и тем же жестом: «+» у её
  // последнего урока — он же последняя запись
  const recorded = page.locator('.plan-row.lesson', { hasText: 'Единственный урок темы' })
  await recorded.hover()
  await expect(recorded.getByTitle('Вставить после')).toBeVisible()

  // а вот у первой строки, за которой стоит ещё одна запись, «+» нет
  const first = page
    .locator('.plan-row.lesson', {
      has: page.locator('.plan-number', { hasText: /^1$/ }),
    })
    .first()
  await first.hover()
  await expect(first.getByTitle('Вставить после')).toHaveCount(0)
})

test('выделение мышью не закрывает окно, а клик по фону закрывает', async ({
  page,
  signIn,
}) => {
  // Выделяешь название справа налево, отпускаешь кнопку чуть за рамкой —
  // и окно закрывалось вместе с правкой: браузер адресует `click` общему
  // предку нажатия и отпускания, то есть самому <dialog>. Поле у рамки
  // узкое, и повторяется это раз за разом.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  await page.locator('.plan-row.lesson .title').first().click()
  const dialog = page.locator('dialog.modal')
  await expect(dialog).toBeVisible()

  const field = dialog.locator('input').first()
  const box = await field.boundingBox()
  const modal = await dialog.locator('.modal-body').boundingBox()

  // от конца поля тянем влево и отпускаем **за** окном
  await page.mouse.move(box.x + box.width - 5, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(modal.x - 60, box.y + box.height / 2, { steps: 10 })
  await page.mouse.up()

  await expect(dialog).toBeVisible()

  // а честный клик по фону — нажали и отпустили там же — закрывает
  await page.mouse.click(modal.x - 60, box.y + box.height / 2)
  await expect(dialog).toHaveCount(0)
})

test('строка под курсором подсвечивается и на полосе недели', async ({
  page,
  signIn,
}) => {
  // Подсветка стояла в файле **до** заливки недели, вес у правил
  // одинаковый — и на каждой второй неделе её не было вовсе. А там, где
  // была, от полосы её было не отличить.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const colour = (row) =>
    row.evaluate((el) => getComputedStyle(el).backgroundColor)

  for (const selector of ['.plan-row.lesson.week-even', '.plan-row.lesson:not(.week-even)']) {
    const row = page.locator(selector).first()
    const before = await colour(row)
    await row.hover()
    const after = await colour(row)
    expect(after, `${selector}: наведение не меняет фон`).not.toBe(before)
    // и это заметный шаг, а не полтона: синий канал уходит вперёд остальных
    const [r, g, b] = after.match(/\d+/g).map(Number)
    expect(b - r, `${selector}: подсветка сливается с фоном`).toBeGreaterThan(20)
  }
})

test('стрелки отрываются от списка: строка ходит, блок стоит', async ({
  page,
  signIn,
}) => {
  // Второе нажатие приходилось по соседу: строки поменялись местами, а мышь
  // осталась там же. Теперь после первого нажатия на том же месте стоит
  // маленький блок со стрелками — он не двигается, ходит строка.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  // строку берём в середине темы: у первой и последней шаг вверх — это
  // выход из блока, и сквозной номер при нём не меняется
  const row = page
    .locator('.plan-row.lesson', {
      has: page.locator('.plan-number', { hasText: /^10$/ }),
    })
    .first()
  const anchor = await row.getAttribute('data-node')
  const held = page.locator(`li[data-node="${anchor}"]`)
  const number = 10

  await row.hover()
  const arrow = row.getByTitle('Выше')
  const box = await arrow.boundingBox()
  await arrow.click()

  // блок появился ровно там, где была кнопка
  const floating = page.locator('.plan-held')
  await expect(floating).toBeVisible()
  const up = await floating.getByTitle('Выше').boundingBox()
  expect(Math.abs(up.x - box.x), 'стрелка уехала по горизонтали').toBeLessThan(3)
  expect(Math.abs(up.y - box.y), 'стрелка уехала по вертикали').toBeLessThan(3)

  // строка подсвечена, и это она
  await expect(held).toHaveClass(/held/)
  await expect(held.locator('.plan-number')).toHaveText(String(number - 1))

  // два нажатия по плавающей стрелке двигают ту же строку
  await floating.getByTitle('Выше').click()
  await expect(held.locator('.plan-number')).toHaveText(String(number - 2))
  await floating.getByTitle('Выше').click()
  await expect(held.locator('.plan-number')).toHaveText(String(number - 3))

  // Escape отпускает
  await page.keyboard.press('Escape')
  await expect(floating).toHaveCount(0)
  await expect(held).not.toHaveClass(/held/)
})

test('формула в названии урока рисуется формулой', async ({ page, signIn }) => {
  // План читают глазами, и `$\sin(a+b)$` в сорока строках подряд читается
  // хуже, чем сама формула. KaTeX при этом приезжает отдельным куском и
  // только когда доллары в строке есть.
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const row = page.locator('.plan-row.lesson').first()
  const title = row.locator('.title')

  // пока формул нет, KaTeX на странице тоже нет
  await expect(page.locator('.katex')).toHaveCount(0)

  await title.click()
  const panel = page.locator('dialog.modal')
  const field = panel.getByLabel('Название')
  await field.fill('Формула $\\sin(a+b)$')
  await panel.getByRole('button', { name: 'Сохранить' }).click()
  await panel.locator('.modal-close').click()

  // формула отрисована, а в подсказке остался исходный текст
  await expect(row.locator('.katex')).toHaveCount(1)
  await expect(title).toContainText('Формула')
  await expect(title).toHaveAttribute('title', 'Формула $\\sin(a+b)$')
})

import { PEOPLE, expect, ready, test } from './harness.js'

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
  await page.getByRole('button', { name: course, exact: true }).click()
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
    Number(await page.locator(`[data-card="${card}"] h2`).textContent())

  const slots = await number('slots')
  const lessons = await number('lessons')
  const balance = await number('balance')

  // плашки сходятся между собой и с таблицей
  expect(slots - lessons).toBe(balance)
  await expect(page.locator('.plan-row.lesson .plan-date')).toHaveCount(lessons)
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
  await lessons.first().getByTitle('Вставить урок после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Вставка')
  await form.getByRole('button', { name: 'Добавить' }).click()

  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toBeVisible()
  await expect.poll(() => dateOfLesson(page, second)).toBe(thirdSlot)
  // а сама вставка встала на освободившуюся дату
  expect(await dateOfLesson(page, 'Вставка')).toBe(dateOfSecond)

  // и обратно: удалили — даты вернулись
  page.once('dialog', (dialog) => dialog.accept())
  const inserted = page.locator('.plan-row', { hasText: 'Вставка' })
  await inserted.hover()
  await inserted.getByTitle('Удалить').click()

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
  await first.getByTitle('Вставить урок после').click()
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

  // баланс отрицательный, и счётчик непоместившихся стоит отдельной
  // плашкой: это единственное число ряда, которого в таблице одним
  // взглядом не видно
  await expect(page.locator('[data-card="balance"].bad')).toBeVisible()
  await expect(page.locator('[data-card="missing"]')).toBeVisible()

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

  await page.getByLabel('Даты').uncheck()
  await expect(page.locator('.plan-date')).toHaveCount(0)

  // и переживает перезагрузку
  await page.reload()
  await ready(page)
  await expect(page.getByLabel('Даты')).not.toBeChecked()
  await expect(page.locator('.plan-date')).toHaveCount(0)
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
  await first.getByTitle('Вставить урок после').click()
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

  await page.getByLabel('Недели').uncheck()
  await expect(page.locator('.plan-row.week-even')).toHaveCount(0)
  await expect(page.locator('.plan-weekmark', { hasText: 'нед' })).toHaveCount(0)
  // даты на месте: пустая ячейка у главы не в счёт, смотрим на урок
  await expect(page.locator('.plan-row.lesson .plan-date').first()).toBeVisible()

  await page.getByLabel('Недели').check()
  await page.getByLabel('Даты').uncheck()
  // без дат номер недели не значит ничего — колонка уходит вместе с ними
  await expect(page.locator('.plan-weekmark')).toHaveCount(0)
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

  await page.getByLabel('Даты').uncheck()
  const after = await columns()

  // левая зона ушла, правая встала к краю, вертикали внутри целы
  expect(after.sections).toEqual(after.lessons)
  expect(after.nested).toHaveLength(1)
  expect(after.nested[0] - after.sectionTitles[0]).toBe(20)
  expect(after.lessons[0]).toBeLessThan(before.lessons[0])
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
  await page.getByRole('button', { name: 'Grade 9 Geometry', exact: true }).click()
  await expect(page.locator('.plan-cards')).toBeVisible()

  const add = async (button, title) => {
    await page.getByRole('button', { name: button }).click()
    const form = page.locator('.plan-add-form')
    await form.getByLabel('Название').fill(title)
    await form.getByRole('button', { name: 'Добавить' }).click()
    await expect(page.locator('.plan-row', { hasText: title })).toBeVisible()
  }

  await add('+ тема', 'Треугольники')
  const head = page.locator('.plan-section .section-head').first()
  await head.hover()
  await head.getByTitle('Добавить урок в тему').click()
  const inner = page.locator('.plan-add-form')
  await inner.getByLabel('Название').fill('Первый признак')
  await inner.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Первый признак' })).toBeVisible()

  await add('+ урок', 'Сам по себе')

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

test('без дат свободные слоты не показываются', async ({ page, signIn }) => {
  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  await page.getByLabel('Даты').uncheck()

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
  await expect(page.locator('[data-card="missing"]')).toBeVisible()
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
  const teacher = await api(PEOPLE.ivanova)
  const courses = await teacher.get('/api/courses/')
  const course = courses.body.find((item) => item.name === COURSE)

  const ribbon = await teacher.get(`/api/plan/layout/slots/?course=${course.id}`)
  const tree = await teacher.get(`/api/plan/?course=${course.id}`)
  const rows = tree.body.nodes.flatMap((node) =>
    node.is_section ? node.children : [node],
  )
  // третий урок плана записываем за третьим часом — как оно и лежит сейчас
  const anchored = rows[2]
  const third = ribbon.body.slots[2]
  await teacher.patch(`/api/slots/${third.id}/`, { lesson: anchored.id })

  await signIn(PEOPLE.ivanova)
  await openPlan(page)

  const before = await dateOfLesson(page, anchored.title)
  const row = page.locator('.plan-row.lesson', { hasText: anchored.title }).first()

  // ручка на месте, но не тянется, и кнопок перестановки у строки нет
  await expect(row.locator('.handle.locked')).toBeVisible()
  await expect(row.locator('button[title="Вверх"]')).toHaveCount(0)

  // вставляем урок выше него — всё, что ниже, обычно уезжает на день
  const first = page.locator('.plan-row.lesson').first()
  const drifting = rows[3].title
  const driftingBefore = await dateOfLesson(page, drifting)

  await first.hover()
  await first.getByTitle('Вставить урок после').click()
  const form = page.locator('.plan-add-form')
  await form.getByLabel('Название').fill('Вставка')
  await form.getByRole('button', { name: 'Добавить' }).click()
  await expect(page.locator('.plan-row', { hasText: 'Вставка' })).toBeVisible()

  // несвязанный уехал — значит правка дошла и лента пересчиталась
  await expect.poll(() => dateOfLesson(page, drifting)).not.toBe(driftingBefore)
  // а записанный стоит там же: за ним записан час
  expect(await dateOfLesson(page, anchored.title)).toBe(before)
})

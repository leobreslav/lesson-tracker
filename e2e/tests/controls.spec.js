import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Сторож строки формы.
 *
 * Раскладку полей и кнопок в этом приложении ломали трижды подряд, и каждый
 * раз одинаково: правка чинила один ряд и портила соседний, потому что
 * проверяли глазами то место, которое чинили. Здесь проверяются все ряды
 * сразу и тремя измерениями, которыми расходились прошлые поломки:
 *
 * 1. высота — все контролы ряда одного роста (поле 128px внутри подписи);
 * 2. перенос — подпись кнопки не уходит на вторую строку (кнопка выше поля);
 * 3. ширина — ряд не вылезает за свою карточку (расплата за nowrap).
 *
 * Обе локали: английские подписи длиннее русских, и там, где по-русски
 * влезало, по-английски переносится.
 */

// Список нарочно широкий: этот обход — самый дешёвый способ пройти по всем
// экранам, а слушатель консоли ловит на них `ReferenceError` и прочее, что
// сборка не видит. Появился раздел — допишите его сюда, иначе он останется
// единственным местом, куда браузер ни разу не заглядывал.
const PAGES = [
  ['/', PEOPLE.ivanova],
  ['/schedule', PEOPLE.ivanova],
  ['/plan', PEOPLE.ivanova],
  ['/works', PEOPLE.ivanova],
  // журнал: чипы четвертей — такой же ряд контролов, как остальные
  ['/journal', PEOPLE.ivanova],
  // переписка: строка отправки — такой же ряд контролов
  ['/talks', PEOPLE.ivanova],
  ['/bank', PEOPLE.ivanova],
  ['/bank/search', PEOPLE.ivanova],
  ['/bank/topics', PEOPLE.ivanova],
  ['/bank/chronology', PEOPLE.ivanova],
  ['/bank/proposals', PEOPLE.ivanova],
  ['/year', PEOPLE.admin],
  ['/school', PEOPLE.admin],
  ['/school/teachers', PEOPLE.admin],
  ['/school/courses', PEOPLE.admin],
  ['/school/students', PEOPLE.admin],
  ['/school/reference', PEOPLE.admin],
  // страница расписания одна на два вида; старый адрес приводит сюда же
  ['/schedule?view=school', PEOPLE.admin],
  // и два размаха: неделя всех курсов и день, где курсы развёрнуты по
  // столбцам. Размах живёт в адресе как раз затем, чтобы на него можно было
  // указать — в том числе отсюда
  ['/schedule?view=school&span=day', PEOPLE.admin],
  // разделы суперпользователя: изнутри школы они недостижимы, и до тех
  // пор, пока в наборе не было суперпользователя, сюда не заглядывал никто
  ['/schools', PEOPLE.developer],
  ['/feedback', PEOPLE.developer],
]

/** Строки контролов страницы: что в них не так. */
const problems = (page) =>
  page.evaluate(() => {
    const ROWS =
      '.add-form, .inline-form, .agenda-bar, .class-filter, .year-picker,' +
      '.term-form .row, .people-list .row, .course-role .row, .preset-row,' +
      '.plan-add-form,' +
      // правый угол бара — такой же ряд контролов, как форма: «Написать» и
      // кнопка с именем стоят рядом, и рост у них общий. Порознь они его
      // считали, и различались на несколько пикселей — непостоянно, потому
      // что у имени, совпавшего с адресом, строка одна вместо двух
      '.topbar-right,' +
      '.actions, .modal-body .row'
    const CONTROLS =
      'input:not([type=checkbox]):not([type=radio]):not([type=file]),' +
      'select, button:not(.link)'
    const found = []

    document.querySelectorAll(ROWS).forEach((row) => {
      if (!row.offsetParent) return
      const name = row.className || row.tagName

      if (row.scrollWidth > row.clientWidth + 1)
        found.push(`${name}: ряд шире карточки, ${row.scrollWidth} > ${row.clientWidth}`)

      const controls = [...row.querySelectorAll(CONTROLS)].filter((el) => el.offsetParent)
      controls.forEach((el) => {
        const style = getComputedStyle(el)
        const line = parseFloat(style.lineHeight) || 21
        const inner =
          el.getBoundingClientRect().height -
          parseFloat(style.paddingTop) -
          parseFloat(style.paddingBottom) -
          parseFloat(style.borderTopWidth) * 2
        if (inner > line * 1.6)
          found.push(
            `${name}: подпись перенеслась — «${(el.textContent || el.value || '').trim().slice(0, 24)}»`,
          )
      })

      const heights = new Set(
        controls.map((el) => Math.round(el.getBoundingClientRect().height)),
      )
      if (heights.size > 1)
        found.push(
          `${name}: разная высота — ` +
            controls
              .map(
                (el) =>
                  `${el.tagName.toLowerCase()} ${Math.round(
                    el.getBoundingClientRect().height,
                  )}px`,
              )
              .join(', '),
        )
    })

    return found
  })

for (const language of ['ru', 'en']) {
  test(`контролы в ряду одного роста: ${language}`, async ({ page, signIn, api }) => {
    await page.setViewportSize({ width: 1024, height: 900 })

    for (const who of [PEOPLE.ivanova, PEOPLE.admin]) {
      await (await api(who)).patch('/api/me/', { language })
    }

    /*
     * Страница правки работы адресуется по id, и статическим списком её не
     * назвать — поэтому она добывается запросом и дописывается к обходу.
     * Заглянуть туда надо тем более: рядов формы там больше, чем на любом
     * другом экране, и живут они теперь на странице, а не в окне.
     */
    const mine = await (await api(PEOPLE.ivanova)).get('/api/works/')
    const work = mine.body?.[0]
    const pages = work ? [...PAGES, [`/works/${work.id}/edit`, PEOPLE.ivanova]] : PAGES

    const found = []
    for (const [path, who] of pages) {
      await signIn(who)
      await page.goto(path)
      await ready(page)
      await page.waitForTimeout(200)
      ;(await problems(page)).forEach((problem) => found.push(`${path} — ${problem}`))
    }

    expect(found, found.join('\n')).toEqual([])
  })
}

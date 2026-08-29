import { PEOPLE, expect, ready, test } from './harness.js'

/**
 * Сторож строки формы.
 *
 * Раскладку полей и кнопок в этом приложении ломали трижды подряд, и каждый
 * раз одинаково: правка чинила один ряд и портила соседний, потому что
 * проверяли глазами то место, которое чинили. Здесь проверяются все ряды
 * сразу и четырьмя измерениями, которыми расходились прошлые поломки:
 *
 * 1. высота — все контролы ряда одного роста (поле 128px внутри подписи);
 * 2. перенос — подпись кнопки не уходит на вторую строку (кнопка выше поля);
 * 3. ширина — ряд не вылезает за свою карточку (расплата за nowrap);
 * 4. линия — соседи по строке стоят низом на одной высоте.
 *
 * Четвёртое появилось последним и стоит объяснения: контрол правильного
 * роста умеет сползти целиком, и первые три мерки этого не видят вовсе.
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
  // личный стол: форма заведения, форма папки и ряд поиска с кнопками
  // папки — три ряда контролов, и все три свои
  ['/bookmarks', PEOPLE.ivanova],
  // тот же экран у администратора — с **четвёртым** рядом: у него сверху
  // общая полка школы со своей формой заведения, и учителю её не видно
  ['/bookmarks', PEOPLE.admin],
  ['/bank', PEOPLE.ivanova],
  ['/bank/search', PEOPLE.ivanova],
  ['/bank/topics', PEOPLE.ivanova],
  ['/bank/chronology', PEOPLE.ivanova],
  ['/bank/proposals', PEOPLE.ivanova],
  // год смотрят двое, и видят разное: у администратора ряд правки, у
  // учителя — только чтение, и ряды там свои
  ['/year', PEOPLE.admin],
  ['/year', PEOPLE.ivanova],
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
      // `.row` — сам по себе, а не пятью путями до него. Пути тут и стояли
      // (`.term-form .row`, `.people-list .row` и ещё три), и это значило,
      // что ряд, не попавший в список, не проверялся вовсе: сдвиг кнопок в
      // «Системах оценивания» и «Видах работ» сторож пропустил именно так —
      // `.row` там лежит прямо в `.panel`. В стилях этот же список ровно по
      // этой причине уже свёрнут к одному классу; здесь он жил своей жизнью
      // и разошёлся с ним молча.
      '.row,' +
      '.add-form, .inline-form, .agenda-bar, .class-filter, .year-picker,' +
      '.preset-row, .plan-add-form,' +
      // правый угол бара — такой же ряд контролов, как форма: «Написать» и
      // кнопка с именем стоят рядом, и рост у них общий. Порознь они его
      // считали, и различались на несколько пикселей — непостоянно, потому
      // что у имени, совпавшего с адресом, строка одна вместо двух
      '.topbar-right,' +
      '.actions'
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

      /*
       * Четвёртое измерение: соседи по строке стоят на одной линии.
       *
       * Одного роста мало — контрол нужного роста умеет сползти целиком.
       * Так и вышло: `.field` носит нижний отступ строки формы, а во флексе
       * равняются внешние боксы, и поле встало на 1.25rem выше соседней
       * кнопки. Высоты при этом совпадали, и сторож молчал.
       *
       * Соседи по строке — те, чьи коробки пересекаются по вертикали хоть
       * на пиксель: стоять бок о бок и не пересекаться нельзя. Ряд,
       * перенёсшийся на вторую строку, так не поймается — там между
       * строками зазор, и пересечения нет вовсе; это не поломка, и ловить
       * её тут нечего.
       */
      const byTop = [...controls].sort(
        (a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top,
      )
      let line = []
      let lineBottom = -Infinity
      const closeLine = () => {
        const bottoms = new Set(
          line.map((el) => Math.round(el.getBoundingClientRect().bottom)),
        )
        if (bottoms.size > 1)
          found.push(
            `${name}: съехало по вертикали — ` +
              line
                .map(
                  (el) =>
                    `${el.tagName.toLowerCase()} низ ${Math.round(
                      el.getBoundingClientRect().bottom,
                    )}`,
                )
                .join(', '),
          )
      }
      byTop.forEach((el) => {
        const box = el.getBoundingClientRect()
        if (line.length && box.top >= lineBottom) {
          closeLine()
          line = []
          lineBottom = -Infinity
        }
        line.push(el)
        lineBottom = Math.max(lineBottom, box.bottom)
      })
      if (line.length) closeLine()
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
    const client = await api(PEOPLE.ivanova)
    const mine = await client.get('/api/works/')
    const work = mine.body?.[0]
    const pages = work ? [...PAGES, [`/works/${work.id}/edit`, PEOPLE.ivanova]] : PAGES

    /*
     * План на полке адресуется так же — по id, — и заглянуть туда надо по
     * той же причине: экран тот же, что у плана курса, но ряд контролов над
     * таблицей там **короче** (нет ни дат, ни утверждения, ни меню обмена), и
     * именно укороченные ряды разъезжаются первыми.
     */
    const shelf = await client.get('/api/library/templates/?mine=true')
    const template = shelf.body?.[0]
    if (template) pages.push([`/library/${template.id}`, PEOPLE.ivanova])

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

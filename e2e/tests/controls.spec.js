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

const PAGES = [
  ['/', PEOPLE.ivanova],
  ['/schedule', PEOPLE.ivanova],
  ['/plan', PEOPLE.ivanova],
  ['/library', PEOPLE.ivanova],
  ['/classes', PEOPLE.ivanova],
  ['/year', PEOPLE.admin],
  ['/school', PEOPLE.admin],
  ['/school/teachers', PEOPLE.admin],
  ['/school/courses', PEOPLE.admin],
  ['/school/reference', PEOPLE.admin],
  ['/school/schedule', PEOPLE.admin],
]

/** Строки контролов страницы: что в них не так. */
const problems = (page) =>
  page.evaluate(() => {
    const ROWS =
      '.add-form, .inline-form, .agenda-bar, .class-filter, .year-picker,' +
      '.term-form .row, .people-list .row, .course-role .row, .preset-row,' +
      '.plan-add-form,' +
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

    const found = []
    for (const [path, who] of PAGES) {
      await signIn(who)
      await page.goto(path)
      await ready(page)
      await page.waitForTimeout(200)
      ;(await problems(page)).forEach((problem) => found.push(`${path} — ${problem}`))
    }

    expect(found, found.join('\n')).toEqual([])
  })
}

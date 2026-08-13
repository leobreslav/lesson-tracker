/**
 * Сшивка плана с лентой слотов.
 *
 * Смысл всей затеи в том, что даты пересчитываются немедленно: добавили урок
 * в середину — всё, что ниже, съехало, и черта конца четверти уехала вверх.
 * Здесь это и проверяется — на чистых данных, без страницы.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { layoutTotals, stitchLayout } from '../src/planLayout.js'
import { planRows } from '../src/planLogic.js'

/** Лента: по слоту в день, с 1 октября. */
const ribbon = (count, options = {}) =>
  Array.from({ length: count }, (_, index) => ({
    id: 100 + index,
    date: `2026-10-${String(index + 1).padStart(2, '0')}`,
    lesson_number: 1,
    is_extra: false,
    term_id: 1,
    term_name: '1 четверть',
    term:
      index >= (options.secondTermFrom ?? Infinity)
        ? { id: 2, name: '2 четверть', start: '2026-11-05', end: '2026-12-28' }
        : { id: 1, name: '1 четверть', start: '2026-09-01', end: '2026-10-26' },
    break_before:
      index === options.breakAt
        ? { title: 'осенние каникулы', start: '2026-10-27', end: '2026-11-03' }
        : null,
  }))

const lesson = (id, sectionId = null) => ({
  is_section: false,
  id,
  section_id: sectionId,
  section_title: sectionId ? 'Тема' : null,
})
const section = (id) => ({ is_section: true, id, title: 'Тема' })

const dates = (rows) =>
  stitchLayout(rows, ribbon(rows.filter((row) => !row.is_section).length + 5)).map(
    (row) => (row.is_section ? 'тема' : (row.slot?.date ?? null)),
  )

describe('stitchLayout', () => {
  it('уроки ложатся на слоты по порядку', () => {
    assert.deepEqual(dates([lesson(1), lesson(2), lesson(3)]), [
      '2026-10-01',
      '2026-10-02',
      '2026-10-03',
    ])
  })

  it('вставленный в середину урок сдвигает даты ниже', () => {
    const dateOf = (rows, id) =>
      stitchLayout(rows, ribbon(8)).find((row) => row.id === id)?.slot?.date

    const before = [lesson(1), lesson(2), lesson(3)]
    const after = [lesson(1), lesson(9), lesson(2), lesson(3)]

    // урок выше вставки стоит там же, уроки ниже уехали на день вперёд
    assert.equal(dateOf(after, 1), dateOf(before, 1))
    assert.equal(dateOf(before, 2), '2026-10-02')
    assert.equal(dateOf(after, 2), '2026-10-03')
    assert.equal(dateOf(after, 3), '2026-10-04')
  })

  it('удаление сдвигает даты обратно', () => {
    const full = dates([lesson(1), lesson(2), lesson(3)])
    const short = dates([lesson(1), lesson(3)])

    assert.deepEqual(short, [full[0], full[1]])
  })

  it('темы дат не занимают', () => {
    assert.deepEqual(dates([section(10), lesson(1, 10), lesson(2, 10)]), [
      'тема',
      '2026-10-01',
      '2026-10-02',
    ])
  })

  it('уроку без слота дата не достаётся', () => {
    const rows = stitchLayout([lesson(1), lesson(2), lesson(3)], ribbon(2))

    assert.equal(rows[1].slot.date, '2026-10-02')
    assert.equal(rows[2].slot, null)
  })
})

describe('границы термов и каникулы', () => {
  const marksOf = (row, kind) => (row.before ?? []).filter((m) => m.kind === kind)

  it('заголовок терма стоит перед первым его уроком', () => {
    const rows = stitchLayout(
      [lesson(1), lesson(2), lesson(3)],
      ribbon(5, { secondTermFrom: 2 }),
    )

    assert.deepEqual(marksOf(rows[0], 'term'), [
      { kind: 'term', id: 1, name: '1 четверть', start: '2026-09-01', end: '2026-10-26' },
    ])
    assert.deepEqual(marksOf(rows[1], 'term'), [])
    assert.equal(marksOf(rows[2], 'term')[0].name, '2 четверть')
  })

  it('граница терма переезжает на другой урок, когда выше добавили ещё один', () => {
    // сама черта привязана к слоту; двигаются уроки под ней, и в этом весь
    // смысл: видно, что тема перестала помещаться в четверть
    const firstOfSecond = (rows) =>
      stitchLayout(rows, ribbon(6, { secondTermFrom: 3 })).find(
        (row) => marksOf(row, 'term')[0]?.id === 2,
      )?.id

    assert.equal(firstOfSecond([lesson(1), lesson(2), lesson(3), lesson(4)]), 4)
    assert.equal(
      firstOfSecond([lesson(9), lesson(1), lesson(2), lesson(3), lesson(4)]),
      3,
    )
  })

  it('каникулы отмечаются перед уроком, который стоит уже после них', () => {
    const rows = stitchLayout([lesson(1), lesson(2)], ribbon(4, { breakAt: 1 }))

    assert.deepEqual(marksOf(rows[1], 'break'), [
      {
        kind: 'break',
        title: 'осенние каникулы',
        start: '2026-10-27',
        end: '2026-11-03',
      },
    ])
    assert.deepEqual(marksOf(rows[0], 'break'), [])
  })

  it('черта «сегодня» — перед первым непрошедшим уроком, прошлое приглушено', () => {
    const rows = stitchLayout(
      [lesson(1), lesson(2), lesson(3)],
      ribbon(5),
      '2026-10-02',
    )

    assert.deepEqual(
      rows.map((row) => row.past),
      [true, false, false],
    )
    assert.deepEqual(marksOf(rows[1], 'today'), [{ kind: 'today' }])
    assert.equal(rows.filter((row) => marksOf(row, 'today').length).length, 1)
  })

  it('без сегодняшней даты черты нет вовсе', () => {
    const rows = stitchLayout([lesson(1), lesson(2)], ribbon(3))

    assert.equal(rows.filter((row) => marksOf(row, 'today').length).length, 0)
    assert.deepEqual(
      rows.map((row) => row.past),
      [false, false],
    )
  })
})

describe('диапазон дат темы', () => {
  const range = (rows, slots) =>
    stitchLayout(rows, ribbon(slots)).find((row) => row.is_section).range

  it('от первого урока темы до последнего', () => {
    assert.deepEqual(range([section(10), lesson(1, 10), lesson(2, 10)], 5), {
      from: '2026-10-01',
      to: '2026-10-02',
      missing: 0,
    })
  })

  it('уроки вне темы в её диапазон не входят', () => {
    const rows = [section(10), lesson(1, 10), lesson(2), lesson(3)]

    assert.deepEqual(range(rows, 5), {
      from: '2026-10-01',
      to: '2026-10-01',
      missing: 0,
    })
  })

  it('непоместившиеся уроки темы посчитаны отдельно', () => {
    const rows = [section(10), lesson(1, 10), lesson(2, 10), lesson(3, 10)]

    assert.deepEqual(range(rows, 2), {
      from: '2026-10-01',
      to: '2026-10-02',
      missing: 1,
    })
  })

  it('тема, не поместившаяся целиком, дат не имеет', () => {
    const rows = [lesson(1), section(10), lesson(2, 10)]

    assert.deepEqual(range(rows, 1), { from: null, to: null, missing: 1 })
  })

  it('пустая тема остаётся без диапазона', () => {
    assert.equal(range([section(10), lesson(1)], 3), null)
  })
})

describe('layoutTotals', () => {
  it('баланс и последний урок', () => {
    const rows = [section(10), lesson(1, 10), lesson(2, 10)]

    assert.deepEqual(layoutTotals(rows, ribbon(5)), {
      slots: 5,
      lessons: 2,
      balance: 3,
      lastDate: '2026-10-02',
      missing: 0,
    })
  })

  it('дефицит: последнего урока нет, потому что план не помещается', () => {
    const rows = [lesson(1), lesson(2), lesson(3)]

    assert.deepEqual(layoutTotals(rows, ribbon(2)), {
      slots: 2,
      lessons: 3,
      balance: -1,
      lastDate: null,
      missing: 1,
    })
  })

  it('сводка сходится со сшивкой', () => {
    const rows = [section(10), lesson(1, 10), lesson(2, 10), lesson(3)]
    const stitched = stitchLayout(rows, ribbon(2))
    const totals = layoutTotals(rows, ribbon(2))

    assert.equal(
      stitched.filter((row) => !row.is_section && row.slot).length,
      totals.slots,
    )
    assert.equal(
      stitched.filter((row) => !row.is_section && !row.slot).length,
      totals.missing,
    )
  })
})

describe('planRows несёт id — иначе сшивать не с чем', () => {
  it('у урока внутри темы и у урока верхнего уровня есть id', () => {
    const rows = planRows([
      { id: 1, is_section: true, title: 'Тема', children: [{ id: 2, title: 'Урок' }] },
      { id: 3, is_section: false, title: 'Вне темы' },
    ])

    assert.deepEqual(
      rows.map((row) => row.id),
      [1, 2, 3],
    )
  })
})

describe('скобка недели', () => {
  /** Лента с настоящими неделями: по уроку в понедельник, среду и пятницу. */
  const weeks = (count) =>
    Array.from({ length: count }, (_, index) => {
      const week = Math.floor(index / 3) + 1
      const day = 7 + (week - 1) * 7 + [0, 2, 4][index % 3]
      const iso = `2026-09-${String(day).padStart(2, '0')}`
      return {
        id: 100 + index,
        date: iso,
        lesson_number: 1,
        is_extra: false,
        week,
        week_start: `2026-09-${String(7 + (week - 1) * 7).padStart(2, '0')}`,
        term: null,
        break_before: null,
      }
    })

  const brackets = (rows, ribbon) =>
    stitchLayout(rows, ribbon).map((row) =>
      row.week
        ? [row.week.number, row.week.first, row.week.label, row.week.last]
        : null,
    )

  it('строка знает свою неделю, края группы и где подпись', () => {
    const rows = [lesson(1), lesson(2), lesson(3), lesson(4), lesson(5)]

    assert.deepEqual(brackets(rows, weeks(6)), [
      [1, true, false, false],
      [1, false, true, false], // подпись — на средней строке группы
      [1, false, false, true],
      [2, true, true, false],
      [2, false, false, true],
    ])
  })

  it('неделя строкой не является: черт перед строками не прибавилось', () => {
    const rows = stitchLayout([lesson(1), lesson(2)], weeks(3))

    assert.deepEqual(
      rows.flatMap((row) => row.before.map((mark) => mark.kind)),
      [],
    )
  })

  it('заголовок темы попадает в неделю своих уроков и скобку не рвёт', () => {
    const rows = [lesson(1), section(10), lesson(2, 10), lesson(3, 10)]

    assert.deepEqual(
      brackets(rows, weeks(3)).map((week) => week[0]),
      [1, 1, 1, 1],
    )
    // тема стоит внутри группы, а не открывает свою
    assert.equal(brackets(rows, weeks(3))[1][1], false)
  })

  it('тема на границе недель уходит к той, что под ней', () => {
    const rows = [lesson(1), lesson(2), lesson(3), section(10), lesson(4, 10)]

    assert.deepEqual(
      brackets(rows, weeks(6)).map((week) => week[0]),
      [1, 1, 1, 2, 2],
    )
  })

  it('неделя целиком на каникулах номера не занимает — счёт идёт подряд', () => {
    // второй недели в ленте нет вовсе, и сервер прислал 1 и 2, а не 1 и 3
    const ribbon = weeks(9)
      .filter((slot) => slot.week !== 2)
      .map((slot) => ({ ...slot, week: slot.week === 3 ? 2 : slot.week }))
    const rows = [lesson(1), lesson(2), lesson(3), lesson(4), lesson(5), lesson(6)]

    assert.deepEqual(
      brackets(rows, ribbon).map((week) => week[0]),
      [1, 1, 1, 2, 2, 2],
    )
  })

  it('уроку без слота скобка не достаётся', () => {
    const rows = [lesson(1), lesson(2), lesson(3), lesson(4)]

    assert.equal(brackets(rows, weeks(3)).at(-1), null)
  })
})

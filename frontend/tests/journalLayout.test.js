import assert from 'node:assert/strict'
import test from 'node:test'

const { columnWidths, markWidth } = await import('../src/journalLayout.js')

/*
 * Подколонки журнала. Проверяется здесь одна вещь и её следствия: ширину
 * колонки считает **один** расчёт, и результат его не зависит от того, каким
 * шрифтом набран элемент, которому он достался.
 */

test('ширина считается в rem, а не в ch — от шрифта элемента она зависеть не должна', () => {
  /*
   * Сторож самой дорогой поломки этого экрана. `ch` — ширина нуля в шрифте
   * **самого элемента**: у значка работы кегль 0.75rem, у отметки под ним
   * 0.9rem, и одна и та же строка давала им разную ширину. Односимвольные
   * отметки это скрывали (обе упирались в общий `min-width`), а первое же
   * «зачёт» разводило шапку с клеткой — и каждая следующая подколонка
   * съезжала сильнее предыдущей.
   */
  const width = markWidth(5)

  assert.match(width, /rem$/)
  assert.ok(!width.includes('ch'), `ширина не должна меряться в ch: ${width}`)
})

test('чем длиннее отметка, тем шире колонка', () => {
  const short = Number.parseFloat(markWidth(1))
  const word = Number.parseFloat(markWidth(6))

  assert.ok(word > short, `«зачёт» должно быть шире «5»: ${word} против ${short}`)
})

test('пустая колонка всё равно занимает место — на нём держится столбец', () => {
  assert.ok(Number.parseFloat(markWidth(0)) > 0)
})

test('мерится самая широкая отметка колонки, а не первая попавшаяся', () => {
  const columns = [{ works: [{ id: 1 }, { id: 2 }] }]
  const students = [
    { cells: [{ marks: [{ work: 1, label: '5' }, { work: 2, label: 'зачёт' }] }] },
    { cells: [{ marks: [{ work: 1, label: '4' }] }] },
  ]

  const [first, second] = columnWidths(columns, students)[0]

  assert.equal(first, markWidth(1))
  assert.equal(second, markWidth(5))
})

test('колонка без единой отметки берёт наименьшую ширину, а не падает', () => {
  const columns = [{ works: [{ id: 7 }] }]
  const students = [{ cells: [{ marks: [] }] }]

  assert.deepEqual(columnWidths(columns, students), [[markWidth(1)]])
})

test('ученик без клетки на этот столбец расчёт не роняет', () => {
  // строка семьи короче учительской: у неё свой набор клеток, и журнал
  // рисуется тем же кодом
  const columns = [{ works: [{ id: 3 }] }, { works: [{ id: 4 }] }]
  const students = [{ cells: [{ marks: [{ work: 3, label: 'B' }] }] }]

  assert.deepEqual(columnWidths(columns, students), [[markWidth(1)], [markWidth(1)]])
})

/*
 * Правка в клетке. Проверяется то, из-за чего журнал перестал бы быть
 * журналом: куда уходит курсор и что кладётся обратно в таблицу после записи.
 */

const { ATTENDANCE, applyAttendance, applyGrade, nextPlace } = await import(
  '../src/journalLayout.js'
)

const grid = {
  students: [{ id: 1 }, { id: 2 }, { id: 3 }],
  columns: [
    { slot: 10, works: [{ id: 100 }, { id: 101 }] },
    { slot: 11, works: [] },
    { slot: null, works: [{ id: 102 }] },
  ],
}

test('Enter ведёт вниз: журнал заполняют по работе, весь класс подряд', () => {
  const now = nextPlace({ student: 1, column: 0, order: 0 }, 'down', grid)

  assert.deepEqual(now, { student: 2, column: 0, order: 0 })
})

test('внизу столбца курсор остаётся на месте, а не прыгает в следующий', () => {
  // перескок читается как промах мимо клетки, а не как помощь
  const now = nextPlace({ student: 3, column: 0, order: 0 }, 'down', grid)

  assert.deepEqual(now, { student: 3, column: 0, order: 0 })
})

test('вправо идёт по работам дня, а последним — присутствие', () => {
  const second = nextPlace({ student: 1, column: 0, order: 0 }, 'right', grid)
  assert.deepEqual(second, { student: 1, column: 0, order: 1 })

  const att = nextPlace(second, 'right', grid)
  assert.deepEqual(att, { student: 1, column: 0, order: ATTENDANCE })
})

test('из присутствия вправо — в следующий день, а не мимо него', () => {
  const now = nextPlace(
    { student: 1, column: 0, order: ATTENDANCE },
    'right',
    grid,
  )

  // у второго дня работ нет вовсе, и первой его клеткой оказывается присутствие
  assert.deepEqual(now, { student: 1, column: 1, order: ATTENDANCE })
})

test('у столбца без занятия присутствия нет — курсор через него перешагивает', () => {
  const now = nextPlace({ student: 1, column: 2, order: 0 }, 'right', grid)

  // дальше правого края не уходим: столбец последний
  assert.deepEqual(now, { student: 1, column: 2, order: 0 })
})

const journal = {
  columns: [
    { slot: 10, works: [{ id: 100 }] },
    { slot: 11, works: [] },
  ],
  students: [
    {
      id: 1,
      cells: [
        { marks: [{ work: 100, label: '3', by_teacher: false }], attendance: null },
        { marks: [], attendance: 'present' },
      ],
    },
    { id: 2, cells: [{ marks: [], attendance: null }, { marks: [], attendance: null }] },
  ],
}

test('ответ сервера кладётся в клетку как есть, без пересчёта отметки', () => {
  const now = applyGrade(journal, 100, 1, {
    label: '5',
    by_teacher: true,
    earned: 9,
    top: 10,
  })

  assert.deepEqual(now.students[0].cells[0].marks, [
    { work: 100, label: '5', by_teacher: true, earned: 9, top: 10 },
  ])
  // соседей это не трогает
  assert.deepEqual(now.students[1].cells[0].marks, [])
})

test('снятая отметка исчезает из клетки, а не становится пустой строкой', () => {
  // пустая строка возвращает работу системе, и сервер отвечает `null`
  const now = applyGrade(journal, 100, 1, null)

  assert.deepEqual(now.students[0].cells[0].marks, [])
})

test('журнал не меняется, если снимать нечего', () => {
  const now = applyGrade(journal, 100, 2, null)

  assert.deepEqual(now.students[1].cells[0], journal.students[1].cells[0])
})

test('присутствие ищется по занятию, а не по номеру столбца', () => {
  const now = applyAttendance(journal, 11, 1, 'late')

  assert.equal(now.students[0].cells[1].attendance, 'late')
  assert.equal(now.students[0].cells[0].attendance, null)
})

test('снятое присутствие возвращает клетку в «не отмечено» вместе с причиной', () => {
  const marked = applyAttendance(
    { ...journal, students: [{ id: 1, cells: [{ marks: [], attendance: 'absent', note: 'по заявлению' }] }] },
    10,
    1,
    null,
  )

  assert.equal(marked.students[0].cells[0].attendance, null)
  assert.equal(marked.students[0].cells[0].note, '')
})

test('чужое занятие журнал не трогает вовсе', () => {
  assert.equal(applyAttendance(journal, 999, 1, 'present'), journal)
})

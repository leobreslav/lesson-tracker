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

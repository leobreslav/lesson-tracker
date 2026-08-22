import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { CORNERS, FIELD, GRID, PAGE } from '../src/blankGeometry.js'

/**
 * Числа бланка живут в двух файлах: `blank/blank_form.tex` рисует лист, а
 * `blankGeometry.js` по ним кропает. Разойтись они могут только молча —
 * напечатанный лист останется правильным, а кроп уедет мимо, и выглядеть это
 * будет как «модель стала хуже читать».
 *
 * Поэтому тест читает сам .tex. Путь тот же, что и с хоста (`../../blank`), —
 * каталог примонтирован в контейнер так же, как `mirrors`.
 */
const source = readFileSync(new URL('../../blank/blank_form.tex', import.meta.url), 'utf8')

test('лист — A4, и это записано в шаблоне', () => {
  assert.match(source, /a4paper/)
  assert.equal(PAGE.width, 210)
  assert.equal(PAGE.height, 297)
})

test('метки стоят на тех вертикалях, что знает код чтения', () => {
  // \fill[black] ([shift={( 6mm, -6mm)}]current page.north west) rectangle ++( 4mm,-4mm);
  const shifts = [...source.matchAll(/shift=\{\(\s*(-?[\d.]+)mm,\s*(-?[\d.]+)mm\)\}/g)]
  assert.ok(shifts.length >= 8, `сдвигов в шаблоне ${shifts.length}`)

  // левая колонка: отступ 6мм + половина метки 4мм = центр на 8мм
  const left = shifts.filter(([, x]) => Number(x) === 6)
  assert.ok(left.length >= 4, 'левых меток меньше четырёх')
  assert.equal(CORNERS.topLeft.x, 8)
  assert.equal(CORNERS.topRight.x, PAGE.width - 8)
})

test('метки шапки стоят на 8, 27 и 39 миллиметрах', () => {
  const tops = [...source.matchAll(/north west\) rectangle/g)]
  assert.ok(tops.length >= 3, 'верхних меток меньше трёх')

  for (const offset of [6, 25, 37]) {
    assert.ok(
      source.includes(`( 6mm,-${offset}mm)`) || source.includes(`( 6mm, -${offset}mm)`),
      `метки на ${offset}мм в шаблоне нет`,
    )
  }
})

test('сетка баллов: шестнадцать клеток той же ширины', () => {
  const width = source.match(/\\def\\w\{([\d.]+)\}/)
  assert.ok(width, 'ширины клетки в шаблоне нет')
  assert.equal(Number(width[1]), GRID.cellWidth)
  assert.equal(GRID.cells, 16)
  assert.match(source, /\\foreach \\q in \{1,\.\.\.,15\}/)
})

test('поле записи начинается там же, где думает код', () => {
  assert.ok(
    source.includes(`(${FIELD.x}mm,-${FIELD.y}mm)`),
    'начало тетрадного поля в шаблоне другое',
  )
  assert.ok(
    source.includes(`(${FIELD.width}mm,-${FIELD.height}mm)`),
    'размер тетрадного поля в шаблоне другой',
  )
})

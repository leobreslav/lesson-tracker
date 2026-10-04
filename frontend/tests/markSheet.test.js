import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { MARKS_ENOUGH, extractMarks, findCode } from '../src/scanSheet.js'
import {
  CORNERS,
  GRID,
  MARKS,
  PAGE,
  QR,
  isMarkSheetCode,
  markCellLabel,
  markCellRect,
  markGrid,
} from '../src/blankGeometry.js'

/**
 * Лист баллов (маркгрид): `blank/mark_sheet.tex` рисует, `MARKS` кропает, а
 * сервер надпечатывает подписи по своим миллиметрам. Три записи одних и тех
 * же чисел, и разойтись они могут только молча — напечатанный лист останется
 * правильным, а кроп или подпись уедут на соседнюю клетку.
 */
const read = (path) => readFileSync(fileURLToPath(new URL(path, import.meta.url)))
const tex = read('../../blank/mark_sheet.tex').toString('utf8')

test('линейки стоят там, где их режет чтение', () => {
  assert.equal(Number(/\\def\\rowy\{([\d.]+)\}/.exec(tex)[1]), MARKS.rowY)
  assert.equal(Number(/\\def\\rowp\{([\d.]+)\}/.exec(tex)[1]), MARKS.rowPitch)
  assert.match(tex, new RegExp(`\\\\foreach \\\\r in \\{0,\\.\\.\\.,${MARKS.rows - 1}\\}`))
  // та же сетка, что в шапке бланка: ширина клетки и высота полосы подписи
  assert.match(tex, new RegExp(`\\\\def\\\\w\\{${GRID.cellWidth}\\}`))
  assert.match(tex, /rectangle \+\+\(\\w,11\.5\)/)
  assert.equal(GRID.labelHeight, 11.5)
  // девяносто пять задач и сумма — последней клеткой последней линейки
  assert.equal(MARKS.rows * GRID.cells, MARKS.questions + 1)
  assert.match(tex, new RegExp(`\\\\ifnum\\\\n=${MARKS.questions + 1} `))
})

test('строка имени и коды стоят там, где их ищет чтение', () => {
  assert.equal(Number(/\\def\\namey\{([\d.]+)\}/.exec(tex)[1]), MARKS.name.y)
  assert.equal(Number(/\\def\\nameh\{([\d.]+)\}/.exec(tex)[1]), MARKS.name.height)
  assert.match(tex, /\(12\.5,\\namey\) rectangle \+\+\(185,\\nameh\)/)
  assert.equal(MARKS.name.x, 12.5)
  assert.equal(MARKS.name.width, 185)
  for (const at of MARKS.codes) {
    assert.ok(tex.includes(`at (${at.x},${at.y}) {\\markqr{${QR.size}mm}}`), `кода в (${at.x}, ${at.y}) в шаблоне нет`)
  }
})

test('угловые метки те же, что у бланка: поиск четвёрки общий', () => {
  // \foreach \x in {6,200}{\foreach \y in {6,287}: левый верхний угол метки 4мм
  assert.match(tex, /\\foreach \\x in \{6,200\}\{\\foreach \\y in \{6,287\}/)
  assert.equal(CORNERS.topLeft.x, 8)
  assert.equal(CORNERS.bottomRight.y, PAGE.height - 8)
})

test('лист баллов не совпадает с бланком ни сеткой, ни кодами', () => {
  /*
   * Нынешнее чтение бланка признаёт лист своим по почти полной сетке на месте
   * шапки и по кодам внизу. Совпади лист баллов с бланком хоть в одном — его
   * прочли бы как бланк ответов, по чужой геометрии и молча.
   */
  assert.ok(MARKS.rowY > GRID.y + GRID.height, 'первая линейка залезла на место шапки бланка')
  for (const code of MARKS.codes) {
    for (const blank of QR.at) {
      assert.ok(Math.abs(code.y - blank.y) > 100, 'код листа баллов стоит на месте кода бланка')
    }
  }
})

test('подписи сервер ставит в те же клетки, что режет чтение', () => {
  const python = read('../../backend/works/blank/__init__.py').toString('utf8')
  const number = (name) => {
    const found = new RegExp(`^${name} = ([\\d.]+)$`, 'm').exec(python)
    assert.ok(found, `${name} не найден в backend/works/blank/__init__.py`)
    return Number(found[1])
  }

  assert.equal(number('MARK_ROW_Y'), MARKS.rowY)
  assert.equal(number('MARK_ROW_PITCH'), MARKS.rowPitch)
  assert.equal(number('MARK_ROWS'), MARKS.rows)
  assert.equal(number('MARK_QUESTIONS'), MARKS.questions)
  assert.equal(number('PER_ROW'), GRID.cells)
})

test('лист баллов на сайте и подложка подписей — тот же файл, что печатают', () => {
  const source = read('../../blank/mark_sheet.pdf')

  assert.deepEqual(
    read('../public/mark-sheet.pdf'),
    source,
    'blank/mark_sheet.pdf и frontend/public/mark-sheet.pdf разошлись: скопируйте заново',
  )
  assert.deepEqual(
    read('../../backend/works/blank/mark_sheet.pdf'),
    source,
    'blank/mark_sheet.pdf и backend/works/blank/mark_sheet.pdf разошлись: скопируйте заново',
  )
})

test('код, напечатанный на листе баллов, читается и называет роль M', () => {
  // та же сборка картинки из заливок, что у кода бланка (`blankCode.test.js`):
  // зеркальная или сдвинутая матрица глазами выглядит нормальным QR
  const qr = read('../../blank/qr_mark.tex').toString('utf8')
  const modules = Number(/x=#1\/(\d+)/.exec(qr)[1])
  const grid = Array.from({ length: modules }, () => new Uint8Array(modules))
  for (const [, x0, , x1, y1] of qr.matchAll(/\\fill \((\d+),(\d+)\) rectangle \((\d+),(\d+)\);/g)) {
    for (let x = Number(x0); x < Number(x1); x += 1) grid[modules - Number(y1)][x] = 1
  }

  const scale = 8
  const side = (modules + 8) * scale
  const data = new Uint8ClampedArray(side * side * 4).fill(255)
  for (let y = 0; y < side; y += 1) {
    for (let x = 0; x < side; x += 1) {
      const mx = Math.floor(x / scale) - 4
      const my = Math.floor(y / scale) - 4
      if (mx >= 0 && my >= 0 && mx < modules && my < modules && grid[my][mx]) {
        const p = (y * side + x) * 4
        data[p] = data[p + 1] = data[p + 2] = 0
      }
    }
  }

  const found = findCode({ data, width: side, height: side })
  assert.ok(found, 'напечатанный код листа баллов не прочитался')
  assert.ok(isMarkSheetCode(found.payload), `в коде ${found.payload}, а не роль M`)
  assert.equal(found.ours, true)
})

test('роль листа узнаётся по коду, а не по поколению', () => {
  assert.ok(isMarkSheetCode('LT/3/M'))
  assert.ok(isMarkSheetCode('LT/4/M'))
  assert.ok(!isMarkSheetCode('LT/3/A'))
  assert.ok(!isMarkSheetCode('XLT/3/M'))
  assert.ok(!isMarkSheetCode(null))
})

test('клетки нумеруются сквозь линейки, а сумма — последней', () => {
  assert.equal(markCellLabel(0), 'Q1')
  assert.equal(markCellLabel(16), 'Q17')
  assert.equal(markCellLabel(MARKS.questions), 'SUM')
  // семнадцатая клетка — первая во второй линейке, под той же колонкой, что первая
  assert.equal(markCellRect(16).x, markCellRect(0).x)
  assert.equal(markCellRect(16).y - markCellRect(0).y, MARKS.rowPitch)
  assert.equal(markGrid(MARKS.rows - 1).y, MARKS.rowY + (MARKS.rows - 1) * MARKS.rowPitch)
})

/** Лист баллов на тёмном столе: углы и шесть линеек, при `flip` — вверх ногами. */
function drawMarkSheet({ scale = 3, margin = 40, flip = false } = {}) {
  const width = Math.round(PAGE.width * scale) + margin * 2
  const height = Math.round(PAGE.height * scale) + margin * 2
  const data = new Uint8ClampedArray(width * height * 4)
  const put = (x, y, value) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return
    const p = (Math.round(y) * width + Math.round(x)) * 4
    data[p] = data[p + 1] = data[p + 2] = value
    data[p + 3] = 255
  }
  const at = (mmX, mmY) => ({
    x: margin + (flip ? PAGE.width - mmX : mmX) * scale,
    y: margin + (flip ? PAGE.height - mmY : mmY) * scale,
  })

  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) put(x, y, 60)
  for (let y = 0; y <= PAGE.height * scale; y += 1) {
    for (let x = 0; x <= PAGE.width * scale; x += 1) put(margin + x, margin + y, 235)
  }
  for (const corner of Object.values(CORNERS)) {
    for (let dy = -2; dy <= 2; dy += 1 / scale) {
      for (let dx = -2; dx <= 2; dx += 1 / scale) {
        const p = at(corner.x + dx, corner.y + dy)
        put(p.x, p.y, 20)
      }
    }
  }
  const line = (x0, y0, x1, y1) => {
    const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) * scale * 2
    for (let i = 0; i <= steps; i += 1) {
      const p = at(x0 + ((x1 - x0) * i) / steps, y0 + ((y1 - y0) * i) / steps)
      for (let w = 0; w < 2; w += 1) put(p.x + w, p.y, 30)
    }
  }
  for (let row = 0; row < MARKS.rows; row += 1) {
    const grid = markGrid(row)
    const right = grid.x + grid.cells * grid.cellWidth
    for (let cell = 0; cell <= grid.cells; cell += 1) {
      const x = grid.x + cell * grid.cellWidth
      line(x, grid.y, x, grid.y + grid.height)
    }
    for (const y of [grid.y, grid.y + grid.labelHeight, grid.y + grid.height]) line(grid.x, y, right, y)
  }
  return { data, width, height }
}

test('лист баллов выпрямляется по всем шести линейкам', () => {
  // кода в фикстуре нет: проверка по месту кода отключается вместе с ним, и
  // проверяется ровно то, что решает этот путь, — сетка каждой линейки
  const found = extractMarks(drawMarkSheet(), null)

  assert.ok(found, 'лист баллов не выпрямился')
  assert.equal(found.fixes.length, MARKS.rows)
  assert.ok(found.score >= MARKS_ENOUGH, `границ ${found.score}, нужно ${MARKS_ENOUGH}`)
})

test('перевёрнутый лист баллов выпрямляется тоже', () => {
  const found = extractMarks(drawMarkSheet({ flip: true }), null)

  assert.ok(found && found.score >= MARKS_ENOUGH, `перевёрнутый: границ ${found?.score}`)
})

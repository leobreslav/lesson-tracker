import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { findCode } from '../src/scanSheet.js'
import { CODE_PREFIX, QR } from '../src/blankGeometry.js'

/**
 * Матрица кода собирается **из того самого файла, который печатается**.
 *
 * `blank/qr_v1.tex` сгенерирован и вписан в бланк готовым; проверять его
 * глазами бесполезно — зеркальная или сдвинутая на модуль матрица выглядит
 * совершенно нормальным QR. Поэтому тест берёт заливки из этого файла,
 * восстанавливает по ним картинку и просит **наш** декодер её прочитать.
 *
 * Так проверяются разом три вещи, которые иначе расходятся молча: что
 * напечатанный код вообще читается, что в нём написано то, что мы думаем, и
 * что число модулей в `blankGeometry.js` совпадает с матрицей.
 */
function shippedMatrix() {
  const tex = readFileSync(
    fileURLToPath(new URL('../../blank/qr_v1.tex', import.meta.url)),
    'utf8',
  )
  const modules = Number(/x=#1\/(\d+)/.exec(tex)[1])
  const grid = Array.from({ length: modules }, () => new Uint8Array(modules))

  // `\fill (x,y) rectangle (x2,y2);` — координаты тиказа, ось Y снизу вверх
  for (const [, x0, y0, x1, y1] of tex.matchAll(
    /\\fill \((\d+),(\d+)\) rectangle \((\d+),(\d+)\);/g,
  )) {
    const row = modules - Number(y1)
    for (let x = Number(x0); x < Number(x1); x += 1) grid[row][x] = 1
  }
  return { grid, modules }
}

/** Матрица -> RGBA-картинка с тихой зоной, как на бумаге. */
function draw({ grid, modules }, scale = 8, quiet = 4) {
  const side = (modules + quiet * 2) * scale
  const data = new Uint8ClampedArray(side * side * 4).fill(255)
  for (let y = 0; y < side; y += 1) {
    for (let x = 0; x < side; x += 1) {
      const mx = Math.floor(x / scale) - quiet
      const my = Math.floor(y / scale) - quiet
      const dark = mx >= 0 && my >= 0 && mx < modules && my < modules && grid[my][mx]
      const p = (y * side + x) * 4
      data[p] = data[p + 1] = data[p + 2] = dark ? 0 : 255
      data[p + 3] = 255
    }
  }
  return { data, width: side, height: side }
}

test('код, который печатается на бланке, читается нашим декодером', () => {
  const shipped = shippedMatrix()

  assert.equal(
    shipped.modules,
    QR.modules,
    'число модулей в blankGeometry.js разошлось с напечатанной матрицей',
  )

  const found = findCode(draw(shipped))

  assert.ok(found, 'напечатанный код не прочитался вовсе')
  assert.ok(
    found.payload.startsWith(CODE_PREFIX),
    `в коде написано ${found.payload}, а лист узнаётся по началу ${CODE_PREFIX}`,
  )
  assert.equal(found.ours, true)
})

test('чужой лист не выдаёт себя за наш', () => {
  /*
   * Пустая бумага — не наш бланк, и молчание декодера тут единственный
   * честный ответ. Ради этого код и стоит: страница без него размечает пачку.
   */
  const white = {
    data: new Uint8ClampedArray(400 * 400 * 4).fill(255),
    width: 400,
    height: 400,
  }

  assert.equal(findCode(white), null)
})

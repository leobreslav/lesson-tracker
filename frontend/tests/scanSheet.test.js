import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ENOUGH_LINES,
  extractHeader,
  extremes,
  findMarks,
  findSheet,
  gridScore,
  homography,
  project,
  quads,
  shrink,
  toGray,
} from '../src/scanSheet.js'
import { CORNERS, GRID, HEADER, PAGE, STRIP_WIDTH } from '../src/blankGeometry.js'

/**
 * Рисуем лист так, как он выглядит на фотографии: тёмный фон, светлый
 * прямоугольник бумаги, метки по углам и сетка баллов. Настоящего снимка тут
 * быть не может — он приходит из PDF в браузере, — а проверять надо ровно то,
 * что этот модуль решает: где лист, где метки и какой поворот верный.
 */
function drawSheet({ scale = 3, angleFlip = 0, margin = 40, noise = 0 } = {}) {
  const width = Math.round(PAGE.width * scale) + margin * 2
  const height = Math.round(PAGE.height * scale) + margin * 2
  const data = new Uint8ClampedArray(width * height * 4)

  const put = (x, y, value) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return
    const p = (Math.round(y) * width + Math.round(x)) * 4
    data[p] = data[p + 1] = data[p + 2] = value
    data[p + 3] = 255
  }

  // фон — тёмный стол
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) put(x, y, 60)

  // лист; при angleFlip=1 он же вверх ногами
  const toPixel = (mmX, mmY) => {
    const x = angleFlip ? PAGE.width - mmX : mmX
    const y = angleFlip ? PAGE.height - mmY : mmY
    return { x: margin + x * scale, y: margin + y * scale }
  }

  for (let y = 0; y <= PAGE.height * scale; y += 1) {
    for (let x = 0; x <= PAGE.width * scale; x += 1) {
      put(margin + x, margin + y, 235 + (noise ? ((x * 7 + y * 13) % noise) : 0))
    }
  }

  const square = (mmX, mmY, side) => {
    for (let dy = -side / 2; dy <= side / 2; dy += 1 / scale) {
      for (let dx = -side / 2; dx <= side / 2; dx += 1 / scale) {
        const at = toPixel(mmX + dx, mmY + dy)
        put(at.x, at.y, 20)
      }
    }
  }

  for (const corner of Object.values(CORNERS)) square(corner.x, corner.y, 4)

  // сетка баллов: семнадцать вертикалей и две горизонтали
  const line = (fromX, fromY, toX, toY) => {
    const steps = Math.max(Math.abs(toX - fromX), Math.abs(toY - fromY)) * scale * 2
    for (let i = 0; i <= steps; i += 1) {
      const mmX = fromX + ((toX - fromX) * i) / steps
      const mmY = fromY + ((toY - fromY) * i) / steps
      const at = toPixel(mmX, mmY)
      for (let w = 0; w < 2; w += 1) put(at.x + w, at.y, 30)
    }
  }
  for (let cell = 0; cell <= GRID.cells; cell += 1) {
    const x = GRID.x + cell * GRID.cellWidth
    line(x, GRID.y, x, GRID.y + GRID.height)
  }
  line(GRID.x, GRID.y, GRID.x + GRID.cells * GRID.cellWidth, GRID.y)
  line(GRID.x, GRID.y + GRID.height, GRID.x + GRID.cells * GRID.cellWidth, GRID.y + GRID.height)

  return { data, width, height }
}

test('гомография переводит углы туда, куда сказано', () => {
  const from = [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 20 },
    { x: 0, y: 20 },
  ]
  const to = [
    { x: 5, y: 7 },
    { x: 105, y: 9 },
    { x: 100, y: 210 },
    { x: 2, y: 200 },
  ]

  const h = homography(from, to)

  for (let i = 0; i < 4; i += 1) {
    const got = project(h, from[i].x, from[i].y)
    assert.ok(Math.abs(got.x - to[i].x) < 1e-6, `x угла ${i}`)
    assert.ok(Math.abs(got.y - to[i].y) < 1e-6, `y угла ${i}`)
  }
})

test('четыре одинаковые точки четырёхугольником не считаются', () => {
  const one = { x: 5, y: 5 }
  assert.equal(extremes([one, one, one, one]), null)
})

test('лист виден на тёмном фоне, а метки — на листе', () => {
  const image = drawSheet()
  const small = shrink(toGray(image))

  assert.ok(findSheet(small), 'лист не найден')

  const marks = findMarks(small)
  assert.ok(marks.length >= 4, `меток найдено ${marks.length}`)
})

test('четвёрка меток узнаётся по пропорции листа', () => {
  const small = shrink(toGray(drawSheet()))
  const marks = findMarks(small)

  const found = quads(marks, small)

  assert.ok(found.length >= 1, 'ни одной четвёрки')
  const [tl, tr, br, bl] = found[0]
  assert.ok(tl.x < tr.x && tl.y < bl.y, 'углы перепутаны')
  assert.ok(Math.abs(tr.x - br.x) < small.width * 0.05, 'правая сторона не вертикальна')
})

test('клякса посреди листа четвёрку не портит', () => {
  const image = drawSheet()
  const small = shrink(toGray(image))
  const marks = findMarks(small)
  // пятно ровно того же размера, но не на своём месте
  const blot = { x: small.width / 2, y: small.height / 2, width: 4, height: 4, size: 16 }

  const found = quads([...marks, blot], small)

  assert.ok(found.length >= 1)
  assert.ok(
    !found[0].some((point) => point === blot),
    'клякса попала в углы',
  )
})

test('полоска шапки вырезается и узнаётся по сетке', () => {
  const found = extractHeader(drawSheet())

  assert.ok(found, 'шапка не вырезалась')
  assert.equal(found.strip.width, STRIP_WIDTH)
  assert.ok(
    found.score >= ENOUGH_LINES,
    `линий сетки насчитано ${found.score}, а нужно хотя бы ${ENOUGH_LINES}`,
  )
})

test('перевёрнутая страница выправляется сама', () => {
  const found = extractHeader(drawSheet({ angleFlip: 1 }))

  assert.ok(found, 'шапка не вырезалась')
  assert.ok(
    found.score >= ENOUGH_LINES,
    `перевёрнутую не выправило: линий ${found.score}`,
  )
})

test('пустой лист без сетки набирает мало и честно об этом говорит', () => {
  const blank = {
    data: new Uint8ClampedArray(200 * 200 * 4).fill(255),
    width: 200,
    height: 200,
  }

  assert.ok(gridScore(blank) < ENOUGH_LINES)
})

test('кроп берёт именно шапку, а не середину листа', () => {
  const found = extractHeader(drawSheet())
  const { gray, width, height } = toGray(found.strip)

  // в нижней половине полоски обязаны быть тёмные вертикали сетки
  let dark = 0
  for (let y = Math.floor(height * 0.5); y < height; y += 1) {
    for (let x = 0; x < width; x += 1) if (gray[y * width + x] < 128) dark += 1
  }

  assert.ok(dark > width, `тёмных точек в полосе клеток всего ${dark}`)
  assert.equal(HEADER.height, 30)
})

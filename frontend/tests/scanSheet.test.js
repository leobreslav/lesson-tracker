import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ENOUGH_LINES,
  GRID_IS_OURS,
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
import { CORNERS, GRID, HEADER, PAGE, STRIP, STRIP_WIDTH } from '../src/blankGeometry.js'

/**
 * Рисуем лист так, как он выглядит на фотографии: тёмный фон, светлый
 * прямоугольник бумаги, метки по углам и сетка баллов. Настоящего снимка тут
 * быть не может — он приходит из PDF в браузере, — а проверять надо ровно то,
 * что этот модуль решает: где лист, где метки и какой поворот верный.
 */
function drawSheet({
  scale = 3,
  angleFlip = 0,
  margin = 40,
  noise = 0,
  marks = true,
  markShift = 0,
  ink = 0,
} = {}) {
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

  // markShift сдвигает реперы, не трогая сетку: так выглядит промах поиска
  // меток — грубое выпрямление уезжает, а печатные линии остаются на местах
  if (marks)
    for (const corner of Object.values(CORNERS)) square(corner.x + markShift, corner.y, 4)

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

  // `ink` — сколько клеток заполнено баллами. Цифра рисуется толстым штрихом
  // почти во всю высоту клетки: так она и выглядит, написанная от руки
  // крупно. Проверяется этим не чтение цифры, а то, что она не мешает считать
  // границы сетки.
  for (let cell = 0; cell < ink; cell += 1) {
    const left = GRID.x + cell * GRID.cellWidth + GRID.cellWidth * 0.3
    const top = GRID.y + GRID.labelHeight + 1
    const bottom = GRID.y + GRID.height - 1
    for (let dx = 0; dx <= GRID.cellWidth * 0.4; dx += 1 / (scale * 2)) {
      line(left + dx, top, left + dx, bottom)
    }
  }

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

test('промах реперов чинится уточнением по сетке', () => {
  /*
   * Метки — приближение, и промах в них уводит всю гомографию. Сетка баллов
   * же стоит ровно там, где мы кропаем: семнадцать вертикалей и три
   * горизонтали высокого контраста на базе 185 мм. Выпрямили как получилось,
   * посмотрели, где линии стоят на самом деле, и поправили прямоугольник
   * кропа так, чтобы они встали на печатные места.
   *
   * Здесь реперы сдвинуты на два миллиметра, а сетка нет: ровно так выглядит
   * ошибка поиска меток, из-за которой на живой пачке терялись страницы.
   */
  const found = extractHeader(drawSheet({ markShift: 2 }))

  assert.ok(found, 'шапка не нашлась вовсе')
  assert.ok(found.fix, 'поправка по сетке не посчиталась')
  assert.ok(
    found.score >= ENOUGH_LINES,
    `после уточнения границ ${found.score} из нужных ${ENOUGH_LINES}`,
  )

  // поправка обязана быть **содержательной**: сдвиг в два миллиметра она и
  // должна была увидеть, а не вернуть тождество и промолчать
  const shift = Math.abs(found.fix.ax * GRID.x + found.fix.bx - GRID.x)
  assert.ok(shift > 0.5, `поправка вышла пустой: сдвиг ${shift.toFixed(2)} мм`)
})

test('ровный лист читается и без единой метки по углам', () => {
  /*
   * Метки — приближение, и на сканере они не нужны: страница уже выпрямлена,
   * край листа совпадает с краем картинки. Хуже того, поиск меток на такой
   * странице умеет **ошибаться**: найдя не ту четвёрку, он строит перекошенную
   * гомографию, набирает семь границ из двенадцати и объявляет лист «не
   * нашим». На живой пачке так пропали три страницы, и две из них читались
   * глазами без усилий — на экране ровные и чистые.
   *
   * Поэтому среди кандидатов есть и тождественная раскладка: углы листа на
   * углы картинки. Испортить она ничего не может — выбор идёт по тому же
   * счёту.
   */
  const found = extractHeader(drawSheet({ marks: false, margin: 0 }))

  assert.ok(found, 'ровный лист без меток не нашёлся вовсе')
  assert.ok(
    found.score >= ENOUGH_LINES,
    `границ нашлось ${found.score} из нужных ${ENOUGH_LINES}`,
  )
})

test('перевёрнутый ровный лист тоже читается без меток', () => {
  const found = extractHeader(drawSheet({ marks: false, margin: 0, angleFlip: 1 }))

  assert.ok(found && found.score >= ENOUGH_LINES, `границ ${found?.score}`)
})

test('полная сетка сама доказывает, что бланк наш', () => {
  /*
   * Доказательством был только код в углу — и стоит он внизу листа. Обрезал
   * скан низ, загнулся угол — доказательства нет, при том что шапка на месте.
   * На живой пачке такие страницы уезжали в «листы условий» и разрезали пачку
   * надвое.
   *
   * Шестнадцать клеток, вставшие все на печатные места, — не совпадение: у
   * чужого листа так не выходит.
   */
  const found = extractHeader(drawSheet({ margin: 0, marks: false }))

  assert.ok(found.score >= GRID_IS_OURS, `сетка сошлась на ${found.score}`)
  assert.equal(found.ours, true, 'полная сетка не признана нашим бланком')
})

test('заполненные баллами клетки не мешают узнать сетку', () => {
  /*
   * Считается счёт по столбцам: линия — это столбец заметно темнее бумаги
   * вокруг. «Бумага» при этом берётся медианой по всей полосе клеток, а чем
   * больше клеток заполнено, тем медиана темнее — то есть порог уезжает вслед
   * за чернилами. Если бы этого хватало, чтобы потерять линии, выходило бы
   * наоборот тому, чего ждёшь: чем прилежнее заполнена шапка, тем хуже она
   * узнаётся.
   *
   * Написан этот тест как **опыт**: на живой пачке страница с восемью
   * выставленными баллами и суммой набрала семь границ из двенадцати и уехала
   * в «листы условий» — то есть не была прочитана вовсе, и учитель увидел
   * пустые клетки там, где сам же написал баллы. Чернила оказались ни при чём:
   * на ровном листе счёт держится и при всех шестнадцати заполненных. Причина
   * той страницы, значит, в другом — скорее всего в неверно выбранной
   * четвёрке меток (см. соседний тест про лист без меток, где симптом ровно
   * тот же), — а тест остаётся сторожем: медиана по полосе с чернилами вещь
   * скользкая, и следующая правка порога должна об этом споткнуться.
   */
  for (const filled of [0, 4, 8, 16]) {
    const score = gridScore(extractHeader(drawSheet({ ink: filled })).strip)
    assert.ok(
      score >= ENOUGH_LINES,
      `при ${filled} заполненных клетках границ ${score} из нужных ${ENOUGH_LINES}`,
    )
  }
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

  // Сверху полоска не режется: она начинается у самого края листа и кончается
  // под сеткой. Промах кропа вверх срезал бы верх букв в строке имени, а
  // выглядело бы это как испортившееся чтение почерка.
  assert.equal(STRIP.y, 0)
  assert.equal(STRIP.height, 38)

  // А **ищут** шапку по другой области — той, что обнята метками. Расширение
  // кропа вверх однажды утащило за собой и поиск: счёт стал считаться там,
  // где гомография продолжена наружу, и две страницы живой пачки перестали
  // опознаваться как наш бланк. Области разные, и это должно остаться так.
  assert.equal(HEADER.y, 8)
  assert.equal(HEADER.height, 30)
  assert.ok(STRIP.y < HEADER.y, 'кроп обязан начинаться выше области поиска')
})

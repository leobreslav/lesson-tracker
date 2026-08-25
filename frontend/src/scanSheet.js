/**
 * Найти лист на фотографии и вырезать из него полоску шапки.
 *
 * Считает это браузер, а не сервер, и причина не в моде на клиентские
 * вычисления: страницы у браузера уже отрисованы (`pdfjs` рисует их ради
 * предпросмотра), а сервер, взявшись за то же самое, потребовал бы
 * растеризатор в образе и книгу целиком по сети — вместо полоски в сотню
 * килобайт. Плюс каждый запрос к нему остаётся коротким, а воркеров на проде
 * два.
 *
 * Порядок работы:
 *
 *   1. **найти лист** — самое светлое крупное пятно кадра. Без этого шага
 *      клавиши ноутбука на столе становятся кандидатами в метки: они тоже
 *      тёмные квадратики нужного размера;
 *   2. **найти метки** внутри листа — тёмные сплошные квадраты;
 *   3. **выбрать четыре угла** и вычислить гомографию «миллиметры → пиксели»;
 *   4. **вырезать полоску**, перебрав четыре поворота и выбрав тот, где
 *      сетка баллов действительно похожа на сетку.
 *
 * Всё здесь — чистые функции над `{data, width, height}` (RGBA, как у
 * `ImageData`), поэтому проверяются в node без браузера.
 */

import { GRID, HEADER, PAGE, QR, STRIP, STRIP_WIDTH, cellRect, headerCorners, nameRow, sheetCorners, stripHeight } from './blankGeometry.js'

/** Оттенки серого одной плоскостью: дальше всё считается по ней. */
export function toGray(image) {
  const { data, width, height } = image
  const gray = new Uint8Array(width * height)
  for (let i = 0, p = 0; i < gray.length; i += 1, p += 4) {
    gray[i] = (data[p] * 299 + data[p + 1] * 587 + data[p + 2] * 114) / 1000
  }
  return { gray, width, height }
}

/** Уменьшенная копия: детект идёт по ней, а режется полноразмерный кадр. */
export function shrink({ gray, width, height }, maxSide = 900) {
  const step = Math.max(1, Math.ceil(Math.max(width, height) / maxSide))
  if (step === 1) return { gray, width, height, step }

  const w = Math.floor(width / step)
  const h = Math.floor(height / step)
  const out = new Uint8Array(w * h)
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      out[y * w + x] = gray[y * step * width + x * step]
    }
  }
  return { gray: out, width: w, height: h, step }
}

/**
 * Порог Оцу: делит гистограмму на тёмное и светлое так, чтобы разброс внутри
 * половин был наименьшим. Свет на фотографиях неровный, и фиксированный порог
 * («темнее 128») на них не работает вовсе.
 */
export function otsu(gray) {
  const hist = new Uint32Array(256)
  for (let i = 0; i < gray.length; i += 1) hist[gray[i]] += 1

  const total = gray.length
  let sum = 0
  for (let t = 0; t < 256; t += 1) sum += t * hist[t]

  let sumB = 0
  let weightB = 0
  let best = 0
  let bestValue = -1
  for (let t = 0; t < 256; t += 1) {
    weightB += hist[t]
    if (!weightB) continue
    const weightF = total - weightB
    if (!weightF) break
    sumB += t * hist[t]
    const meanB = sumB / weightB
    const meanF = (sum - sumB) / weightF
    const between = weightB * weightF * (meanB - meanF) * (meanB - meanF)
    if (between > bestValue) {
      bestValue = between
      best = t
    }
  }
  return best
}

/**
 * Связные области одного цвета. Обход в ширину явной очередью, а не
 * рекурсией: на снимке в шесть мегапикселей рекурсия кладёт стек.
 */
export function components({ gray, width, height }, keep) {
  const seen = new Uint8Array(width * height)
  const found = []
  const queue = new Int32Array(width * height)

  for (let start = 0; start < seen.length; start += 1) {
    if (seen[start] || !keep(gray[start])) continue

    let head = 0
    let tail = 0
    queue[tail += 1] = start
    seen[start] = 1
    let size = 0
    let minX = width
    let maxX = 0
    let minY = height
    let maxY = 0
    let sumX = 0
    let sumY = 0

    while (head < tail) {
      const at = queue[head += 1]
      const x = at % width
      const y = (at - x) / width
      size += 1
      sumX += x
      sumY += y
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y

      const neighbours = [
        x > 0 ? at - 1 : -1,
        x < width - 1 ? at + 1 : -1,
        y > 0 ? at - width : -1,
        y < height - 1 ? at + width : -1,
      ]
      for (const next of neighbours) {
        if (next >= 0 && !seen[next] && keep(gray[next])) {
          seen[next] = 1
          queue[tail += 1] = next
        }
      }
    }

    found.push({
      size,
      minX,
      maxX,
      minY,
      maxY,
      x: sumX / size,
      y: sumY / size,
      width: maxX - minX + 1,
      height: maxY - minY + 1,
    })
  }
  return found
}

/**
 * Лист — самое крупное светлое пятно кадра.
 *
 * Опорой он не служит: на живых снимках бумага сливается то с экраном
 * ноутбука, то со светлым столом, и её рамка оказывается шире листа. Нужен он
 * ровно для одного — сказать человеку «листа в кадре не видно», когда не
 * нашлось вообще ничего.
 */
export function findSheet(small) {
  const level = otsu(small.gray)
  const bright = components(small, (value) => value > level)
  if (!bright.length) return null

  const sheet = bright.reduce((best, one) => (one.size > best.size ? one : best))
  if (sheet.size < small.width * small.height * 0.05) return null
  return sheet
}

/**
 * Тёмные сплошные квадратики кадра — кандидаты в метки.
 *
 * Размер спрашивается у кадра, а не задаётся в пикселях: метка это 4 мм на
 * 210 мм ширины листа, то есть постоянная доля снимка, как бы близко ни
 * снимали. Границы взяты с большим запасом — отсеивать лишнее будет геометрия
 * четвёрки, а не размер поодиночке.
 */
export function findMarks(small) {
  const level = otsu(small.gray)
  const dark = components(small, (value) => value < level * 0.8)

  const frame = Math.max(small.width, small.height)
  const min = (frame * 0.004) ** 2
  const max = (frame * 0.05) ** 2

  return dark.filter((blob) => {
    if (blob.size < min || blob.size > max) return false
    const ratio = blob.width / blob.height
    if (ratio < 0.5 || ratio > 2) return false
    // сплошной, а не буква и не линия
    return blob.size / (blob.width * blob.height) > 0.6
  })
}

/** Четыре крайние точки набора: левый верх, правый верх, правый низ, левый низ. */
export function extremes(points) {
  if (points.length < 4) return null
  let tl = points[0]
  let tr = points[0]
  let br = points[0]
  let bl = points[0]
  for (const point of points) {
    if (point.x + point.y < tl.x + tl.y) tl = point
    if (point.x + point.y > br.x + br.y) br = point
    if (point.x - point.y > tr.x - tr.y) tr = point
    if (point.x - point.y < bl.x - bl.y) bl = point
  }
  const corners = [tl, tr, br, bl]
  // Четыре одинаковые точки — это не четырёхугольник, а одно пятно.
  const seen = new Set(corners.map((p) => `${p.x},${p.y}`))
  return seen.size === 4 ? corners : null
}

/**
 * Четвёрки меток, похожие на углы листа. Лучшие первыми.
 *
 * Перебор, а не хитрость: кандидатов после отсева единицы, а `C(8,4)` это
 * семьдесят вариантов — считается мгновенно. Зато отбор идёт по тому
 * единственному, что настоящие метки отличает от случайной кляксы: вчетвером
 * они образуют прямоугольник с пропорцией листа A4, и он занимает почти весь
 * кадр.
 *
 * Пропорция проверяется обе — портретная и лежачая: снимок бывает повёрнут, и
 * отбрасывать его на этом шаге значило бы решать за поворот раньше, чем мы
 * посмотрели на сетку.
 */
const PORTRAIT = 194 / 281
const LANDSCAPE = 281 / 194

export function quads(marks, frame) {
  const found = []
  const least = Math.min(frame.width, frame.height) * 0.2

  for (let a = 0; a < marks.length; a += 1) {
    for (let b = a + 1; b < marks.length; b += 1) {
      for (let c = b + 1; c < marks.length; c += 1) {
        for (let d = c + 1; d < marks.length; d += 1) {
          const corners = extremes([marks[a], marks[b], marks[c], marks[d]])
          if (!corners) continue

          const [tl, tr, br, bl] = corners
          const top = Math.hypot(tr.x - tl.x, tr.y - tl.y)
          const bottom = Math.hypot(br.x - bl.x, br.y - bl.y)
          const left = Math.hypot(bl.x - tl.x, bl.y - tl.y)
          const right = Math.hypot(br.x - tr.x, br.y - tr.y)
          if (Math.min(top, bottom, left, right) < least) continue
          // противоположные стороны у прямоугольника похожи, даже в перспективе
          if (Math.abs(top - bottom) / Math.max(top, bottom) > 0.35) continue
          if (Math.abs(left - right) / Math.max(left, right) > 0.35) continue

          const ratio = (top + bottom) / (left + right)
          const off = Math.min(
            Math.abs(ratio - PORTRAIT) / PORTRAIT,
            Math.abs(ratio - LANDSCAPE) / LANDSCAPE,
          )
          if (off > 0.25) continue

          const area = ((top + bottom) / 2) * ((left + right) / 2)
          found.push({ corners, score: area / (1 + off * 4) })
        }
      }
    }
  }

  found.sort((one, two) => two.score - one.score)
  return found.slice(0, 8).map((one) => one.corners)
}

/**
 * Полосы, которые метки бланка образуют **вокруг шапки**.
 *
 * Меток на бумаге восемь: четыре по углам листа и ещё две пары по бокам, на
 * 27 и 39 мм. Вторые напечатаны ровно затем, чтобы обнять шапку, — так и
 * сказано в `blank/README.md`, — но `extractHeader` брал только углы листа, и
 * четыре метки из восьми не участвовали ни в чём.
 *
 * Стоило это непрочитанных страниц. Нижняя пара стоит у самого края листа и
 * пропадает первой: обрезал скан низ, легла страница не целиком — и углов
 * больше нет. Четвёрки из оставшихся верхних меток плоские, пропорцию A4 не
 * дают и отсеиваются, кандидатов не остаётся вовсе, а последняя надежда —
 * «лист лежит ровно» — верна только на сканере и только если поля не срезаны.
 * Дальше страница набирает семь-девять границ из двенадцати и объявляется
 * листом условий: то есть **не читается вовсе**, и учитель видит пустые
 * клетки там, где сам выставил баллы.
 *
 * Пар три, и какая из них перед нами, решает пропорция: ширина у всех одна
 * (194 мм), а высота разная. Гадать не нужно — выбор идёт по той же сетке,
 * что и всё остальное.
 */
const BANDS = [
  { top: 8, bottom: 39 },
  { top: 8, bottom: 27 },
  { top: 27, bottom: 39 },
]

const BAND_LEFT = 8
const BAND_RIGHT = 202

export function bands(marks, frame) {
  const found = []
  const least = Math.min(frame.width, frame.height) * 0.2

  for (let a = 0; a < marks.length; a += 1) {
    for (let b = a + 1; b < marks.length; b += 1) {
      for (let c = b + 1; c < marks.length; c += 1) {
        for (let d = c + 1; d < marks.length; d += 1) {
          const corners = extremes([marks[a], marks[b], marks[c], marks[d]])
          if (!corners) continue

          const [tl, tr, br, bl] = corners
          const top = Math.hypot(tr.x - tl.x, tr.y - tl.y)
          const bottom = Math.hypot(br.x - bl.x, br.y - bl.y)
          const left = Math.hypot(bl.x - tl.x, bl.y - tl.y)
          const right = Math.hypot(br.x - tr.x, br.y - tr.y)

          // Длинные стороны — во всю ширину листа, короткие просто не нулевые:
          // полоса низкая, и мерять её тем же порогом, что сторону листа,
          // значит отбросить её всю.
          if (Math.min(top, bottom) < least) continue
          if (Math.min(left, right) < 2) continue
          if (Math.abs(top - bottom) / Math.max(top, bottom) > 0.35) continue
          if (Math.abs(left - right) / Math.max(left, right) > 0.35) continue

          const ratio = (top + bottom) / (left + right)
          let best = null
          for (const band of BANDS) {
            const want = (BAND_RIGHT - BAND_LEFT) / (band.bottom - band.top)
            const off = Math.abs(ratio - want) / want
            if (off > 0.2) continue
            if (!best || off < best.off) best = { band, off }
          }
          if (!best) continue

          const area = ((top + bottom) / 2) * ((left + right) / 2)
          found.push({ corners, band: best.band, score: area / (1 + best.off * 4) })
        }
      }
    }
  }

  found.sort((one, two) => two.score - one.score)
  return found.slice(0, 6)
}

/**
 * Гомография по четырём парам точек: решается система 8×8 методом Гаусса.
 *
 * Возвращает матрицу, переводящую `from` в `to`. Восьми уравнений ровно
 * столько, сколько неизвестных: девятый коэффициент принят за единицу.
 */
export function homography(from, to) {
  const a = []
  const b = []
  for (let i = 0; i < 4; i += 1) {
    const { x, y } = from[i]
    const { x: u, y: v } = to[i]
    a.push([x, y, 1, 0, 0, 0, -x * u, -y * u])
    b.push(u)
    a.push([0, 0, 0, x, y, 1, -x * v, -y * v])
    b.push(v)
  }

  for (let col = 0; col < 8; col += 1) {
    let pivot = col
    for (let row = col + 1; row < 8; row += 1) {
      if (Math.abs(a[row][col]) > Math.abs(a[pivot][col])) pivot = row
    }
    if (Math.abs(a[pivot][col]) < 1e-9) return null
    ;[a[col], a[pivot]] = [a[pivot], a[col]]
    ;[b[col], b[pivot]] = [b[pivot], b[col]]

    for (let row = 0; row < 8; row += 1) {
      if (row === col) continue
      const factor = a[row][col] / a[col][col]
      if (!factor) continue
      for (let k = col; k < 8; k += 1) a[row][k] -= factor * a[col][k]
      b[row] -= factor * b[col]
    }
  }

  const h = b.map((value, i) => value / a[i][i])
  return [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1]
}

/** Точка через гомографию. */
export function project(h, x, y) {
  const w = h[6] * x + h[7] * y + h[8]
  return { x: (h[0] * x + h[1] * y + h[2]) / w, y: (h[3] * x + h[4] * y + h[5]) / w }
}

/**
 * Вырезать прямоугольник листа (в миллиметрах) в картинку заданного размера.
 *
 * Идём от выходного пикселя к входному и берём билинейную выборку: обратный
 * ход не оставляет дыр, которые появились бы при прямом.
 */
export function warp(image, h, rect, outWidth, outHeight) {
  const { data, width, height } = image
  const out = new Uint8ClampedArray(outWidth * outHeight * 4)

  for (let y = 0; y < outHeight; y += 1) {
    const mmY = rect.y + (rect.height * (y + 0.5)) / outHeight
    for (let x = 0; x < outWidth; x += 1) {
      const mmX = rect.x + (rect.width * (x + 0.5)) / outWidth
      const at = project(h, mmX, mmY)
      const p = (y * outWidth + x) * 4

      const x0 = Math.floor(at.x)
      const y0 = Math.floor(at.y)
      if (x0 < 0 || y0 < 0 || x0 + 1 >= width || y0 + 1 >= height) {
        out[p] = out[p + 1] = out[p + 2] = 255
        out[p + 3] = 255
        continue
      }

      const fx = at.x - x0
      const fy = at.y - y0
      for (let c = 0; c < 3; c += 1) {
        const i00 = (y0 * width + x0) * 4 + c
        const i10 = i00 + 4
        const i01 = i00 + width * 4
        const i11 = i01 + 4
        const top = data[i00] * (1 - fx) + data[i10] * fx
        const bottom = data[i01] * (1 - fx) + data[i11] * fx
        out[p + c] = top * (1 - fy) + bottom * fy
      }
      out[p + 3] = 255
    }
  }

  return { data: out, width: outWidth, height: outHeight }
}

/**
 * Похожа ли вырезанная полоска на шапку бланка.
 *
 * Не «сколько тут вертикальных линий» — этим счётом полоска однажды уже
 * обманулась: перевёрнутая страница даёт на месте шапки поле записи, а в нём
 * тетрадных линий вчетверо больше, и она выигрывала у настоящей шапки. Считаем
 * поэтому не количество, а **совпадение с ожидаемым**: полоска вырезана в
 * миллиметрах листа, значит границы шестнадцати клеток обязаны стоять там, где
 * их напечатали, и нигде больше.
 *
 * Отсюда и защита от тетрадной сетки: её шаг пять миллиметров, в ожидаемые
 * места она попадает случайно, а лишние линии выдают её с головой.
 */
const CROWDED = 25

/**
 * Тёмные полосы поперёк картинки: сначала средняя яркость, потом центры.
 *
 * Одна функция на оба направления — вертикали сетки и её горизонтали, — потому
 * что вопрос один и тот же: где линия. Порог берётся **от самой бумаги**, а не
 * абсолютный: на фотографии линия чёрная и толстая, в отрисованном PDF серая в
 * полтора пикселя со сглаживанием, и один порог либо пропускает вторую, либо
 * принимает за линию любую тень.
 */
function darkBands(gray, width, height, { across }) {
  const outer = across ? width : height
  const inner = across ? height : width

  const level = new Float32Array(outer)
  for (let a = 0; a < outer; a += 1) {
    let sum = 0
    for (let b = 0; b < inner; b += 1) sum += gray[across ? b * width + a : a * width + b]
    level[a] = sum / inner
  }

  const paper = [...level].sort((one, two) => one - two)[Math.floor(outer / 2)]
  const limit = paper - Math.max(8, paper * 0.08)

  const centres = []
  let from = -1
  for (let a = 0; a <= outer; a += 1) {
    const dark = a < outer && level[a] < limit
    if (dark && from < 0) from = a
    if (!dark && from >= 0) {
      centres.push((from + a - 1) / 2)
      from = -1
    }
  }
  return centres
}

/** Прямая по парам методом наименьших квадратов: `to = a * from + b`. */
function fitLine(pairs) {
  const n = pairs.length
  if (n < 3) return null
  let sx = 0
  let sy = 0
  let sxx = 0
  let sxy = 0
  for (const [x, y] of pairs) {
    sx += x
    sy += y
    sxx += x * x
    sxy += x * y
  }
  const denominator = n * sxx - sx * sx
  if (Math.abs(denominator) < 1e-9) return null
  const a = (n * sxy - sx * sy) / denominator
  return { a, b: (sy - a * sx) / n }
}

/**
 * Уточнение по самой сетке — тот шаг, который в `blank/README.md` описан как
 * главный, а в коде долго отсутствовал.
 *
 * Метки по углам это **приближение**: их четыре (из шести), они мелкие, и
 * промах в одной уводит всю гомографию. Сетка баллов же стоит ровно там, где
 * мы кропаем: семнадцать вертикалей и три горизонтали высокого контраста на
 * базе 185 мм. Ей безразличны порванный угол, обрез и бледная печать —
 * избыточность такая, что хватит и половины линий.
 *
 * Поэтому: выпрямили как получилось, посмотрели, **где на самом деле** стоят
 * линии, и поправили прямоугольник кропа так, чтобы они встали на печатные
 * места. Возвращается поправка в миллиметрах листа (`x' = ax·x + bx`), потому
 * что применять её надо ко всем кропам сразу — к полоске, к клеткам и к
 * проверке кода в углу, — а прямоугольники у них разные.
 *
 * `null` значит «уточнять не по чему»: линий нашлось слишком мало, и подгонка
 * по трём случайным теням была бы хуже, чем её отсутствие.
 */
export function gridFix(strip, rect) {
  const { gray, width, height } = toGray(strip)
  const mmX = (px) => rect.x + (rect.width * px) / width
  const mmY = (px) => rect.y + (rect.height * px) / height

  const near = (rect.width * 3) / 190

  const verticals = darkBands(gray, width, height, { across: true }).map(mmX)
  const pairs = []
  for (let cell = 0; cell <= GRID.cells; cell += 1) {
    const want = GRID.x + cell * GRID.cellWidth
    let best = null
    for (const found of verticals) {
      const gap = Math.abs(found - want)
      if (gap <= near && (!best || gap < Math.abs(best - want))) best = found
    }
    if (best !== null) pairs.push([want, best])
  }

  const horizontals = darkBands(gray, width, height, { across: false }).map(mmY)
  const rows = []
  for (const want of [GRID.y, GRID.y + GRID.labelHeight, GRID.y + GRID.height]) {
    let best = null
    for (const found of horizontals) {
      const gap = Math.abs(found - want)
      if (gap <= near && (!best || gap < Math.abs(best - want))) best = found
    }
    if (best !== null) rows.push([want, best])
  }

  const byX = fitLine(pairs)
  if (!byX) return null
  const byY = fitLine(rows)

  const fix = {
    ax: byX.a,
    bx: byX.b,
    // горизонталей всего три, и найтись должны все: по двум прямая проходит
    // через любые две точки и врёт с уверенным видом
    ay: byY ? byY.a : 1,
    by: byY ? byY.b : 0,
  }

  /*
   * Поправка бывает только **маленькой**, и это не придирка.
   *
   * Уточнение подгоняет прямую по найденным полосам, а полос на листе много:
   * ниже шапки лежит тетрадное поле с шагом 5 мм. Свободная подгонка растянула
   * бы его вдвое с лишним и объявила сеткой баллов — то есть нашла бы шапку
   * там, где её нет. Настоящий же промах реперов измеряется миллиметрами:
   * метки мелкие, но стоят они на своих местах.
   */
  const sane = (a, b) => Math.abs(a - 1) <= 0.1 && Math.abs(b) <= 6
  if (!sane(fix.ax, fix.bx)) return null
  if (!sane(fix.ay, fix.by)) {
    fix.ay = 1
    fix.by = 0
  }
  return fix
}

/** Прямоугольник листа с поправкой: те же миллиметры, сдвинутые и растянутые. */
export function fixed(rect, fix) {
  if (!fix) return rect
  return {
    x: fix.ax * rect.x + fix.bx,
    y: fix.ay * rect.y + fix.by,
    width: fix.ax * rect.width,
    height: fix.ay * rect.height,
  }
}

export function gridScore(strip) {
  const { gray, width, height } = toGray(strip)

  // полоса клеток: под подписями Q1..Σ и до низа сетки
  const top = Math.round(((GRID.y + GRID.labelHeight - HEADER.y) / HEADER.height) * height)
  const bottom = Math.round(((GRID.y + GRID.height - HEADER.y) / HEADER.height) * height)
  const rows = Math.max(1, bottom - top)

  // Средняя яркость столбца, а не «доля тёмных точек ниже порога». Порог тут
  // не работает: на фотографии линия чёрная и толстая, а в отрисованном PDF —
  // серая в полтора пикселя со сглаживанием, и один и тот же порог либо
  // пропускает вторую, либо принимает за линию любую тень. Считаем поэтому от
  // самой бумаги: линия — это столбец заметно темнее, чем лист вокруг него.
  const column = new Float32Array(width)
  for (let x = 0; x < width; x += 1) {
    let sum = 0
    for (let y = top; y < bottom; y += 1) sum += gray[y * width + x]
    column[x] = sum / rows
  }

  const paper = [...column].sort((a, b) => a - b)[Math.floor(width / 2)]
  const level = paper - Math.max(8, paper * 0.08)

  const solid = new Uint8Array(width)
  let strong = 0
  for (let x = 0; x < width; x += 1) {
    if (column[x] < level) {
      solid[x] = 1
      if (!solid[x - 1]) strong += 1
    }
  }

  // Сплошная стена вертикалей — это тетрадное поле, а не сетка баллов.
  if (strong > CROWDED) return 0

  const near = Math.max(3, Math.round((1.2 / HEADER.width) * width))
  let matched = 0
  for (let cell = 0; cell <= GRID.cells; cell += 1) {
    const mm = GRID.x + cell * GRID.cellWidth
    const at = Math.round(((mm - HEADER.x) / HEADER.width) * width)
    for (let dx = -near; dx <= near; dx += 1) {
      if (solid[at + dx]) {
        matched += 1
        break
      }
    }
  }
  return matched
}

/**
 * Наш ли это лист — по QR в углу поля записи.
 *
 * Код **не декодируется**: содержимое у него постоянное, и читать его незачем.
 * Проверяется узор — три «глаза» по углам, те самые концентрические квадраты,
 * по которым QR узнают все декодеры. Каждый из них семь модулей на семь:
 * тёмная рамка, светлое кольцо, тёмная сердцевина. Три совпавших глаза значит
 * «наш лист», и никакой библиотеки для этого не нужно.
 *
 * Работает это только после выпрямления: без гомографии мы не знаем, где у
 * листа угол. Так и надо — лист без меток и не наш по определению.
 */
export function hasBlankMark(image, h, fix = null) {
  // код в углу ищется с той же поправкой, что и полоска: уточнение по сетке
  // говорит, куда уехал весь лист, а не одна его шапка
  const where = fixed(QR, fix)
  const step = where.width / QR.modules
  const dark = (mx, my) => {
    const at = project(h, where.x + (mx + 0.5) * step, where.y + (my + 0.5) * step)
    const x = Math.round(at.x)
    const y = Math.round(at.y)
    if (x < 1 || y < 1 || x >= image.width - 1 || y >= image.height - 1) return null
    const p = (y * image.width + x) * 4
    return (image.data[p] * 299 + image.data[p + 1] * 587 + image.data[p + 2] * 114) / 1000
  }

  // яркость бумаги рядом с кодом: порог считаем от неё, а не от абсолютного
  const around = []
  for (let mx = 0; mx < QR.modules; mx += 1) {
    const value = dark(mx, -2)
    if (value !== null) around.push(value)
  }
  if (!around.length) return false
  const paper = around.sort((a, b) => a - b)[Math.floor(around.length / 2)]
  const level = paper * 0.6

  const eye = (left, top) => {
    let right = 0
    let wrong = 0
    for (let my = 0; my < 7; my += 1) {
      for (let mx = 0; mx < 7; mx += 1) {
        const value = dark(left + mx, top + my)
        if (value === null) return false
        const ring = mx === 0 || my === 0 || mx === 6 || my === 6
        const middle = mx >= 2 && mx <= 4 && my >= 2 && my <= 4
        const shouldBeDark = ring || middle
        if ((value < level) === shouldBeDark) right += 1
        else wrong += 1
      }
    }
    return right / (right + wrong) > 0.8
  }

  const eyes = [eye(0, 0), eye(QR.modules - 7, 0), eye(0, QR.modules - 7)]
  return eyes.filter(Boolean).length >= 2
}

/**
 * Полоска шапки с фотографии страницы.
 *
 * Возвращает `{strip, score, corners}` или `null`, если ни одна четвёрка меток
 * не дала похожей на шапку картинки.
 *
 * Поворот выбирается перебором: какой из четырёх даёт настоящую сетку, тот и
 * верный. Это надёжнее, чем угадывать по меньшей метке, — она мельче всех и
 * теряется первой на смазанном снимке.
 *
 * Перебор идёт **дешёвой** копией: полоска в пятьсот точек шириной сетку
 * показывает не хуже, а считается в двадцать раз быстрее. Полное разрешение
 * достаётся одному победителю — тому, что поедет на чтение.
 */
const TRY_WIDTH = 512

export function extractHeader(image) {
  const small = shrink(toGray(image))
  const marks = findMarks(small)
  const candidates = quads(marks, small)

  const tryHeight = Math.round((TRY_WIDTH * HEADER.height) / HEADER.width)
  const nominal = sheetCorners()
  const rough = []

  /*
   * Каждый кандидат проверяется дважды: как есть и **после уточнения по
   * сетке**.
   *
   * Уточнялись сперва только лучшие по грубому счёту — и это было ровно
   * наоборот: спасать надо тех, у кого грубый счёт мал. Сдвиньте реперы на два
   * миллиметра, и настоящая, годная четвёрка наберёт ноль совпадений — при
   * том, что сетка на её полоске видна целиком и промах измеряется одной
   * подгонкой. Такой кандидат до уточнения не доживал.
   *
   * Стоит это второго выпрямления на кандидата, и оба идут дешёвой копией в
   * пятьсот точек шириной.
   */
  const consider = (from, to) => {
    const h = homography(from, to)
    if (!h) return

    const strip = warp(image, h, HEADER, TRY_WIDTH, tryHeight)
    rough.push({ score: gridScore(strip), h, fix: null })

    const fix = gridFix(strip, HEADER)
    if (!fix) return
    const window = fixed(HEADER, fix)
    rough.push({
      score: gridScore(warp(image, h, window, TRY_WIDTH, tryHeight)),
      h,
      fix,
    })
  }

  for (const quad of candidates) {
    for (let turn = 0; turn < 4; turn += 1) {
      const turned = quad.slice(turn).concat(quad.slice(0, turn))
      consider(
        nominal,
        turned.map((point) => ({ x: point.x * small.step, y: point.y * small.step })),
      )
    }
  }

  /*
   * Кандидаты по полосе меток вокруг шапки.
   *
   * Углов листа может не быть — нижняя пара пропадает первой, — а шапку
   * обнимают ещё четыре метки, и напечатаны они ровно для этого. Выпрямление
   * по ним даже точнее: полоса и есть то, что мы читаем, а ошибка гомографии
   * растёт с расстоянием от опор.
   *
   * Поворотов тут два, а не четыре: полоса лежачая, и на бок её не кладут —
   * страница бывает вверх ногами, но не поперёк себя.
   */
  for (const { corners, band } of bands(marks, small)) {
    const nominal = [
      { x: BAND_LEFT, y: band.top },
      { x: BAND_RIGHT, y: band.top },
      { x: BAND_RIGHT, y: band.bottom },
      { x: BAND_LEFT, y: band.bottom },
    ]
    for (const turn of [0, 2]) {
      const turned = corners.slice(turn).concat(corners.slice(0, turn))
      consider(
        nominal,
        turned.map((point) => ({ x: point.x * small.step, y: point.y * small.step })),
      )
    }
  }

  /*
   * И последний кандидат: **лист просто лежит ровно**.
   *
   * Метки — приближение, и на сканере они не нужны вовсе: страница уже
   * выпрямлена, край листа совпадает с краем картинки. А поиск меток на такой
   * странице умеет ошибаться: найдя не ту четвёрку, он строит перекошенную
   * гомографию, набирает 7 из 12 и объявляет лист «не нашим». На живой пачке
   * так пропали три страницы, из которых две прочитались бы глазами без
   * усилий — на экране они были ровные и чистые.
   *
   * Испортить она ничего не может — выбор идёт по тому же счёту, и побеждает
   * она только там, где сетка действительно сошлась лучше. Повороты те же
   * четыре: страница из сканера бывает и вверх ногами.
   */
  const page = [
    { x: 0, y: 0 },
    { x: PAGE.width, y: 0 },
    { x: PAGE.width, y: PAGE.height },
    { x: 0, y: PAGE.height },
  ]
  const frame = [
    { x: 0, y: 0 },
    { x: image.width, y: 0 },
    { x: image.width, y: image.height },
    { x: 0, y: image.height },
  ]
  for (let turn = 0; turn < 4; turn += 1) {
    consider(page, frame.slice(turn).concat(frame.slice(0, turn)))
  }

  if (!rough.length) return null

  const best = rough.reduce((one, two) => (two.score > one.score ? two : one))

  return {
    ...best,
    // наш бланк доказывают двое, и хватает любого: код в углу поля записи и
    // сама сетка баллов, вставшая на печатные места
    ours: hasBlankMark(image, best.h, best.fix) || best.score >= GRID_IS_OURS,
    // ищем по HEADER, а режем по STRIP: счёт считается там, где выпрямление
    // подпёрто метками, а картинка берётся от верха листа
    strip: warp(image, best.h, fixed(STRIP, best.fix), STRIP_WIDTH, stripHeight()),
  }
}

/**
 * Ниже этого счёта полоска не считается прочитанной шапкой.
 *
 * Шестнадцать клеток дают семнадцать границ, и на хорошем снимке находятся все.
 * Двенадцать — это уже страница, у которой часть сетки съел блик или обрез;
 * читать её можно, а вот меньше двенадцати значит, что мы смотрим не туда.
 */
export const ENOUGH_LINES = 12

/**
 * Счёт, при котором сетка сама доказывает, что бланк наш.
 *
 * Доказательством этого был только код в углу — и стоит он **внизу** листа, в
 * поле записи. Обрезал скан низ, загнулся угол, лёг лист не целиком — и
 * доказательства нет, при том что шапка на месте и читается. На живой пачке
 * такие страницы уезжали в «листы условий» и разрезали пачку надвое.
 *
 * Между тем шестнадцать клеток по 11.5625 мм на базе 185 мм, вставшие **все**
 * на печатные места после подгонки, — это не совпадение и не тень: у чужого
 * листа так не выходит. Поэтому почти полная сетка считается такой же печатью,
 * как код в углу, и доказывается она по той самой полоске, которую мы и так
 * кропаем.
 *
 * Порог высокий нарочно: у порога чтения (12) запас на блик и обрез, а здесь
 * речь о признаке, по которому лист объявляется нашим.
 */
export const GRID_IS_OURS = 16

/**
 * Разрезать выпрямленную шапку на то, из чего собирается картинка для чтения:
 * строку имени и шестнадцать клеток по отдельности.
 *
 * Резать по гомографии — значит не спрашивать модель о том, что уже
 * посчитано. Где кончается Q14 и начинается Q15, известно с точностью до
 * миллиметра; на глаз же это и ошибалось — балл из Q15 уезжал в сумму, а вся
 * строка съезжала на клетку влево, причём в разные стороны на разных
 * страницах.
 *
 * Разрешение клетки берётся под её натуральную величину: клетка бланка
 * 11.5 × 11.5 мм, страница рисуется примерно в десять точек на миллиметр, и
 * больше ста двадцати точек на клетку взять просто неоткуда.
 */
export const CELL_SIDE = 120

export function cutForReading(image, h, fix = null) {
  const row = fixed(nameRow(), fix)
  const rowHeight = Math.round((STRIP_WIDTH * row.height) / row.width)
  return {
    name: warp(image, h, row, STRIP_WIDTH, rowHeight),
    cells: Array.from({ length: GRID.cells }, (_, index) =>
      warp(image, h, fixed(cellRect(index), fix), CELL_SIDE, CELL_SIDE),
    ),
  }
}

export { HEADER, headerCorners }

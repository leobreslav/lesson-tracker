/**
 * Геометрия просмотрщика: где на экране лежит точка, записанная долями.
 *
 * Отдельный модуль без единого обращения к DOM — по тому же правилу, что и
 * `calendarLogic.js` со `scheduleLogic.js`: тут считаются числа, а числа
 * должны быть под тестами. Ошибка здесь выглядит не как поломка, а как
 * пометка, стоящая рядом с ошибкой ученика, — и заметит её ученик.
 *
 * Одно решение объясняет весь модуль. **Пометки хранятся в осях исходной,
 * неповёрнутой картинки** (см. `works.PhotoStroke`), а видит человек её
 * повёрнутой и увеличенной. Значит между «где записано» и «где нарисовано»
 * стоит преобразование, и оно должно быть ровно одно, обратимое: тем же
 * кодом мазок кладётся на холст и тем же — палец на экране превращается в
 * долю. Два кода для двух направлений разъехались бы молча, а выглядело бы
 * это как «рисую здесь, появляется рядом».
 */

/** Четыре положения, и пятого нет: поворот — это про «боком снято». */
export const TURNS = [0, 90, 180, 270]

/**
 * Повернуть на четверть в ту или иную сторону.
 *
 * Считается по кругу, а не прибавлением с проверкой границ: 270 + 90 это 0,
 * а не «дальше некуда». Кнопка, которая на четвёртом нажатии перестаёт
 * работать, читается как сломанная.
 */
export function turn(rotation, direction) {
  const step = direction === 'ccw' ? -90 : 90
  return (((rotation + step) % 360) + 360) % 360
}

/** Размер картинки после поворота: у четверти стороны меняются местами. */
export function rotatedSize({ width, height }, rotation) {
  return rotation % 180 === 0
    ? { width, height }
    : { width: height, height: width }
}

/**
 * Куда и в каком размере ложится картинка внутри отведённой ей рамки.
 *
 * Вписывается она целиком (`min` по сторонам), а не по ширине: тетрадь
 * снимают и вдоль, и поперёк, и подгонка по одной стороне у половины
 * снимков уводила бы низ за край. Увеличение — множитель поверх вписанного,
 * поэтому «единица» всегда значит «видно всё», на любом экране.
 */
export function layout({ box, image, rotation = 0, zoom = 1, pan = { x: 0, y: 0 } }) {
  const turned = rotatedSize(image, rotation)

  if (!turned.width || !turned.height || !box.width || !box.height) {
    return { scale: 0, width: 0, height: 0, left: 0, top: 0 }
  }

  const fit = Math.min(box.width / turned.width, box.height / turned.height)
  const scale = fit * zoom
  const width = turned.width * scale
  const height = turned.height * scale

  return {
    scale,
    width,
    height,
    left: (box.width - width) / 2 + pan.x,
    top: (box.height - height) / 2 + pan.y,
  }
}

/**
 * Доля исходной картинки → доля повёрнутой.
 *
 * Поворот считается **по часовой стрелке**, как его и называет кнопка.
 * Проверять эту таблицу удобнее всего на углу: левый верхний угол исходника
 * (0, 0) после поворота на 90° оказывается правым верхним — то есть (1, 0).
 */
export function spin([x, y], rotation) {
  switch (((rotation % 360) + 360) % 360) {
    case 90:
      return [1 - y, x]
    case 180:
      return [1 - x, 1 - y]
    case 270:
      return [y, 1 - x]
    default:
      return [x, y]
  }
}

/** Обратный ход: доля повёрнутой → доля исходной. */
export function unspin([x, y], rotation) {
  switch (((rotation % 360) + 360) % 360) {
    case 90:
      return [y, 1 - x]
    case 180:
      return [1 - x, 1 - y]
    case 270:
      return [1 - y, x]
    default:
      return [x, y]
  }
}

/** Точка, записанная долями исходника, — в пиксели внутри рамки. */
export function toScreen(point, place, rotation = 0) {
  const [x, y] = spin(point, rotation)
  return { x: place.left + x * place.width, y: place.top + y * place.height }
}

/**
 * Пиксель внутри рамки — в доли исходника.
 *
 * Зажимается в границы **здесь**, а не на сервере, и это не спор с ним:
 * сервер отказывает, потому что доля вне картинки — признак ошибки в коде;
 * а палец, съехавший за край при рисовании, — обычное дело, и обрывать из-за
 * него мазок было бы хуже, чем прижать его к краю.
 */
export function toSource({ x, y }, place, rotation = 0) {
  if (!place.width || !place.height) return [0, 0]

  const inside = [(x - place.left) / place.width, (y - place.top) / place.height]
  return unspin(inside, rotation).map(clamp)
}

const clamp = (value) => Math.min(1, Math.max(0, value))

/**
 * Толщина пера в пикселях экрана.
 *
 * Хранится она в тысячных **ширины исходника** — на снимке с телефона перо,
 * заданное в пикселях, превращается в волосок, а на маленьком снимке в
 * кляксу. Считать её от ширины на экране нельзя по той же причине: тогда
 * один и тот же мазок был бы разной толщины до и после увеличения.
 */
export function penPixels(width, place, rotation = 0) {
  const along = rotation % 180 === 0 ? place.width : place.height
  return Math.max(1, (width / 1000) * along)
}

/**
 * Соседний снимок в наборе — или тот же, если набор из одного.
 *
 * По кругу намеренно: листают тут не список, а стопку тетрадей, и после
 * последней страницы человек ждёт первую, а не упор. Пустой набор ответа не
 * имеет, и `null` тут честнее нуля.
 */
export function step(list, current, direction) {
  if (!list.length) return null

  const at = list.findIndex((item) => item.id === current)
  const from = at === -1 ? 0 : at
  return list[(from + direction + list.length) % list.length]
}

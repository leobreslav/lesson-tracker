/**
 * Пачка сканов в браузере: страница за страницей, а не всё разом.
 *
 * Порядок работы на каждую страницу один и тот же: отрисовать её, вырезать
 * полоску шапки, отправить полоску на чтение. Три вещи это даёт бесплатно:
 * прогресс виден по-настоящему (а не «идёт загрузка»), сервер занят
 * секунду-другую вместо минут, и неудачная страница повторяется одна, а не вся
 * пачка. Прочитанное сервер кладёт в базу, поэтому закрытая вкладка не стоит
 * денег дважды.
 *
 * Разрешение рендера — не «побольше»: `RENDER_WIDTH` подобран так, чтобы после
 * выпрямления полоска вышла не мельче той, что уезжает на чтение. Больше
 * платить нечем — картинку всё равно ужимает Anthropic.
 */

import { GRID, MARKS, PAGE, STRIP_WIDTH, cellLabel, isMarkSheetCode, markCellLabel } from './blankGeometry'
import {
  ENOUGH_LINES,
  MARKS_ENOUGH,
  cutForReading,
  cutLabelledForReading,
  cutMarksForReading,
  extractHeader,
  extractMarks,
  findCodes,
  marksPlain,
} from './scanSheet'

/**
 * Ширина отрисовки страницы. Полоска занимает 190 мм из 210, и хочется, чтобы
 * в ней было около 1568 точек — значит страница должна быть чуть шире. Ещё
 * половина сверху заложена на перспективу: на снимке лист занимает не весь
 * кадр.
 */
export const RENDER_WIDTH = Math.round((STRIP_WIDTH * PAGE.width) / 190 / 0.75)

let loading = null

/** pdfjs грузится один раз и лениво: он большой, а нужен на одном экране. */
export async function pdfjs() {
  if (!loading) {
    loading = (async () => {
      const lib = await import('pdfjs-dist')
      lib.GlobalWorkerOptions.workerSrc = (
        await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
      ).default
      return lib
    })()
  }
  return loading
}

/** Открыть книгу и сказать, сколько в ней страниц. */
export async function openBook(file) {
  const lib = await pdfjs()
  const data = new Uint8Array(await file.arrayBuffer())
  return lib.getDocument({ data }).promise
}

/** Одна страница книги в пиксели. */
export async function drawPage(book, number, width = RENDER_WIDTH, turn = 0) {
  const page = await book.getPage(number)
  const first = page.getViewport({ scale: 1 })
  // `turn` — поворот, который человек задал руками на шаге разбора. Крутит его
  // pdfjs при отрисовке, а не мы после: страница перерисовывается из исходника,
  // и качества на повороте не теряется ни на йоту.
  const viewport = page.getViewport({ scale: width / first.width, rotation: turn })

  const canvas = document.createElement('canvas')
  canvas.width = viewport.width
  canvas.height = viewport.height
  const context = canvas.getContext('2d', { willReadFrequently: true })

  // Холст начинается прозрачным, а прозрачное — это RGBA (0,0,0,0), то есть
  // чёрное для всякого, кто смотрит на каналы цвета. pdfjs фон не красит, и
  // непокрашенная бумага приезжала в детект чёрным листом: меток на нём не
  // находилось вовсе. В node этого не увидеть: там картинку рисуем мы сами.
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)

  await page.render({ canvasContext: context, viewport }).promise

  return {
    image: context.getImageData(0, 0, canvas.width, canvas.height),
    canvas,
  }
}

/** Картинка из наших пикселей обратно в canvas — чтобы отдать её как файл. */
export function toCanvas(image) {
  const canvas = document.createElement('canvas')
  canvas.width = image.width
  canvas.height = image.height
  const context = canvas.getContext('2d')
  context.putImageData(new ImageData(image.data, image.width, image.height), 0, 0)
  return canvas
}

/**
 * JPEG из холста, ужатый до длинной стороны.
 *
 * Больше 1568 точек посылать некуда: Anthropic ужмёт сам, а трафик и время
 * загрузки мы заплатим. Полоска в этот предел укладывается по построению, а
 * страница условий — нет.
 */
export function scaledJpeg(canvas, maxSide = STRIP_WIDTH, quality = 0.8) {
  const scale = Math.min(1, maxSide / Math.max(canvas.width, canvas.height))
  const small = document.createElement('canvas')
  small.width = Math.round(canvas.width * scale)
  small.height = Math.round(canvas.height * scale)
  small.getContext('2d').drawImage(canvas, 0, 0, small.width, small.height)
  return new Promise((resolve) => small.toBlob(resolve, 'image/jpeg', quality))
}

/*
 * Плитка клетки: подпись слева, сама клетка справа.
 *
 * Колонок шесть, а не четыре, и это про **строку имени**. Ширину картинке
 * задаёт она: имя пишут поперёк всего листа, и режется оно в 1568 точек —
 * ровно столько, сколько оставляет от картинки Anthropic. Пока ширину задавали
 * плитки (четыре по 240 — 960 точек), строка имени ужималась под них и теряла
 * две пятых разрешения. Выходило это худшим из возможных способов: «Варвара
 * Миронова» читалась как «Варварец Лосеводь», то есть страница честно уходила
 * к человеку, хотя на бумаге имя написано разборчиво.
 */
const TILE_COLUMNS = 6
const TILE = { width: Math.floor(STRIP_WIDTH / TILE_COLUMNS), height: 128, label: 74, pad: 4 }

/**
 * Картинка, которая уезжает на чтение: строка имени и шестнадцать плиток.
 *
 * **Выравнивать модели больше нечего, и в этом весь смысл.** Полоска шапки —
 * это шестнадцать узких колонок на картинке пять к одному, и чтобы сказать
 * «тройка стоит под Q15», модель должна пройти взглядом вдоль всей строки и
 * не сбиться. Она сбивалась: на одной странице балл из Q15 уезжал в сумму, на
 * другой вся строка съезжала на клетку влево. Схема с подписями («назови
 * клетку, а не место») это уменьшила, но не убрала — потому что задача
 * осталась той же.
 *
 * Между тем ответ у нас уже посчитан: гомография знает с точностью до
 * миллиметра, где кончается Q14 и начинается Q15. Поэтому клетки режет
 * браузер, а рядом с каждой **мы сами** рисуем её имя. Модели остаётся
 * прочесть цифру в квадратике — то, что она делает хорошо.
 *
 * Подпись рисуется красным и снаружи клетки: спутать её с напечатанным на
 * бланке нечем, и внутрь клетки она не залезает.
 */
export function readingSheet(image, h, fix = null) {
  const { name, cells } = cutForReading(image, h, fix)
  return assembled(name, cells, cellLabel)
}

/**
 * Картинка тестового алгоритма: у каждой плитки над клеткой — её полоса
 * подписи, как на бумаге. Красная метка по-прежнему называет **физическую**
 * клетку (`Q3`), а задачу называет вписанная подпись (`2b`): по ней сервер и
 * узнаёт, чей это балл (`scanning.match_label`).
 *
 * Плитка вдвое выше обычной, поэтому колонок восемь: шестнадцать плиток
 * встают в два ряда, и картинка не вытягивается в высоту.
 */
export function labelledSheet(image, h, fix = null) {
  const { name, cells, labels } = cutLabelledForReading(image, h, fix)
  const columns = 8
  const side = TILE.height - TILE.pad * 2
  const tile = { width: Math.floor(STRIP_WIDTH / columns), height: side * 2 + TILE.pad * 3 }
  const rows = Math.ceil(cells.length / columns)

  const canvas = document.createElement('canvas')
  canvas.width = Math.max(name.width, tile.width * columns)
  canvas.height = name.height + rows * tile.height
  const context = canvas.getContext('2d')
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(toCanvas(name), 0, 0)

  context.font = 'bold 26px sans-serif'
  context.textBaseline = 'middle'
  cells.forEach((cell, index) => {
    const left = (index % columns) * tile.width
    const top = name.height + Math.floor(index / columns) * tile.height

    context.strokeStyle = '#000'
    context.lineWidth = 1
    context.strokeRect(left + 0.5, top + 0.5, tile.width - 1, tile.height - 1)

    context.fillStyle = '#c00'
    context.fillText(cellLabel(index), left + TILE.pad * 2, top + tile.height / 2)

    context.drawImage(toCanvas(labels[index]), left + TILE.label, top + TILE.pad, side, side)
    context.drawImage(toCanvas(cell), left + TILE.label, top + TILE.pad * 2 + side, side, side)
  })

  return canvas
}

/*
 * У листа баллов плиток больше — до девяноста шести, — и в шесть колонок они
 * вытянули бы картинку в три с лишним раза выше ширины, а Anthropic ужал бы её
 * по длинной стороне вместе со строкой имени. В восемь колонок плитка всё ещё
 * вмещает подпись и клетку (74 + 120 точек).
 */
const MARK_COLUMNS = 8

/**
 * Картинка листа баллов на чтение: строка имени и плитки нужных клеток,
 * каждая со своей подписью — `Q23`, а не «восьмая во второй строке».
 */
export function marksSheet(image, found, indexes) {
  const { name, cells } = cutMarksForReading(image, found, indexes)
  return assembled(name, cells, (at) => markCellLabel(indexes[at]), MARK_COLUMNS)
}

function assembled(name, cells, labelOf, columns = TILE_COLUMNS) {
  const tile = { ...TILE, width: Math.floor(STRIP_WIDTH / columns) }

  // строка имени идёт в свою натуральную величину, без ужатия
  const nameHeight = name.height
  const rows = Math.ceil(cells.length / columns)

  const canvas = document.createElement('canvas')
  canvas.width = Math.max(name.width, tile.width * columns)
  canvas.height = nameHeight + rows * tile.height
  const context = canvas.getContext('2d')
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)

  context.drawImage(toCanvas(name), 0, 0)

  context.font = 'bold 26px sans-serif'
  context.textBaseline = 'middle'
  cells.forEach((cell, index) => {
    const left = (index % columns) * tile.width
    const top = nameHeight + Math.floor(index / columns) * tile.height

    context.strokeStyle = '#000'
    context.lineWidth = 1
    context.strokeRect(left + 0.5, top + 0.5, tile.width - 1, tile.height - 1)

    context.fillStyle = '#c00'
    context.fillText(labelOf(index), left + tile.pad * 2, top + tile.height / 2)

    const side = tile.height - tile.pad * 2
    context.drawImage(toCanvas(cell), left + tile.label, top + tile.pad, side, side)
  })

  return canvas
}

/**
 * Короткий отпечаток полоски: та же страница не перечитывается второй раз.
 *
 * Обычный хеш, а не `crypto.subtle`: тот живёт только в защищённом контексте,
 * и там, где приложение открыто по имени контейнера, его нет вовсе —
 * страница падала с «Cannot read properties of undefined». Защищать тут
 * нечего: это ключ кэша, и цена совпадения — одно лишнее чтение.
 */
export async function fingerprint(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  let hash = 0x811c9dc5
  for (let i = 0; i < bytes.length; i += 1) {
    hash ^= bytes[i]
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return `${bytes.length.toString(16)}-${hash.toString(16)}`
}

/**
 * Пройти пачку целиком.
 *
 * `onPage` зовётся после каждой страницы — им и рисуется прогресс. Страница,
 * на которой не нашлось шапки, не прерывает работу и не стоит денег: про неё
 * сообщается отдельно (`blank`), потому что обычно это лист условий, а ряд
 * таких листов размечает пачку. Прерывает только `stop`.
 */
/**
 * Разобрать одну страницу: нарисовать, вырезать шапку, отправить на чтение.
 *
 * Вынесено из `walk` затем, что ровно то же самое нужно **повороту**: человек
 * увидел страницу вверх ногами, нажал перевернуть — и она проходит тот же путь
 * заново, только с другим углом. Двух копий этого пути быть не должно: они
 * разойдутся молча, и половина пачки станет читаться иначе, чем другая.
 */
export async function readPage(
  book,
  number,
  {
    send,
    blank,
    questions,
    tasks = 0,
    turn = 0,
    first = false,
    namesOnly = false,
    byLabels = false,
  } = {},
) {
  const { image, canvas } = await drawPage(book, number, RENDER_WIDTH, turn)

  // Коды декодируются один раз на страницу, и первым делом: по их содержимому
  // видно, бланк это или лист баллов, а читаются они по разной геометрии.
  // Шапке бланка найденный код передаётся готовым — звать декодер второй раз
  // за тем же самым незачем.
  const codes = findCodes(image)
  const markCode = codes.find((one) => isMarkSheetCode(one.payload))
  if (markCode) {
    return readMarkSheet(image, canvas, markCode, { index: number - 1, send, blank, tasks, turn })
  }

  const found = extractHeader(image, codes[0] ?? null)
  const enough = found && found.score >= ENOUGH_LINES

  const page = {
    index: number - 1,
    score: found?.score ?? 0,
    // порог едет вместе со счётом: человеку показывают «12 из 17 границ», а
    // не голое число, и порог для этого нужен там же, где счёт
    need: ENOUGH_LINES,
    enough,
    turn,
    // метка в углу: наш лист или чужой. У листа без меток гомографии нет
    // вовсе, а значит и смотреть негде — такой лист не наш по определению
    ours: Boolean(found?.ours),
    // Код бланка, если декодер его нашёл. Отдельно от `ours`, потому что это
    // разные свидетельства: код доказывает лист сам по себе, а `ours`
    // складывается ещё и из сетки. Разделителем пачки служит именно код —
    // на листе условий его нет.
    code: found?.code?.payload ?? null,
    preview: canvas.toDataURL('image/jpeg', 0.5),
    strip: found ? toCanvas(found.strip).toDataURL('image/jpeg', 0.8) : null,
  }

  /*
   * Читаем, если сетка сошлась **или** нашлась наша метка в углу.
   *
   * Метка — признак твёрдый, и твёрже сетки: код в углу поля записи стоит
   * только на нашем бланке, а раз бланк наш, то шапка на нём **есть** — это
   * не вопрос и не оценка вероятности, это печать. Проверяется она уже
   * после выпрямления, той же гомографией, которой режется полоска; значит
   * найденная метка заодно говорит, что выпрямление годное.
   *
   * Пока читали только по счёту сетки, лист с нашим кодом и подпорченной
   * сеткой (блик, обрез, бледная печать) не читался вовсе — при том, что
   * про него было точно известно, что читать там есть что.
   */
  const worthReading = enough || page.ours
  // экрану нужен тот же ответ, что и циклу: показывать полоску или сказать,
  // что выпрямить не удалось
  page.readable = worthReading

  if (worthReading && send) {
    /*
     * Уезжают **две** картинки одной и той же шапки, и это не расточительство.
     *
     * `blob` — собранный лист: строка имени и шестнадцать плиток с нашими
     * подписями. По нему читают клетки: языковая модель без подписей сбивается
     * со счёта, а Mathpix на голой полоске не видит ни одной цифры вовсе.
     *
     * `plain` — та же шапка как на бумаге. По ней читают **имя**, и разница
     * измерена живой пачкой: распознаватель на собранном листе склеивает
     * строку имени с первым рядом плиток — «Миронова» приезжала как
     * «Леилонова», «Тимур Кузнецов» как «иму Кузнецов». На полоске те же
     * страницы читаются верно.
     *
     * Отпечаток берётся по собранному листу: он же ключ кэша, и по нему
     * страница узнаётся, чтобы не платить второй раз. Перевёрнутая страница
     * даёт другую картинку и другой отпечаток — значит читается заново, и это
     * честно: за неё и правда платят второй раз, ради верного чтения.
     */
    // Тестовый алгоритм — своя картинка: клетка вместе с подписью над ней.
    // Отпечаток у неё свой, и это честно: прочитанное прежним алгоритмом
    // клеткам по подписям не отвечает, и кэш его не отдаст
    const full = await scaledJpeg(
      byLabels
        ? labelledSheet(image, found.h, found.fix)
        : readingSheet(image, found.h, found.fix),
      1568,
      0.9,
    )
    const plain = await scaledJpeg(toCanvas(found.strip), 1568, 0.9)
    /*
     * В пачке уже был лист баллов — значит баллы ставили на нём, и клетки
     * этого бланка не в счёт (`scanning.marks_rule`). Читать их — платить за
     * выброшенное, поэтому уезжает одна строка имени.
     *
     * **Отпечаток при этом — по полной картинке**, как всегда. Он ключ кэша:
     * посчитай его по укороченной, и вернувшийся к пачке человек заплатил бы
     * второй раз за все страницы, прочитанные целиком в прошлый заход.
     */
    const blob = namesOnly
      ? await scaledJpeg(toCanvas(cutForReading(image, found.h, found.fix).name), 1568, 0.9)
      : full
    page.sent = await send({
      index: page.index,
      blob,
      plain,
      mark: await fingerprint(full),
      cells: !namesOnly,
      // клеток бланка не в счёт — и подписям над ними стоять не над чем
      labels: byLabels && !namesOnly,
    })
  } else if (!worthReading && blank) {
    // Шапки нет — читать нечего и платить не за что, но сказать серверу
    // надо: ряд таких листов размечает пачку, и без них он не увидит, где
    // кончается работа одного ученика и начинается другого.
    await blank(page.index, page.ours)

    /* Условия читаются **один раз на пачку**, и только по просьбе. Их
       раздают одинаковыми, поэтому второй экземпляр ничего нового не
       скажет, а стоит страница условий заметно дороже полоски шапки:
       читается целиком и моделью посерьёзнее. Первый ряд — тот, что идёт
       до первого прочитанного листа. */
    if (questions && first) {
      page.questions = await questions(await scaledJpeg(canvas))
    }
  }

  return page
}

/**
 * Лист баллов: прочитать имя и клетки задач работы.
 *
 * Свой путь, а не ветка внутри шапки бланка: геометрия другая целиком — шесть
 * линеек вместо одной, коды вверху, строка имени в клетках, — и общего у них
 * только устройство картинки на чтение (`assembled`).
 *
 * `tasks` — сколько задач в работе: столько плиток и поедет, плюс сумма.
 * Работа без заведённых задач читается всеми девяноста пятью — лучше лишние
 * пустые плитки, чем потерянный балл.
 *
 * Читается, если код нашёлся на своём месте хоть при каком-нибудь выпрямлении,
 * — как бланк с найденным кодом (`readPage`): лист наш, и читать на нём есть
 * что, даже если сетка сошлась хуже порога. Не сошлось ничего — лист всё
 * равно записывается листом баллов: и непрочитанный, он решает, откуда в
 * пачке берутся баллы.
 */
async function readMarkSheet(image, canvas, code, { index, send, blank, tasks, turn }) {
  const found = extractMarks(image, code)
  const questions = tasks > 0 ? Math.min(tasks, MARKS.questions) : MARKS.questions
  const indexes = [...Array(questions).keys(), MARKS.questions]
  const sheet = found ? marksSheet(image, found, indexes) : null

  const page = {
    index,
    sheet: 'marks',
    score: found?.score ?? 0,
    need: MARKS_ENOUGH,
    enough: Boolean(found && found.score >= MARKS_ENOUGH),
    turn,
    ours: true,
    code: code.payload,
    preview: canvas.toDataURL('image/jpeg', 0.5),
    // экрану показывается собранная картинка, а не полоска: шесть линеек
    // в одну полоску не лягут, а плитки подписаны теми же Q23, что и поля
    strip: sheet ? sheet.toDataURL('image/jpeg', 0.8) : null,
    readable: Boolean(found),
  }

  if (found && send) {
    const lastRow = Math.floor((questions - 1) / GRID.cells)
    const blob = await scaledJpeg(sheet, 1568, 0.9)
    const plain = await scaledJpeg(toCanvas(marksPlain(image, found, lastRow)), 1568, 0.9)
    page.sent = await send({ index, blob, plain, mark: await fingerprint(blob), sheet: 'marks' })
  } else if (!found && blank) {
    await blank(index, true, 'marks')
  }
  return page
}

/**
 * С первого листа баллов бланки читаются одной строкой имени, до конца пачки.
 *
 * Лист баллов значит, что у работы задач больше, чем клеток на бланке, и
 * клетки бланков не в счёт ни у кого (`scanning.marks_rule`) — читать их
 * значит платить за выброшенное. Имя же читать надо: по нему узнаётся, что
 * начался чужой лист. Галочки на это не нужно, пачка говорит сама.
 *
 * Пачку складывают всегда одинаково — условия, лист баллов, бланки, блок на
 * ученика, — поэтому лист баллов встречается раньше любого бланка, и ни одна
 * выброшенная клетка не оплачивается. Вернувшемуся к пачке помнить ничего не
 * надо: обход снова идёт по всем страницам, прочитанные отдаются из кэша.
 */
export async function walk(
  file,
  { onPage, send, blank, questions, tasks = 0, byLabels = false, stop } = {},
) {
  const book = await openBook(file)
  const pages = []
  // первый ряд условий — тот, что встретился до первого листа решения
  let seenAnswer = false
  let marks = false

  for (let number = 1; number <= book.numPages; number += 1) {
    if (stop?.()) break

    const page = await readPage(book, number, {
      send,
      blank,
      questions,
      tasks,
      first: !seenAnswer,
      namesOnly: marks,
      byLabels,
    })
    const worthReading = page.readable

    if (worthReading) seenAnswer = true
    if (page.sheet === 'marks') marks = true

    pages.push(page)
    onPage?.(page, book.numPages)
  }

  return pages
}

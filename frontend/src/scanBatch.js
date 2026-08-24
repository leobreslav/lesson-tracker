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

import { GRID, PAGE, STRIP_WIDTH, cellLabel } from './blankGeometry'
import { ENOUGH_LINES, cutForReading, extractHeader } from './scanSheet'

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
export async function drawPage(book, number, width = RENDER_WIDTH) {
  const page = await book.getPage(number)
  const first = page.getViewport({ scale: 1 })
  const viewport = page.getViewport({ scale: width / first.width })

  const canvas = document.createElement('canvas')
  canvas.width = viewport.width
  canvas.height = viewport.height
  const context = canvas.getContext('2d', { willReadFrequently: true })

  // Холст начинается прозрачным, а прозрачное — это RGBA (0,0,0,0), то есть
  // чёрное для всякого, кто смотрит на каналы цвета. pdfjs фон не красит, и
  // непокрашенная бумага приезжала в детект чёрным листом: меток на нём не
  // находилось вовсе. Поймано браузерным тестом — в node этого не увидеть,
  // там картинку рисуем мы сами.
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
export function readingSheet(image, h) {
  const { name, cells } = cutForReading(image, h)

  // строка имени идёт в свою натуральную величину, без ужатия
  const nameHeight = name.height
  const rows = Math.ceil(cells.length / TILE_COLUMNS)

  const canvas = document.createElement('canvas')
  canvas.width = Math.max(name.width, TILE.width * TILE_COLUMNS)
  canvas.height = nameHeight + rows * TILE.height
  const context = canvas.getContext('2d')
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)

  context.drawImage(toCanvas(name), 0, 0)

  context.font = 'bold 26px sans-serif'
  context.textBaseline = 'middle'
  cells.forEach((cell, index) => {
    const left = (index % TILE_COLUMNS) * TILE.width
    const top = nameHeight + Math.floor(index / TILE_COLUMNS) * TILE.height

    context.strokeStyle = '#000'
    context.lineWidth = 1
    context.strokeRect(left + 0.5, top + 0.5, TILE.width - 1, TILE.height - 1)

    context.fillStyle = '#c00'
    context.fillText(cellLabel(index), left + TILE.pad * 2, top + TILE.height / 2)

    const side = TILE.height - TILE.pad * 2
    context.drawImage(toCanvas(cell), left + TILE.label, top + TILE.pad, side, side)
  })

  return canvas
}

/**
 * Короткий отпечаток полоски: та же страница не перечитывается второй раз.
 *
 * Обычный хеш, а не `crypto.subtle`: тот живёт только в защищённом контексте,
 * и на стенде, где приложение открыто по имени контейнера, его нет вовсе —
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
export async function walk(file, { onPage, send, blank, questions, stop } = {}) {
  const book = await openBook(file)
  const pages = []
  // первый ряд условий — тот, что встретился до первого листа решения
  let seenAnswer = false

  for (let number = 1; number <= book.numPages; number += 1) {
    if (stop?.()) break

    const { image, canvas } = await drawPage(book, number)
    const found = extractHeader(image)
    const enough = found && found.score >= ENOUGH_LINES

    const page = {
      index: number - 1,
      score: found?.score ?? 0,
      // порог едет вместе со счётом: человеку показывают «12 из 17 границ», а
      // не голое число, и порог для этого нужен там же, где счёт
      need: ENOUGH_LINES,
      enough,
      // метка в углу: наш лист или чужой. У листа без меток гомографии нет
      // вовсе, а значит и смотреть негде — такой лист не наш по определению
      ours: Boolean(found?.ours),
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
      // на чтение уезжает не полоска, а собранная из неё картинка: строка
      // имени и шестнадцать плиток с нашими подписями
      const blob = await scaledJpeg(readingSheet(image, found.h), 1568, 0.9)
      page.sent = await send({
        index: page.index,
        blob,
        mark: await fingerprint(blob),
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
      if (questions && !seenAnswer) {
        page.questions = await questions(await scaledJpeg(canvas))
      }
    }

    if (worthReading) seenAnswer = true

    pages.push(page)
    onPage?.(page, book.numPages)
  }

  return pages
}

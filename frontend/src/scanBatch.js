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

import { PAGE, STRIP_WIDTH } from './blankGeometry'
import { ENOUGH_LINES, extractHeader } from './scanSheet'

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

/** JPEG из картинки: полоска уезжает на сервер именно так. */
export function toJpeg(image, quality = 0.88) {
  return new Promise((resolve) =>
    toCanvas(image).toBlob((blob) => resolve(blob), 'image/jpeg', quality),
  )
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
export async function walk(file, { onPage, send, blank, stop } = {}) {
  const book = await openBook(file)
  const pages = []

  for (let number = 1; number <= book.numPages; number += 1) {
    if (stop?.()) break

    const { image, canvas } = await drawPage(book, number)
    const found = extractHeader(image)
    const enough = found && found.score >= ENOUGH_LINES

    const page = {
      index: number - 1,
      score: found?.score ?? 0,
      enough,
      preview: canvas.toDataURL('image/jpeg', 0.5),
      strip: found ? toCanvas(found.strip).toDataURL('image/jpeg', 0.8) : null,
    }

    if (enough && send) {
      const blob = await toJpeg(found.strip)
      page.sent = await send({
        index: page.index,
        blob,
        mark: await fingerprint(blob),
      })
    } else if (!enough && blank) {
      // Шапки нет — читать нечего и платить не за что, но сказать серверу
      // надо: ряд таких листов размечает пачку, и без них он не увидит, где
      // кончается работа одного ученика и начинается другого.
      await blank(page.index)
    }

    pages.push(page)
    onPage?.(page, book.numPages)
  }

  return pages
}

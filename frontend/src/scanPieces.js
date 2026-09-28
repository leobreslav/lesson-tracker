/**
 * Нарезка пачки по ученикам и сборка работ обратно в один файл.
 *
 * Режет браузер, и это решение выросло из живой пачки. Скан класса весит от
 * тридцати до двухсот мегабайт — двадцать два ученика по семь двусторонних
 * листов в трёхстах точках, — а сервер принимает запрос в двадцать пять и
 * держит два воркера на весь прод. Целиком пачка до него не доезжает, да и
 * незачем: страницы браузер и так открывает, а кому какая досталась, знает
 * от сервера. Поэтому на сервер едут готовые работы, по несколько мегабайт.
 *
 * **Страницы копируются, а не перерисовываются.** Перерисовка в картинку
 * сжала бы файл, но испортила бы его: учитель сканирует в трёхстах точках не
 * затем, чтобы мы отдали ученику сто пятьдесят. Копия объекта страницы
 * качества не трогает вовсе и делается на порядок быстрее отрисовки.
 *
 * Слов здесь нет, только байты и числа: модуль под узловыми тестами.
 */

/**
 * Потолок на один файл. Сервер хранит до двадцати мегабайт; запас оставлен
 * на то, что считаем мы размер куска после сборки, а режем до неё.
 */
export const PIECE_LIMIT = 18 * 1024 * 1024

let loading = null

/** Библиотека грузится лениво: нужна она одному мастеру сканов из всех экранов. */
const lib = () => {
  loading ??= import('pdf-lib')
  return loading
}

/** Страница, которой в файле нет: выбран не тот файл, что читали. */
export class PageOutside extends Error {
  constructor(index, pages) {
    super(`page ${index + 1} is outside the file, which has ${pages}`)
    this.code = 'page_outside'
    this.index = index
    this.pages = pages
  }
}

/** Открыть пачку для нарезки. */
export async function openSource(bytes) {
  const { PDFDocument } = await lib()
  // сканеры нередко ставят на файл пустой пароль владельца: читать такой
  // можно, а без флага библиотека отказалась бы его открыть
  return PDFDocument.load(bytes, { ignoreEncryption: true })
}

/**
 * Страницы одного ученика — решения вместе с условиями, по порядку пачки.
 *
 * Условия едут в работу ученика вместе с решением: без них он открывает свои
 * ответы без вопросов. По номерам они встают в начало сами — раздают их перед
 * работой, значит и в стопке они лежат раньше.
 *
 * Повторы убираются: слияние пакетов складывает их условия списком, и один
 * лист может быть назван дважды.
 */
export const pagesOf = (packet) =>
  [...new Set([...(packet.conditions ?? []), ...(packet.pages ?? [])])].sort(
    (one, two) => one - two,
  )

/** Названные страницы пачки — отдельным файлом. Номера от нуля. */
export async function cut(source, indices) {
  const { PDFDocument } = await lib()
  const pages = source.getPageCount()
  const outside = indices.find((index) => index < 0 || index >= pages)
  if (outside !== undefined) throw new PageOutside(outside, pages)

  // Без метаданных: библиотека вписывает в файл время сборки, и тот же
  // кусок, собранный дважды, выходил бы разными байтами. Сервер узнаёт
  // повтор по содержимому — с разными байтами оборвавшийся и продолженный
  // разбор оставил бы ученику две копии одной работы.
  const piece = await PDFDocument.create({ updateMetadata: false })
  const copied = await piece.copyPages(source, indices)
  copied.forEach((page) => piece.addPage(page))
  return piece.save({ updateFieldAppearances: false })
}

/**
 * Работа ученика — одним файлом, а если он тяжелее предела, то несколькими.
 *
 * Делится пополам и так до тех пор, пока кусок не пройдёт. Одна страница
 * тяжелее предела не делится — отдаём как есть, и отказ сервера скажет об
 * этом своими словами: молча выбросить страницу было бы хуже отказа.
 */
export async function pieces(source, indices, limit = PIECE_LIMIT) {
  if (!indices.length) return []

  const whole = await cut(source, indices)
  if (whole.length <= limit || indices.length === 1) return [whole]

  const half = Math.ceil(indices.length / 2)
  return [
    ...(await pieces(source, indices.slice(0, half), limit)),
    ...(await pieces(source, indices.slice(half), limit)),
  ]
}

/**
 * Несколько файлов — одним, в том порядке, в каком их дали.
 *
 * Так собираются «все работы одним PDF»: на сервере этот файл не лежит, его
 * складывает браузер из работ учеников в момент, когда о нём попросили.
 * `onStep` зовётся после каждого файла — сборка двадцати работ идёт секунды,
 * и молчащая кнопка читалась бы как сломанная.
 */
export async function join(files, onStep = () => {}) {
  const { PDFDocument } = await lib()
  const book = await PDFDocument.create({ updateMetadata: false })

  let done = 0
  for (const bytes of files) {
    const one = await PDFDocument.load(bytes, { ignoreEncryption: true })
    const copied = await book.copyPages(one, one.getPageIndices())
    copied.forEach((page) => book.addPage(page))
    done += 1
    onStep(done, files.length)
  }

  return book.save({ updateFieldAppearances: false })
}

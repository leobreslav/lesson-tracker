/**
 * Страница PDF, нарисованная в холст, — источник для просмотрщика работ.
 *
 * Просмотрщик умеет ровно одно: взять что-нибудь с шириной, высотой и
 * пикселями и положить это на холст вместе с мазками (`PhotoViewer`,
 * `photoGeometry`). Картинка это умеет сама; PDF не умеет вовсе — тегом его
 * не покажешь. Поэтому здесь он превращается в то же самое: холст с готовыми
 * пикселями, который дальше идёт по общей дороге.
 *
 * **Своя отрисовка, а не та, что в `scanBatch`.** Там книгу открывают из
 * файла, лежащего в руках у браузера, и режут страницы ради чтения шапок;
 * тут — из подписанной ссылки, ради показа. Общий у них ровно один вызов —
 * ленивая загрузка `pdfjs`, и он из `scanBatch` и берётся: две загрузки
 * большой библиотеки на одну вкладку были бы двумя копиями в памяти.
 *
 * **Открытая книга помнится**, и это не украшение. Листающий учитель иначе
 * скачивал бы весь PDF заново на каждую страницу — по подписанной ссылке, с
 * чужого домена, при каждом нажатии «дальше».
 */

import { pdfjs } from './scanBatch'

/* Ширина отрисовки. Больше исходного разрешения бумаги смысла не имеет, а
 * меньше — видно на увеличении: просмотрщик умеет шестикратное, и страница,
 * нарисованная в ширину окна, на нём расплывётся. */
const WIDTH = 1600

// Открытые книги: ссылка на вложение -> обещание документа. Держим по одной
// на вложение, а не на страницу.
const open = new Map()

/** Открыть книгу по подписанной ссылке (или вернуть уже открытую). */
export function book(id, url) {
  const known = open.get(id)
  if (known) return known

  const loading = pdfjs().then((lib) => lib.getDocument({ url }).promise)
  loading.catch(() => open.delete(id))
  open.set(id, loading)
  return loading
}

/** Забыть книгу: вложение убрали или ссылка протухла. */
export function forget(id) {
  open.delete(id)
}

/**
 * Нарисовать страницу (с нуля) в новый холст.
 *
 * Возвращается холст, а не пиксели: просмотрщику нужен источник для
 * `drawImage`, и холст им работает наравне с картинкой. Заодно у него есть
 * `width`/`height` — те же поля, по которым считается раскладка.
 */
export async function drawPageOf(document, page) {
  const sheet = await document.getPage(page + 1)
  const first = sheet.getViewport({ scale: 1 })
  const viewport = sheet.getViewport({ scale: WIDTH / first.width })

  const canvas = window.document.createElement('canvas')
  canvas.width = Math.round(viewport.width)
  canvas.height = Math.round(viewport.height)
  const context = canvas.getContext('2d')

  // Холст начинается прозрачным, а прозрачное — это чёрное для всякого, кто
  // смотрит на каналы цвета; pdfjs фона не красит. На белой бумаге это видно
  // сразу — та же ловушка, что поймана в разборе сканов.
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)

  await sheet.render({ canvasContext: context, viewport }).promise
  return canvas
}

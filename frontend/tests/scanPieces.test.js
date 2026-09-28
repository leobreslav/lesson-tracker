/**
 * Нарезка пачки по ученикам.
 *
 * Под тестами потому, что ошибка тут молчит и дорого стоит: страница,
 * попавшая не в тот кусок, — это чужая контрольная с отметками у
 * одноклассника. Раньше резал сервер, и проверял это питоновский набор;
 * теперь режет браузер, и сторож переехал сюда вместе с работой.
 *
 * Страницы пачки различаются шириной: страница номер `n` шириной `100 + n`
 * точек. Так по готовому куску видно, какие страницы в него попали и в каком
 * порядке, — не заглядывая в содержимое.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import { PDFDocument } from 'pdf-lib'

import { PageOutside, cut, join, openSource, pagesOf, pieces } from '../src/scanPieces.js'

/** Пачка из `count` страниц; у страницы `n` ширина `100 + n`. */
async function pile(count, { heavy = 0 } = {}) {
  const book = await PDFDocument.create()
  for (let index = 0; index < count; index += 1) {
    const page = book.addPage([100 + index, 200])
    // «тяжёлая» страница несёт балласт: так проверяется деление по размеру,
    // не заводя мегабайтных фикстур
    if (heavy) page.drawText('x'.repeat(heavy), { x: 5, y: 100, size: 4 })
  }
  return openSource(await book.save())
}

/** Какие страницы пачки лежат в куске — по их ширине. */
async function pagesIn(bytes) {
  const book = await PDFDocument.load(bytes)
  return book.getPages().map((page) => Math.round(page.getWidth()) - 100)
}

test('в кусок попадают названные страницы и никакие другие', async () => {
  const source = await pile(6)

  assert.deepEqual(await pagesIn(await cut(source, [1, 4])), [1, 4])
})

test('условия едут в работу ученика вместе с решением', () => {
  // без них он открывает свои ответы без вопросов
  assert.deepEqual(pagesOf({ pages: [3, 4], conditions: [2] }), [2, 3, 4])
})

test('страницы куска идут по порядку пачки, а не по порядку списков', () => {
  assert.deepEqual(pagesOf({ pages: [7, 1], conditions: [5, 0] }), [0, 1, 5, 7])
})

test('лист, названный дважды, попадает в работу один раз', () => {
  // слияние пакетов складывает условия списком, и общий лист повторяется
  assert.deepEqual(pagesOf({ pages: [2], conditions: [0, 0, 2] }), [0, 2])
})

test('общий лист условий попадает каждому', async () => {
  const source = await pile(3)
  const first = pagesOf({ pages: [1], conditions: [0] })
  const second = pagesOf({ pages: [2], conditions: [0] })

  assert.deepEqual(await pagesIn(await cut(source, first)), [0, 1])
  assert.deepEqual(await pagesIn(await cut(source, second)), [0, 2])
})

test('страница, которой в файле нет, останавливает нарезку', async () => {
  // прочитали одну пачку, а резать принесли другую, короче
  const source = await pile(2)

  await assert.rejects(cut(source, [0, 5]), (error) => {
    assert.ok(error instanceof PageOutside)
    assert.equal(error.code, 'page_outside')
    assert.equal(error.index, 5)
    assert.equal(error.pages, 2)
    return true
  })
})

test('тот же кусок, собранный дважды, выходит теми же байтами', async () => {
  // сервер узнаёт повтор по содержимому: с разными байтами продолженный
  // после обрыва разбор оставил бы ученику две копии одной работы
  const source = await pile(4)

  const once = await cut(source, [1, 2])
  await new Promise((resolve) => setTimeout(resolve, 1100))
  const again = await cut(source, [1, 2])

  assert.deepEqual(Buffer.from(once), Buffer.from(again))
})

test('работа легче предела уезжает одним файлом', async () => {
  const source = await pile(4)

  assert.equal((await pieces(source, [0, 1, 2, 3])).length, 1)
})

test('работа тяжелее предела делится, и ни одна страница не теряется', async () => {
  const source = await pile(4, { heavy: 4000 })
  const whole = await cut(source, [0, 1, 2, 3])

  const parts = await pieces(source, [0, 1, 2, 3], Math.ceil(whole.length / 2))

  assert.ok(parts.length > 1, 'кусок тяжелее предела ушёл одним файлом')
  const kept = []
  for (const part of parts) kept.push(...(await pagesIn(part)))
  assert.deepEqual(kept, [0, 1, 2, 3])
})

test('одна страница тяжелее предела уезжает как есть', async () => {
  // молча выбросить её было бы хуже отказа сервера
  const source = await pile(1, { heavy: 4000 })

  const parts = await pieces(source, [0], 10)

  assert.equal(parts.length, 1)
  assert.deepEqual(await pagesIn(parts[0]), [0])
})

test('работе без страниц отправлять нечего', async () => {
  assert.deepEqual(await pieces(await pile(2), []), [])
})

test('работы собираются одним файлом в том порядке, в каком их дали', async () => {
  const source = await pile(5)
  const first = await cut(source, [3, 4])
  const second = await cut(source, [0])

  const steps = []
  const book = await join([first, second], (done, total) => steps.push([done, total]))

  assert.deepEqual(await pagesIn(book), [3, 4, 0])
  assert.deepEqual(steps, [
    [1, 2],
    [2, 2],
  ])
})

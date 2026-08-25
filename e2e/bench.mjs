/**
 * Прогнать настоящую пачку настоящим путём чтения и записать, что вышло.
 *
 * Путь этот живёт в браузере: страницы рисует pdfjs, шапку вырезает канва, и
 * повторять всё это на сервере значило бы мерить не то, что работает у
 * учителя. Поэтому берётся тот же dev-сервер, те же модули и та же дверь
 * `/api/works/<id>/scan/read/` — меняются только ответы на два вопроса, ради
 * которых замер и затеян.
 *
 * Аргументы: <reader> <second> <файл-результата>
 *   reader — '' | 'anthropic' | 'yandex'
 *   second — 'true' | 'false'
 */
import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'

const [reader, second, out] = process.argv.slice(2)
const WORK = Number(process.env.WORK_ID)
const TOKEN = process.env.AUTH_TOKEN
const PDF = process.env.PDF_PATH

const browser = await chromium.launch()
const context = await browser.newContext()
await context.addInitScript(
  ([key, value]) => window.localStorage.setItem(key, value),
  ['authToken', TOKEN],
)

// Файл не кладётся в дерево проекта нарочно: это чужие работы, и место им не
// в репозитории. Отдаём его перехватом запроса — для страницы это обычный URL.
await context.route('**/bench-pile.pdf', (route) =>
  route.fulfill({ path: PDF, contentType: 'application/pdf' }),
)

const page = await context.newPage()
page.on('console', (message) => {
  if (message.type() === 'error') console.error('[консоль]', message.text())
})

await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' })
await page.waitForFunction(() => Boolean(window.document.querySelector('#root')?.children.length), {
  timeout: 30_000,
})

const answer = await page.evaluate(
  async ({ work, reader, second }) => {
    const api = await import('/src/api.js')
    const { walk } = await import('/src/scanBatch.js')

    const body = await (await fetch('/bench-pile.pdf')).blob()
    const file = new File([body], 'bench-pile.pdf', { type: 'application/pdf' })

    // Прочитанное узнаётся по отпечатку и второй раз не читается — значит
    // между вариантами пачку надо сбрасывать, иначе второй замер покажет
    // ответы первого.
    await api.resetScan(work)

    const started = Date.now()
    const seen = []
    await walk(file, {
      stop: () => false,
      onPage: (one) => seen.push({ index: one.index, score: one.score, ours: one.ours, readable: one.readable }),
      send: async ({ index, blob, mark }) => {
        await api.readScanPage(work, { index, blob, mark, second, reader })
        return true
      },
      blank: async (index, ours) => {
        await api.markHeaderless(work, index, ours)
      },
      questions: null,
    })

    const state = await api.fetchScanState(work)
    return { state, seen, seconds: Math.round((Date.now() - started) / 1000) }
  },
  { work: WORK, reader: reader || '', second: second === 'true' },
)

writeFileSync(out, JSON.stringify({ reader, second, ...answer }, null, 1))
console.log(
  `готово: ${reader || 'кем умеет'} + ${second === 'true' ? 'Mathpix' : 'без Mathpix'},` +
    ` страниц ${answer.state.pages.length}, ${answer.seconds} с`,
)
await browser.close()

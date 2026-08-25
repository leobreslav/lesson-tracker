/**
 * Вырезать шапки всех страниц пачки и сложить картинками на диск.
 *
 * Ни одного платного вызова: `send` и `blank` пустые, наружу не уходит
 * ничего. Нужно это затем, что мерить чтение можно только против бумаги, а
 * бумагу надо сперва увидеть.
 */
import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'

const out = process.argv[2]
const PDF = process.env.PDF_PATH

const browser = await chromium.launch()
const context = await browser.newContext()
await context.route('**/bench-pile.pdf', (route) =>
  route.fulfill({ path: PDF, contentType: 'application/pdf' }),
)

const page = await context.newPage()
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' })

const pages = await page.evaluate(async () => {
  const { walk } = await import('/src/scanBatch.js')
  const body = await (await fetch('/bench-pile.pdf')).blob()
  const file = new File([body], 'bench-pile.pdf', { type: 'application/pdf' })

  const seen = []
  await walk(file, {
    stop: () => false,
    onPage: (one) =>
      seen.push({
        index: one.index,
        score: one.score,
        need: one.need,
        ours: one.ours,
        code: one.code ?? null,
        readable: one.readable,
        strip: one.strip,
      }),
  })
  return seen
})

for (const one of pages) {
  if (!one.strip) continue
  const data = one.strip.split(',')[1]
  writeFileSync(`${out}/strip-${String(one.index + 1).padStart(2, '0')}.jpg`, Buffer.from(data, 'base64'))
}
writeFileSync(
  `${out}/strips.json`,
  JSON.stringify(pages.map(({ strip, ...rest }) => rest), null, 1),
)
console.log(`шапок вырезано: ${pages.filter((one) => one.strip).length} из ${pages.length}`)
await browser.close()

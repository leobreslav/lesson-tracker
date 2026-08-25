import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'
const out = process.argv[2]
const want = process.argv.slice(3).map(Number)
const browser = await chromium.launch()
const context = await browser.newContext()
await context.route('**/bench-pile.pdf', (route) =>
  route.fulfill({ path: process.env.PDF_PATH, contentType: 'application/pdf' }),
)
const page = await context.newPage()
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' })
const shots = await page.evaluate(async (want) => {
  const { walk } = await import('/src/scanBatch.js')
  const body = await (await fetch('/bench-pile.pdf')).blob()
  const file = new File([body], 'p.pdf', { type: 'application/pdf' })
  const out = []
  await walk(file, {
    stop: () => false,
    onPage: (one) => { if (want.includes(one.index + 1)) out.push({ n: one.index + 1, preview: one.preview }) },
  })
  return out
}, want)
for (const one of shots) writeFileSync(`${out}/page-${one.n}.jpg`, Buffer.from(one.preview.split(',')[1], 'base64'))
console.log('снято:', shots.map((o) => o.n).join(', '))
await browser.close()

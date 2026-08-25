/**
 * Отладочный разбор одной страницы: что нашлось метками, какие четвёрки из
 * них сложились, какой счёт даёт каждая и как выглядит её полоска.
 * Ни одного платного вызова.
 */
import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'

const want = Number(process.argv[2])
const out = process.argv[3]
const browser = await chromium.launch()
const context = await browser.newContext()
await context.route('**/bench-pile.pdf', (route) =>
  route.fulfill({ path: process.env.PDF_PATH, contentType: 'application/pdf' }),
)
const page = await context.newPage()
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' })

const report = await page.evaluate(async (want) => {
  const S = await import('/src/scanSheet.js')
  const B = await import('/src/blankGeometry.js')
  const { openBook, drawPage, toCanvas } = await import('/src/scanBatch.js')

  const body = await (await fetch('/bench-pile.pdf')).blob()
  const file = new File([body], 'p.pdf', { type: 'application/pdf' })
  const book = await openBook(file)
  const { image } = await drawPage(book, want)

  const small = S.shrink(S.toGray(image))
  const marks = S.findMarks(small)
  const quads = S.quads(marks, small)
  const bands = S.bands(marks, small)
  const tryHeight = Math.round((512 * B.HEADER.height) / B.HEADER.width)
  const rows = []
  const consider = (kind, from, to) => {
    const h = S.homography(from, to)
    if (!h) return
    const strip = S.warp(image, h, B.HEADER, 512, tryHeight)
    rows.push({
      kind,
      score: S.gridScore(strip),
      qr: S.hasBlankMark(image, h, null),
      shot: toCanvas(strip).toDataURL('image/jpeg', 0.8),
    })
  }

  const nominal = B.sheetCorners()
  quads.forEach((quad, q) => {
    for (let turn = 0; turn < 4; turn += 1) {
      const turned = quad.slice(turn).concat(quad.slice(0, turn))
      consider(
        `лист${q}-п${turn}`,
        nominal,
        turned.map((p) => ({ x: p.x * small.step, y: p.y * small.step })),
      )
    }
  })
  bands.forEach(({ corners, band }, b) => {
    const box = [
      { x: 8, y: band.top },
      { x: 202, y: band.top },
      { x: 202, y: band.bottom },
      { x: 8, y: band.bottom },
    ]
    for (const turn of [0, 2]) {
      const turned = corners.slice(turn).concat(corners.slice(0, turn))
      consider(
        `полоса${band.top}_${band.bottom}-${b}-п${turn}`,
        box,
        turned.map((p) => ({ x: p.x * small.step, y: p.y * small.step })),
      )
    }
  })

  return rows
}, want)

for (const one of report) {
  writeFileSync(`${out}/cand-${one.score}-${one.kind}.jpg`, Buffer.from(one.shot.split(',')[1], 'base64'))
}
console.log(
  report
    .map((one) => `${one.kind}: счёт ${one.score}${one.qr ? ', код найден' : ''}`)
    .join('\n'),
)
await browser.close()

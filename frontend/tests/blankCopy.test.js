import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { GRID } from '../src/blankGeometry.js'

/**
 * Бланк лежит в трёх местах, и это осознанные копии.
 *
 * `blank/blank_form.pdf` — исходник: его собирают из .tex и печатают пачкой на
 * год. `frontend/public/blank.pdf` — то же самое, но внутри контекста сборки
 * фронта: иначе сайту его неоткуда отдать, а учителю неоткуда взять.
 * `backend/works/blank/blank_form.pdf` — подложка бланка с подписями задач:
 * сервер надпечатывает на ней имена вопросов, а образ бэкенда собирается
 * только из `./backend`. Контекст сборки у обоих — свой каталог, и обойти это
 * можно либо копией, либо лишним слоем раздачи.
 *
 * Копия допустима ровно потому, что расхождение ловится: разошлись — тест
 * красный, и печатать будут не тот лист, по которому кропает чтение.
 */
const source = readFileSync(new URL('../../blank/blank_form.pdf', import.meta.url))

test('бланк на сайте — тот же файл, что печатают', () => {
  const served = readFileSync(new URL('../public/blank.pdf', import.meta.url))

  assert.deepEqual(
    served,
    source,
    'blank/blank_form.pdf и frontend/public/blank.pdf разошлись: скопируйте заново',
  )
})

test('подложка бланка с подписями — тот же файл, что печатают', () => {
  const base = readFileSync(
    new URL('../../backend/works/blank/blank_form.pdf', import.meta.url),
  )

  assert.deepEqual(
    base,
    source,
    'blank/blank_form.pdf и backend/works/blank/blank_form.pdf разошлись: скопируйте заново',
  )
})

/**
 * Подписи сервер ставит по своим миллиметрам, а кропает чтение по своим.
 * Разойдутся — подпись «2c» встанет над чужой клеткой, и на бумаге это
 * увидит только тот, кто поставит балл не туда.
 */
test('подписи ставятся в те же клетки, что режет чтение', () => {
  const python = readFileSync(
    new URL('../../backend/works/blank/__init__.py', import.meta.url),
    'utf8',
  )
  const number = (name) => {
    const found = new RegExp(`^${name} = ([\\d.]+)$`, 'm').exec(python)
    assert.ok(found, `${name} не найден в backend/works/blank/__init__.py`)
    return Number(found[1])
  }

  assert.equal(number('GRID_X'), GRID.x)
  assert.equal(number('GRID_Y'), GRID.y)
  assert.equal(number('CELL_WIDTH'), GRID.cellWidth)
  assert.equal(number('LABEL_HEIGHT'), GRID.labelHeight)
  assert.equal(number('QUESTIONS'), GRID.cells - 1)
})

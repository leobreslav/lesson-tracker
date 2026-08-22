import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

/**
 * Бланк лежит в двух местах, и это осознанная копия.
 *
 * `blank/blank_form.pdf` — исходник: его собирают из .tex и печатают пачкой на
 * год. `frontend/public/blank.pdf` — то же самое, но внутри контекста сборки
 * фронта: иначе сайту его неоткуда отдать, а учителю неоткуда взять. Контекст
 * сборки — только каталог `frontend`, и обойти это можно либо копией, либо
 * лишним слоем раздачи через Django.
 *
 * Копия допустима ровно потому, что расхождение ловится: разошлись — тест
 * красный, и печатать будут не тот лист, по которому кропает чтение.
 */
test('бланк на сайте — тот же файл, что печатают', () => {
  const source = readFileSync(new URL('../../blank/blank_form.pdf', import.meta.url))
  const served = readFileSync(new URL('../public/blank.pdf', import.meta.url))

  assert.deepEqual(
    served,
    source,
    'blank/blank_form.pdf и frontend/public/blank.pdf разошлись: скопируйте заново',
  )
})

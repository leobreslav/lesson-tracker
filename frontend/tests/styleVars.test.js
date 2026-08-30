/**
 * У каждой переменной в `var(--x)` должно быть объявление.
 *
 * Незнакомая переменная не роняет ничего и ничего не печатает в консоль:
 * браузер объявляет **всё объявление целиком** недействительным и молча
 * выкидывает. Наружу это выходит по-разному, и оба раза не как ошибка.
 *
 * У `color` свойство наследуется, поэтому приглушённый текст просто перестаёт
 * быть приглушённым — цвет берётся от соседей, и на глаз это «шрифт чуть
 * темнее, чем задумывали». А `border: 1px solid var(--нет-такой)` не даёт
 * рамки **вовсе**: `border-style` не наследуется и падает в `none`, то есть
 * элемент теряет границу, а не красит её не тем серым.
 *
 * Проверено на себе, и дважды. Сперва `--border` и `--muted` поминались по
 * восемь раз каждая, не будучи объявлены нигде; восемь рамок отсутствовали, и
 * ни один тест этого не видел — цвета и рамки не проверяет ни один. Потом это
 * **нашли** — у полоски скана — и вылечили **местно**: подставили литерал и
 * приписали «такой переменной в теме нет». Приписка верная, остальные восемь
 * мест остались сломанными.
 *
 * Отсюда сторож, и стоит он тут, а не в браузерном наборе: это разбор текста,
 * он идёт миллисекунды и не требует ни стенда, ни экрана.
 *
 * Считается **только голый** `var(--x)`. С запасом (`var(--x, #fff)`) объявление
 * действительно и без переменной — это законный приём, и трогать его незачем.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'

const srcDir = fileURLToPath(new URL('../src', import.meta.url))
const css = readFileSync(join(srcDir, 'styles.css'), 'utf8')

/** Имена, объявленные в самом файле — в `:root` или на любом селекторе. */
function declaredInCss() {
  return new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]))
}

/**
 * Имена, которые ставит код через `style`.
 *
 * Так живёт `--switch-count`: сколько сегментов у тумблера, знает только
 * `Switch.jsx`, и объявлять это в теме нечем.
 */
function declaredInCode() {
  const names = new Set()
  for (const name of readdirSync(srcDir)) {
    if (!/\.jsx?$/.test(name)) continue
    const source = readFileSync(join(srcDir, name), 'utf8')
    for (const [, found] of source.matchAll(/'(--[a-z0-9-]+)'/g)) names.add(found)
    for (const [, found] of source.matchAll(/"(--[a-z0-9-]+)"/g)) names.add(found)
  }
  return names
}

test('every bare var(--x) in styles.css has a declaration', () => {
  const declared = new Set([...declaredInCss(), ...declaredInCode()])
  // голый — значит без запасного значения: `var(--x)`, а не `var(--x, …)`
  const used = [...css.matchAll(/var\((--[a-z0-9-]+)\)/g)].map((m) => m[1])

  assert.ok(used.length > 20, `разобрано только ${used.length} — файл переехал?`)

  const orphans = [...new Set(used.filter((name) => !declared.has(name)))].sort()
  assert.deepEqual(
    orphans,
    [],
    'переменные без объявления: у color они молча перестают приглушать, ' +
      'у border забирают рамку целиком',
  )
})

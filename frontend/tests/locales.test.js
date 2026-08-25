/**
 * The dictionaries have to stay in step.
 *
 * A missing key does not crash anything — i18next quietly falls back to
 * English — so without this test a half-translated release looks fine until a
 * Russian-speaking user hits the one screen nobody re-read.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import i18next from 'i18next'
import { weekOrder } from '../src/weekStart.js'

const load = (name) =>
  JSON.parse(
    readFileSync(fileURLToPath(new URL(`../src/locales/${name}.json`, import.meta.url))),
  )

const en = load('en')
const ru = load('ru')

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/

/** Every leaf key of a nested dictionary, as dotted paths. */
function leaves(node, prefix = '') {
  return Object.entries(node).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'object' && value !== null ? leaves(value, path) : [path]
  })
}

/** Leaf keys with the plural suffix stripped: what the code actually calls. */
const called = (dict) => new Set(leaves(dict).map((key) => key.replace(PLURAL_SUFFIX, '')))

function values(node, prefix = '') {
  return Object.entries(node).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'object' && value !== null
      ? values(value, path)
      : [[path, value]]
  })
}

const placeholders = (text) =>
  new Set([...String(text).matchAll(/{{\s*(\w+)/g)].map((match) => match[1]))

test('both dictionaries cover the same keys', () => {
  const missingInRu = [...called(en)].filter((key) => !called(ru).has(key))
  const extraInRu = [...called(ru)].filter((key) => !called(en).has(key))

  assert.deepEqual(missingInRu, [], 'keys missing from ru.json')
  assert.deepEqual(extraInRu, [], 'keys in ru.json that English does not have')
})

test('russian counters carry all three plural forms', () => {
  const counters = [...called(ru)].filter((key) =>
    leaves(ru).some((leaf) => leaf.startsWith(`${key}_`) && PLURAL_SUFFIX.test(leaf)),
  )
  assert.ok(counters.length > 0, 'no plural keys found at all')

  const all = leaves(ru)
  for (const key of counters) {
    for (const form of ['one', 'few', 'many']) {
      assert.ok(all.includes(`${key}_${form}`), `ru.json has no ${key}_${form}`)
    }
  }
})

test('a phrase uses the same placeholders in both languages', () => {
  const russian = new Map(values(ru))

  for (const [key, text] of values(en)) {
    const base = key.replace(PLURAL_SUFFIX, '')
    // a plural form of its own may be spelled differently, compare by base
    const counterpart =
      russian.get(key) ??
      [...russian].find(([other]) => other.replace(PLURAL_SUFFIX, '') === base)?.[1]

    if (counterpart === undefined) continue
    assert.deepEqual(
      [...placeholders(counterpart)].sort(),
      [...placeholders(text)].sort(),
      `placeholders differ in ${key}`,
    )
  }
})

test('russian counts read correctly for 1, 2, 5, 11 and 21', async () => {
  const instance = i18next.createInstance()
  await instance.init({
    lng: 'ru',
    resources: { ru: { translation: ru } },
    interpolation: { escapeValue: false },
  })

  const lesson = (count) => instance.t('common.lessonCount', { count })

  assert.equal(lesson(1), '1 урок')
  assert.equal(lesson(2), '2 урока')
  assert.equal(lesson(5), '5 уроков')
  assert.equal(lesson(11), '11 уроков')
  assert.equal(lesson(21), '21 урок')
})

test('english counts pick singular and plural', async () => {
  const instance = i18next.createInstance()
  await instance.init({
    lng: 'en',
    resources: { en: { translation: en } },
    interpolation: { escapeValue: false },
  })

  assert.equal(instance.t('common.lessonCount', { count: 1 }), '1 lesson')
  assert.equal(instance.t('common.lessonCount', { count: 2 }), '2 lessons')
})

test('an unknown error code still shows the text the server sent', async () => {
  const instance = i18next.createInstance()
  await instance.init({
    lng: 'ru',
    resources: { ru: { translation: ru } },
    interpolation: { escapeValue: false },
  })

  const detail = 'Something entirely new went wrong'
  assert.equal(instance.t('errors.brand_new_code', { defaultValue: detail }), detail)
  assert.equal(
    instance.t('errors.term_overlap', {
      defaultValue: 'ignored',
      name: '1 четверть',
      start: '2026-09-01',
      end: '2026-10-25',
    }),
    'Пересекается с «1 четверть» (2026-09-01 — 2026-10-25).',
  )
})

test('every key the code asks for exists in English', () => {
  const dir = fileURLToPath(new URL('../src', import.meta.url))
  const known = new Set(leaves(en))
  const asked = []

  for (const name of readdirSync(dir)) {
    if (!/\.(js|jsx)$/.test(name) || name === 'i18n.js') continue

    const source = readFileSync(join(dir, name), 'utf8')
    for (const [, key] of source.matchAll(/\bt\(\s*'([\w.]+)'/g)) {
      asked.push([name, key])
    }
    for (const [, key] of source.matchAll(/i18nKey="([\w.]+)"/g)) {
      asked.push([name, key])
    }
  }

  assert.ok(asked.length > 0, 'no t() calls found — did the scan break?')

  const unknown = asked.filter(
    // a counter is called by its base name, the suffix belongs to i18next
    ([, key]) => !known.has(key) && ![...known].some((leaf) => leaf.startsWith(`${key}_`)),
  )
  assert.deepEqual(unknown, [], 'keys used in code but missing from en.json')
})

test('every error code of the backend has a phrase', () => {
  // the single list of codes lives in backend/config/errors.py; a code added
  // there and forgotten here would reach the user as bare English `detail`
  const source = readFileSync(
    fileURLToPath(new URL('../../backend/config/errors.py', import.meta.url)),
    'utf8',
  )
  const codes = [...source.matchAll(/^\s{4}[A-Z_]+ = "([a-z_]+)"$/gm)].map((m) => m[1])
  assert.ok(codes.length > 20, `only ${codes.length} codes parsed — did the file move?`)

  const known = new Set(leaves(en))
  const missing = codes.filter(
    (code) => !known.has(`errors.${code}`) && !known.has(`warnings.${code}`),
  )
  assert.deepEqual(missing, [], 'codes without a phrase in en.json')
})

test('keys built at runtime exist for every value they take', () => {
  const known = new Set(leaves(en))
  const expected = [
    ...['study', 'holiday', 'vacation', 'weekend'].map((s) => `dayStatus.${s}`),
    ...['holiday', 'vacation', 'workday'].map((k) => `calendar.kind.${k}`),
    // «курсы» и «учебный год» из бара убраны: оба живут в разделе «Школа»
    ...['schedule', 'plan', 'works', 'school'].map((s) => `nav.${s}`),
    ...['year', 'calendar', 'classes', 'schedule', 'plan'].flatMap((step) =>
      ['title', 'action', 'missing'].map((part) => `dashboard.steps.${step}.${part}`),
    ),
    // the lesson panel builds these from the field name and from the unit
    // `fileKind.formatSize` picked
    ...['objectives', 'body', 'formative', 'homework'].flatMap((field) => [
      `lesson.fields.${field}`,
      `lesson.placeholders.${field}`,
    ]),
    ...['b', 'kb', 'mb'].map((unit) => `lesson.size.${unit}`),
    // журнал трат и разбивка пачки строят ключ из повода, а поводы заводятся
    // на сервере (`vision/models.py`, `AiSpend.PURPOSES`). Новый повод без
    // фразы показал бы человеку сам ключ — в списке, по которому решают,
    // стоит ли второй читатель своих денег
    ...['scan_header', 'scan_second', 'scan_reread', 'scan_questions'].map(
      (purpose) => `ai.purpose.${purpose}`,
    ),
    // читателей шапки трое, и выбирает между ними человек: имя каждого
    // строится из его кода (`vision/services.py`, NAME_READERS). Забытая
    // фраза показала бы код в выпадающем списке
    ...['anthropic', 'yandex', 'mathpix'].map((one) => `scan.reader.${one}`),
    // недоступный читатель показывается заглушённым и со словом о причине —
    // в том и смысл, что он не пропадает. Причины приходят с сервера
    // (`vision/services.py`, `readers_state`), кроме `same_reader`: её
    // считает сам экран по соседнему выбору. Забытая фраза оставила бы
    // строку без объяснения, то есть ровно с той загадкой, ради которой
    // заглушённый вариант и показывается
    ...['not_configured', 'unreachable', 'same_reader'].map(
      (why) => `scan.why.${why}`,
    ),
  ]

  assert.deepEqual(
    expected.filter((key) => !known.has(key)),
    [],
    'keys the code builds from a code word but the dictionary lacks',
  )
})

test('the week starts on Monday, whatever the language', () => {
  // A school week is Monday to Sunday, and the backend numbers weekdays the
  // same way. Letting the locale decide meant that switching the interface
  // to English reflowed the grid without a lesson having moved.
  for (const language of ['ru', 'en', 'en-US', 'en-GB', undefined]) {
    assert.deepEqual(weekOrder(language), [0, 1, 2, 3, 4, 5, 6], String(language))
  }
})

test('the dictionary has no keys the code stopped asking for', () => {
  // Обратная сторона проверки выше. Та ловит опечатку в `t()`, эта — мусор:
  // раздел переделали, ключи остались, и через полгода никто не отличит
  // живую фразу от памятника прошлой версии экрана. Ключей шестьсот, руками
  // это не проверяется вовсе.
  const dir = fileURLToPath(new URL('../src', import.meta.url))
  const literal = new Set()
  const prefixes = []

  for (const name of readdirSync(dir)) {
    if (!/\.(js|jsx)$/.test(name) || name === 'i18n.js') continue

    const source = readFileSync(join(dir, name), 'utf8')
    // берём любую строку, похожую на ключ, а не только сразу после `t(`:
    // ключ приезжает и тернарником, и списком, и через переменную —
    // ложно живой ключ здесь дешевле ложно мёртвого
    for (const [, key] of source.matchAll(/['"`]([a-z][\w]*(?:\.[\w]+)+)['"`]/g)) {
      literal.add(key)
    }
    // ключи, собираемые на лету: `t(`nav.${section}`)` — живым считается
    // весь раздел, потому что имена значений код знает, а тест нет
    for (const [, key] of source.matchAll(/\bt\(\s*`([\w.]+\.)\$\{/g)) prefixes.push(key)
  }

  assert.ok(prefixes.length > 0, 'no dynamic keys found — did the scan break?')

  // коды ошибок и предупреждений приходят с сервера, в коде их нет
  prefixes.push('errors.', 'warnings.')

  const stale = leaves(en)
    // счётчик зовут по базовому имени, суффикс подставляет i18next
    .map((key) => key.replace(/_(one|few|many|other)$/, ''))
    .filter(
      (key) => !literal.has(key) && !prefixes.some((prefix) => key.startsWith(prefix)),
    )

  assert.deepEqual([...new Set(stale)], [], 'keys in en.json that nothing asks for')
})

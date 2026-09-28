/**
 * В коде интерфейса нет имени, которое никто не объявил.
 *
 * Сборка такого не ловит: Vite соберёт обращение к несуществующей переменной
 * молча, и узнают о нём в браузере — `ReferenceError` посреди отрисовки,
 * страница падает целиком. Хуже того, падает она обычно не на главном пути,
 * а на боковом, куда заходят редко и который руками не проходили.
 *
 * Так и нашли. Шаг разбора сканов пользовался `hasFile`, которого ему никто
 * не передавал; нужен он был в одном случае — когда к прочитанной пачке
 * возвращаются без файла, — и учитель, закрывший окно посреди работы,
 * вернувшись, получил «страница не отрисовалась». Вторая такая же, `saved`
 * в форме работы, роняла окно на первом приложенном файле. Обе пережили
 * сборку, узловые тесты и выкатку, потому что ни одна из трёх проверок в эту
 * сторону не смотрит.
 *
 * Правил ровно два, и оба про одно — имя, взятое из ниоткуда: переменная
 * (`no-undef`) и компонент в разметке (`react/jsx-no-undef`; первое правило
 * теги не видит). Стиль, порядок импортов и прочее здесь не проверяются
 * намеренно: сторож, который ругается на вкус, приучает отмахиваться от
 * него не глядя, и тогда он молчит ровно в тот раз, когда прав.
 *
 * В коде встречаются пометки `eslint-disable` для правил, которых здесь нет
 * (`react-hooks/exhaustive-deps` и соседи). Линтер считает незнакомое правило
 * ошибкой; нам оно не ошибка, поэтому находки отбираются по имени правила, а
 * не берутся все подряд.
 */

import assert from 'node:assert/strict'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { ESLint } from 'eslint'
import react from 'eslint-plugin-react'
import globals from 'globals'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const WATCHED = ['no-undef', 'react/jsx-no-undef']

const config = [
  {
    files: ['**/*.js', '**/*.jsx'],
    plugins: { react },
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      // тесты гоняет node, а код живёт в браузере: знакомы оба набора имён
      globals: { ...globals.browser, ...globals.node },
    },
    rules: { 'no-undef': 'error', 'react/jsx-no-undef': 'error' },
  },
]

const linter = () =>
  new ESLint({ cwd: ROOT, overrideConfigFile: true, overrideConfig: config })

/** Находки сторожа — строками «файл:строка имя», по одной на место. */
const found = (results) =>
  results.flatMap((file) =>
    file.messages
      .filter((message) => WATCHED.includes(message.ruleId))
      .map(
        (message) =>
          `${path.relative(ROOT, file.filePath)}:${message.line} ${message.message}`,
      ),
  )

test('в коде интерфейса нет необъявленных имён', async () => {
  const results = await linter().lintFiles(['src/**/*.js', 'src/**/*.jsx'])

  assert.ok(results.length > 50, 'сторож не нашёл файлов: проверять было нечего')
  assert.deepEqual(
    found(results),
    [],
    'имя взято из ниоткуда: сборка это пропустит, а страница упадёт в браузере',
  )
})

test('сторож ловит необъявленную переменную', async () => {
  // Проверка самого сторожа. Расчёт, вернувший пустой список, сделал бы
  // тест выше зелёным, не проверив ничего: так уже было с отсевом «наших»
  // приложений на сервере
  const results = await linter().lintText(
    'export default function Step() { return hasFile ? 1 : 2 }\n',
    { filePath: path.join(ROOT, 'src', 'Probe.jsx') },
  )

  assert.equal(found(results).length, 1)
  assert.match(found(results)[0], /hasFile/)
})

test('сторож ловит необъявленный компонент', async () => {
  const results = await linter().lintText(
    'export default function Page() { return <PhotoViewer /> }\n',
    { filePath: path.join(ROOT, 'src', 'Probe.jsx') },
  )

  assert.equal(found(results).length, 1)
  assert.match(found(results)[0], /PhotoViewer/)
})

test('пометка для незнакомого правила находкой не считается', async () => {
  const results = await linter().lintText(
    [
      "import { useEffect } from 'react'",
      'export default function Page() {',
      '  useEffect(() => {}, [])',
      '  // eslint-disable-next-line react-hooks/exhaustive-deps',
      '  return null',
      '}',
      '',
    ].join('\n'),
    { filePath: path.join(ROOT, 'src', 'Probe.jsx') },
  )

  assert.deepEqual(found(results), [])
})

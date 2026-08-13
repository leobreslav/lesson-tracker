/**
 * The client-side mirror of `parse_plan_csv`.
 *
 * What matters here is the id format: the dialog decides from these results
 * whether «Sync» may be offered at all, and the id column changes what an
 * empty theme cell means. Getting that wrong client-side would show one plan
 * in the preview and write another.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { detectIds, parsePlanCsv, sniffDelimiter } from '../src/planCsv.js'

const WITH_IDS = [
  'id,Тема,Урок,Заметка',
  '10,Тригонометрия,,',
  '11,Тригонометрия,Синус суммы,',
  '12,Тригонометрия,Косинус суммы,на дом',
  '13,,Повторение,',
  ',,Новый урок,добавлен вручную',
].join('\n')

const PLAIN = ['Тема,Урок,Заметка', 'Векторы,,', ',Понятие вектора,'].join('\n')

describe('detectIds', () => {
  it('распознаёт файл по шапке экспорта', () => {
    assert.equal(parsePlanCsv(WITH_IDS).hasIds, true)
  })

  it('трёхстолбцовый файл остаётся без id', () => {
    assert.equal(parsePlanCsv(PLAIN).hasIds, false)
  })

  it('узнаёт файл и без шапки, если первый столбец числовой', () => {
    assert.equal(detectIds([['10', 'Векторы', '', ''], ['11', '', 'Понятие', '']]), true)
  })

  it('пустая четвёртая колонка от Excel не превращается в id', () => {
    // все первые ячейки пусты: чисел нет, значит и столбца id нет
    assert.equal(detectIds([['', 'Понятие', 'заметка', ''], ['', 'Второй', '', '']]), false)
  })

  it('темы в первом столбце — это не id', () => {
    assert.equal(detectIds([['Векторы', '', '', ''], ['', 'Понятие', '', '']]), false)
  })
})

describe('parsePlanCsv с id', () => {
  const { rows } = parsePlanCsv(WITH_IDS)

  it('шапка со столбцом id пропускается', () => {
    assert.equal(rows.length, 5)
  })

  it('id доезжает до строки, а пустой становится null', () => {
    assert.deepEqual(
      rows.map((row) => row.id),
      [10, 11, 12, 13, null],
    )
  })

  it('повторённая тема не создаёт второй заголовок', () => {
    assert.deepEqual(
      rows.map((row) => (row.is_section ? 'тема' : 'урок')),
      ['тема', 'урок', 'урок', 'урок', 'урок'],
    )
  })

  it('пустая ячейка темы означает урок вне темы', () => {
    assert.equal(rows[3].title, 'Повторение')
    assert.equal(rows[3].at_top_level, true)
    assert.equal(rows[1].at_top_level, false)
  })

  it('заметка читается из четвёртого столбца', () => {
    assert.equal(rows[2].note, 'на дом')
  })
})

describe('parsePlanCsv без id', () => {
  it('пустая ячейка темы по-прежнему значит «внутри темы»', () => {
    const { rows } = parsePlanCsv(PLAIN)

    assert.equal(rows[1].title, 'Понятие вектора')
    assert.equal(rows[1].at_top_level, false)
    assert.equal(rows[1].id, null)
  })
})

/**
 * Ниже — зеркало `plans/test_csv_shapes.py`: те же файлы, те же ожидания.
 * Предпросмотр показывает то, что импортирует сервер, и разойтись они могут
 * только если кто-то поправит один разбор и забудет другой.
 */

const shape = (rows) =>
  rows.map((row) =>
    row.is_section
      ? ['тема', row.title]
      : [row.at_top_level ? 'урок вне темы' : 'урок', row.title],
  )

const EXPECTED = [
  ['тема', 'Тема 1'],
  ['урок', 'Урок 1'],
  ['урок', 'Урок 2'],
  ['тема', 'Тема 2'],
  ['урок', 'Урок 3'],
]

describe('вложенность', () => {
  it('уроки идут внутрь темы, написанной выше', () => {
    const text = 'Тема 1,,\n,Урок 1,\n,Урок 2,\nТема 2,,\n,Урок 3,\n'

    assert.deepEqual(shape(parsePlanCsv(text).rows), EXPECTED)
  })

  it('столбец id не меняет смысла пустой ячейки темы', () => {
    const text =
      'id,Тема,Урок,Заметка\n,Тема 1,,\n,,Урок 1,\n,,Урок 2,\n,Тема 2,,\n,,Урок 3,\n'
    const parsed = parsePlanCsv(text)

    assert.equal(parsed.hasIds, true)
    assert.deepEqual(shape(parsed.rows), EXPECTED)
  })

  it('протянутая тема даёт то же дерево', () => {
    const text = 'Тема,Урок\nТема 1,Урок 1\nТема 1,Урок 2\nТема 2,Урок 3\n'

    assert.deepEqual(shape(parsePlanCsv(text).rows), EXPECTED)
  })

  it('в протянутом файле пустая тема значит «вне темы»', () => {
    const text = 'id,Тема,Урок,Заметка\n1,Тема 1,,\n2,Тема 1,Урок 1,\n3,,Повторение,\n'

    assert.deepEqual(shape(parsePlanCsv(text).rows), [
      ['тема', 'Тема 1'],
      ['урок', 'Урок 1'],
      ['урок вне темы', 'Повторение'],
    ])
  })
})

describe('спецсимволы', () => {
  const titles = (text) => parsePlanCsv(text).rows.map((row) => row.title)

  it('запятая внутри названия не разрывает ячейку', () => {
    const text = 'Тема,Урок,Заметка\n"Дроби, обычные",,\n,"Сложение, вычитание",\n'

    assert.deepEqual(titles(text), ['Дроби, обычные', 'Сложение, вычитание'])
  })

  it('файл, где каждое название с запятой, читается как «;»', () => {
    const text =
      'Тема;Урок;Заметка\n"Дроби, обычные";;\n;"Сложение, вычитание";\n' +
      ';"Умножение, деление";\n;"Точка, ещё";\n'

    assert.equal(sniffDelimiter(text), ';')
    assert.deepEqual(titles(text), [
      'Дроби, обычные',
      'Сложение, вычитание',
      'Умножение, деление',
      'Точка, ещё',
    ])
  })

  it('точка с запятой внутри названия не перебивает запятую', () => {
    const text = 'Тема,Урок,Заметка\nДроби; и точки,,\n,"Урок; раз",\n,"Урок; два",\n'

    assert.equal(sniffDelimiter(text), ',')
    assert.deepEqual(titles(text), ['Дроби; и точки', 'Урок; раз', 'Урок; два'])
  })

  it('удвоенные кавычки схлопываются в одну', () => {
    const text = 'Тема,Урок,Заметка\nТема 1,,\n,"Урок ""в кавычках""",\n'

    assert.equal(titles(text)[1], 'Урок "в кавычках"')
  })

  it('перевод строки внутри заметки не путает определение разделителя', () => {
    const text =
      'Тема;Урок;Заметка\n"Дроби, обычные";;"первая, строка\nвторая, строка"\n' +
      ';"Сложение, вычитание";\n'

    assert.equal(sniffDelimiter(text), ';')
    assert.equal(parsePlanCsv(text).rows[0].note, 'первая, строка\nвторая, строка')
  })

  it('пробелы по краям обрезаются', () => {
    const text = 'Тема,Урок,Заметка\n  Тема 1  ,,\n,  Урок 1  ,  заметка  \n'
    const rows = parsePlanCsv(text).rows

    assert.deepEqual(
      rows.map((row) => [row.title, row.note]),
      [
        ['Тема 1', ''],
        ['Урок 1', 'заметка'],
      ],
    )
  })
})

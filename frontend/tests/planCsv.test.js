/**
 * Клиентский разбор CSV — зеркало `plans/services.parse_plan_csv`.
 *
 * Файлы и ожидания здесь те же, что в `plans/test_csv.py`: предпросмотр
 * показывает то, что положит сервер, и разойтись они могут только если
 * кто-то поправит один разбор и забудет другой. Отдельно проверяется, что
 * непонятный файл здесь **отклоняется** тем же кодом, что и на сервере, —
 * иначе диалог отправил бы заведомо негодный файл.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { parsePlanCsv, sniffDelimiter } from '../src/planCsv.js'

const HEAD = 'id,Тема,Урок,Заметка\n'

const shape = (rows) =>
  rows.map((row) =>
    row.is_section
      ? ['тема', row.title]
      : [row.at_top_level ? 'урок вне темы' : 'урок', row.title],
  )

const codes = (text) => parsePlanCsv(text).errors.map((error) => error.code)

describe('единственный формат', () => {
  it('тема повторяется в каждой строке', () => {
    const text =
      HEAD +
      ',Тема 1,Урок 1,\n' +
      ',Тема 1,Урок 2,\n' +
      ',Тема 2,Урок 3,\n'
    const parsed = parsePlanCsv(text)

    assert.deepEqual(parsed.errors, [])
    assert.deepEqual(shape(parsed.rows), [
      ['тема', 'Тема 1'],
      ['урок', 'Урок 1'],
      ['урок', 'Урок 2'],
      ['тема', 'Тема 2'],
      ['урок', 'Урок 3'],
    ])
  })

  it('пустая тема значит «урок вне темы»', () => {
    const text = HEAD + ',Тема 1,Урок 1,\n,,Повторение,\n'

    assert.deepEqual(shape(parsePlanCsv(text).rows), [
      ['тема', 'Тема 1'],
      ['урок', 'Урок 1'],
      ['урок вне темы', 'Повторение'],
    ])
  })

  it('id читается, пустой остаётся пустым', () => {
    const { rows } = parsePlanCsv(HEAD + '10,Тема 1,Урок 1,\n,Тема 1,Новый,\n')

    assert.deepEqual(
      rows.map((row) => row.id),
      [null, 10, null],
    )
  })

  it('заметка читается из четвёртого столбца', () => {
    const { rows } = parsePlanCsv(HEAD + ',Тема 1,Урок 1,на дом\n')

    assert.equal(rows[1].note, 'на дом')
  })

  it('шапка сравнивается без регистра и пробелов', () => {
    const parsed = parsePlanCsv('ID; ТЕМА ;Урок;ЗАМЕТКА\n;Тема 1;Урок 1;\n')

    assert.deepEqual(parsed.errors, [])
    assert.equal(parsed.rows.length, 2)
  })

  it('пустые строки в конце файла не мешают', () => {
    const parsed = parsePlanCsv(HEAD + ',Тема 1,Урок 1,\n\n\n')

    assert.deepEqual(parsed.errors, [])
    assert.equal(parsed.dataRows, 1)
  })
})

describe('отказы', () => {
  it('файл без шапки', () => {
    assert.deepEqual(codes(',Тема 1,Урок 1,\n'), ['csv_header_invalid'])
  })

  it('прежняя трёхстолбцовая шапка', () => {
    assert.deepEqual(codes('Тема,Урок,Заметка\nТема 1,,\n'), ['csv_header_invalid'])
  })

  it('строка с темой, но без урока — бывший заголовок', () => {
    const [error] = parsePlanCsv(HEAD + ',Тема 1,,\n').errors

    assert.equal(error.code, 'csv_section_row')
    assert.deepEqual(error.params, { row: 2, title: 'Тема 1' })
  })

  it('столбцов не четыре', () => {
    assert.deepEqual(codes(HEAD + ',Тема 1,Урок 1\n'), ['csv_bad_columns'])
    assert.deepEqual(codes(HEAD + ',Тема 1,Урок 1,,лишнее\n'), ['csv_bad_columns'])
  })

  it('ни темы, ни урока', () => {
    assert.deepEqual(codes(HEAD + ',,,только заметка\n'), ['csv_row_empty'])
  })

  it('id не число, отрицательный или ноль', () => {
    assert.deepEqual(codes(HEAD + 'абв,Тема 1,Урок 1,\n'), ['csv_bad_id'])
    assert.deepEqual(codes(HEAD + '-5,Тема 1,Урок 1,\n'), ['csv_bad_id'])
    assert.deepEqual(codes(HEAD + '0,Тема 1,Урок 1,\n'), ['csv_bad_id'])
  })

  it('слишком длинное название', () => {
    assert.deepEqual(codes(HEAD + `,Тема 1,${'о'.repeat(201)},\n`), [
      'csv_row_too_long',
    ])
  })

  it('называются все плохие строки разом, с номерами', () => {
    const errors = parsePlanCsv(
      HEAD + ',Тема 1,,\nабв,Тема 1,Урок 1,\n,,,только заметка\n',
    ).errors

    assert.deepEqual(
      errors.map((error) => error.code),
      ['csv_section_row', 'csv_bad_id', 'csv_row_empty'],
    )
    assert.deepEqual(
      errors.map((error) => error.params.row),
      [2, 3, 4],
    )
  })
})

describe('спецсимволы', () => {
  const titles = (text) => parsePlanCsv(text).rows.map((row) => row.title)

  it('запятая внутри названия не разрывает ячейку', () => {
    const text = HEAD + ',"Дроби, обычные","Сложение, вычитание",\n'

    assert.deepEqual(titles(text), ['Дроби, обычные', 'Сложение, вычитание'])
  })

  it('файл, где каждое название с запятой, читается как «;»', () => {
    const text =
      'id;Тема;Урок;Заметка\n' +
      ';"Дроби, обычные";"Сложение, вычитание";\n' +
      ';"Дроби, обычные";"Умножение, деление";\n' +
      ';"Дроби, обычные";"Точка, ещё";\n'

    assert.equal(sniffDelimiter(text), ';')
    assert.deepEqual(titles(text), [
      'Дроби, обычные',
      'Сложение, вычитание',
      'Умножение, деление',
      'Точка, ещё',
    ])
  })

  it('точка с запятой внутри названия не перебивает запятую', () => {
    const text =
      HEAD + ',Дроби; и точки,"Урок; раз",\n,Дроби; и точки,"Урок; два",\n'

    assert.equal(sniffDelimiter(text), ',')
    assert.deepEqual(titles(text), ['Дроби; и точки', 'Урок; раз', 'Урок; два'])
  })

  it('удвоенные кавычки схлопываются в одну', () => {
    const text = HEAD + ',Тема 1,"Урок ""в кавычках""",\n'

    assert.equal(titles(text)[1], 'Урок "в кавычках"')
  })

  it('перевод строки внутри заметки не путает определение разделителя', () => {
    const text =
      'id;Тема;Урок;Заметка\n' +
      ';"Дроби, обычные";"Сложение, вычитание";"первая, строка\nвторая, строка"\n' +
      ';"Дроби, обычные";"Умножение, деление";\n'

    assert.equal(sniffDelimiter(text), ';')
    assert.equal(parsePlanCsv(text).rows[1].note, 'первая, строка\nвторая, строка')
  })

  it('пробелы по краям обрезаются', () => {
    const text = HEAD + ' ,  Тема 1  ,  Урок 1  ,  заметка  \n'
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

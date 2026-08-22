/** Буфер из Excel: табуляции, кавычки, переводы строк внутри ячеек. */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { parseClipboard } from '../src/clipboardGrid.js'

describe('вставка из таблицы', () => {
  it('колонки через табуляцию, строки через перевод', () => {
    assert.deepEqual(parseClipboard('\tВекторы\tПонятие\n\tВекторы\tСложение\n'), [
      ['', 'Векторы', 'Понятие'],
      ['', 'Векторы', 'Сложение'],
    ])
  })

  it('хвостовой перевод строки не даёт пустой строки', () => {
    assert.deepEqual(parseClipboard('a\tb\n'), [['a', 'b']])
    assert.deepEqual(parseClipboard('a\tb\r\n\r\n'), [['a', 'b']])
    assert.deepEqual(parseClipboard(''), [])
  })

  it('перевод строки внутри ячейки — часть значения', () => {
    assert.deepEqual(parseClipboard('\tТема\t"Первая\nвторая"\n'), [
      ['', 'Тема', 'Первая\nвторая'],
    ])
  })

  it('удвоенные кавычки схлопываются в одну', () => {
    assert.deepEqual(parseClipboard('\tТема\t"Урок ""в кавычках"""\n'), [
      ['', 'Тема', 'Урок "в кавычках"'],
    ])
  })

  it('кавычка в середине значения остаётся кавычкой', () => {
    // Excel закавычивает всю ячейку целиком, и открывающая кавычка бывает
    // только в начале — иначе это обычный символ
    assert.deepEqual(parseClipboard('Дюйм 5"\tТема\n'), [['Дюйм 5"', 'Тема']])
  })

  it('пустые ячейки посередине сохраняются', () => {
    assert.deepEqual(parseClipboard('\t\tПовторение\n'), [['', '', 'Повторение']])
  })

  it('строки разной длины приезжают как есть — дополнит сетка', () => {
    assert.deepEqual(parseClipboard('Тема\nа\tб\tв\n'), [['Тема'], ['а', 'б', 'в']])
  })
})

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

import { detectIds, parsePlanCsv } from '../src/planCsv.js'

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

/**
 * Стрелки в ряду клеток с баллами.
 *
 * Под тестами потому, что ошибка тут не падает: она уводит курсор не туда, и
 * балл, набранный не глядя, ложится в соседнюю клетку. Заметить это можно
 * только сличив экран с бумагой, а клавиатурой пользуются как раз затем,
 * чтобы не сличать каждую цифру.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import { digits, neighbour } from '../src/cellKeys.js'

const at = (fields) =>
  neighbour({ start: 0, end: 0, length: 0, position: 3, count: 16, ...fields })

test('в пустой клетке стрелки уводят в обе стороны', () => {
  assert.equal(at({ key: 'ArrowRight' }), 4)
  assert.equal(at({ key: 'ArrowLeft' }), 2)
})

test('курсор в конце числа: вправо уводит, влево остаётся в клетке', () => {
  const end = { start: 2, end: 2, length: 2 }

  assert.equal(at({ key: 'ArrowRight', ...end }), 4)
  assert.equal(at({ key: 'ArrowLeft', ...end }), null)
})

test('курсор в начале числа: влево уводит, вправо остаётся в клетке', () => {
  const start = { start: 0, end: 0, length: 2 }

  assert.equal(at({ key: 'ArrowLeft', ...start }), 2)
  assert.equal(at({ key: 'ArrowRight', ...start }), null)
})

test('курсор посреди числа не уводит никуда', () => {
  // иначе поправить вторую цифру нельзя, не уехав из клетки
  const middle = { start: 1, end: 1, length: 2 }

  assert.equal(at({ key: 'ArrowLeft', ...middle }), null)
  assert.equal(at({ key: 'ArrowRight', ...middle }), null)
})

test('выделенное целиком — край в обе стороны', () => {
  // придя стрелкой, человек застаёт содержимое выделенным; считай мы это
  // «курсором внутри», на каждую клетку уходило бы два нажатия
  const whole = { start: 0, end: 1, length: 1 }

  assert.equal(at({ key: 'ArrowRight', ...whole }), 4)
  assert.equal(at({ key: 'ArrowLeft', ...whole }), 2)
})

test('выделенная часть числа краем не считается', () => {
  const part = { start: 0, end: 1, length: 2 }

  assert.equal(at({ key: 'ArrowRight', ...part }), null)
  assert.equal(at({ key: 'ArrowLeft', ...part }), null)
})

test('за край ряда стрелка не уводит', () => {
  assert.equal(at({ key: 'ArrowLeft', position: 0 }), null)
  assert.equal(at({ key: 'ArrowRight', position: 15 }), null)
})

test('прочие клавиши ряд не трогают', () => {
  for (const key of ['ArrowUp', 'ArrowDown', 'Enter', 'Tab', '5']) {
    assert.equal(at({ key }), null, key)
  }
})

test('неизвестное положение курсора — никуда не идём', () => {
  // числовое поле положения не отдаёт; увести наугад хуже, чем остаться
  assert.equal(at({ key: 'ArrowRight', start: null, end: null }), null)
  assert.equal(at({ key: 'ArrowRight', start: undefined, end: undefined }), null)
})

test('в клетку попадают только цифры, не больше двух', () => {
  assert.equal(digits('3'), '3')
  assert.equal(digits('12'), '12')
  assert.equal(digits('123'), '12')
  assert.equal(digits('1a'), '1')
  assert.equal(digits(' 7 '), '7')
  assert.equal(digits('-2'), '2')
  assert.equal(digits(''), '')
  assert.equal(digits(null), '')
})

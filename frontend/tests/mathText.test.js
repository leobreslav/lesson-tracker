/** Формулы в однострочном названии: что считается формулой, а что долларом. */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { hasMath, splitMath } from '../src/mathText.js'

describe('формулы в названии', () => {
  it('без долларов ничего не находит — по этому и не грузится KaTeX', () => {
    assert.equal(hasMath('Синус суммы'), false)
    assert.equal(hasMath(''), false)
    assert.equal(hasMath(null), false)
    assert.deepEqual(splitMath('Синус суммы'), [
      { math: false, text: 'Синус суммы' },
    ])
  })

  it('режет строку на текст и формулы по порядку', () => {
    assert.equal(hasMath('Формула $\\sin(a+b)$ и дальше'), true)
    assert.deepEqual(splitMath('Формула $\\sin(a+b)$ и дальше'), [
      { math: false, text: 'Формула ' },
      { math: true, text: '\\sin(a+b)' },
      { math: false, text: ' и дальше' },
    ])
  })

  it('двойные доллары — та же формула: выключать в названии нечего', () => {
    assert.deepEqual(splitMath('$$x^2$$'), [{ math: true, text: 'x^2' }])
  })

  it('одинокий доллар остаётся долларом', () => {
    assert.equal(hasMath('Задача про $5'), false)
    assert.deepEqual(splitMath('Задача про $5'), [
      { math: false, text: 'Задача про $5' },
    ])
  })

  it('две формулы в строке — обе', () => {
    const parts = splitMath('$a$ против $b$')
    assert.deepEqual(
      parts.map((part) => [part.math, part.text]),
      [
        [true, 'a'],
        [false, ' против '],
        [true, 'b'],
      ],
    )
  })
})

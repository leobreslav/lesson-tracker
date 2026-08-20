import assert from 'node:assert/strict'
import test from 'node:test'

import { prune } from '../src/expressionTree.js'

test('пустая группа исчезает вместе с пустым деревом', () => {
  assert.equal(prune({ all: [] }), null)
  assert.equal(prune({ any: [{ all: [] }] }), null)
  assert.equal(prune({ text: '   ' }), null)
})

test('группа из одного условия схлопывается в само условие', () => {
  assert.deepEqual(prune({ all: [{ tag: 5 }] }), { tag: 5 })
})

test('живые условия остаются, порядок сохраняется', () => {
  const tree = { any: [{ tag: 1 }, { all: [] }, { not: { tag: 2, side: 'uses' } }] }
  assert.deepEqual(prune(tree), {
    any: [{ tag: 1 }, { not: { tag: 2, side: 'uses' } }],
  })
})

test('отрицание пустоты — тоже пустота, а не «всё»', () => {
  assert.equal(prune({ not: { all: [] } }), null)
})

/**
 * The one place the Markdown pipeline is bent to fit how people write.
 *
 * Tested against hand-built trees rather than through remark: the rule is
 * about tree shapes, and building them by hand states the rule more plainly
 * than a paragraph of Markdown would.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loneMath, promote } from '../src/markdownMath.js'

const math = (value) => ({ type: 'inlineMath', value })
const text = (value) => ({ type: 'text', value })
const para = (...children) => ({ type: 'paragraph', children })

test('a paragraph that is only a formula becomes a displayed one', () => {
  const tree = { type: 'root', children: [para(math('a^2 + b^2 = c^2'))] }

  assert.equal(promote(tree), 1)
  assert.deepEqual(tree.children[0], {
    type: 'math',
    value: 'a^2 + b^2 = c^2',
    data: {
      hName: 'div',
      hProperties: { className: ['math', 'math-display'] },
      hChildren: [{ type: 'text', value: 'a^2 + b^2 = c^2' }],
    },
  })
})

test('the class is what rehype-katex reads, so it must say display', () => {
  // carrying the original node's data across would keep the formula inline
  // while calling it display — the failure this whole file exists to prevent
  const tree = {
    type: 'root',
    children: [
      { type: 'paragraph', children: [{ type: 'inlineMath', value: 'x', data: {
        hName: 'span',
        hProperties: { className: ['math', 'math-inline'] },
      } }] },
    ],
  }

  promote(tree)
  assert.deepEqual(tree.children[0].data.hProperties.className, [
    'math',
    'math-display',
  ])
})

test('surrounding whitespace does not stop it', () => {
  const tree = { type: 'root', children: [para(text('  '), math('x'), text('\n'))] }

  assert.equal(promote(tree), 1)
  assert.equal(tree.children[0].type, 'math')
})

test('a formula with words around it stays inline', () => {
  const tree = {
    type: 'root',
    children: [para(text('где '), math('x'), text(' — сторона'))],
  }

  assert.equal(promote(tree), 0)
  assert.equal(tree.children[0].type, 'paragraph')
})

test('two formulas in one paragraph stay inline', () => {
  assert.equal(loneMath(para(math('a'), text(' и '), math('b'))), null)
  assert.equal(loneMath(para(math('a'), math('b'))), null)
})

test('it reaches into lists and quotes', () => {
  const item = { type: 'listItem', children: [para(math('x'))] }
  const tree = { type: 'root', children: [{ type: 'list', children: [item] }] }

  assert.equal(promote(tree), 1)
  assert.equal(tree.children[0].children[0].children[0].type, 'math')
})

test('nothing else is touched', () => {
  const heading = { type: 'heading', depth: 2, children: [text('Тема')] }
  const tree = { type: 'root', children: [heading, para(text('обычный текст'))] }

  assert.equal(promote(tree), 0)
  assert.deepEqual(tree.children, [heading, para(text('обычный текст'))])
})

/**
 * The two bends in the Markdown pipeline that pictures need.
 *
 * Tested against hand-built trees, like `markdownMath.test.js` and for the
 * same reason: the rules are about tree shapes, and a tree written out says
 * them more plainly than a paragraph of Markdown put through remark.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import remarkImageAttributes, {
  absorb,
  describe as describeImage,
  remarkBlockOffsets,
} from '../src/markdownImages.js'

const at = (offset, length) => ({
  start: { offset },
  end: { offset: offset + length },
})

const image = (url, position) => ({ type: 'image', url, position })
const text = (value) => ({ type: 'text', value })
const para = (...children) => ({ type: 'paragraph', children })

test('an image says where in the source it was written', () => {
  const node = image('file:12', at(40, 12))
  describeImage(node, {})

  assert.deepEqual(node.data.hProperties, {
    className: ['md-image', 'md-image-block'],
    'data-offset': 40,
  })
})

test('the braces after an image become its size and its placement', () => {
  const tree = para(image('file:12', at(0, 12)), text('{width=320 .right}'))

  assert.equal(absorb(tree), 1)
  assert.deepEqual(tree.children[0].data.hProperties, {
    className: ['md-image', 'md-image-right'],
    width: 320,
    'data-offset': 0,
  })
  // the literal braces are gone — otherwise they would be printed on the page
  assert.equal(tree.children.length, 1)
})

test('words after the braces stay where they were', () => {
  const tree = para(image('file:1', at(0, 11)), text('{.center} и дальше'))

  assert.equal(absorb(tree), 1)
  assert.deepEqual(tree.children[1], text(' и дальше'))
})

test('braces that are not attributes are left alone', () => {
  const tree = para(image('file:1', at(0, 11)), text(' {это просто текст}'))

  assert.equal(absorb(tree), 0)
  assert.equal(tree.children.length, 2)
  assert.equal(tree.children[0].data.hProperties.className[1], 'md-image-block')
})

test('the plugin reaches images nested inside other blocks', () => {
  const tree = {
    type: 'root',
    children: [
      { type: 'blockquote', children: [para(image('file:5', at(2, 11)), text('{width=80}'))] },
    ],
  }

  remarkImageAttributes()(tree)

  const [quoted] = tree.children[0].children[0].children
  assert.equal(quoted.data.hProperties.width, 80)
})

test('top-level blocks carry the offsets they start at', () => {
  const tree = {
    type: 'root',
    children: [
      { ...para(text('раз')), position: at(0, 3) },
      { ...para(text('два')), position: at(5, 3) },
    ],
  }

  remarkBlockOffsets()(tree)

  assert.deepEqual(
    tree.children.map((node) => node.data.hProperties['data-block']),
    [0, 5],
  )
  assert.equal(tree.children[1].data.hProperties['data-block-end'], 8)
})

test('a block that came from nowhere is labelled with nothing', () => {
  // remark plugins may replace a node with one of their own making, and a
  // made-up node has no place in the source to point at
  const tree = { type: 'root', children: [para(text('раз'))] }

  remarkBlockOffsets()(tree)

  assert.equal(tree.children[0].data, undefined)
})

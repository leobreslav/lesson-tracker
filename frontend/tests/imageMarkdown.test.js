/**
 * The string surgery behind pasting, resizing and dragging a picture.
 *
 * Everything the editor does to an image ends up here, as characters put
 * into and taken out of a piece of Markdown, so this is where the rules are
 * actually stated: a picture stands alone as a paragraph, a move leaves no
 * hole behind, and nothing else in the text is touched.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  findImages,
  formatAttrs,
  imageAt,
  imageToken,
  insertAsBlock,
  moveImage,
  parseAttrs,
  removeImage,
  writeImage,
} from '../src/imageMarkdown.js'

test('an image with nothing said about it carries no braces', () => {
  assert.equal(imageToken({ file: 12 }), '![](file:12)')
  assert.equal(formatAttrs({ width: null, placement: 'block' }), '')
})

test('size and placement are written the way Pandoc reads them', () => {
  assert.equal(
    imageToken({ file: 7, alt: 'схема', width: 320.4, placement: 'right' }),
    '![схема](file:7){width=320 .right}',
  )
})

test('attributes are read back, and an unknown one is ignored', () => {
  assert.deepEqual(parseAttrs('width=320 .right'), {
    width: 320,
    placement: 'right',
  })
  assert.deepEqual(parseAttrs('.center'), { width: null, placement: 'center' })
  assert.deepEqual(parseAttrs('#id .nonsense'), {
    width: null,
    placement: 'block',
  })
})

test('images are found with the exact characters they occupy', () => {
  const text = 'до\n\n![](file:3){width=100}\n\nпосле ![x](file:4) внутри'
  const [first, second] = findImages(text)

  assert.equal(findImages(text).length, 2)
  assert.equal(text.slice(first.start, first.end), '![](file:3){width=100}')
  assert.deepEqual(
    { file: first.file, width: first.width, placement: first.placement },
    { file: 3, width: 100, placement: 'block' },
  )
  assert.equal(text.slice(second.start, second.end), '![x](file:4)')
  assert.equal(imageAt(text, second.start).alt, 'x')
  assert.equal(imageAt(text, second.start + 1), null)
})

test('a picture pasted mid-sentence still becomes its own paragraph', () => {
  const { text, caret } = insertAsBlock('раз два', 3, '![](file:1)')

  assert.equal(text, 'раз\n\n![](file:1)\n\n два')
  assert.equal(text.slice(0, caret), 'раз\n\n![](file:1)')
})

test('pasting where a paragraph already ends adds no extra blank line', () => {
  assert.equal(
    insertAsBlock('раз\n\n', null, '![](file:1)').text,
    'раз\n\n![](file:1)',
  )
  assert.equal(insertAsBlock('', 0, '![](file:1)').text, '![](file:1)')
})

test('removing a picture closes the gap it leaves', () => {
  const text = 'раз\n\n![](file:1)\n\nдва'
  assert.equal(removeImage(text, findImages(text)[0]), 'раз\n\nдва')
})

test('resizing rewrites one image and nothing around it', () => {
  const text = 'раз\n\n![](file:1)\n\n![](file:2){width=50}'
  const changed = writeImage(text, findImages(text)[0], { width: 240 })

  assert.equal(changed, 'раз\n\n![](file:1){width=240}\n\n![](file:2){width=50}')
})

test('a picture dragged downwards lands before the block it was dropped on', () => {
  const text = '![](file:1)\n\nраз\n\nдва'
  const image = findImages(text)[0]
  // «два» starts here in the text as it stands now
  const at = text.indexOf('два')

  assert.equal(moveImage(text, image, at), 'раз\n\n![](file:1)\n\nдва')
})

test('a picture dragged upwards lands before the block it was dropped on', () => {
  const text = 'раз\n\nдва\n\n![](file:1){width=200}'
  const image = findImages(text)[0]

  assert.equal(
    moveImage(text, image, text.indexOf('два')),
    'раз\n\n![](file:1){width=200}\n\nдва',
  )
})

test('two pictures swap places when one is dropped in front of the other', () => {
  const text = '![](file:1)\n\n![](file:2)'
  const second = findImages(text)[1]

  assert.equal(moveImage(text, second, 0), '![](file:2)\n\n![](file:1)')
})

test('dragging to the very end puts the picture last', () => {
  const text = '![](file:1)\n\nраз'
  const image = findImages(text)[0]

  assert.equal(moveImage(text, image, text.length), 'раз\n\n![](file:1)')
})

test('a hard line break survives every edit', () => {
  // two trailing spaces are a line break in Markdown, and tidying up after
  // a move must not quietly rewrite somebody's verse
  const text = 'раз  \nдва\n\n![](file:1)'
  const image = findImages(text)[0]

  assert.equal(moveImage(text, image, 0), '![](file:1)\n\nраз  \nдва')
})

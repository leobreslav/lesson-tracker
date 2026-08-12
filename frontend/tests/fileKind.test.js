/**
 * Sizes and icons — the pure half of the attachment list.
 *
 * Worth testing because both are easy to get subtly wrong and neither shows
 * up as a crash: a file listed as «0 KB» or with the wrong icon just looks
 * slightly broken forever.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatSize, iconFor } from '../src/fileKind.js'

test('bytes stay bytes, kilobytes round, megabytes keep a decimal', () => {
  assert.deepEqual(formatSize(0), { unit: 'b', value: 0 })
  assert.deepEqual(formatSize(999), { unit: 'b', value: 999 })
  assert.deepEqual(formatSize(2048), { unit: 'kb', value: 2 })
  assert.deepEqual(formatSize(1024 * 1024 * 1.5), { unit: 'mb', value: 1.5 })
})

test('a file smaller than a kilobyte but not tiny never reads as zero', () => {
  // 1100 bytes is 1.07 KB; rounding it to 1 is fine, rounding to 0 is not
  assert.deepEqual(formatSize(1100), { unit: 'kb', value: 1 })
  assert.deepEqual(formatSize(1025), { unit: 'kb', value: 1 })
})

test('a missing size says nothing rather than guessing', () => {
  assert.equal(formatSize(undefined), null)
  assert.equal(formatSize(null), null)
  assert.equal(formatSize(-1), null)
})

test('the icon follows the extension, then the declared type', () => {
  assert.equal(iconFor({ kind: 'file', file_name: 'plan.PDF' }), '📕')
  assert.equal(iconFor({ kind: 'file', file_name: 'sheet.xlsx' }), '📗')
  assert.equal(
    iconFor({ kind: 'file', file_name: 'scan', content_type: 'image/heic' }),
    '🖼️',
  )
  assert.equal(iconFor({ kind: 'file', file_name: 'thing.bin' }), '📎')
  assert.equal(iconFor({ kind: 'link', url: 'https://example.org' }), '🔗')
})

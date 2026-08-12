/**
 * What a file looks like in a list: an icon and a readable size.
 *
 * Pure, and therefore under test. The unit comes back as a code word rather
 * than as text — «КБ» and «KB» are the dictionary's business, not this
 * module's, the same rule the rest of the shared logic follows.
 */

const BY_EXTENSION = {
  pdf: '📕',
  doc: '📘',
  docx: '📘',
  xls: '📗',
  xlsx: '📗',
  ppt: '📙',
  pptx: '📙',
  txt: '📄',
  zip: '🗜️',
  png: '🖼️',
  jpg: '🖼️',
  jpeg: '🖼️',
  gif: '🖼️',
  webp: '🖼️',
  svg: '🖼️',
}

const KB = 1024
const MB = KB * 1024

/** The icon for an attachment: by extension first, by declared type second. */
export function iconFor({ kind, file_name: name, content_type: type } = {}) {
  if (kind === 'link') return '🔗'

  const extension = String(name || '')
    .split('.')
    .pop()
    .toLowerCase()
  if (BY_EXTENSION[extension]) return BY_EXTENSION[extension]

  if (String(type || '').startsWith('image/')) return '🖼️'
  return '📎'
}

/**
 * `{unit, value}` for a byte count, or null when there is nothing to say.
 *
 * Megabytes keep one decimal and everything below is whole: «1.4 МБ» is
 * useful, «1434 КБ» is noise next to a file name.
 */
export function formatSize(bytes) {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes < 0) return null

  if (bytes < KB) return { unit: 'b', value: bytes }
  if (bytes < MB) return { unit: 'kb', value: Math.max(1, Math.round(bytes / KB)) }

  return { unit: 'mb', value: Math.round((bytes / MB) * 10) / 10 }
}

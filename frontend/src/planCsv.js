/**
 * Client-side parsing of a plan CSV — purely for the preview.
 *
 * A mirror of `parse_plan_csv` from plans/services.py: we show exactly what
 * the server will see. The server still does the import and stays the
 * authority. Warnings carry the same shape as the server's — {code, params} —
 * so both are rendered through the same `warnings.*` keys.
 */

// header words in both languages: this recognises the file, not the interface
const HEADER_CELLS = new Set([
  'тема', 'темы', 'раздел', 'topic', 'section',
  'урок', 'уроки', 'название', 'тема урока', 'lesson',
  'заметка', 'заметки', 'примечание', 'комментарий', 'note',
])

const TITLE_LIMIT = 200
export const MAX_ROWS = 2000

/** File bytes into text: UTF-8, else Windows-1251 (Excel on Windows). */
export function decodeCsv(buffer) {
  try {
    return new TextDecoder('utf-8', { fatal: true })
      .decode(buffer)
      .replace(/^﻿/, '')
  } catch {
    return new TextDecoder('windows-1251').decode(buffer)
  }
}

/** Row parsing that respects quotes: "a, b" is one cell. */
function readRows(text, delimiter) {
  const rows = []
  let row = ['']
  let quoted = false

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]

    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          row[row.length - 1] += '"'
          index += 1
        } else {
          quoted = false
        }
      } else {
        row[row.length - 1] += char
      }
      continue
    }

    if (char === '"') quoted = true
    else if (char === delimiter) row.push('')
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[index + 1] === '\n') index += 1
      rows.push(row)
      row = ['']
    } else row[row.length - 1] += char
  }

  rows.push(row)
  return rows
}

export function sniffDelimiter(text) {
  const head = text.split(/\r?\n/).filter((line) => line.trim()).slice(0, 5)
  if (!head.length) return ','

  const score = (delimiter) => {
    const widths = readRows(head.join('\n'), delimiter).map((row) => row.length)
    const same = new Set(widths).size === 1
    return [same && Math.min(...widths) > 1, Math.min(...widths)]
  }

  const [semiSame, semiWidth] = score(';')
  const [commaSame, commaWidth] = score(',')
  const better = semiSame !== commaSame ? semiSame : semiWidth > commaWidth
  return better ? ';' : ','
}

function looksLikeHeader(cells) {
  const filled = cells.map((cell) => cell.trim().toLowerCase()).filter(Boolean)
  return filled.length > 0 && filled.every((cell) => HEADER_CELLS.has(cell))
}

export function parsePlanCsv(text) {
  const rows = []
  const warnings = []
  let theme = null

  readRows(text, sniffDelimiter(text)).forEach((raw, index) => {
    const number = index + 1
    if (number > MAX_ROWS) return

    const cells = [0, 1, 2].map((position) => (raw[position] ?? '').trim())
    const [themeCell, lessonCell, note] = cells

    if (number === 1 && looksLikeHeader(cells)) return

    if (!themeCell && !lessonCell) {
      if (raw.some((cell) => cell.trim())) {
        warnings.push({ code: 'csv_row_empty', params: { row: number } })
      }
      return
    }

    if (Math.max(themeCell.length, lessonCell.length) > TITLE_LIMIT) {
      warnings.push({
        code: 'csv_row_too_long',
        params: { row: number, limit: TITLE_LIMIT },
      })
      return
    }

    if (themeCell && !lessonCell) {
      theme = themeCell
      rows.push({ is_section: true, title: themeCell, note })
      return
    }

    if (themeCell && themeCell !== theme) {
      theme = themeCell
      rows.push({ is_section: true, title: themeCell, note: '' })
    }

    rows.push({ is_section: false, title: lessonCell, note })
  })

  return { rows, warnings }
}

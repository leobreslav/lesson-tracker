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

// the first header cell when the file carries the id column
const ID_CELLS = new Set(['id', 'ид', '№'])

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
  // записи, а не строки: перевод строки внутри кавычек — часть заметки, и,
  // порезав текст по \n, мы сравнивали бы обрывки
  const score = (delimiter) => {
    const widths = readRows(text, delimiter)
      .filter((row) => row.some((cell) => cell.trim()))
      .slice(0, 5)
      .map((row) => row.length)
    if (!widths.length) return [false, 0]
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

function headerWithIds(cells) {
  if (!cells.length || !ID_CELLS.has(cells[0].trim().toLowerCase())) return false
  const rest = cells.slice(1)
  return looksLikeHeader(rest) || !rest.some((cell) => cell.trim())
}

/**
 * Is the theme written on every lesson row?
 *
 * That is what decides the meaning of an **empty** theme cell: in a file
 * that repeats the theme, emptiness means «this lesson is outside a
 * section»; in a file written as «a header, then lessons under it» it means
 * nothing at all. Mirrors `uses_spread` on the server.
 */
export function usesSpread(rawRows, shift) {
  return rawRows.some((raw) => {
    const theme = (raw[shift] ?? '').trim()
    const lesson = (raw[shift + 1] ?? '').trim()
    return Boolean(theme && lesson)
  })
}

/** Does the file carry an id column? Decided over the file, not per row. */
export function detectIds(rawRows) {
  const filled = rawRows.filter((row) => row.some((cell) => cell.trim()))
  if (!filled.length) return false
  if (headerWithIds(filled[0])) return true
  if (Math.max(...filled.map((row) => row.length)) < 4) return false

  const first = filled.map((row) => (row[0] ?? '').trim())
  return (
    first.some(Boolean) && first.every((cell) => cell === '' || /^\d+$/.test(cell))
  )
}

export function parsePlanCsv(text) {
  const rows = []
  const warnings = []
  let theme = null

  const raws = readRows(text, sniffDelimiter(text))
  const hasIds = detectIds(raws)
  const shift = hasIds ? 1 : 0
  // шапку в счёт не берём: «Тема» и «Урок» в ней стоят рядом заполненными и
  // выглядят в точности как строка урока с протянутой темой
  const first = raws[0] ?? []
  const header = hasIds ? headerWithIds(first) : looksLikeHeader(first)
  const spread = usesSpread(header ? raws.slice(1) : raws, shift)

  raws.forEach((raw, index) => {
    const number = index + 1
    if (number > MAX_ROWS) return

    const cells = [0, 1, 2, 3]
      .slice(0, 3 + shift)
      .map((position) => (raw[position] ?? '').trim())
    const [idCell, themeCell, lessonCell, note] = hasIds ? cells : ['', ...cells]

    if (number === 1 && (hasIds ? headerWithIds(cells) : looksLikeHeader(cells))) return

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

    const id = /^\d+$/.test(idCell) ? Number(idCell) : null

    if (themeCell && !lessonCell) {
      theme = themeCell
      rows.push({ is_section: true, title: themeCell, note, id })
      return
    }

    if (themeCell && themeCell !== theme) {
      theme = themeCell
      rows.push({ is_section: true, title: themeCell, note: '', id: null })
    }

    rows.push({
      is_section: false,
      title: lessonCell,
      note,
      id,
      // an empty theme cell means «outside a section» only in a file that
      // writes the theme on every lesson row — see usesSpread
      at_top_level: spread && !themeCell,
    })
  })

  return { rows, warnings, hasIds }
}

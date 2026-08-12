/**
 * Разбор CSV учебного плана на клиенте — только ради предпросмотра.
 *
 * Зеркало `parse_plan_csv` из plans/services.py: показываем то же, что
 * увидит сервер. Импортирует всё равно сервер, он же и авторитет.
 */

const HEADER_CELLS = new Set([
  'тема', 'темы', 'раздел', 'topic', 'section',
  'урок', 'уроки', 'название', 'тема урока', 'lesson',
  'заметка', 'заметки', 'примечание', 'комментарий', 'note',
])

const TITLE_LIMIT = 200
export const MAX_ROWS = 2000

/** Байты файла в текст: UTF-8, иначе Windows-1251 (Excel на Windows). */
export function decodeCsv(buffer) {
  try {
    return new TextDecoder('utf-8', { fatal: true })
      .decode(buffer)
      .replace(/^﻿/, '')
  } catch {
    return new TextDecoder('windows-1251').decode(buffer)
  }
}

/** Разбор строк с учётом кавычек: "а, б" — одна ячейка. */
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
        warnings.push(`Строка ${number}: нет ни темы, ни урока — пропущена.`)
      }
      return
    }

    if (Math.max(themeCell.length, lessonCell.length) > TITLE_LIMIT) {
      warnings.push(
        `Строка ${number}: название длиннее ${TITLE_LIMIT} символов — пропущена.`,
      )
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

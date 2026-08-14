/**
 * Клиентский разбор CSV учебного плана — зеркало `parse_plan_csv`.
 *
 * Формат ровно один: `id,Тема,Урок,Заметка`, шапка обязательна, одна строка —
 * один урок, тема повторяется в каждой строке. Пустая тема значит «урок вне
 * темы», пустой id — «урок новый». Стилей больше не три и угадывать нечего:
 * непонятная строка — ошибка всего файла с её номером.
 *
 * Зеркало нужно, чтобы предпросмотр показывал ровно то, что положит сервер;
 * коды ошибок здесь те же самые (`{code, params}`), поэтому и текст один и
 * тот же — из словаря `errors.*`. Импортирует всё равно сервер.
 */

const CSV_HEADER = ['id', 'Тема', 'Урок', 'Заметка']
const HEADER_TEXT = CSV_HEADER.join(',')
const HEADER_NORMALIZED = CSV_HEADER.map(normalizedCell)

const TITLE_LIMIT = 200
const MAX_ROWS = 2000

function normalizedCell(cell) {
  return cell.replace(/\s+/g, '').toLowerCase()
}

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

/**
 * Четыре ячейки строки — или null, если столбцов не четыре.
 *
 * Пустые столбцы справа Excel дописывает сам; заполненный пятый — уже
 * другой файл.
 */
function rowCells(raw) {
  const width = CSV_HEADER.length
  if (raw.length < width) return null
  if (raw.slice(width).some((cell) => cell.trim())) return null
  return raw.slice(0, width).map((cell) => cell.trim())
}

const problem = (code, params) => ({ code, params })

export function parsePlanCsv(text) {
  const raws = readRows(text, sniffDelimiter(text))

  if (raws.length > MAX_ROWS + 1) {
    return { rows: [], errors: [problem('file_too_many_rows', {})], dataRows: 0 }
  }

  const head = raws.length ? rowCells(raws[0]) : null
  const headerOk =
    head !== null &&
    head.every((cell, index) => normalizedCell(cell) === HEADER_NORMALIZED[index])

  if (!headerOk) {
    return {
      rows: [],
      dataRows: 0,
      errors: [
        problem('csv_header_invalid', {
          expected: HEADER_TEXT,
          got: raws.length ? raws[0].join(',') : '',
        }),
      ],
    }
  }

  const rows = []
  const errors = []
  let currentTheme = null
  let dataRows = 0

  raws.slice(1).forEach((raw, index) => {
    const row = index + 2
    if (!raw.some((cell) => cell.trim())) return // пустая строка от Excel

    dataRows += 1

    const cells = rowCells(raw)
    if (cells === null) {
      errors.push(problem('csv_bad_columns', { row, count: raw.length }))
      return
    }

    const [idCell, theme, lesson, note] = cells

    if (theme && !lesson) {
      errors.push(problem('csv_section_row', { row, title: theme }))
      return
    }

    if (!theme && !lesson) {
      errors.push(problem('csv_row_empty', { row }))
      return
    }

    if (Math.max(theme.length, lesson.length) > TITLE_LIMIT) {
      errors.push(problem('csv_row_too_long', { row, limit: TITLE_LIMIT }))
      return
    }

    let id = null
    if (idCell) {
      if (!/^\d+$/.test(idCell) || Number(idCell) === 0) {
        errors.push(problem('csv_bad_id', { row, value: idCell }))
        return
      }
      id = Number(idCell)
    }

    if (theme !== currentTheme) {
      currentTheme = theme
      if (theme) rows.push({ is_section: true, title: theme, note: '', id: null })
    }

    rows.push({
      is_section: false,
      title: lesson,
      note,
      id,
      at_top_level: !theme,
    })
  })

  return { rows, errors, dataRows }
}

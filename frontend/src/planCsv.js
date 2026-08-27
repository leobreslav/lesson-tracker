/**
 * Клиентский разбор CSV учебного плана — зеркало `parse_plan_csv`.
 *
 * Формат ровно один: `id,Тема,Урок`, шапка обязательна, одна строка —
 * один урок, тема повторяется в каждой строке. Пустая тема значит «урок вне
 * темы», пустой id — «урок новый». Стилей больше не три и угадывать нечего:
 * непонятная строка — ошибка всего файла с её номером.
 *
 * Зеркало нужно, чтобы предпросмотр показывал ровно то, что положит сервер;
 * коды ошибок здесь те же самые (`{code, params}`), поэтому и текст один и
 * тот же — из словаря `errors.*`. Импортирует всё равно сервер.
 */

const CSV_HEADER = ['id', 'Тема', 'Урок']
/**
 * Тот же формат плюс столбец дат — им выгружают план «с датами».
 *
 * Дата в плане не живёт: её даёт раскладка, то есть расписание, и приехать
 * обратно ей некуда. Поэтому столбец читается и отбрасывается, а не отвергает
 * файл: иначе собственная выгрузка не ложилась бы обратно. Зеркало сервера
 * (`services.CSV_HEADER_DATED`) — правьте оба места вместе.
 */
const CSV_HEADER_DATED = [...CSV_HEADER, 'Дата']
const HEADER_TEXT = CSV_HEADER.join(',')
const HEADER_NORMALIZED = CSV_HEADER.map(normalizedCell)
const HEADER_DATED_NORMALIZED = CSV_HEADER_DATED.map(normalizedCell)

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
 * Ячейки строки по объявленной ширине — или null, если столбцов не столько.
 *
 * Ширину называет шапка: три столбца у обычного файла, четыре у файла с
 * датами. Пустые столбцы справа Excel дописывает сам; заполненный столбец за
 * объявленной шириной — уже другой файл.
 */
function rowCells(raw, width = CSV_HEADER.length) {
  if (raw.length < width) return null
  if (raw.slice(width).some((cell) => cell.trim())) return null
  return raw.slice(0, width).map((cell) => cell.trim())
}

/**
 * Сколько столбцов объявила первая строка: три, четыре — или null, не шапка.
 *
 * Шапки ровно две, и обе сравниваются дословно. Угадыванием ширины это не
 * является: либо шапка совпала целиком, либо файл отклонён — как и раньше.
 */
function headerWidth(raw) {
  for (const expected of [HEADER_NORMALIZED, HEADER_DATED_NORMALIZED]) {
    const head = rowCells(raw, expected.length)
    if (
      head !== null &&
      head.every((cell, index) => normalizedCell(cell) === expected[index])
    ) {
      return expected.length
    }
  }
  return null
}

const problem = (code, params) => ({ code, params })

export function parsePlanCsv(text) {
  const raws = readRows(text, sniffDelimiter(text))

  if (raws.length > MAX_ROWS + 1) {
    return {
      rows: [],
      errors: [problem('file_too_many_rows', {})],
      dataRows: 0,
      datesIgnored: false,
    }
  }

  const width = raws.length ? headerWidth(raws[0]) : null

  if (width === null) {
    return {
      rows: [],
      dataRows: 0,
      datesIgnored: false,
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

    const cells = rowCells(raw, width)
    if (cells === null) {
      errors.push(
        problem('csv_bad_columns', { row, count: raw.length, expected: width })
      )
      return
    }

    // четвёртая ячейка — дата, и она отбрасывается здесь: дальше формат
    // ровно один, и знать про даты ему незачем
    const [idCell, theme, lesson] = cells

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
      note: '',
      id,
      at_top_level: !theme,
    })
  })

  return { rows, errors, dataRows, datesIgnored: width > CSV_HEADER.length }
}

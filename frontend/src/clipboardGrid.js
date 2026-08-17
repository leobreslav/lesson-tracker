/**
 * Буфер обмена из Excel — в матрицу ячеек.
 *
 * Копируя лист, Excel и Google Sheets кладут в буфер TSV: колонки через
 * табуляцию, строки через перевод. Ячейка с табуляцией, переводом строки
 * или кавычкой приезжает в кавычках, а кавычка внутри удваивается — те же
 * правила, что у CSV, только разделитель другой.
 *
 * Разбирается это **здесь, в браузере**, там же, где происходит вставка:
 * серверу уезжают готовые ячейки, и `parse_plan_rows` принимает их так же,
 * как ячейки из книги. Второго разбора и второго угадывания разделителя
 * поэтому нет нигде.
 */

/**
 * TSV в матрицу строк.
 *
 * Пустой хвост отбрасывается: Excel почти всегда кладёт в конец перевод
 * строки, и без этого каждая вставка добавляла бы пустую строку.
 */
export function parseClipboard(text) {
  const rows = []
  let row = []
  let cell = ''
  let quoted = false

  const endCell = () => {
    row.push(cell)
    cell = ''
  }
  const endRow = () => {
    endCell()
    rows.push(row)
    row = []
  }

  for (let index = 0; index < text.length; index += 1) {
    const symbol = text[index]

    if (quoted) {
      if (symbol !== '"') {
        cell += symbol
      } else if (text[index + 1] === '"') {
        cell += '"'
        index += 1
      } else {
        quoted = false
      }
      continue
    }

    if (symbol === '"' && cell === '') {
      quoted = true
    } else if (symbol === '\t') {
      endCell()
    } else if (symbol === '\n') {
      endRow()
    } else if (symbol !== '\r') {
      cell += symbol
    }
  }

  if (cell !== '' || row.length) endRow()

  while (rows.length && rows[rows.length - 1].every((value) => !value.trim())) {
    rows.pop()
  }

  return rows
}

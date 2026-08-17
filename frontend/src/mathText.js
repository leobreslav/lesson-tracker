/**
 * Формулы в однострочном тексте — названии урока или темы.
 *
 * Содержание урока рисует `Markdown.jsx` целиком, со списками, заголовками
 * и выключными формулами. Названию всё это не нужно и вредно: оно живёт в
 * строке таблицы, обрезается многоточием и попадает в подсказку — абзац
 * или список сломали бы саму строку. Поэтому здесь разбирается **только**
 * математика, а остальное остаётся текстом.
 *
 * Разделители те же, что в содержании: `$…$` и `$$…$$`. Второе в одну
 * строку выключной формулой не делаем — выключать в названии нечего.
 */

const MATH = /\$\$([\s\S]+?)\$\$|\$([\s\S]+?)\$/g

/** Есть ли в строке хоть одна формула — по ней решается, грузить ли KaTeX. */
export function hasMath(text) {
  if (!text) return false

  MATH.lastIndex = 0
  return MATH.test(text)
}

/**
 * Куски строки: текст и формулы по порядку.
 *
 * Незакрытый доллар — просто доллар: в названии он бывает и сам по себе
 * («Задача про $5»), и превращать хвост строки в формулу из-за него
 * нельзя. Регулярное выражение требует пару, так что такой случай сюда
 * даже не доходит — он остаётся текстом.
 */
export function splitMath(text) {
  const parts = []
  let last = 0

  MATH.lastIndex = 0
  for (let found = MATH.exec(text); found; found = MATH.exec(text)) {
    if (found.index > last) {
      parts.push({ math: false, text: text.slice(last, found.index) })
    }
    parts.push({ math: true, text: found[1] ?? found[2] })
    last = found.index + found[0].length
  }

  if (last < text.length) parts.push({ math: false, text: text.slice(last) })

  return parts
}

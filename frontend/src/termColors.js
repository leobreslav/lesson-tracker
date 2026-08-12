/**
 * Цвета термов.
 *
 * Цвет привязан к порядковому номеру терма в году, а не к его id: так
 * первая четверть всегда одного цвета, сколько бы термов ни удаляли.
 * Классов пять, дальше цикл — больше пяти четвертей не бывает.
 */
export const TERM_COLORS = 5

export function termColorIndex(terms, termId) {
  const index = terms.findIndex((term) => term.id === termId)
  return index === -1 ? 0 : (index % TERM_COLORS) + 1
}

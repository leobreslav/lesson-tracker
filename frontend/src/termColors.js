/**
 * Term colours.
 *
 * The colour follows the term's position in the year, not its id: the first
 * quarter keeps its colour however many terms get deleted around it. There
 * are five classes and then it wraps — nobody has more than five quarters.
 */
export const TERM_COLORS = 5

export function termColorIndex(terms, termId) {
  const index = terms.findIndex((term) => term.id === termId)
  return index === -1 ? 0 : (index % TERM_COLORS) + 1
}

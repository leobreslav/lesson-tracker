/**
 * Where a week begins, per language.
 *
 * Separate from `dates.js` on purpose: this half depends on nothing but Intl,
 * so it is testable without booting i18next, and the weekday numbering it
 * speaks is ours (Monday is 0), not the CLDR one.
 */

// Intl.Locale.getWeekInfo is missing in some engines; this table covers ours
const FIRST_DAY_FALLBACK = { en: 6, 'en-GB': 0, ru: 0 }

/** First weekday of the week in our numbering: Monday is 0, Sunday is 6. */
export function firstWeekday(language) {
  try {
    // getWeekInfo counts 1 for Monday and 7 for Sunday
    const info = new Intl.Locale(language).getWeekInfo?.()
    if (info?.firstDay) return (info.firstDay - 1) % 7
  } catch {
    // an old engine or an unknown tag — the table below answers instead
  }

  const base = String(language).split('-')[0]
  return FIRST_DAY_FALLBACK[language] ?? FIRST_DAY_FALLBACK[base] ?? 0
}

/**
 * Week column order: our weekday numbers starting from the first day of the
 * week in this language. Russian gives [0…6], American English [6,0,…,5].
 */
export function weekOrder(language) {
  const first = firstWeekday(language)
  return Array.from({ length: 7 }, (_, index) => (first + index) % 7)
}

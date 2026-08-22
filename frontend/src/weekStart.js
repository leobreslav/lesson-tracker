/**
 * Where a week begins. Always Monday.
 *
 * It used to depend on the interface language: Russian read Monday first,
 * American English Sunday first. That is right for a wall calendar and wrong
 * here. A school week is Monday to Sunday whatever language the interface is
 * in, and everything below the surface already agrees — the backend numbers
 * weekdays from Monday (`date.weekday()`), `weekend_days` is written in those
 * numbers, and copying a period rounds the source to whole weeks starting
 * Monday. With the locale in charge, switching the interface to English
 * reflowed the timetable grid without a single lesson having moved.
 *
 * The numbering itself stays ours — Monday is 0, Sunday is 6 — and the
 * functions stay, because the column order is still built from them.
 */

/** First weekday of the week in our numbering: Monday is 0. */
export function firstWeekday() {
  return 0
}

/** Week column order: Monday through Sunday. */
export function weekOrder() {
  return [0, 1, 2, 3, 4, 5, 6]
}

/**
 * Номер дня недели у даты, в нашей нумерации: понедельник — 0.
 *
 * `Date.getDay()` считает от воскресенья, и это ровно та мелочь, на
 * которой ряды разъезжаются на день: сервер думает `date.weekday()`, то
 * есть от понедельника. Перевод живёт здесь, рядом с самим правилом.
 */
export function weekdayIndex(iso) {
  return (new Date(`${iso}T12:00:00`).getDay() + 6) % 7
}

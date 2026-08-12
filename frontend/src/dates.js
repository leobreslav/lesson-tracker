/**
 * Date formatting in the current language.
 *
 * No month or weekday name is spelled out here: Intl.DateTimeFormat provides
 * them, so adding a language needs no changes in this file.
 *
 * The internal weekday numbering stays the same as on the backend
 * (`date.weekday()`: Monday is 0). Only the column order of a week grid
 * depends on the language — that is what `weekOrder` is for.
 */

import i18n from './i18n'
import { parseDate } from './calendarLogic'
import { firstWeekday as firstWeekdayOf, weekOrder as weekOrderOf } from './weekStart'

const locale = () => i18n.language || 'en'

const cache = new Map()

function formatter(options) {
  const key = `${locale()}|${JSON.stringify(options)}`
  if (!cache.has(key)) cache.set(key, new Intl.DateTimeFormat(locale(), options))
  return cache.get(key)
}

const format = (iso, options) => formatter(options).format(parseDate(iso))

/** "14 Oct" — for dense lists. */
export const shortDate = (iso) => format(iso, { day: 'numeric', month: 'short' })

/** "14 October 2026" */
export const longDate = (iso) =>
  format(iso, { day: 'numeric', month: 'long', year: 'numeric' })

/** "Wednesday, 14 October" — the heading of a single-day dialog. */
export const weekdayWithDate = (iso) =>
  format(iso, { weekday: 'long', day: 'numeric', month: 'long' })

/** "Mon" — a column heading in the schedule grid. */
export const shortWeekday = (iso) => format(iso, { weekday: 'short' })

/** "October 2026" — a month heading. */
export const monthTitle = (iso) => format(iso, { month: 'long', year: 'numeric' })

/** "10/14/2026" — an all-numeric date. */
export const numericDate = (iso) => format(iso, { dateStyle: 'short' })

/** A span of dates on one line. */
export function dateRange(startIso, endIso) {
  return `${shortDate(startIso)} — ${shortDate(endIso)}`
}

/** First weekday of the current language, in our numbering (Monday is 0). */
export const firstWeekday = (language = locale()) => firstWeekdayOf(language)

/** Week column order for the current language. */
export const weekOrder = (language = locale()) => weekOrderOf(language)

/** Short weekday labels in the order this language reads them. */
export function weekdayHeadings(language = locale()) {
  return weekOrder(language).map((weekday) => ({
    weekday,
    // 2026-01-05 is a Monday, so our weekday number is the offset from it
    label: shortWeekday(addIsoDays('2026-01-05', weekday)),
  }))
}

function addIsoDays(iso, count) {
  const date = parseDate(iso)
  date.setDate(date.getDate() + count)
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/**
 * Calendar markup on the client.
 *
 * A mirror of calendars/services.py: it exists so that editing a day shows up
 * in the grid and in the counters at once, without waiting for the server.
 * The server stays the authority — after a successful request the days are
 * re-read from /days/. Change the priority of kinds there, change it here.
 *
 * Priority (the long reasoning lives at the top of services.py):
 * moved workday → weekend → holiday → break → study day.
 * A day holds exactly one status, so the per-status counters always add up to
 * the number of calendar days in the period.
 *
 * No wording lives here: statuses and kinds are codes, and the interface
 * looks them up in `dayStatus.*` / `calendar.kind.*`.
 */

export const KIND_HOLIDAY = 'holiday'
export const KIND_VACATION = 'vacation'
export const KIND_WORKDAY = 'workday'

export const STATUS_STUDY = 'study'
const STATUS_HOLIDAY = 'holiday'
export const STATUS_VACATION = 'vacation'
export const STATUS_WEEKEND = 'weekend'

const WEEKDAYS = 7

export const STATUSES = [STATUS_STUDY, STATUS_HOLIDAY, STATUS_VACATION, STATUS_WEEKEND]

/** A YYYY-MM-DD date into a Date at noon (noon survives DST shifts). */
export function parseDate(iso) {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day, 12)
}

export function formatDate(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/** Weekday number: Monday is 0, the same as on the backend. */
export function weekdayOf(iso) {
  return (parseDate(iso).getDay() + 6) % 7
}

export function addDays(iso, count) {
  const date = parseDate(iso)
  date.setDate(date.getDate() + count)
  return formatDate(date)
}

/** How many days from one date to another (noon survives DST shifts). */
export function daysBetween(fromIso, toIso) {
  return Math.round((parseDate(toIso) - parseDate(fromIso)) / 86400000)
}

export function eachDate(startIso, endIso) {
  const dates = []
  const current = parseDate(startIso)
  const end = parseDate(endIso)

  while (current <= end) {
    dates.push(formatDate(current))
    current.setDate(current.getDate() + 1)
  }

  return dates
}

/**
 * Typical breaks for a year starting in September of the given year.
 *
 * The dates are deliberately approximate: one button offers them and the
 * teacher then moves them to fit their school. The same values are created by
 * the demo set on the server (onboarding/services.py).
 *
 * The titles arrive from the caller: they are saved into the database, so
 * they are written in the teacher's language, not in the module's.
 */
export function suggestVacations(startYear, titles = {}) {
  return [
    {
      title: titles.autumn ?? 'Autumn break',
      start_date: `${startYear}-10-26`,
      end_date: `${startYear}-11-03`,
    },
    {
      title: titles.winter ?? 'Winter break',
      start_date: `${startYear}-12-28`,
      end_date: `${startYear + 1}-01-08`,
    },
    {
      title: titles.spring ?? 'Spring break',
      start_date: `${startYear + 1}-03-23`,
      end_date: `${startYear + 1}-03-31`,
    },
  ]
}

/**
 * First day of the week the date falls into.
 *
 * `firstDay` is the weekday a week starts on in the current language, in our
 * numbering (Monday is 0). It defaults to Monday, which is what the backend
 * counts from; the schedule passes the language's own value so an American
 * week runs Sunday to Saturday.
 */
export function startOfWeek(iso, firstDay = 0) {
  return addDays(iso, -((weekdayOf(iso) - firstDay + WEEKDAYS) % WEEKDAYS))
}

export function endOfWeek(iso, firstDay = 0) {
  return addDays(startOfWeek(iso, firstDay), WEEKDAYS - 1)
}

export function startOfMonth(iso) {
  return `${iso.slice(0, 7)}-01`
}

export function endOfMonth(iso) {
  const date = parseDate(iso)
  // day zero of the next month is the last day of this one
  return formatDate(new Date(date.getFullYear(), date.getMonth() + 1, 0, 12))
}

export function today() {
  return formatDate(new Date())
}


function covering(exceptions, iso) {
  return exceptions.filter((item) => item.start_date <= iso && iso <= item.end_date)
}

function makeDay(date, weekday, status, source, term) {
  return {
    date,
    weekday,
    status,
    title: source ? source.title : '',
    exception: source ? source.id : null,
    term_id: term ? term.id : null,
    term_name: term ? term.name : '',
  }
}

/** The term covering the date, or null: days between quarters are normal. */
export function findTerm(iso, terms) {
  return terms.find((term) => term.start_date <= iso && iso <= term.end_date) ?? null
}

export function buildDays(year, exceptions, terms = []) {
  const weekend = new Set(year.weekend_days)

  return eachDate(year.start_date, year.end_date).map((iso) => {
    const weekday = weekdayOf(iso)
    const found = covering(exceptions, iso)
    const of = (kind) => found.find((item) => item.kind === kind)
    // null is a day between quarters, which is a normal state
    const term = findTerm(iso, terms)

    const workday = of(KIND_WORKDAY)
    if (workday) return makeDay(iso, weekday, STATUS_STUDY, workday, term)

    const holiday = of(KIND_HOLIDAY)
    const vacation = of(KIND_VACATION)

    // a weekend outranks a holiday and a break, but the note is kept
    if (weekend.has(weekday)) {
      return makeDay(iso, weekday, STATUS_WEEKEND, holiday || vacation || null, term)
    }

    if (holiday) return makeDay(iso, weekday, STATUS_HOLIDAY, holiday, term)
    if (vacation) return makeDay(iso, weekday, STATUS_VACATION, vacation, term)

    return makeDay(iso, weekday, STATUS_STUDY, null, term)
  })
}

export function buildStats(days) {
  const byWeekday = Array.from({ length: WEEKDAYS }, () => 0)
  const byStatus = Object.fromEntries(STATUSES.map((status) => [status, 0]))

  days.forEach((day) => {
    byStatus[day.status] += 1
    if (day.status === STATUS_STUDY) byWeekday[day.weekday] += 1
  })

  // split by term: days outside every term go into the id === null row
  const byTerm = new Map()
  days.forEach((day) => {
    const key = day.term_id ?? null
    if (!byTerm.has(key)) {
      byTerm.set(key, {
        id: key,
        name: day.term_name ?? '',
        study: 0,
        calendar_days: 0,
      })
    }
    const bucket = byTerm.get(key)
    bucket.calendar_days += 1
    if (day.status === STATUS_STUDY) bucket.study += 1
  })

  return {
    calendar_days: days.length,
    total: byStatus[STATUS_STUDY],
    by_status: byStatus,
    by_weekday: byWeekday.map((count, weekday) => ({ weekday, count })),
    by_term: [...byTerm.values()],
  }
}

/**
 * Days grouped by month, with the blank cells before the first one.
 *
 * `firstDay` is the weekday a week starts on in the current language (in our
 * numbering, Monday is 0): the number of leading blanks depends on it, which
 * is why the grid shifts as a whole for a Sunday-first locale. The month
 * heading is not built here — `dates.monthTitle` knows the language.
 */
export function groupByMonth(days, firstDay = 0) {
  const months = []

  days.forEach((day) => {
    const key = day.date.slice(0, 7)

    if (months.at(-1)?.key !== key) {
      months.push({
        key,
        first: day.date,
        leading: (day.weekday - firstDay + WEEKDAYS) % WEEKDAYS,
        days: [],
      })
    }

    months.at(-1).days.push(day)
  })

  return months
}

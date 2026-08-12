/**
 * Разметка учебного календаря на клиенте.
 *
 * Повторяет calendars/services.py на бэкенде: нужна, чтобы правка дня
 * отражалась в сетке и в счётчике сразу, не дожидаясь ответа сервера.
 * Авторитетным остаётся сервер — после успешного запроса дни
 * перечитываются из /days/. Меняете приоритет видов — правьте оба места.
 *
 * Приоритет (подробное обоснование — в шапке services.py):
 * перенос → выходной → праздник → каникулы → учебный день.
 * У дня ровно один статус, поэтому сумма счётчиков по статусам всегда
 * равна числу календарных дней периода.
 */

export const KIND_HOLIDAY = 'holiday'
export const KIND_VACATION = 'vacation'
export const KIND_WORKDAY = 'workday'

export const STATUS_STUDY = 'study'
export const STATUS_HOLIDAY = 'holiday'
export const STATUS_VACATION = 'vacation'
export const STATUS_WEEKEND = 'weekend'

export const KIND_LABELS = {
  [KIND_HOLIDAY]: 'Праздник',
  [KIND_VACATION]: 'Каникулы',
  [KIND_WORKDAY]: 'Рабочий день',
}

export const STATUS_LABELS = {
  [STATUS_STUDY]: 'Учебный день',
  [STATUS_HOLIDAY]: 'Праздник',
  [STATUS_VACATION]: 'Каникулы',
  [STATUS_WEEKEND]: 'Выходной',
}

// понедельник — 0, как в date.weekday() на бэкенде
export const WEEKDAY_SHORT = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

const MONTH_NAMES = [
  'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
]

export const STATUSES = [STATUS_STUDY, STATUS_HOLIDAY, STATUS_VACATION, STATUS_WEEKEND]

/** Дата вида YYYY-MM-DD -> Date на полдень (полдень спасает от сдвигов при переводе часов). */
export function parseDate(iso) {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day, 12)
}

export function formatDate(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/** Номер дня недели: понедельник — 0. */
export function weekdayOf(iso) {
  return (parseDate(iso).getDay() + 6) % 7
}

export function addDays(iso, count) {
  const date = parseDate(iso)
  date.setDate(date.getDate() + count)
  return formatDate(date)
}

/** Сколько суток от одной даты до другой (полдень спасает от перевода часов). */
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

/** Понедельник недели, в которую попадает дата. */
export function startOfWeek(iso) {
  return addDays(iso, -weekdayOf(iso))
}

export function endOfWeek(iso) {
  return addDays(startOfWeek(iso), 6)
}

export function startOfMonth(iso) {
  return `${iso.slice(0, 7)}-01`
}

export function endOfMonth(iso) {
  const date = parseDate(iso)
  // нулевой день следующего месяца — последний день текущего
  return formatDate(new Date(date.getFullYear(), date.getMonth() + 1, 0, 12))
}

export function today() {
  return formatDate(new Date())
}

/** Человекочитаемый интервал: «4 ноября» или «26 октября — 3 ноября». */
export function formatRange(startIso, endIso) {
  const options = { day: 'numeric', month: 'long' }
  const start = parseDate(startIso).toLocaleDateString('ru-RU', options)
  if (startIso === endIso) return start
  return `${start} — ${parseDate(endIso).toLocaleDateString('ru-RU', options)}`
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

/** Терм, накрывающий дату, или null: дни между четвертями — это норма. */
export function findTerm(iso, terms) {
  return terms.find((term) => term.start_date <= iso && iso <= term.end_date) ?? null
}

export function buildDays(year, exceptions, terms = []) {
  const weekend = new Set(year.weekend_days)

  return eachDate(year.start_date, year.end_date).map((iso) => {
    const weekday = weekdayOf(iso)
    const found = covering(exceptions, iso)
    const of = (kind) => found.find((item) => item.kind === kind)
    // null — день между четвертями, это нормальное состояние
    const term = findTerm(iso, terms)

    const workday = of(KIND_WORKDAY)
    if (workday) return makeDay(iso, weekday, STATUS_STUDY, workday, term)

    const holiday = of(KIND_HOLIDAY)
    const vacation = of(KIND_VACATION)

    // выходной сильнее праздника и каникул, но пометку на дне сохраняем
    if (weekend.has(weekday)) {
      return makeDay(iso, weekday, STATUS_WEEKEND, holiday || vacation || null, term)
    }

    if (holiday) return makeDay(iso, weekday, STATUS_HOLIDAY, holiday, term)
    if (vacation) return makeDay(iso, weekday, STATUS_VACATION, vacation, term)

    return makeDay(iso, weekday, STATUS_STUDY, null, term)
  })
}

export function buildStats(days) {
  const byWeekday = WEEKDAY_SHORT.map(() => 0)
  const byStatus = Object.fromEntries(STATUSES.map((status) => [status, 0]))

  days.forEach((day) => {
    byStatus[day.status] += 1
    if (day.status === STATUS_STUDY) byWeekday[day.weekday] += 1
  })

  // разбивка по термам: дни вне термов идут записью с id === null
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

/** Дни, разложенные по месяцам, с отступом до первого дня недели. */
export function groupByMonth(days) {
  const months = []

  days.forEach((day) => {
    const date = parseDate(day.date)
    const key = day.date.slice(0, 7)

    if (months.at(-1)?.key !== key) {
      months.push({
        key,
        label: `${MONTH_NAMES[date.getMonth()]} ${date.getFullYear()}`,
        // сколько пустых клеток до первого дня месяца в сетке пн–вс
        leading: day.weekday,
        days: [],
      })
    }

    months.at(-1).days.push(day)
  })

  return months
}

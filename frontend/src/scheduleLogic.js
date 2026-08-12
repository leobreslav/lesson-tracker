/**
 * Расписание на клиенте: раскладка копирования и счётчики.
 *
 * Повторяет schedule/services.py и schedule/views.py::stats — нужно для
 * предпросмотра «сколько создастся» и для мгновенного пересчёта панели
 * после правки. Авторитет за сервером: после запроса состояние
 * перечитывается. Меняете правила там — правьте и здесь.
 */

import { addDays, daysBetween, eachDate, formatDate } from './calendarLogic'

export const MAX_LESSON_NUMBER = 10

/** Длина цикла источника в днях, округлённая вверх до целых недель. */
export function cycleDays(startIso, endIso) {
  return Math.ceil((daysBetween(startIso, endIso) + 1) / 7) * 7
}

/** Какой день источника отвечает за целевую дату. */
export function sourceDateFor(targetIso, sourceStartIso, cycle) {
  const delta = daysBetween(sourceStartIso, targetIso)
  // остаток в JS может быть отрицательным, приводим к неотрицательному
  return addDays(sourceStartIso, ((delta % cycle) + cycle) % cycle)
}

export function groupByDate(slots) {
  const map = new Map()
  slots.forEach((slot) => {
    if (!map.has(slot.date)) map.set(slot.date, [])
    map.get(slot.date).push(slot)
  })
  map.forEach((list) => list.sort((a, b) => a.lesson_number - b.lesson_number))
  return map
}

export const isRegular = (slot) => !slot.is_extra && !slot.is_cancelled

/**
 * Предпросмотр копирования: сколько уроков создастся и сколько пропустим.
 *
 * Пропуск — неучебный день цели или занятый номер (в режиме merge и на
 * уцелевших дополнительных/отменённых уроках в режиме replace).
 */
export function planCopy({
  slots,
  studyDates,
  sourceStart,
  sourceEnd,
  targetStart,
  targetEnd,
  mode,
  classIds = null,
}) {
  // копируем только выбранные классы, а занятость смотрим по всем:
  // чужой урок на этом номере всё равно не даст поставить свой
  const byDate = groupByDate(
    slots.filter(isRegular).filter((slot) => !classIds || classIds.has(slot.class_id)),
  )
  const occupied = new Set(
    slots
      .filter((slot) => (mode === 'replace' ? !isRegular(slot) : true))
      .filter((slot) => slot.date >= targetStart && slot.date <= targetEnd)
      .map((slot) => `${slot.date}#${slot.lesson_number}`),
  )

  const cycle = cycleDays(sourceStart, sourceEnd)
  let created = 0
  let skipped = 0

  eachDate(targetStart, targetEnd).forEach((target) => {
    const source = byDate.get(sourceDateFor(target, sourceStart, cycle)) || []
    source.forEach((slot) => {
      if (!studyDates.has(target)) {
        skipped += 1
      } else if (occupied.has(`${target}#${slot.lesson_number}`)) {
        skipped += 1
      } else {
        occupied.add(`${target}#${slot.lesson_number}`)
        created += 1
      }
    })
  })

  return { created, skipped }
}

/** Человеческий итог копирования: числа плюс первые конфликты занятости. */
export function describeCopyResult(result) {
  const conflicts = result.conflicts ?? []
  const shown = conflicts.slice(0, 3).map((item) => item.message)
  const rest = conflicts.length - shown.length

  return (
    `Создано уроков: ${result.created}, пропущено: ${result.skipped}` +
    (result.deleted ? `, удалено при замене: ${result.deleted}` : '') +
    '.' +
    (shown.length
      ? ` Уже занято другими классами: ${shown.join('; ')}` +
        (rest > 0 ? ` и ещё ${rest}.` : '.')
      : '')
  )
}

/** Сколько уроков снесёт очистка периода. */
export function planClear({ slots, start, end, onlyRegular, classIds = null }) {
  return slots.filter(
    (slot) =>
      slot.date >= start &&
      slot.date <= end &&
      (!classIds || classIds.has(slot.class_id)) &&
      (!onlyRegular || isRegular(slot)),
  ).length
}

export function buildStats(slots, today = formatDate(new Date())) {
  const live = slots.filter((slot) => !slot.is_cancelled)
  const past = live.filter((slot) => slot.date < today).length
  const cancelled = slots.filter((slot) => slot.is_cancelled)

  const counted = {}
  cancelled.forEach((slot) => {
    counted[slot.reason] = (counted[slot.reason] || 0) + 1
  })

  // сервер отдаёт причины от частых к редким — держим тот же порядок,
  // иначе список в панели прыгает между локальным и серверным ответом
  const byReason = Object.fromEntries(
    Object.entries(counted).sort(
      ([leftReason, left], [rightReason, right]) =>
        right - left || leftReason.localeCompare(rightReason, 'ru'),
    ),
  )

  return {
    total: live.length,
    past,
    remaining: live.length - past,
    cancelled: cancelled.length,
    extra: live.filter((slot) => slot.is_extra).length,
    cancelled_by_reason: byReason,
  }
}

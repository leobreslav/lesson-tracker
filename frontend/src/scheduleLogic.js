/**
 * The schedule on the client: the layout a copy would produce.
 *
 * A mirror of schedule/services.py — needed for the "how many will be
 * created" preview. The server stays the authority: the state is re-read
 * once it answers. Change the rules there, change them here.
 *
 * The counters used to be mirrored here too (`buildStats`, a copy of
 * /api/slots/stats/). Nothing called it: every page that shows counters
 * reads them from the server. A hand-kept mirror nobody uses is not a
 * spare — it is a second version of the truth waiting to be believed.
 */

import { addDays, daysBetween, eachDate } from './calendarLogic'

export const MAX_LESSON_NUMBER = 10

/** The source cycle in days, rounded up to whole weeks. */
export function cycleDays(startIso, endIso) {
  return Math.ceil((daysBetween(startIso, endIso) + 1) / 7) * 7
}

/** Which source day answers for a target date. */
export function sourceDateFor(targetIso, sourceStartIso, cycle) {
  const delta = daysBetween(sourceStartIso, targetIso)
  // a JS remainder can be negative, bring it back to non-negative
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
 * A copy preview: how many lessons appear and how many are skipped.
 *
 * A skip is a non-study target day or a taken number (in merge mode, and on
 * the surviving extra/cancelled lessons in replace mode).
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
  // only the chosen classes are copied, but occupancy is read across all of
  // them: another class's lesson on that number still blocks ours
  const byDate = groupByDate(
    slots.filter(isRegular).filter((slot) => !classIds || classIds.has(slot.course_id)),
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

/**
 * A readable summary of a copy: the numbers plus the first conflicts.
 *
 * The translator comes in as an argument — this module stays free of any
 * wording, exactly like its counterpart on the server.
 */
export function describeCopyResult(result, t) {
  const conflicts = result.conflicts ?? []
  const shown = conflicts.slice(0, 3).map((item) => item.message)
  const rest = conflicts.length - shown.length

  return (
    t('copy.summary', { created: result.created, skipped: result.skipped }) +
    (result.deleted ? t('copy.summaryDeleted', { deleted: result.deleted }) : '') +
    '.' +
    (shown.length
      ? t('copy.summaryConflicts', { list: shown.join('; ') }) +
        (rest > 0 ? t('copy.summaryMore', { count: rest }) : '.')
      : '')
  )
}

/** How many lessons clearing the period would remove. */
export function planClear({ slots, start, end, onlyRegular, classIds = null }) {
  return slots.filter(
    (slot) =>
      slot.date >= start &&
      slot.date <= end &&
      (!classIds || classIds.has(slot.course_id)) &&
      (!onlyRegular || isRegular(slot)),
  ).length
}

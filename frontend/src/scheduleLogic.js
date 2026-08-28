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

// расширение обязательно: этот модуль читает не только Vite, но и node —
// его тесты гоняют общие случаи из mirrors/, а node ESM путь без .js не
// достраивает
import { addDays, daysBetween, eachDate } from './calendarLogic.js'

export const MAX_LESSON_NUMBER = 10

/** The source cycle in days, rounded up to whole weeks. */
/**
 * Длина цикла источника: недели, округлённые вверх, умноженные на шаг.
 *
 * `step` — «через сколько раз повторять»: 1 каждую неделю, 2 через
 * неделю. Растягивается цикл, а не источник, поэтому пропущенная неделя
 * получается сама: её даты смотрят в пустой хвост цикла.
 */
export function cycleDays(startIso, endIso, step = 1) {
  return Math.ceil((daysBetween(startIso, endIso) + 1) / 7) * 7 * step
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
 * A skip is a non-study target day or a taken number. What counts as taken
 * follows `place_copies` on the server exactly, and the three rules below
 * are the ones this preview used to get wrong — each of them now has a case
 * in `mirrors/copy.json`, checked from both sides:
 *
 * * **the source is the chosen period and nothing else.** The cycle rounds
 *   up to whole weeks, so a three-day source has a seven-day cycle, and the
 *   four days past its end take part in the layout as empty ones. A lesson
 *   standing on one of them belongs to the week, not to the selection;
 * * **a cancelled lesson frees the slot.** Somebody else's cancelled lesson
 *   is not an obstacle: the window is free, which is the whole meaning of a
 *   cancellation;
 * * **replace clears only the chosen courses.** A neighbouring course keeps
 *   its lessons through a replace, so its number stays taken.
 *
 * One limit is left in on purpose: copying several courses at once, the
 * server walks them one by one, and a course can be blocked by another
 * course's lesson that a later step will delete. The preview does not model
 * that order — for a single course it is exact, for a selection it can
 * differ on the places where two copied courses meet.
 */
export function planCopy({
  slots,
  studyDates,
  sourceStart,
  sourceEnd,
  targetStart,
  targetEnd,
  mode,
  step = 1,
  classIds = null,
}) {
  const chosen = (slot) => !classIds || classIds.has(slot.course_id)
  const at = (date, number) => `${date}#${number}`

  const byDate = groupByDate(
    slots
      .filter(isRegular)
      .filter(chosen)
      .filter((slot) => slot.date >= sourceStart && slot.date <= sourceEnd),
  )

  const inTarget = slots.filter(
    (slot) => slot.date >= targetStart && slot.date <= targetEnd,
  )

  const cycle = cycleDays(sourceStart, sourceEnd, step)
  const span = daysBetween(sourceStart, sourceEnd)
  // куда копирование действительно кладёт: при шаге «через неделю»
  // пропущенные недели оно не трогает, значит и replace их не трогает
  const covered = (date) => daysBetween(sourceStart, date) % cycle <= span

  // taken by a course we are copying: replace removes its regular lessons,
  // the hand-made ones (cancelled, extra) survive and keep the place
  const taken = new Set(
    inTarget
      .filter(chosen)
      .filter((slot) => mode !== 'replace' || !isRegular(slot) || !covered(slot.date))
      .map((slot) => at(slot.date, slot.lesson_number)),
  )

  // taken by a course we are not copying: it lives through a replace, and
  // only a cancellation lets go of the number
  inTarget
    .filter((slot) => !chosen(slot) && !slot.is_cancelled)
    .forEach((slot) => taken.add(at(slot.date, slot.lesson_number)))

  let created = 0
  let skipped = 0

  eachDate(targetStart, targetEnd).forEach((target) => {
    const source = byDate.get(sourceDateFor(target, sourceStart, cycle)) || []
    source.forEach((slot) => {
      if (!studyDates.has(target) || taken.has(at(target, slot.lesson_number))) {
        skipped += 1
      } else {
        taken.add(at(target, slot.lesson_number))
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

/**
 * A readable summary of a permanent move: what travelled, what stayed.
 *
 * The two extra numbers are not decoration. A row that spans a year almost
 * always runs into something — an occupied number, a holiday, an hour that
 * already carries a record — and those hours stay where they were. Reporting
 * only «moved» would read as «the whole row moved», which is the one thing
 * the reader must not assume.
 */
export function describeMoveResult(result, t) {
  return (
    t('agenda.menu.moveSeriesDone', { moved: result.moved }) +
    (result.skipped ? t('agenda.menu.moveSeriesSkipped', { skipped: result.skipped }) : '') +
    (result.kept ? t('agenda.menu.moveSeriesKept', { kept: result.kept }) : '') +
    '.'
  )
}

/**
 * A readable summary of a room set on a whole row.
 *
 * Same shape and same reason as the move above: an hour that already carries
 * a record keeps the room it was held in — «the lesson took place in 214» is
 * a fact of a past day — and reporting only «updated» would read as «the
 * whole row», which is exactly what the reader must not assume.
 */
export function describeRoomResult(result, t) {
  return (
    t('agenda.menu.roomSeriesDone', { updated: result.updated }) +
    (result.kept ? t('agenda.menu.roomSeriesKept', { kept: result.kept }) : '') +
    '.'
  )
}

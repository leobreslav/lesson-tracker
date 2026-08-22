import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { buildDays, STATUS_STUDY } from '../src/calendarLogic.js'
import { cycleDays, planCopy, sourceDateFor } from '../src/scheduleLogic.js'

/**
 * Клиентская половина общих случаев копирования.
 *
 * Файл случаев один на две реализации (`mirrors/copy.json`), и это главное:
 * зеркала расходятся молча, а тесты, написанные порознь, проверяют то, что
 * автор помнил в тот день. Здесь и там — буквально одни данные и одни
 * ожидания, а ожидания — это поведение сервера.
 */
const CASES = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../mirrors/copy.json', import.meta.url)), 'utf8'),
)

/** Курсы в случае названы буквами; клиенту нужны id. */
const courseId = (name) => name.charCodeAt(0)

/**
 * Учебные дни года — своим расчётом, как их считает страница.
 *
 * Не подсунуты списком: `calendarLogic` — тоже зеркало, и пусть заодно
 * отвечает за то, что каникулы и выходные у него те же, что у сервера.
 */
function studyDatesOf(caseSpec) {
  const year = CASES.year
  const exceptions = (caseSpec.vacations ?? []).map((item, index) => ({
    id: index + 1,
    start_date: item.start,
    end_date: item.end,
    kind: 'vacation',
    title: item.title,
  }))

  return new Set(
    buildDays(year, exceptions)
      .filter((day) => day.status === STATUS_STUDY)
      .map((day) => day.date),
  )
}

for (const spec of CASES.cases) {
  test(`копирование: ${spec.name}`, () => {
    const slots = spec.slots.map((slot, index) => ({
      id: index + 1,
      course_id: courseId(slot.course),
      date: slot.date,
      lesson_number: slot.number,
      is_cancelled: Boolean(slot.cancelled),
      is_extra: Boolean(slot.extra),
    }))

    const preview = planCopy({
      slots,
      studyDates: studyDatesOf(spec),
      sourceStart: spec.source.start,
      sourceEnd: spec.source.end,
      targetStart: spec.target.start,
      targetEnd: spec.target.end,
      mode: spec.mode,
      step: spec.step ?? 1,
      classIds: new Set([courseId(spec.copy)]),
    })

    assert.deepEqual(
      { created: preview.created, skipped: preview.skipped },
      { created: spec.expected.created, skipped: spec.expected.skipped },
      `${spec.name}: ${spec.why}`,
    )
  })
}

test('цикл округляется вверх до целых недель', () => {
  assert.equal(cycleDays('2026-09-07', '2026-09-13'), 7)
  assert.equal(cycleDays('2026-09-07', '2026-09-07'), 7)
  // три дня — всё равно неделя: кратность семи и есть механизм совпадения
  // дней недели, без неё понедельник источника поехал бы на четверг цели
  assert.equal(cycleDays('2026-09-07', '2026-09-09'), 7)
  assert.equal(cycleDays('2026-09-07', '2026-09-20'), 14)
  assert.equal(cycleDays('2026-09-07', '2026-09-21'), 21)
})

test('целевая дата смотрит в источник по остатку', () => {
  assert.equal(sourceDateFor('2026-09-14', '2026-09-07', 7), '2026-09-07')
  assert.equal(sourceDateFor('2026-09-29', '2026-09-07', 14), '2026-09-15')
  // цель раньше источника — остаток всё равно неотрицательный
  assert.equal(sourceDateFor('2026-08-31', '2026-09-07', 7), '2026-09-07')
})


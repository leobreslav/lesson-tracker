/**
 * Тесты клиентской разметки календаря.
 *
 * Запуск: npm test (встроенный в node тест-раннер, зависимостей не нужно).
 * Файлы логики импортируются напрямую, поэтому в них указывают расширения.
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  STATUS_STUDY,
  STATUS_VACATION,
  STATUS_WEEKEND,
  buildDays,
  buildStats,
  findTerm,
} from '../src/calendarLogic.js'

const YEAR = {
  start_date: '2026-09-07', // понедельник
  end_date: '2026-09-20',
  weekend_days: [5, 6],
}

const TERM = {
  id: 1,
  name: '1 четверть',
  start_date: '2026-09-07',
  end_date: '2026-09-13',
}

describe('findTerm', () => {
  it('находит терм по дате, границы включительно', () => {
    assert.equal(findTerm('2026-09-07', [TERM]), TERM)
    assert.equal(findTerm('2026-09-13', [TERM]), TERM)
  })

  it('вне терма отдаёт null, а не падает', () => {
    assert.equal(findTerm('2026-09-14', [TERM]), null)
    assert.equal(findTerm('2026-09-07', []), null)
  })
})

describe('buildDays', () => {
  it('работает без единого терма в году', () => {
    const days = buildDays(YEAR, [])

    assert.equal(days.length, 14)
    assert.ok(days.every((day) => day.term_id === null && day.term_name === ''))
    assert.equal(days[0].status, STATUS_STUDY)
    assert.equal(days[5].status, STATUS_WEEKEND)
  })

  it('проставляет терм и оставляет null дням вне термов', () => {
    const days = buildDays(YEAR, [], [TERM])

    assert.deepEqual(
      days.map((day) => day.term_id),
      [...Array(7).fill(1), ...Array(7).fill(null)],
    )
    assert.equal(days[0].term_name, '1 четверть')
    assert.equal(days[7].term_name, '')
  })

  it('терм не мешает статусам и пометкам исключений', () => {
    const vacation = {
      id: 5,
      kind: 'vacation',
      title: 'Осенние',
      start_date: '2026-09-09',
      end_date: '2026-09-10',
    }

    const days = buildDays(YEAR, [vacation], [TERM])

    assert.equal(days[2].status, STATUS_VACATION)
    assert.equal(days[2].title, 'Осенние')
    assert.equal(days[2].exception, 5)
    assert.equal(days[2].term_id, 1)
  })

  it('день вне терма с исключением тоже считается', () => {
    const vacation = {
      id: 6,
      kind: 'vacation',
      title: 'Осенние',
      start_date: '2026-09-16',
      end_date: '2026-09-17',
    }

    const days = buildDays(YEAR, [vacation], [TERM])
    const day = days.find((item) => item.date === '2026-09-16')

    assert.equal(day.status, STATUS_VACATION)
    assert.equal(day.term_id, null)
    assert.equal(day.term_name, '')
  })
})

describe('buildStats', () => {
  it('разбивает дни по термам, вне термов — запись с id null', () => {
    const stats = buildStats(buildDays(YEAR, [], [TERM]))

    assert.deepEqual(
      stats.by_term.map((row) => [row.id, row.study, row.calendar_days]),
      [
        [1, 5, 7],
        [null, 5, 7],
      ],
    )
    assert.equal(
      stats.by_term.reduce((sum, row) => sum + row.study, 0),
      stats.total,
    )
  })

  it('без термов даёт одну запись', () => {
    const stats = buildStats(buildDays(YEAR, []))

    assert.equal(stats.by_term.length, 1)
    assert.equal(stats.by_term[0].id, null)
    assert.equal(stats.by_term[0].calendar_days, stats.calendar_days)
  })

  it('каждый день посчитан ровно один раз', () => {
    const stats = buildStats(buildDays(YEAR, [], [TERM]))
    const byStatus = Object.values(stats.by_status).reduce((a, b) => a + b, 0)

    assert.equal(byStatus, stats.calendar_days)
  })
})

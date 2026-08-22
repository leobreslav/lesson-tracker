import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ANY,
  emptyFilters,
  filterOptions,
  pick,
  reconcile,
  slotMatches,
} from '../src/scheduleFilters.js'

/**
 * Школа на семь курсов: два предмета, три учителя и курс без ведущего.
 *
 * Курс без ведущего здесь не для полноты: именно на нём ломается
 * «доназначить учителя вверх» — подставить его нечем, а подставленный
 * чужой спрятал бы его же часы.
 */
const ALGEBRA = { id: 1, name: 'Алгебра' }
const GEOMETRY = { id: 2, name: 'Геометрия' }

const PETROVA = { id: 10, first_name: 'Мария', last_name: 'Петрова' }
const IVANOV = { id: 11, first_name: 'Иван', last_name: 'Иванов' }
const SIDOROV = { id: 12, first_name: 'Пётр', last_name: 'Сидоров' }
const NEWCOMER = { id: 13, first_name: 'Анна', last_name: 'Новикова' }

const MEMBERS = [PETROVA, IVANOV, SIDOROV, NEWCOMER]

const course = (courseId, name, subject, teacher) => ({
  id: courseId,
  name,
  subject: subject.id,
  subject_name: subject.name,
  teachers: teacher ? [{ id: teacher.id, name: teacher.last_name }] : [],
})

const COURSES = [
  course(101, '9А Алгебра', ALGEBRA, PETROVA),
  course(102, '9Б Алгебра', ALGEBRA, PETROVA),
  course(103, '10А Алгебра', ALGEBRA, IVANOV),
  course(104, '9А Геометрия', GEOMETRY, IVANOV),
  course(105, '10А Геометрия', GEOMETRY, SIDOROV),
  course(106, '11А Геометрия', GEOMETRY, null),
  course(107, '11Б Геометрия', GEOMETRY, SIDOROV),
]

const names = (list) => list.map((item) => item.name)
const ids = (list) => list.map((item) => item.id)

test('без выбора предлагаются все предметы и все ведущие курсы учителя', () => {
  const options = filterOptions(COURSES, MEMBERS, emptyFilters())

  assert.deepEqual(names(options.subjects), ['Алгебра', 'Геометрия'])
  // Новикова не ведёт ничего — выбирать её значило бы получить пустую сетку
  assert.deepEqual(ids(options.teachers), [PETROVA.id, IVANOV.id, SIDOROV.id])
  assert.equal(options.courses.length, COURSES.length)
})

test('выбранный предмет сужает и учителей, и курсы', () => {
  const filters = pick(COURSES, emptyFilters(), 'subject', '1')
  const options = filterOptions(COURSES, MEMBERS, filters)

  assert.deepEqual(ids(options.teachers), [PETROVA.id, IVANOV.id])
  assert.deepEqual(names(options.courses), ['9А Алгебра', '9Б Алгебра', '10А Алгебра'])
  // предметы остаются все: с первого уровня цепочки уходят, не сбрасывая её
  assert.deepEqual(names(options.subjects), ['Алгебра', 'Геометрия'])
})

test('выбранный учитель сужает курсы до своих', () => {
  const filters = pick(COURSES, emptyFilters(), 'teacher', '10')
  const options = filterOptions(COURSES, MEMBERS, filters)

  assert.deepEqual(names(options.courses), ['9А Алгебра', '9Б Алгебра'])
})

test('выбранный курс называет своего учителя и свой предмет', () => {
  const filters = pick(COURSES, emptyFilters(), 'course', '105')

  assert.deepEqual(filters, { subject: '2', teacher: '12', course: '105' })
})

test('курс чужого учителя переставляет учителя, а не отменяет выбор', () => {
  // тот самый случай, ради которого всё это: пересечение показало бы пустую
  // неделю, и по ней было бы не понять, что фильтры друг другу противоречат
  const chosen = pick(COURSES, emptyFilters(), 'teacher', '10')
  const filters = pick(COURSES, chosen, 'course', '105')

  assert.deepEqual(filters, { subject: '2', teacher: '12', course: '105' })
})

test('курс без ведущего оставляет учителя незаполненным', () => {
  const filters = pick(COURSES, emptyFilters(), 'course', '106')

  assert.deepEqual(filters, { subject: '2', teacher: ANY, course: '106' })
})

test('учитель одного предмета называет и предмет', () => {
  const filters = pick(COURSES, emptyFilters(), 'teacher', '12')

  assert.equal(filters.subject, '2')
})

test('учитель двух предметов предмета не называет', () => {
  const filters = pick(COURSES, emptyFilters(), 'teacher', '11')

  assert.equal(filters.subject, ANY)
})

test('смена предмета снимает не подходящего к нему учителя', () => {
  const chosen = pick(COURSES, emptyFilters(), 'course', '101')
  const filters = pick(COURSES, chosen, 'subject', '2')

  assert.deepEqual(filters, { subject: '2', teacher: ANY, course: ANY })
})

test('смена предмета оставляет учителя, который ведёт и этот предмет', () => {
  const chosen = pick(COURSES, emptyFilters(), 'teacher', '11')
  const filters = pick(COURSES, { ...chosen, subject: '1' }, 'subject', '2')

  assert.deepEqual(filters, { subject: '2', teacher: '11', course: ANY })
})

test('«все» на широком уровне сбрасывает и узкие', () => {
  const chosen = pick(COURSES, emptyFilters(), 'course', '105')

  assert.deepEqual(pick(COURSES, chosen, 'teacher', ANY), {
    subject: '2',
    teacher: ANY,
    course: ANY,
  })
  assert.deepEqual(pick(COURSES, chosen, 'subject', ANY), emptyFilters())
})

test('снятие курса не трогает того, кто его вёл', () => {
  const chosen = pick(COURSES, emptyFilters(), 'course', '105')

  assert.deepEqual(pick(COURSES, chosen, 'course', ANY), {
    subject: '2',
    teacher: '12',
    course: ANY,
  })
})

test('сохранённый выбор сверяется с сегодняшними курсами', () => {
  // курс удалили — уходит он один, предмет с учителем остаются
  assert.deepEqual(reconcile(COURSES, { subject: '2', teacher: '12', course: '999' }), {
    subject: '2',
    teacher: '12',
    course: ANY,
  })

  // ведущего сняли с курса — уходит и он, и повисший на нём курс
  assert.deepEqual(reconcile(COURSES, { subject: '1', teacher: '12', course: '105' }), {
    subject: '1',
    teacher: ANY,
    course: ANY,
  })
})

test('до ответа сервера сохранённый выбор не трогается', () => {
  const kept = { subject: '2', teacher: '12', course: '105' }

  assert.deepEqual(reconcile([], kept), kept)
})

test('занятие отбирается по предмету своего курса', () => {
  const byId = new Map(COURSES.map((item) => [item.id, item]))
  const slot = { course: 105, teacher: 12, date: '2026-09-07', lesson_number: 3 }

  assert.equal(slotMatches(slot, byId, { subject: '2' }), true)
  assert.equal(slotMatches(slot, byId, { subject: '1' }), false)
  assert.equal(slotMatches(slot, byId, { teacher: '12', course: '105' }), true)
  assert.equal(slotMatches(slot, byId, { teacher: '10' }), false)
  assert.equal(slotMatches(slot, byId, emptyFilters()), true)
})

test('час курса без ведущего не прячется фильтром предмета', () => {
  const byId = new Map(COURSES.map((item) => [item.id, item]))
  const slot = { course: 106, teacher: null, date: '2026-09-07', lesson_number: 1 }

  assert.equal(slotMatches(slot, byId, { subject: '2' }), true)
  assert.equal(slotMatches(slot, byId, { teacher: '12' }), false)
})

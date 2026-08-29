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

const NINTH = { id: 9, name: 'MYP 4', level: 9 }
const TENTH = { id: 10, name: '10 класс', level: 10 }
const ELEVENTH = { id: 11, name: '11 класс', level: 11 }

const course = (courseId, name, subject, teacher, grade) => ({
  id: courseId,
  name,
  subject: subject.id,
  subject_name: subject.name,
  // год обучения — самый широкий уровень цепочки. Имя у него нарочно не по
  // алфавиту («MYP 4» это девятый год): порядок идёт по `level`
  grade: grade.id,
  grade_name: grade.name,
  grade_level: grade.level,
  teachers: teacher ? [{ id: teacher.id, name: teacher.last_name }] : [],
})

const COURSES = [
  course(101, '9А Алгебра', ALGEBRA, PETROVA, NINTH),
  course(102, '9Б Алгебра', ALGEBRA, PETROVA, NINTH),
  course(103, '10А Алгебра', ALGEBRA, IVANOV, TENTH),
  course(104, '9А Геометрия', GEOMETRY, IVANOV, NINTH),
  course(105, '10А Геометрия', GEOMETRY, SIDOROV, TENTH),
  course(106, '11А Геометрия', GEOMETRY, null, ELEVENTH),
  course(107, '11Б Геометрия', GEOMETRY, SIDOROV, ELEVENTH),
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

  // и свой год обучения: курс определяет его так же однозначно
  assert.deepEqual(filters, {
    grade: '10',
    subject: '2',
    teacher: '12',
    course: '105',
  })
})

test('курс чужого учителя переставляет учителя, а не отменяет выбор', () => {
  // тот самый случай, ради которого всё это: пересечение показало бы пустую
  // неделю, и по ней было бы не понять, что фильтры друг другу противоречат
  const chosen = pick(COURSES, emptyFilters(), 'teacher', '10')
  const filters = pick(COURSES, chosen, 'course', '105')

  assert.deepEqual(filters, {
    grade: '10',
    subject: '2',
    teacher: '12',
    course: '105',
  })
})

test('курс без ведущего оставляет учителя незаполненным', () => {
  const filters = pick(COURSES, emptyFilters(), 'course', '106')

  assert.deepEqual(filters, {
    grade: '11',
    subject: '2',
    teacher: ANY,
    course: '106',
  })
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

  // год девятый остаётся: он выбору не противоречит — геометрия в девятом
  // есть, — а уступают только те уровни, что противоречат
  assert.deepEqual(filters, { grade: '9', subject: '2', teacher: ANY, course: ANY })
})

test('смена предмета оставляет учителя, который ведёт и этот предмет', () => {
  const chosen = pick(COURSES, emptyFilters(), 'teacher', '11')
  const filters = pick(COURSES, { ...chosen, subject: '1' }, 'subject', '2')

  // а год доназначился: геометрию Иванов ведёт только в девятом
  assert.deepEqual(filters, { grade: '9', subject: '2', teacher: '11', course: ANY })
})

test('«все» на широком уровне сбрасывает и узкие', () => {
  const chosen = pick(COURSES, emptyFilters(), 'course', '105')

  assert.deepEqual(pick(COURSES, chosen, 'teacher', ANY), {
    grade: '10',
    subject: '2',
    teacher: ANY,
    course: ANY,
  })
  // «все предметы» сбрасывает то, что ниже предмета, а год остаётся: он
  // теперь **шире** предмета, и его никто не отменял
  assert.deepEqual(pick(COURSES, chosen, 'subject', ANY), {
    grade: '10',
    subject: ANY,
    teacher: ANY,
    course: ANY,
  })
  // а «все годы» — самый широкий уровень, и он сбрасывает всё
  assert.deepEqual(pick(COURSES, chosen, 'grade', ANY), emptyFilters())
})

test('снятие курса не трогает того, кто его вёл', () => {
  const chosen = pick(COURSES, emptyFilters(), 'course', '105')

  assert.deepEqual(pick(COURSES, chosen, 'course', ANY), {
    grade: '10',
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

test('выбранный год сужает и предметы, и учителей, и курсы', () => {
  const filters = pick(COURSES, emptyFilters(), 'grade', '11')
  const options = filterOptions(COURSES, MEMBERS, filters)

  // в одиннадцатом только геометрия, и ведёт её один Сидоров
  assert.deepEqual(names(options.subjects), ['Геометрия'])
  assert.deepEqual(ids(options.teachers), [SIDOROV.id])
  assert.deepEqual(names(options.courses), ['11А Геометрия', '11Б Геометрия'])
  // а предмет при этом **не** выбран, хотя он в списке один: доназначают
  // только вверх. Выбрать год и молча получить ещё и предмет значило бы
  // ответить за человека на вопрос, которого он не задавал
  assert.equal(filters.subject, ANY)
})

test('годы идут по году обучения, а не по алфавиту', () => {
  const options = filterOptions(COURSES, MEMBERS, emptyFilters())

  // «MYP 4» — это девятый год: по алфавиту он встал бы между четвёртым и
  // пятым, и порядок списка перестал бы что-либо значить
  assert.deepEqual(names(options.grades), ['MYP 4', '10 класс', '11 класс'])
})

test('список годов не сужается ничем — он первый в цепочке', () => {
  const filters = pick(COURSES, emptyFilters(), 'teacher', '10')
  const options = filterOptions(COURSES, MEMBERS, filters)

  // Петрова ведёт только девятый, но перейти к другому году надо уметь, не
  // сбрасывая сначала всё остальное
  assert.equal(options.grades.length, 3)
})

test('час фильтруется по году своего курса, а не своего поля', () => {
  const courseById = new Map(COURSES.map((one) => [one.id, one]))
  const slot = { course: 103, teacher: IVANOV.id }

  assert.equal(slotMatches(slot, courseById, { grade: '10' }), true)
  assert.equal(slotMatches(slot, courseById, { grade: '9' }), false)
})

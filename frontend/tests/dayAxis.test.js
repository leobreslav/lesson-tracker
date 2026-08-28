import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import {
  AXES,
  NONE,
  columns,
  keysOf,
  layout,
  prefillFor,
  teacherOf,
} from '../src/dayAxis.js'

const slot = (fields) => ({
  id: 1,
  course: 10,
  course_name: '9Б Алгебра',
  teacher: 100,
  teacher_name: 'Мария Иванова',
  taught_by: null,
  room: 200,
  room_name: '214',
  lesson_number: 1,
  ...fields,
})

const teachers = [
  { id: 100, name: 'Мария Иванова' },
  { id: 101, name: 'Пётр Петров' },
]
const rooms = [
  { id: 200, name: '214' },
  { id: 201, name: 'Спортзал', is_shared: true },
  { id: 202, name: 'Склад', is_archived: true },
]

describe('в какой столбец попадает час', () => {
  test('оси курсов нет: столбец с названием курса не отвечал ни на чей вопрос', () => {
    // с неё дневная сетка начиналась, и убрана она по просьбе: столбец
    // «9Б Алгебра» пересказывал то, что и так стоит в фильтрах, и молчал о
    // том, где урок идёт и кто его ведёт. Тест сторожит решение, а не код:
    // вернуть ось — значит сначала объяснить, кому она отвечает
    assert.deepEqual(AXES, ['teacher', 'room', 'homegroup'])
  })

  test('на оси кабинетов столбец ровно один — тот, что записан в часе', () => {
    assert.deepEqual(keysOf(slot({}), 'room'), ['200'])
  })

  test('замена ведёт час в столбец того, кто ведёт на самом деле', () => {
    // иначе экран врёт ровно про тот день, ради которого на него смотрят:
    // заменяющий стоит у себя, а заболевший — как будто на работе
    assert.equal(teacherOf(slot({ taught_by: 101 })), 101)
    assert.deepEqual(keysOf(slot({ taught_by: 101 }), 'teacher'), ['101'])
  })

  test('курс без ведущего и час без кабинета уходят в крайний столбец', () => {
    assert.deepEqual(keysOf(slot({ teacher: null }), 'teacher'), [NONE])
    assert.deepEqual(keysOf(slot({ room: null }), 'room'), [NONE])
  })
})

describe('какие столбцы показать', () => {
  test('делимость столбца — признак, а не готовое слово', () => {
    // перевод в чистом модуле означал бы, что он знает про словарь, а сырое
    // «shared» доехало бы до экрана словом — так и доехало в первом заходе
    const shown = columns('room', { rooms, slots: [] })

    assert.equal(shown.find((one) => one.name === 'Спортзал').shared, true)
    assert.equal(shown.find((one) => one.name === '214').shared, false)
  })

  test('пустой столбец остаётся: это и есть ответ «свободно»', () => {
    const shown = columns('room', { rooms, slots: [] })

    assert.deepEqual(
      shown.map((one) => one.name),
      ['214', 'Спортзал'],
    )
  })

  test('архивный кабинет из столбцов убран, пока в нём никто не стоит', () => {
    const shown = columns('room', { rooms, slots: [] })
    assert.ok(!shown.some((one) => one.name === 'Склад'))
  })

  test('но час, оставшийся в архивном кабинете, столбец получает', () => {
    // иначе урок пропадает с экрана, а пропавший урок не находят месяцами
    const shown = columns('room', {
      rooms,
      slots: [slot({ room: 202, room_name: 'Склад' })],
    })

    const gone = shown.find((one) => one.name === 'Склад')
    assert.ok(gone?.gone)
  })

  test('крайний столбец появляется, только когда есть кому в нём стоять', () => {
    assert.ok(!columns('room', { rooms, slots: [slot({})] }).some((one) => one.none))
    assert.ok(
      columns('room', { rooms, slots: [slot({ room: null })] }).some((one) => one.none),
    )
  })

  test('на оси учителей столбцы — люди школы', () => {
    const shown = columns('teacher', { teachers, slots: [] })
    assert.deepEqual(shown.map((one) => one.name), ['Мария Иванова', 'Пётр Петров'])
  })
})

describe('раскладка часов по клеткам', () => {
  test('клетка держит стопку: подгруппы и делимый зал — это норма', () => {
    const first = slot({ id: 1, course: 10 })
    const second = slot({ id: 2, course: 11, course_name: '10А Физика' })

    const byColumn = layout([first, second], 'room')

    assert.deepEqual(
      byColumn.get('200').get(1).map((one) => one.id),
      [1, 2],
    )
  })

  test('на оси учителей те же два часа расходятся по своим столбцам', () => {
    const byColumn = layout(
      [slot({ id: 1, teacher: 100 }), slot({ id: 2, teacher: 101 })],
      'teacher',
    )

    assert.deepEqual(byColumn.get('100').get(1).length, 1)
    assert.deepEqual(byColumn.get('101').get(1).length, 1)
  })
})

describe('что знает форма, когда нажали «+» в столбце', () => {
  test('столбец сужает выбор, а не заменяет его', () => {
    // час принадлежит курсу, и без курса его не создать: кабинет и учитель
    // подставляются, но про курс форма всё равно спросит
    assert.deepEqual(prefillFor('room', { id: 200 }), { room: 200 })
    assert.deepEqual(prefillFor('teacher', { id: 100 }), { teacher: 100 })
    assert.deepEqual(prefillFor('homegroup', { id: 300 }), { homegroup: 300 })
  })

  test('в крайнем столбце подставлять нечего', () => {
    assert.deepEqual(prefillFor('room', { key: NONE, none: true }), {})
    assert.deepEqual(prefillFor('room', { id: 202, gone: true }), {})
  })
})

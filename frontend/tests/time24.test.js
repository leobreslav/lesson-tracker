/**
 * Время в 24-часовой записи.
 *
 * Под тестами потому, что ошибка тут молчит: неверно разобранное «9:5» не
 * роняет ничего, а сдвигает окно работы, и узнают об этом ученики — работа
 * закрылась на сорок пять минут раньше обещанного.
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import { joinLocal, parseTime, splitLocal } from '../src/time24.js'

test('обычная запись читается как есть', () => {
  assert.equal(parseTime('14:30'), '14:30')
  assert.equal(parseTime('00:00'), '00:00')
  assert.equal(parseTime('23:59'), '23:59')
})

test('час без нуля впереди дополняется', () => {
  assert.equal(parseTime('9:05'), '09:05')
})

test('набранное без двоеточия понято так же', () => {
  assert.equal(parseTime('0905'), '09:05')
  assert.equal(parseTime('905'), '09:05')
  assert.equal(parseTime('1430'), '14:30')
  assert.equal(parseTime('9.05'), '09:05')
  assert.equal(parseTime('9 05'), '09:05')
  assert.equal(parseTime(' 14:30 '), '14:30')
})

test('одно число — это ровно час', () => {
  assert.equal(parseTime('9'), '09:00')
  assert.equal(parseTime('14'), '14:00')
  assert.equal(parseTime('0'), '00:00')
})

test('времени, которого не бывает, нет', () => {
  assert.equal(parseTime('24:00'), null)
  assert.equal(parseTime('12:60'), null)
  assert.equal(parseTime('2500'), null)
  assert.equal(parseTime('99'), null)
})

test('недописанные минуты — не время', () => {
  // «9:5» это набранное наполовину «9:50» или «9:05», и угадать, какое из
  // двух, значит однажды угадать неверно
  assert.equal(parseTime('9:5'), null)
  assert.equal(parseTime('9:'), null)
})

test('двенадцатичасовая запись не принимается', () => {
  // ради того поле и заведено: режим в интерфейсе один
  assert.equal(parseTime('9 pm'), null)
  assert.equal(parseTime('9:00 AM'), null)
})

test('пустое и мусор — не время', () => {
  assert.equal(parseTime(''), null)
  assert.equal(parseTime(null), null)
  assert.equal(parseTime('утром'), null)
})

test('момент раскладывается на дату и время и собирается обратно', () => {
  assert.deepEqual(splitLocal('2026-09-27T14:30'), {
    date: '2026-09-27',
    time: '14:30',
  })
  assert.equal(joinLocal('2026-09-27', '14:30'), '2026-09-27T14:30')
})

test('секунды в значении не мешают', () => {
  assert.equal(splitLocal('2026-09-27T14:30:00').time, '14:30')
})

test('пустое значение даёт пустые половины', () => {
  assert.deepEqual(splitLocal(''), { date: '', time: '' })
})

test('без даты момента нет', () => {
  assert.equal(joinLocal('', '14:30'), '')
})

test('дата без времени — полночь, а не пустое значение', () => {
  assert.equal(joinLocal('2026-09-27', ''), '2026-09-27T00:00')
})

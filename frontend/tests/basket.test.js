import assert from 'node:assert/strict'
import test, { beforeEach } from 'node:test'

// Хранилища в node нет — подставляем самое простое, что отвечает на три
// вызова: модуль обязан работать и там, где localStorage недоступен.
const store = new Map()
globalThis.localStorage = {
  getItem: (key) => (store.has(key) ? store.get(key) : null),
  setItem: (key, value) => store.set(key, String(value)),
}

const { taken, take, drop, toggle, clear } = await import('../src/basket.js')

beforeEach(() => {
  store.clear()
})

test('порядок отбора сохраняется — по нему задачи и встанут в работе', () => {
  take(7)
  take(3)
  take(9)
  assert.deepEqual(taken(), [7, 3, 9])
})

test('повторный отбор той же задачи её не двигает', () => {
  take(7)
  take(3)
  take(7)
  assert.deepEqual(taken(), [7, 3])
})

test('снятая уходит, остальные на местах', () => {
  ;[1, 2, 3].forEach(take)
  drop(2)
  assert.deepEqual(taken(), [1, 3])
})

test('переключатель работает в обе стороны', () => {
  toggle(5)
  assert.deepEqual(taken(), [5])
  toggle(5)
  assert.deepEqual(taken(), [])
})

test('мусор в хранилище читается как пустой набор, а не роняет страницу', () => {
  store.set('bank.basket', 'не json')
  assert.deepEqual(taken(), [])

  store.set('bank.basket', '[1, "два", 3]')
  assert.deepEqual(taken(), [1, 3])

  clear()
  assert.deepEqual(taken(), [])
})

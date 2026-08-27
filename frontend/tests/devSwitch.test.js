import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ORIGIN_KEY,
  forgetIfHome,
  forgetOrigin,
  homeToken,
  origin,
  rememberOrigin,
  wayHome,
} from '../src/devSwitch.js'

/** Хранилище браузера в двух строках: этому модулю больше и не нужно. */
const shelf = (start = {}) => {
  const box = { ...start }
  return {
    getItem: (key) => (key in box ? box[key] : null),
    setItem: (key, value) => {
      box[key] = String(value)
    },
    removeItem: (key) => {
      delete box[key]
    },
  }
}

const ADMIN = { email: 'director@example.com', name: 'Ольга Дирекова', token: 'aaa' }
const TEACHER = { email: 'ivanova@example.com', name: 'Мария Иванова', token: 'bbb' }

test('дорога домой запоминается при первой подмене', () => {
  const box = shelf()

  assert.equal(rememberOrigin(ADMIN, box), true)
  assert.deepEqual(origin(box), ADMIN)
})

test('вторая подмена дома не переписывает', () => {
  // завуч → ученик → учитель: «вернуться» ведёт к завучу, а не на шаг
  // назад. Это дорога домой, а не история переходов
  const box = shelf()
  rememberOrigin(ADMIN, box)

  assert.equal(rememberOrigin(TEACHER, box), false)
  assert.deepEqual(origin(box), ADMIN)
})

test('без адреса запоминать нечего', () => {
  const box = shelf()

  assert.equal(rememberOrigin({ name: 'кто-то' }, box), false)
  assert.equal(origin(box), null)
})

test('дорога показывается, только когда идти есть куда', () => {
  const box = shelf()
  assert.equal(wayHome({ email: ADMIN.email }, box), null, 'подмены не было')

  rememberOrigin(ADMIN, box)
  assert.deepEqual(wayHome({ email: TEACHER.email }, box), ADMIN)
  // вернулись своим входом — кнопка, нажатие на которую ничего не меняет,
  // хуже отсутствующей
  assert.equal(wayHome({ email: ADMIN.email }, box), null)
})

test('забытое не возвращается', () => {
  const box = shelf()
  rememberOrigin(ADMIN, box)

  forgetOrigin(box)

  assert.equal(origin(box), null)
  assert.equal(wayHome({ email: TEACHER.email }, box), null)
})

test('испорченное значение — это «дома не помним», а не поломка', () => {
  const box = shelf({ [ORIGIN_KEY]: '{не json' })

  assert.equal(origin(box), null)
  assert.equal(wayHome({ email: TEACHER.email }, box), null)
})

test('дома дорога домой забывается вместе с её токеном', () => {
  // База стенда пересеяна или подменена целиком, а запись о доме её
  // пережила: токен в ней мёртвый. Стучаться им в дверь нельзя — она
  // ответит как анониму, и переключатель пропадёт совсем
  const box = shelf()
  rememberOrigin(ADMIN, box)

  assert.equal(forgetIfHome({ email: ADMIN.email }, box), true)
  assert.equal(origin(box), null)
  // а раз записи нет, дверь спросят текущим токеном, и он живой
  assert.equal(homeToken(box), null)
})

test('в гостях дорога домой не трогается', () => {
  // подменившийся ходит чужим токеном, и home-токен — единственное, чем он
  // может достучаться до двери на контуре со списком допущенных
  const box = shelf()
  rememberOrigin(ADMIN, box)

  assert.equal(forgetIfHome({ email: TEACHER.email }, box), false)
  assert.deepEqual(origin(box), ADMIN)
  assert.equal(homeToken(box), ADMIN.token)
})

test('забывать нечего, когда пользователя ещё нет', () => {
  // меню рисуется раньше, чем приехал профиль: не знать, кто мы, — это не
  // повод стирать дорогу домой
  const box = shelf()
  rememberOrigin(ADMIN, box)

  assert.equal(forgetIfHome(null, box), false)
  assert.equal(forgetIfHome({}, box), false)
  assert.deepEqual(origin(box), ADMIN)
})

test('приватный режим ничего не ломает', () => {
  const closed = {
    getItem: () => {
      throw new Error('доступ к хранилищу запрещён')
    },
    setItem: () => {
      throw new Error('доступ к хранилищу запрещён')
    },
    removeItem: () => {
      throw new Error('доступ к хранилищу запрещён')
    },
  }

  assert.equal(rememberOrigin(ADMIN, closed), false)
  assert.equal(origin(closed), null)
  assert.doesNotThrow(() => forgetOrigin(closed))
})

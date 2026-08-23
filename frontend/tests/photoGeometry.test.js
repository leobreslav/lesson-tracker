/**
 * Геометрия просмотрщика фотографий.
 *
 * Стоит под тестами по той же причине, что и раскладка плана: ошибка здесь
 * не роняет ничего и не пишет ни слова в консоль — она рисует пометку учителя
 * рядом с тем местом, где ученик ошибся. Отличить «на пару сантиметров не
 * туда» от «так и было снято» глазами нельзя, а числа проверяются в секунду.
 *
 * Главное здесь — **обратимость**: тем же кодом мазок ложится на холст и тем
 * же палец превращается в долю. Разъедься эти два направления, и выглядело бы
 * это как «рисую здесь, появляется рядом».
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  layout,
  penPixels,
  spin,
  step,
  toScreen,
  toSource,
  turn,
  unspin,
} from '../src/photoGeometry.js'

const near = (a, b, why) => assert.ok(Math.abs(a - b) < 1e-9, why ?? `${a} ≠ ${b}`)

test('поворот идёт по кругу в обе стороны', () => {
  assert.equal(turn(0, 'cw'), 90)
  assert.equal(turn(270, 'cw'), 0, 'после четвёртого нажатия кнопка не упирается')
  assert.equal(turn(0, 'ccw'), 270)
  assert.equal(turn(90, 'ccw'), 0)
})

test('на четверти стороны картинки меняются местами', () => {
  const shot = { width: 800, height: 600 }

  assert.deepEqual(layout({ box: { width: 800, height: 600 }, image: shot }).width, 800)

  // повёрнутый вбок «альбомный» снимок вписывается по высоте, и вписанным
  // оказывается 600×800 в рамке 800×600 — то есть масштаб 0.75
  const sideways = layout({
    box: { width: 800, height: 600 },
    image: shot,
    rotation: 90,
  })
  near(sideways.scale, 0.75)
  near(sideways.width, 450)
  near(sideways.height, 600)
})

test('картинка вписывается целиком, а не по одной стороне', () => {
  // высокая тетрадь в широкой рамке: подгонка по ширине увела бы низ за край
  const place = layout({
    box: { width: 1000, height: 400 },
    image: { width: 600, height: 900 },
  })

  assert.ok(place.height <= 400 + 1e-9, 'снизу ничего не обрезано')
  assert.ok(place.width <= 1000 + 1e-9)
})

test('единица увеличения всегда значит «видно всё»', () => {
  const box = { width: 300, height: 300 }
  const image = { width: 1200, height: 400 }

  const whole = layout({ box, image })
  const closer = layout({ box, image, zoom: 2 })

  near(closer.width, whole.width * 2)
  near(closer.height, whole.height * 2)
})

test('угол исходника после четверти оказывается там, где положено', () => {
  // левый верхний угол при повороте по часовой уезжает в правый верхний
  assert.deepEqual(spin([0, 0], 90), [1, 0])
  assert.deepEqual(spin([0, 0], 180), [1, 1])
  assert.deepEqual(spin([0, 0], 270), [0, 1])
})

test('поворот обратим на всех четырёх положениях', () => {
  const point = [0.23, 0.71]

  for (const rotation of [0, 90, 180, 270]) {
    const there = spin(point, rotation)
    const back = unspin(there, rotation)
    near(back[0], point[0], `${rotation}°: x не вернулся`)
    near(back[1], point[1], `${rotation}°: y не вернулся`)
  }
})

test('экран и обратно: куда нарисовали, туда и попало', () => {
  const box = { width: 640, height: 480 }
  const image = { width: 1600, height: 1200 }
  const point = [0.3, 0.8]

  for (const rotation of [0, 90, 180, 270]) {
    for (const zoom of [1, 2.5]) {
      const place = layout({ box, image, rotation, zoom })
      const back = toSource(toScreen(point, place, rotation), place, rotation)

      near(back[0], point[0], `${rotation}° ×${zoom}: x`)
      near(back[1], point[1], `${rotation}° ×${zoom}: y`)
    }
  }
})

test('сдвиг картинки мышью не сдвигает пометки относительно неё', () => {
  const box = { width: 400, height: 400 }
  const image = { width: 800, height: 800 }
  const point = [0.25, 0.6]

  const still = layout({ box, image })
  const moved = layout({ box, image, pan: { x: 37, y: -12 } })

  near(toScreen(point, moved, 0).x - toScreen(point, still, 0).x, 37)
  near(toScreen(point, moved, 0).y - toScreen(point, still, 0).y, -12)
})

test('палец за краем прижимается к краю, а не обрывает мазок', () => {
  const place = layout({ box: { width: 200, height: 200 }, image: { width: 200, height: 200 } })

  assert.deepEqual(toSource({ x: -80, y: 500 }, place, 0), [0, 1])
})

test('перо считается от исходника, а не от того, что на экране', () => {
  const box = { width: 500, height: 500 }
  const image = { width: 1000, height: 500 }

  const whole = layout({ box, image })
  const closer = layout({ box, image, zoom: 3 })

  // толщина в тысячных ширины снимка: увеличили втрое — и на экране мазок
  // втрое толще, то есть по отношению к тетради он тот же самый
  near(penPixels(20, closer, 0), penPixels(20, whole, 0) * 3)
})

test('после поворота перо меряется по той же стороне снимка', () => {
  const box = { width: 600, height: 600 }
  const image = { width: 1200, height: 600 }

  const flat = layout({ box, image, rotation: 0 })
  const sideways = layout({ box, image, rotation: 90 })

  // ширина снимка после поворота лежит вдоль высоты рамки, и мазок обязан
  // остаться той же доли тетради, а не поменять толщину от поворота
  near(penPixels(20, flat, 0), penPixels(20, sideways, 90))
})

test('пустая рамка не даёт ни деления на ноль, ни NaN', () => {
  const place = layout({ box: { width: 0, height: 0 }, image: { width: 10, height: 10 } })

  assert.equal(place.scale, 0)
  assert.deepEqual(toSource({ x: 5, y: 5 }, place, 0), [0, 0])
})

test('листание идёт по кругу: за последней тетрадью первая', () => {
  const set = [{ id: 4 }, { id: 7 }, { id: 9 }]

  assert.deepEqual(step(set, 4, 1), { id: 7 })
  assert.deepEqual(step(set, 9, 1), { id: 4 })
  assert.deepEqual(step(set, 4, -1), { id: 9 })
})

test('пустой набор листать некуда, и это не ноль', () => {
  assert.equal(step([], 1, 1), null)
})

test('снимок, которого в наборе уже нет, не роняет листание', () => {
  // учитель убрал фотографию, пока просмотрщик был открыт: «дальше» должно
  // остаться работающей кнопкой, а не уехать в конец списка
  assert.deepEqual(step([{ id: 2 }, { id: 3 }], 99, 1), { id: 3 })
})

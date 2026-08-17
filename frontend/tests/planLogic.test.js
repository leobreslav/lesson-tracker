/** Счётчики блоков учебного плана и перестроение дерева. */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  applyMove,
  countBlocks,
  planRows,
  resolveDropTarget,
} from '../src/planLogic.js'

const section = (id, title, children = []) => ({
  id,
  title,
  is_section: true,
  note: '',
  children,
})
const lesson = (id, title) => ({ id, title, is_section: false, note: '' })

/** Папка, папка, урок, урок — как в примере из задания. */
const TREE = [
  section(1, 'Тригонометрия', [lesson(11, 'Синус'), lesson(12, 'Косинус')]),
  section(2, 'Векторы', [lesson(21, 'Понятие')]),
  lesson(3, 'Повторение'),
  lesson(4, 'Контрольная'),
]

const counts = (nodes) => {
  const { blocks, loose } = countBlocks(planRows(nodes))
  return { blocks: blocks.map((b) => [b.title, b.lessons]), loose }
}


describe('countBlocks по дереву плана', () => {
  it('считает уроки каждого блока', () => {
    assert.deepEqual(counts(TREE).blocks, [
      ['Тригонометрия', 2],
      ['Векторы', 1],
    ])
  })

  it('уроки до первого заголовка не попадают ни в один блок', () => {
    const nodes = [lesson(9, 'Вводный'), lesson(8, 'Ещё один'), ...TREE]

    const result = counts(nodes)
    assert.equal(result.loose, 4) // два сверху и два внизу
    assert.deepEqual(result.blocks, [
      ['Тригонометрия', 2],
      ['Векторы', 1],
    ])
  })

  it('пустой блок показывает 0', () => {
    assert.deepEqual(counts([section(1, 'Пустая')]).blocks, [['Пустая', 0]])
  })

  it('заголовок сразу за заголовком — тоже 0', () => {
    const nodes = [section(1, 'Первая'), section(2, 'Вторая', [lesson(21, 'Урок')])]

    assert.deepEqual(counts(nodes).blocks, [
      ['Первая', 0],
      ['Вторая', 1],
    ])
  })

  it('последний блок считается до конца списка', () => {
    const nodes = [
      section(1, 'Первая', [lesson(11, 'A')]),
      section(2, 'Последняя', [lesson(21, 'B'), lesson(22, 'C'), lesson(23, 'D')]),
    ]

    assert.deepEqual(counts(nodes).blocks[1], ['Последняя', 3])
  })

  it('план без заголовков: всё вне блоков', () => {
    const result = counts([lesson(1, 'A'), lesson(2, 'B')])

    assert.deepEqual(result.blocks, [])
    assert.equal(result.loose, 2)
  })

  it('план целиком из заголовков: у всех 0', () => {
    const result = counts([section(1, 'A'), section(2, 'B')])

    assert.deepEqual(result.blocks, [
      ['A', 0],
      ['B', 0],
    ])
    assert.equal(result.loose, 0)
  })
})

describe('пересчёт после правок дерева', () => {
  it('перетаскивание урока между блоками меняет оба счётчика', () => {
    const moved = applyMove({ nodes: TREE }, 11, 2, 0)

    assert.deepEqual(counts(moved.nodes).blocks, [
      ['Тригонометрия', 1],
      ['Векторы', 2],
    ])
  })

  it('урок, вынесенный на верхний уровень, уходит в «вне блоков»', () => {
    const moved = applyMove({ nodes: TREE }, 21, null, 0)

    const result = counts(moved.nodes)
    assert.deepEqual(result.blocks, [
      ['Тригонометрия', 2],
      ['Векторы', 0],
    ])
    assert.equal(result.loose, 3)
  })

  it('вставка заголовка в середину блока делит его на две половины', () => {
    // «Тригонометрия» с четырьмя уроками, второй заголовок забирает хвост
    const wide = [
      section(1, 'Тригонометрия', [
        lesson(11, 'A'),
        lesson(12, 'B'),
        lesson(13, 'C'),
        lesson(14, 'D'),
      ]),
    ]
    const rows = planRows(wide)
    // имитируем вставку заголовка после второго урока — как в плоском виде
    // у хвоста поле section_id убрано — так включается позиционное правило
    const split = [
      ...rows.slice(0, 3),
      { is_section: true, id: 99, title: 'Новая тема' },
      ...rows.slice(3).map(() => ({ is_section: false })),
    ]

    const { blocks } = countBlocks(split)
    assert.deepEqual(
      blocks.map((b) => [b.title, b.lessons]),
      [
        ['Тригонометрия', 2],
        ['Новая тема', 2],
      ],
    )
  })

  it('удаление урока уменьшает счётчик блока', () => {
    const withoutLesson = [
      section(1, 'Тригонометрия', [lesson(11, 'Синус')]),
      ...TREE.slice(1),
    ]

    assert.deepEqual(counts(withoutLesson).blocks[0], ['Тригонометрия', 1])
  })
})



/**
 * Зеркало серверного запрета: за спину проведённого урока строку не кладут.
 *
 * Сервер откажет всё равно (`plan_before_taught`), но подсветить цель, а
 * потом отказать — это обещать место, которого нет. Клиент обязан не
 * предлагать того, что сервер не сделает.
 */
describe('перетаскивание за спину проведённого', () => {
  // «нед 1» проведена, дальше свободно; ключи — id для dnd-kit
  const items = new Map([
    ['n-11', { node: lesson(11, 'Синус'), parent: null, index: 0, number: 1 }],
    ['n-12', { node: lesson(12, 'Косинус'), parent: null, index: 1, number: 2 }],
    ['n-13', { node: lesson(13, 'Тангенс'), parent: null, index: 2, number: 3 }],
    [
      'n-2',
      {
        node: section(2, 'Векторы', [lesson(21, 'Понятие')]),
        parent: null,
        index: 3,
        number: null,
        first: 4,
        last: 4,
      },
    ],
  ])

  const drop = (overId, below, boundary) =>
    resolveDropTarget({ items, activeId: 'n-13', overId, below, boundary })

  it('без единой записи место свободно везде', () => {
    assert.deepEqual(drop('n-11', false, 0), { parent: null, index: 0 })
  })

  it('на место проведённого урока не встать', () => {
    assert.equal(drop('n-11', false, 1), null)
  })

  it('сразу за последней записью — можно', () => {
    assert.deepEqual(drop('n-11', true, 1), { parent: null, index: 1 })
  })

  it('между двумя записями места нет', () => {
    assert.equal(drop('n-11', true, 2), null)
  })

  it('тема приземляется своими уроками, а не собой', () => {
    assert.equal(drop('n-2', false, 4), null)
    // индекс среди сиблингов, из которого уже вычтен сам переносимый узел
    assert.deepEqual(drop('n-2', true, 4), { parent: null, index: 3 })
  })
})

/** Счётчики блоков учебного плана и перестроение дерева. */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  applyMove,
  countBlocks,
  layoutBlocks,
  planRows,
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

describe('layoutBlocks', () => {
  const entry = (title, sectionId, date, term) => ({
    status: date ? 'matched' : 'no_slot',
    slot: date ? { id: date, date, lesson_number: 1, is_extra: false } : null,
    plan_row: { id: 1, title: 'Урок', number: 1, section_id: sectionId, section_title: title },
    term_id: term ? 1 : null,
    term_name: term ?? null,
  })

  it('считает уроки, даты и непоместившиеся', () => {
    const { blocks, loose } = layoutBlocks([
      entry('Тригонометрия', 1, '2026-10-14', '1 четверть'),
      entry('Тригонометрия', 1, '2026-11-21', '2 четверть'),
      entry('Тригонометрия', 1, null),
      { status: 'no_plan', slot: { id: 9, date: '2026-12-01', lesson_number: 1 }, plan_row: null, term_id: null, term_name: null },
    ])

    assert.equal(blocks.length, 1)
    assert.equal(blocks[0].lessons, 3)
    assert.equal(blocks[0].missing, 1)
    assert.equal(blocks[0].first, '2026-10-14')
    assert.equal(blocks[0].last, '2026-11-21')
    assert.deepEqual(blocks[0].terms, ['1 четверть', '2 четверть'])
    assert.equal(loose, 0)
  })

  it('уроки вне тем идут в «вне блоков»', () => {
    const { blocks, loose } = layoutBlocks([
      entry(null, null, '2026-10-14', '1 четверть'),
      entry('Векторы', 2, '2026-10-15', '1 четверть'),
    ])

    assert.equal(loose, 1)
    assert.deepEqual(
      blocks.map((b) => [b.title, b.lessons]),
      [['Векторы', 1]],
    )
  })
})

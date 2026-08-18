/** Счётчики блоков учебного плана и перестроение дерева. */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  afterClick,
  applyMove,
  countBlocks,
  planRows,
  resolveDropTarget,
  selectableIds,
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
    ['n-11', { id: 'n-11', node: lesson(11, 'Синус'), parent: null, index: 0, number: 1 }],
    ['n-12', { id: 'n-12', node: lesson(12, 'Косинус'), parent: null, index: 1, number: 2 }],
    ['n-13', { id: 'n-13', node: lesson(13, 'Тангенс'), parent: null, index: 2, number: 3 }],
    [
      'n-2',
      {
        id: 'n-2',
        node: section(2, 'Векторы', [lesson(21, 'Понятие')]),
        parent: null,
        index: 3,
        number: null,
        first: 4,
        last: 4,
        count: 1,
      },
    ],
  ])

  const drop = (overId, below, boundary) =>
    resolveDropTarget({ items, activeId: 'n-13', overId, below, boundary })

  it('без единой записи место свободно везде', () => {
    assert.deepEqual(drop('n-11', false, 0), {
      parent: null,
      index: 0,
      overId: 'n-11',
      side: 'before',
    })
  })

  it('на место проведённого урока не встать', () => {
    assert.equal(drop('n-11', false, 1), null)
  })

  it('сразу за последней записью — можно', () => {
    assert.equal(drop('n-11', true, 1).index, 1)
  })

  it('между двумя записями места нет', () => {
    assert.equal(drop('n-11', true, 2), null)
  })

  it('тема приземляется своими уроками, а не собой', () => {
    assert.equal(drop('n-2', false, 4), null)
    // индекс среди сиблингов, из которого уже вычтен сам переносимый узел
    assert.equal(drop('n-2', true, 4).index, 3)
  })
})

/**
 * Цель для темы — весь её блок, а не шапка.
 *
 * Пока целиться приходилось в шапку соседней темы, перетащить тему было
 * почти нельзя: блок из десяти уроков занимает пол-экрана, и весь этот
 * экран отвечал отказом — «тема в тему не кладётся».
 */
describe('перетаскивание темы через блоки', () => {
  const trig = section(1, 'Тригонометрия', [
    lesson(11, 'Синус'),
    lesson(12, 'Косинус'),
    lesson(13, 'Тангенс'),
    lesson(14, 'Котангенс'),
  ])
  const vectors = section(2, 'Векторы', [lesson(21, 'Понятие')])
  const probability = section(3, 'Вероятность', [lesson(31, 'Событие')])

  const trigEntry = {
    id: 'n-1',
    node: trig,
    parent: null,
    index: 0,
    number: null,
    first: 1,
    last: 4,
    count: 4,
  }
  const vectorsEntry = {
    id: 'n-2',
    node: vectors,
    parent: null,
    index: 1,
    number: null,
    first: 5,
    last: 5,
    count: 1,
  }

  const items = new Map([
    ['n-1', trigEntry],
    ...trig.children.map((child, index) => [
      `n-${child.id}`,
      {
        id: `n-${child.id}`,
        node: child,
        parent: trig.id,
        index,
        number: index + 1,
        section: trigEntry,
      },
    ]),
    ['n-2', vectorsEntry],
    [
      'n-21',
      {
        id: 'n-21',
        node: vectors.children[0],
        parent: vectors.id,
        index: 0,
        number: 5,
        section: vectorsEntry,
      },
    ],
    [
      'n-3',
      {
        id: 'n-3',
        node: probability,
        parent: null,
        index: 2,
        number: null,
        first: 6,
        last: 6,
        count: 1,
      },
    ],
  ])

  // тащим третий блок: у второго место «за Тригонометрией» и так занято,
  // а сброс, ничего не меняющий, законно отвечает null
  const drag = (overId, below) =>
    resolveDropTarget({ items, activeId: 'n-3', overId, below })

  it('наведение на верхнюю половину блока ставит тему перед ним', () => {
    assert.deepEqual(drag('n-11', false), {
      parent: null,
      index: 0,
      overId: 'n-1',
      side: 'before',
    })
  })

  it('наведение на нижнюю половину блока ставит тему за ним', () => {
    // третий и четвёртый уроки блока из четырёх — это уже «ниже»
    assert.equal(drag('n-14', true).side, 'after')
    assert.equal(drag('n-14', true).parent, null)
  })

  it('черта рисуется на блоке, а не на строке под курсором', () => {
    assert.equal(drag('n-12', false).overId, 'n-1')
  })

  it('внутрь себя тема не кладётся', () => {
    assert.equal(
      resolveDropTarget({ items, activeId: 'n-1', overId: 'n-12', below: true }),
      null,
    )
  })

  it('урок по-прежнему кладётся внутрь блока', () => {
    const target = resolveDropTarget({
      items,
      activeId: 'n-21',
      overId: 'n-12',
      below: true,
    })

    assert.equal(target.parent, trig.id)
    assert.equal(target.index, 2)
  })
})


describe('выделение строк для удаления пачкой', () => {
  const order = selectableIds(TREE)

  it('лента идёт в порядке показа, а тем в ней нет', () => {
    assert.deepEqual(order, [11, 12, 21, 3, 4])
  })

  it('проведённой строки в ленте нет: её всё равно не удалить', () => {
    const taught = [
      section(1, 'Тригонометрия', [
        { ...lesson(11, 'Синус'), taught: true },
        lesson(12, 'Косинус'),
      ]),
      { ...lesson(3, 'Повторение'), taught: true },
      lesson(4, 'Контрольная'),
    ]

    assert.deepEqual(selectableIds(taught), [12, 4])
  })

  it('обычный клик выделяет, повторный снимает', () => {
    assert.deepEqual(afterClick([], order, 12), [12])
    assert.deepEqual(afterClick([12], order, 12), [])
  })

  it('Shift тянет диапазон от прошлого нажатия, через границу темы', () => {
    assert.deepEqual(afterClick([11], order, 3, { anchor: 11, range: true }), [
      11, 12, 21, 3,
    ])
  })

  it('диапазон тянется и снизу вверх', () => {
    assert.deepEqual(afterClick([3], order, 12, { anchor: 3, range: true }), [12, 21, 3])
  })

  it('вторая протяжка добавляется к первой, а не заменяет её', () => {
    const first = afterClick([], order, 11)
    const both = afterClick(first, order, 4, { anchor: 3, range: true })

    assert.deepEqual(both, [11, 3, 4])
  })

  it('Shift без прошлого нажатия — это просто клик', () => {
    assert.deepEqual(afterClick([], order, 21, { anchor: null, range: true }), [21])
  })

  it('выбранное идёт в порядке ленты, а не нажатий', () => {
    const chosen = afterClick(afterClick([], order, 4), order, 11)

    assert.deepEqual(chosen, [11, 4])
  })

  it('строки не из ленты не выделяются: тему так не подцепить', () => {
    assert.deepEqual(afterClick([], order, 1), [])
  })
})

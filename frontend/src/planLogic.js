/**
 * The lesson plan on the client: rebuilding the tree and reading a drop.
 *
 * A mirror of plans/services.py in the part needed for optimistic dragging:
 * remove a node, insert it elsewhere, renumber the lessons. The server stays
 * the authority — the tree is re-read once it answers. Change the numbering
 * or the nesting rules there, change them here.
 */

const clamp = (value, max) => Math.max(0, Math.min(value, max))

/** Take a node out of the tree. Returns [node, tree without it]. */
function extract(nodes, nodeId) {
  let found = null
  const rest = []

  for (const node of nodes) {
    if (node.id === nodeId) {
      found = node
      continue
    }

    if (node.children) {
      const kept = node.children.filter((child) => {
        if (child.id !== nodeId) return true
        found = child
        return false
      })
      rest.push({ ...node, children: kept })
    } else {
      rest.push(node)
    }
  }

  return [found, rest]
}

function insert(list, node, index) {
  const next = [...list]
  next.splice(clamp(index, next.length), 0, node)
  return next
}

/** Number lessons depth-first; sections get no number. */
export function renumber(nodes) {
  let number = 0

  return nodes.map((node, position) => {
    if (node.is_section) {
      return {
        ...node,
        position,
        number: null,
        children: node.children.map((child, childPosition) => ({
          ...child,
          position: childPosition,
          parent: node.id,
          number: ++number,
        })),
      }
    }

    return { ...node, position, parent: null, number: ++number }
  })
}

export function countPlan(nodes) {
  const lessons = nodes.flatMap((node) =>
    node.is_section ? node.children : [node],
  )

  return {
    lessons: lessons.length,
    sections: nodes.filter((node) => node.is_section).length,
  }
}

/**
 * Plan rows in display order: a block header, then its lessons.
 *
 * This flattens the tree into the same shape `countBlocks` counts over, so
 * one function serves both the plan and the layout.
 */
export function planRows(nodes) {
  return nodes.flatMap((node) =>
    node.is_section
      ? [
          { is_section: true, id: node.id, title: node.title },
          ...(node.children ?? []).map((child) => ({
            is_section: false,
            id: child.id,
            section_id: node.id,
            section_title: node.title,
          })),
        ]
      : [
          {
            is_section: false,
            id: node.id,
            section_id: null,
            section_title: null,
          },
        ],
  )
}

/**
 * How many lessons each block holds, and how many sit outside every block.
 *
 * A header row opens a block. A lesson's block comes from its own
 * `section_id`: `null` means "outside the blocks" — in this model a top-level
 * lesson lies outside every section, even when it stands right after one. If
 * the field is missing altogether (a flat list with no nesting), the
 * positional rule applies: a lesson belongs to the last header above it.
 */
export function countBlocks(rows) {
  const blocks = []
  const byId = new Map()
  let current = null
  let loose = 0

  const open = (id, title) => {
    if (byId.has(id)) return byId.get(id)
    const block = { id, title, lessons: 0 }
    byId.set(id, block)
    blocks.push(block)
    return block
  }

  rows.forEach((row) => {
    if (row.is_section) {
      current = open(row.id, row.title)
      return
    }

    let block
    if ('section_id' in row) {
      block = row.section_id != null ? open(row.section_id, row.section_title ?? '') : null
    } else {
      block = current
    }

    if (block) block.lessons += 1
    else loose += 1
  })

  return { blocks, byId, loose }
}


/**
 * Move a node and recompute the whole tree.
 *
 * `index` is the position in the level WITHOUT the dragged node — exactly
 * how `place()` counts on the server.
 */
export function applyMove(data, nodeId, parent, index) {
  const [node, rest] = extract(data.nodes, nodeId)
  if (!node) return data

  const moved = { ...node, parent }
  const nodes =
    parent === null
      ? insert(rest, moved, index)
      : rest.map((item) =>
          item.id === parent
            ? { ...item, children: insert(item.children, moved, index) }
            : item,
        )

  const renumbered = renumber(nodes)
  return { nodes: renumbered, counts: countPlan(renumbered) }
}

/**
 * Where a drop will land.
 *
 * `items` is Map<drag id, {id, node, parent, index, …}>. Returns
 * {parent, index, overId, side} — the last two say, куда рисовать черту, —
 * или null, когда сброс не разрешён или ничего не меняет.
 *
 * **У темы цель — весь её блок, а не шапка.** Тема ходит только по верхнему
 * уровню, и пока целиться в неё приходилось в 29-пиксельную шапку соседней
 * темы, перетащить её было почти нельзя: блок из десяти уроков занимает
 * пол-экрана, и весь этот экран отвечал отказом. Наведение на любую строку
 * блока значит теперь «рядом с этим блоком» — выше в его верхней половине,
 * ниже в нижней.
 */
export function resolveDropTarget({ items, activeId, overId, below, boundary = 0 }) {
  const active = items.get(activeId)
  if (!active || !overId) return null

  if (typeof overId === 'string' && overId.startsWith('empty-')) {
    // an empty section: the only way to put a first lesson into it
    if (active.node.is_section) return null
    return {
      parent: Number(overId.slice('empty-'.length)),
      index: 0,
      overId,
      side: 'before',
    }
  }

  let over = items.get(overId)
  if (!over || over.node.id === active.node.id) return null

  let after = below

  if (active.node.is_section && over.parent !== null) {
    const host = over.section
    if (!host || host.node.id === active.node.id) return null

    // половина блока решает сторону: у урока номер три из десяти «выше»,
    // у восьмого — «ниже», и целиться в шапку больше не надо
    after = over.index + (below ? 1 : 0) > (host.count ?? 0) / 2
    over = host
  }

  // За спину проведённого урока ходу нет: `boundary` — его сквозной номер,
  // и место, в которое строка приземлится, должно быть строго за ним. Тема
  // приземляется своим первым уроком (сверху) или сразу за последним
  // (снизу); тема без уроков места в ленте не занимает, и мерить нечего.
  if (boundary) {
    const at = over.node.is_section ? (after ? over.last : over.first) : over.number
    if (at && (after ? at + 1 : at) <= boundary) return null
  }

  let parent
  if (over.node.is_section) {
    // a section header means the place next to it on the top level;
    // hovering over its contents is what puts a lesson inside
    parent = null
  } else {
    parent = over.parent
  }

  let index = over.index + (after ? 1 : 0)

  if (parent === active.parent) {
    // the index is counted without the node itself
    if (active.index < index) index -= 1
    if (index === active.index) return null
  }

  return { parent, index, overId: over.id ?? overId, side: after ? 'after' : 'before' }
}

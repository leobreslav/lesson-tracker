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
 * `items` is Map<drag id, {node, parent, index}>. Returns {parent, index}, or
 * null when the drop is not allowed or would change nothing.
 */
export function resolveDropTarget({ items, activeId, overId, below }) {
  const active = items.get(activeId)
  if (!active || !overId) return null

  if (typeof overId === 'string' && overId.startsWith('empty-')) {
    // an empty section: the only way to put a first lesson into it
    if (active.node.is_section) return null
    return { parent: Number(overId.slice('empty-'.length)), index: 0 }
  }

  const over = items.get(overId)
  if (!over || over.node.id === active.node.id) return null

  let parent
  if (over.node.is_section) {
    // a section header means the place next to it on the top level;
    // hovering over its contents is what puts a lesson inside
    parent = null
  } else if (active.node.is_section && over.parent !== null) {
    return null // a section cannot go inside a section
  } else {
    parent = over.parent
  }

  let index = over.index + (below ? 1 : 0)

  if (parent === active.parent) {
    // the index is counted without the node itself
    if (active.index < index) index -= 1
    if (index === active.index) return null
  }

  return { parent, index }
}

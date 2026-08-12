/**
 * Учебный план на клиенте: перестроение дерева и разбор точки сброса.
 *
 * Повторяет plans/services.py в той части, что нужна для оптимистичного
 * перетаскивания: убрать узел, вставить на новое место, пересчитать сквозные
 * номера. Авторитет за сервером — после ответа дерево перечитывается.
 * Меняете нумерацию или правила вложенности там — правьте и здесь.
 */

const clamp = (value, max) => Math.max(0, Math.min(value, max))

/** Убрать узел из дерева. Возвращает [узел, дерево без него]. */
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

/** Проставить сквозные номера обходом в глубину; папки номеров не получают. */
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
    control: lessons.filter((item) => item.kind === 'control').length,
    reserve: lessons.filter((item) => item.kind === 'reserve').length,
    sections: nodes.filter((node) => node.is_section).length,
  }
}

/**
 * Перенести узел и пересчитать всё дерево.
 *
 * `index` — место в уровне БЕЗ перетаскиваемого узла: ровно так же считает
 * `place()` на сервере.
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
 * Куда попадёт сброс.
 *
 * `items` — Map<id перетаскивания, {node, parent, index}>. Возвращает
 * {parent, index} либо null, если бросать сюда нельзя или ничего не меняется.
 */
export function resolveDropTarget({ items, activeId, overId, below }) {
  const active = items.get(activeId)
  if (!active || !overId) return null

  if (typeof overId === 'string' && overId.startsWith('empty-')) {
    // пустая папка: единственный способ положить в неё первый урок
    if (active.node.is_section) return null
    return { parent: Number(overId.slice('empty-'.length)), index: 0 }
  }

  const over = items.get(overId)
  if (!over || over.node.id === active.node.id) return null

  let parent
  if (over.node.is_section) {
    // шапка папки — это место рядом с ней на верхнем уровне,
    // внутрь кладут наведением на содержимое
    parent = null
  } else if (active.node.is_section && over.parent !== null) {
    return null // папку внутрь папки нельзя
  } else {
    parent = over.parent
  }

  let index = over.index + (below ? 1 : 0)

  if (parent === active.parent) {
    // индекс считается без самого узла
    if (active.index < index) index -= 1
    if (index === active.index) return null
  }

  return { parent, index }
}

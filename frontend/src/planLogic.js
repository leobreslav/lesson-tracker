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
    sections: nodes.filter((node) => node.is_section).length,
  }
}

/** «1 урок» / «3 урока» / «12 уроков». */
export function pluralLessons(count) {
  const tail = count % 10
  const hundred = count % 100

  if (tail === 1 && hundred !== 11) return `${count} урок`
  if (tail >= 2 && tail <= 4 && (hundred < 10 || hundred >= 20)) return `${count} урока`
  return `${count} уроков`
}

/**
 * Строки плана в порядке отображения: заголовок блока, потом его уроки.
 *
 * Тем самым дерево приводится к тому же плоскому виду, в котором считает
 * `countBlocks`, — одна и та же функция обслуживает и план, и раскладку.
 */
export function planRows(nodes) {
  return nodes.flatMap((node) =>
    node.is_section
      ? [
          { is_section: true, id: node.id, title: node.title },
          ...(node.children ?? []).map((child) => ({
            is_section: false,
            section_id: node.id,
            section_title: node.title,
          })),
        ]
      : [{ is_section: false, section_id: null, section_title: null }],
  )
}

/**
 * Сколько уроков в каждом блоке и сколько их вне блоков.
 *
 * Строка-заголовок открывает блок. У урока блок берётся из его собственного
 * `section_id`: значение `null` означает «вне блоков» — в нашей модели урок
 * верхнего уровня лежит вне темы, даже если стоит после папки. Если поля
 * нет вовсе (плоский список без вложенности), работает позиционное правило:
 * урок относится к последнему заголовку выше.
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
 * То же по записям раскладки плюс даты блока, непоместившиеся уроки и
 * термы, через которые блок проходит.
 */
export function layoutBlocks(entries) {
  const rows = entries
    .filter((entry) => entry.plan_row)
    .map((entry) => ({
      is_section: false,
      section_id: entry.plan_row.section_id ?? null,
      section_title: entry.plan_row.section_title ?? null,
    }))

  const { blocks, byId, loose } = countBlocks(rows)

  blocks.forEach((block) => {
    block.first = null
    block.last = null
    block.missing = 0
    block.terms = []
  })

  entries.forEach((entry) => {
    const id = entry.plan_row?.section_id ?? null
    const block = id != null ? byId.get(id) : null
    if (!block) return

    if (entry.slot) {
      block.first ??= entry.slot.date
      block.last = entry.slot.date
      if (entry.term_name && !block.terms.includes(entry.term_name)) {
        block.terms.push(entry.term_name)
      }
    } else {
      // уроку блока не хватило слота — он не помещается в год
      block.missing += 1
    }
  })

  return { blocks, byId, loose }
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
